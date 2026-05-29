"""Tests for the asynchronous crawl path and its parity with the sync path."""

import asyncio

import httpx

from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.scraper import Scraper


class _DummyDB:
    """Minimal DatabaseManager stand-in for unit tests that don't touch the DB."""

    def __del__(self):
        pass


class FixtureTransport(httpx.AsyncBaseTransport):
    """
    An httpx async transport that serves a fixed map of URL -> HTML.

    Optionally records in-flight concurrency (to prove overlapping requests)
    and sleeps to widen the overlap window.
    """

    def __init__(self, pages, tracker=None, delay=0.0):
        """
        Args:
            pages (dict[str, str]): Mapping of absolute URL to HTML body.
            tracker (dict | None): Optional dict with ``inflight``/``max`` keys
                updated to record concurrency.
            delay (float): Seconds to sleep inside each request to widen overlap.
        """
        self.pages = pages
        self.tracker = tracker
        self.delay = delay

    async def handle_async_request(self, request):
        """Serve the fixture page for the requested URL."""
        if self.tracker is not None:
            self.tracker["inflight"] += 1
            self.tracker["max"] = max(self.tracker["max"], self.tracker["inflight"])
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            url = str(request.url)
            html = self.pages.get(url)
            if html is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(
                200, headers={"content-type": "text/html"}, text=html
            )
        finally:
            if self.tracker is not None:
                self.tracker["inflight"] -= 1


class SyncResp:
    """Minimal stand-in for a requests.Response used by the sync path."""

    def __init__(self, text):
        self.status_code = 200 if text is not None else 404
        self.text = text or ""
        self.headers = {"content-type": "text/html"}


# A small interlinked fixture site reachable entirely from the root.
SITE = {
    "http://site.test/": (
        '<html><body><a href="/a">a</a><a href="/b">b</a></body></html>'
    ),
    "http://site.test/a": '<html><body><a href="/c">c</a></body></html>',
    "http://site.test/b": (
        '<html><body><a href="/c">c</a><a href="/a">a</a></body></html>'
    ),
    "http://site.test/c": "<html><body>leaf</body></html>",
}


def _make_scraper(db, **kwargs):
    """Build a Scraper rooted at the fixture site with test defaults."""
    params = dict(
        base_url="http://site.test",
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    params.update(kwargs)
    return Scraper(**params)


def _corpus(db):
    """Return the scraped corpus as a set of (url, content) pairs."""
    return {(url, content) for url, content, _ in db.get_all_pages()}


def test_async_sync_parity(monkeypatch):
    """Sync (concurrency=1) and async (concurrency=5) yield an identical corpus."""
    # Deterministic scrape: content is simply the page HTML.
    monkeypatch.setattr(
        Scraper, "scrape_page", lambda self, html, url: (html, {"url": url})
    )

    # Synchronous crawl.
    sync_db = DatabaseManager(":memory:")
    sync_scraper = _make_scraper(sync_db)
    monkeypatch.setattr(
        sync_scraper.session, "get", lambda url, **k: SyncResp(SITE.get(url))
    )
    sync_scraper.start_scraping(url="http://site.test/")

    # Asynchronous crawl with concurrency 5 over the same fixture.
    async_db = DatabaseManager(":memory:")
    async_scraper = _make_scraper(async_db, concurrency=5)
    monkeypatch.setattr(
        async_scraper,
        "_make_async_client",
        lambda: httpx.AsyncClient(
            transport=FixtureTransport(SITE), follow_redirects=True
        ),
    )
    asyncio.run(async_scraper.start_scraping_async(url="http://site.test/"))

    sync_corpus = _corpus(sync_db)
    async_corpus = _corpus(async_db)

    # Both crawled the full reachable set, identically.
    assert {url for url, _ in sync_corpus} == set(SITE.keys())
    assert sync_corpus == async_corpus


def test_async_issues_overlapping_requests(monkeypatch):
    """concurrency>1 actually fetches in parallel; concurrency=1 never overlaps."""
    monkeypatch.setattr(
        Scraper, "scrape_page", lambda self, html, url: (html, {"url": url})
    )

    hub = {
        "http://hub.test/": "".join(
            f'<a href="/p{i}">p{i}</a>' for i in range(1, 6)
        ),
    }
    hub.update({f"http://hub.test/p{i}": "<html>leaf</html>" for i in range(1, 6)})

    # Concurrent run: a batch of 5 leaf pages should overlap.
    tracker = {"inflight": 0, "max": 0}
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db, base_url="http://hub.test", concurrency=5)
    monkeypatch.setattr(
        scraper,
        "_make_async_client",
        lambda: httpx.AsyncClient(
            transport=FixtureTransport(hub, tracker=tracker, delay=0.02),
            follow_redirects=True,
        ),
    )
    asyncio.run(scraper.start_scraping_async(url="http://hub.test/"))

    assert len(db.get_all_pages()) == 6  # hub + 5 leaves
    assert tracker["max"] >= 2  # genuine overlap occurred

    # Serial run: concurrency=1 must never have more than one request in flight.
    tracker1 = {"inflight": 0, "max": 0}
    db1 = DatabaseManager(":memory:")
    scraper1 = _make_scraper(db1, base_url="http://hub.test", concurrency=1)
    monkeypatch.setattr(
        scraper1,
        "_make_async_client",
        lambda: httpx.AsyncClient(
            transport=FixtureTransport(hub, tracker=tracker1, delay=0.01),
            follow_redirects=True,
        ),
    )
    asyncio.run(scraper1.start_scraping_async(url="http://hub.test/"))
    assert tracker1["max"] == 1


def test_aget_with_retry_succeeds_after_429(monkeypatch):
    """The async retry helper retries a 429 and returns the eventual 200."""
    scraper = Scraper(
        base_url="http://x",
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=_DummyDB(),
        max_retries=2,
    )

    calls = {"n": 0}

    class _RetryTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"content-type": "text/html"})
            return httpx.Response(
                200, headers={"content-type": "text/html"}, text="ok"
            )

    async def _fast_sleep(_seconds):
        return None

    monkeypatch.setattr("crawler_to_md.scraper.asyncio.sleep", _fast_sleep)

    async def run():
        async with httpx.AsyncClient(transport=_RetryTransport()) as client:
            return await scraper._aget_with_retry(client, "http://x/")

    response = asyncio.run(run())

    assert response.status_code == 200
    assert calls["n"] == 2  # one retry after the 429
