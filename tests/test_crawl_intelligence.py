"""Tests for Wave 2a crawl-intelligence features.

Covers robots.txt compliance, sitemap seeding, custom headers/cookies/auth,
non-HTML (allow-types) ingestion, and the clear missing-extra error paths for
readability extraction and JS rendering. Each behavior is asserted on both the
configuration and, where relevant, the actual outgoing request.
"""

import asyncio
import sys
from unittest.mock import patch

import httpx
import pytest

from crawler_to_md import cli
from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.export_manager import ExportManager
from crawler_to_md.scraper import Scraper


class _DummyDB:
    """Minimal DatabaseManager stand-in for tests that never touch the DB."""

    def __del__(self):
        pass


class Resp:
    """Minimal response stand-in exposing the consumed response interface."""

    def __init__(self, text="", status=200, content_type="text/html", content=None):
        """
        Args:
            text (str): Response body decoded as text.
            status (int): HTTP status code.
            content_type (str): Value for the ``content-type`` header.
            content (bytes | None): Raw body; defaults to ``text`` encoded.
        """
        self.status_code = status
        self.text = text
        self.headers = {"content-type": content_type}
        self.content = content if content is not None else text.encode("utf-8")


def _make_scraper(db, **kwargs):
    """Build a Scraper rooted at example.com with test defaults."""
    params = dict(
        base_url="http://example.com",
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    params.update(kwargs)
    return Scraper(**params)


ROBOTS_BODY = "User-agent: *\nDisallow: /private"

ROBOTS_SITE = {
    "http://example.com/robots.txt": ROBOTS_BODY,
    "http://example.com/": (
        '<html><body><a href="/public">p</a>'
        '<a href="/private">x</a></body></html>'
    ),
    "http://example.com/public": "<html><body>public</body></html>",
    "http://example.com/private": "<html><body>private</body></html>",
}


def _robots_site_get(url, **kwargs):
    """Serve the robots fixture site, 404 for unknown URLs."""
    body = ROBOTS_SITE.get(url)
    if body is None:
        return Resp(status=404, content=b"")
    return Resp(text=body, status=200)


def test_robots_blocks_disallowed_path(monkeypatch):
    """A path disallowed by robots.txt is never scraped (default behavior)."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db)
    monkeypatch.setattr(scraper.session, "get", _robots_site_get)
    monkeypatch.setattr(
        Scraper, "scrape_page", lambda self, html, url: (html, {"url": url})
    )

    scraper.start_scraping(url="http://example.com/")

    scraped = {url for url, _, _ in db.get_all_pages()}
    assert "http://example.com/public" in scraped
    assert "http://example.com/private" not in scraped


def test_ignore_robots_overrides_disallow(monkeypatch):
    """--ignore-robots crawls a path that robots.txt would otherwise block."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db, ignore_robots=True)
    monkeypatch.setattr(scraper.session, "get", _robots_site_get)
    monkeypatch.setattr(
        Scraper, "scrape_page", lambda self, html, url: (html, {"url": url})
    )

    scraper.start_scraping(url="http://example.com/")

    scraped = {url for url, _, _ in db.get_all_pages()}
    assert "http://example.com/private" in scraped


def test_robots_allowed_helper(monkeypatch):
    """The robots helper allows/denies individual URLs per the rules."""
    db = _DummyDB()
    scraper = _make_scraper(db)
    monkeypatch.setattr(scraper.session, "get", _robots_site_get)

    assert scraper._robots_allowed("http://example.com/public") is True
    assert scraper._robots_allowed("http://example.com/private/x") is False


SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>http://example.com/a</loc></url>"
    "<url><loc>http://example.com/b</loc></url>"
    "</urlset>"
)


def test_sitemap_seeds_frontier(monkeypatch):
    """Sitemap <loc> URLs are parsed, validated, and seeded into the frontier."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db, sitemap=True)

    def fake_get(url, **kwargs):
        assert url == "http://example.com/sitemap.xml"
        return Resp(text=SITEMAP_XML)

    monkeypatch.setattr(scraper.session, "get", fake_get)

    seeded = scraper._seed_from_sitemap()

    assert seeded == 2
    urls = {url for url, _ in db.get_unvisited_links()}
    assert "http://example.com/a" in urls
    assert "http://example.com/b" in urls


def test_sitemap_index_followed(monkeypatch):
    """A sitemap index is followed to its child sitemaps to collect URLs."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db, sitemap=True)

    index_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>http://example.com/sm1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    child_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>http://example.com/c</loc></url>"
        "</urlset>"
    )
    mapping = {
        "http://example.com/sitemap.xml": index_xml,
        "http://example.com/sm1.xml": child_xml,
    }

    def fake_get(url, **kwargs):
        body = mapping.get(url)
        if body is None:
            return Resp(status=404, content=b"")
        return Resp(text=body)

    monkeypatch.setattr(scraper.session, "get", fake_get)

    scraper._seed_from_sitemap()

    urls = {url for url, _ in db.get_unvisited_links()}
    assert "http://example.com/c" in urls


def test_sitemap_tolerates_missing(monkeypatch):
    """A missing/non-200 sitemap seeds nothing and does not raise."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db, sitemap=True)
    monkeypatch.setattr(
        scraper.session, "get", lambda url, **k: Resp(status=404, content=b"")
    )

    assert scraper._seed_from_sitemap() == 0
    assert db.get_links_count() == 0


def test_custom_headers_cookie_auth_configured():
    """UA, headers, cookies, and basic auth are applied to the sync session."""
    db = _DummyDB()
    scraper = _make_scraper(
        db,
        user_agent="MyUA/9.9",
        headers=["X-Test: yes"],
        cookies=["session=abc"],
        auth="alice:secret",
    )

    assert scraper.session.headers["User-Agent"] == "MyUA/9.9"
    assert scraper.session.headers["X-Test"] == "yes"
    assert scraper.session.cookies.get("session") == "abc"
    assert scraper.session.auth == ("alice", "secret")


def test_custom_headers_sent_on_request():
    """The configured UA/header/cookie/auth are actually present on the wire."""
    db = _DummyDB()
    scraper = _make_scraper(
        db,
        user_agent="MyUA/9.9",
        headers=["X-Test: yes"],
        cookies=["session=abc"],
        auth="alice:secret",
    )

    captured = {}

    class CaptureTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            captured["ua"] = request.headers.get("user-agent")
            captured["xtest"] = request.headers.get("x-test")
            captured["cookie"] = request.headers.get("cookie")
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, text="ok")

    async def run():
        async with httpx.AsyncClient(
            transport=CaptureTransport(),
            headers=scraper._headers,
            cookies=scraper._cookies,
            auth=scraper._auth,
        ) as client:
            await client.get("http://example.com/")

    asyncio.run(run())

    assert captured["ua"] == "MyUA/9.9"
    assert captured["xtest"] == "yes"
    assert "session=abc" in (captured["cookie"] or "")
    assert (captured["auth"] or "").startswith("Basic ")


def test_allow_types_lets_pdf_through(monkeypatch):
    """A PDF content-type is ingested via MarkItDown when in --allow-types."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db, allow_types=["application/pdf"])

    def fake_get(url, **kwargs):
        if url.endswith("robots.txt"):
            return Resp(status=404, content=b"")
        return Resp(
            status=200,
            content_type="application/pdf",
            content=b"%PDF-1.4",
            text="",
        )

    monkeypatch.setattr(scraper.session, "get", fake_get)

    with patch("crawler_to_md.scraper.MarkItDown") as mock_markdown:
        mock_markdown.return_value.convert.return_value = "PDF TEXT"
        scraper.start_scraping(url="http://example.com/doc.pdf")

    pages = db.get_all_pages()
    assert len(pages) == 1
    assert pages[0][0] == "http://example.com/doc.pdf"
    assert pages[0][1] == "PDF TEXT"


def test_disallowed_content_type_skipped(monkeypatch):
    """A non-HTML type not in --allow-types is skipped, not stored."""
    db = DatabaseManager(":memory:")
    scraper = _make_scraper(db)  # no allow_types

    def fake_get(url, **kwargs):
        if url.endswith("robots.txt"):
            return Resp(status=404, content=b"")
        return Resp(status=200, content_type="application/pdf", content=b"%PDF")

    monkeypatch.setattr(scraper.session, "get", fake_get)

    scraper.start_scraping(url="http://example.com/doc.pdf")

    assert db.get_all_pages() == []


def _block_import(monkeypatch, prefix):
    """Force ImportError for any module whose name starts with ``prefix``."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == prefix or name.startswith(prefix + "."):
            raise ImportError(f"blocked: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_readability_missing_extra_clear_error(monkeypatch):
    """Readability extraction with trafilatura missing raises a clear error."""
    db = _DummyDB()
    scraper = _make_scraper(db, extract="readability")
    _block_import(monkeypatch, "trafilatura")

    with pytest.raises(RuntimeError) as excinfo:
        scraper.scrape_page("<html><body>hi</body></html>", "http://example.com/")

    message = str(excinfo.value).lower()
    assert "readability" in message
    assert "pip install" in message


def test_render_missing_extra_clear_error_sync(monkeypatch):
    """Sync rendering with playwright missing raises a clear, actionable error."""
    db = _DummyDB()
    scraper = _make_scraper(db, render=True)
    _block_import(monkeypatch, "playwright")

    with pytest.raises(RuntimeError) as excinfo:
        scraper._render_sync("http://example.com/")

    message = str(excinfo.value).lower()
    assert "render" in message
    assert "pip install" in message


def test_render_missing_extra_clear_error_async(monkeypatch):
    """Async rendering with playwright missing raises a clear, actionable error."""
    db = _DummyDB()
    scraper = _make_scraper(db, render=True)
    _block_import(monkeypatch, "playwright")

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(scraper._render_async("http://example.com/"))

    assert "render" in str(excinfo.value).lower()


def test_cli_passes_crawl_intelligence_flags(monkeypatch, tmp_path):
    """All new CLI flags are wired through to the Scraper constructor."""
    captured = {}

    def fake_init(
        self,
        base_url,
        exclude_patterns,
        include_url_patterns,
        db_manager,
        **kwargs,
    ):
        captured.update(kwargs)

    monkeypatch.setattr(Scraper, "__init__", fake_init)
    monkeypatch.setattr(Scraper, "start_scraping", lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, "export_to_markdown", lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, "export_to_json", lambda *a, **k: None)

    cache_folder = tmp_path / "cache"
    args = [
        "prog",
        "--url",
        "http://example.com",
        "--output-folder",
        str(tmp_path),
        "--cache-folder",
        str(cache_folder),
        "--ignore-robots",
        "--user-agent",
        "UA/1.0",
        "--sitemap",
        "--extract",
        "readability",
        "--render",
        "--header",
        "X-A: 1",
        "--cookie",
        "c=1",
        "--auth",
        "u:p",
        "--allow-types",
        "application/pdf",
    ]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()

    assert captured["ignore_robots"] is True
    assert captured["user_agent"] == "UA/1.0"
    assert captured["sitemap"] is True
    assert captured["extract"] == "readability"
    assert captured["render"] is True
    assert captured["headers"] == ["X-A: 1"]
    assert captured["cookies"] == ["c=1"]
    assert captured["auth"] == "u:p"
    assert captured["allow_types"] == ["application/pdf"]
