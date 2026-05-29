from unittest.mock import MagicMock, patch

import pytest
import requests
import tqdm

from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.scraper import Scraper


class DummyDB(DatabaseManager):
    def __init__(self):
        pass

    def __del__(self):
        pass

    def insert_link(self, url, visited=False, depth=0):
        return True

    def get_unvisited_links(self):
        return []

    def mark_link_visited(self, url):
        pass


def test_is_valid_link():
    db = DummyDB()
    scraper = Scraper(
        base_url='https://example.com',
        exclude_patterns=['/exclude'],
        include_url_patterns=[],
        db_manager=db,
    )
    assert scraper.is_valid_link('https://example.com/page')
    assert not scraper.is_valid_link('https://example.com/exclude/page')
    assert not scraper.is_valid_link('https://other.com/')

    include_scraper = Scraper(
        base_url='https://example.com',
        exclude_patterns=[],
        include_url_patterns=['/docs'],
        db_manager=db,
    )
    assert include_scraper.is_valid_link('https://example.com/docs/page')
    assert not include_scraper.is_valid_link('https://example.com/blog')


def test_fetch_links():
    db = DummyDB()
    scraper = Scraper(
        base_url='https://example.com',
        exclude_patterns=['/exclude'],
        include_url_patterns=[],
        db_manager=db,
    )
    html = '''<html><body>
    <a href="https://example.com/page1">1</a>
    <a href="/page2">2</a>
    <a href="https://example.com/exclude/hidden">3</a>
    </body></html>'''
    links = scraper.fetch_links(url='https://example.com', html=html)
    assert links == {'https://example.com/page1', 'https://example.com/page2'}


def test_fetch_links_includes_only_matching_patterns():
    db = DummyDB()
    scraper = Scraper(
        base_url='https://example.com',
        exclude_patterns=[],
        include_url_patterns=['/page1'],
        db_manager=db,
    )
    html = '''<html><body>
    <a href="https://example.com/page1">1</a>
    <a href="/page2">2</a>
    <a href="https://example.com/page3">3</a>
    </body></html>'''
    links = scraper.fetch_links(url='https://example.com', html=html)
    assert links == {'https://example.com/page1'}




@patch('os.remove')
@patch('tempfile.NamedTemporaryFile')
def test_scrape_page_parses_content_and_metadata(mock_tempfile, mock_os_remove):
    # Arrange
    mock_file = MagicMock()
    mock_file.name = "dummy_path"
    mock_tempfile.return_value.__enter__.return_value = mock_file

    db = DummyDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    html = '<html><head><title>Test</title></head><body><p>Hello</p></body></html>'

    # Act
    with patch('crawler_to_md.scraper.MarkItDown') as mock_markdown:
        mock_markdown.return_value.convert.return_value = "Hello"
        content, metadata = scraper.scrape_page(html, 'http://example.com/test')

    # Assert
    assert content is not None
    assert 'Hello' in content
    assert metadata is not None
    assert metadata.get('title') == 'Test'

@patch('os.remove')
@patch('tempfile.NamedTemporaryFile')
def test_scrape_page_with_markitdown(mock_tempfile, mock_os_remove):
    # Arrange
    mock_file = MagicMock()
    mock_file.name = "dummy_path"
    mock_tempfile.return_value.__enter__.return_value = mock_file

    db = DummyDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    html = (
        '<html><head><title>Test</title></head><body><h1>A Title</h1>'
        '<p>This is a paragraph with <strong>bold</strong> text.</p></body></html>'
    )

    # Act
    with patch('crawler_to_md.scraper.MarkItDown') as mock_markdown:
        mock_markdown.return_value.convert.return_value = (
            "# A Title\n\nThis is a paragraph with **bold** text."
        )
        content, metadata = scraper.scrape_page(html, 'http://example.com/test')

    # Assert
    assert content is not None
    assert content == '# A Title\n\nThis is a paragraph with **bold** text.'
    assert metadata is not None
    assert metadata.get('title') == 'Test'


@patch('os.remove')
@patch('tempfile.NamedTemporaryFile')
def test_scrape_page_include_exclude(mock_tempfile, mock_os_remove):
    """
    Verify include and exclude selectors filter HTML before conversion.

    Args:
        mock_tempfile (MagicMock): Mock for NamedTemporaryFile.
        mock_os_remove (MagicMock): Mock for os.remove.
    """
    mock_file = MagicMock()
    mock_file.name = "dummy_path"
    mock_tempfile.return_value.__enter__.return_value = mock_file

    db = DummyDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
        include_filters=['p'],
        exclude_filters=['.remove'],
    )
    html = (
        '<html><body><p class="keep">Keep</p>'
        '<p class="remove">Remove</p><span>Ignore</span></body></html>'
    )

    with patch('crawler_to_md.scraper.MarkItDown') as mock_markdown:
        def convert_side_effect(path):
            """Return the HTML written to the temporary file."""
            return mock_file.write.call_args[0][0]

        mock_markdown.return_value.convert.side_effect = convert_side_effect
        content, metadata = scraper.scrape_page(html, 'http://example.com/test')

    assert 'Keep' in content
    assert 'Remove' not in content
    assert 'Ignore' not in content
    assert metadata.get('title') == ''



class ListDB(DummyDB):
    def __init__(self):
        self.links = []
        self.visited = set()
        self.pages = []

    def insert_link(self, url, visited=False, depth=0):
        urls = url if isinstance(url, list) else [url]
        inserted = False
        for u in urls:
            if u not in self.links:
                self.links.append(u)
                inserted = True
        return inserted

    def get_unvisited_links(self):
        return [(u,) for u in self.links if u not in self.visited]

    def mark_link_visited(self, url):
        self.visited.add(url)

    def get_links_count(self):
        return len(self.links)

    def get_visited_links_count(self):
        return len(self.visited)

    def insert_page(self, url, content, metadata):
        self.pages.append((url, content, metadata))

    def get_all_pages(self):
        return self.pages


def test_start_scraping_process(monkeypatch):
    db = ListDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )

    monkeypatch.setattr(Scraper, 'fetch_links', lambda self, url, html=None: set())
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    class DummyResp:
        status_code = 200
        headers = {'content-type': 'text/html'}
        content = b'<html></html>'
        text = '<html></html>'

    monkeypatch.setattr(scraper.session, 'get', lambda url, **kwargs: DummyResp())

    class DummyTqdm:
        def __init__(self, *a, **k):
            self.total = k.get('total', 0)
        def update(self, n):
            pass
        def refresh(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(tqdm, 'tqdm', lambda *a, **k: DummyTqdm(*a, **k))

    scraper.start_scraping(url='http://example.com/page')

    assert db.get_links_count() == 1
    assert db.get_visited_links_count() == 1
    assert db.pages[0][0] == 'http://example.com/page'


def test_scraper_proxy_initialization(monkeypatch):
    db = DummyDB()
    monkeypatch.setattr(Scraper, '_test_proxy', lambda self: None)
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
        proxy='http://proxy:8080'
    )
    assert scraper.session.proxies.get('http') == 'http://proxy:8080'
    assert scraper.session.proxies.get('https') == 'http://proxy:8080'


def test_scraper_socks_proxy_initialization(monkeypatch):
    db = DummyDB()
    proxy = 'socks5://localhost:9050'
    monkeypatch.setattr(Scraper, '_test_proxy', lambda self: None)
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
        proxy=proxy
    )
    assert scraper.session.proxies.get('http') == proxy
    assert scraper.session.proxies.get('https') == proxy


def test_scraper_proxy_failure_detection(monkeypatch):
    db = DummyDB()
    def fake_head(self, url, timeout=5):
        raise requests.exceptions.ProxyError("fail")

    monkeypatch.setattr(requests.Session, 'head', fake_head)
    with pytest.raises(ValueError):
        Scraper(
            base_url='http://example.com',
            exclude_patterns=[],
            include_url_patterns=[],
            db_manager=db,
            proxy='http://proxy:8080'
        )


def test_scrape_page_returns_none_for_empty_content(monkeypatch):
    db = DummyDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    html = '<html><body></body></html>'

    with patch('crawler_to_md.scraper.MarkItDown') as mock_markdown:
        mock_markdown.return_value.convert.return_value = ''
        content, metadata = scraper.scrape_page(html, 'http://example.com/empty')

    assert content is None
    assert metadata is None


def test_start_scraping_excludes_invalid_urls(monkeypatch):
    db = ListDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=['/exclude'],
        include_url_patterns=[],
        db_manager=db,
    )

    monkeypatch.setattr(Scraper, 'fetch_links', lambda self, url, html=None: set())
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    class DummyResp:
        status_code = 200
        headers = {'content-type': 'text/html'}
        content = b'<html></html>'
        text = '<html></html>'

    monkeypatch.setattr(scraper.session, 'get', lambda url, **kwargs: DummyResp())

    class DummyTqdm:
        def __init__(self, *a, **k):
            self.total = k.get('total', 0)
        def update(self, n):
            pass
        def refresh(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(tqdm, 'tqdm', lambda *a, **k: DummyTqdm(*a, **k))

    urls = [
        'http://example.com/page1',
        'http://example.com/exclude/page',
        'http://example.com/page2',
    ]

    scraper.start_scraping(urls_list=urls)

    assert 'http://example.com/exclude/page' not in db.links


def test_start_scraping_filters_discovered_links(monkeypatch):
    db = ListDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=['/exclude'],
        include_url_patterns=[],
        db_manager=db,
    )

    html = (
        '<html><body>'
        '<a href="/page1">1</a>'
        '<a href="/exclude/page">2</a>'
        '<a href="/page2">3</a>'
        '</body></html>'
    )

    class DummyResp:
        status_code = 200
        headers = {'content-type': 'text/html'}
        text = html

    monkeypatch.setattr(scraper.session, 'get', lambda url, **kwargs: DummyResp())

    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    class DummyTqdm:
        def __init__(self, *a, **k):
            self.total = k.get('total', 0)
        def update(self, n):
            pass
        def refresh(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(tqdm, 'tqdm', lambda *a, **k: DummyTqdm(*a, **k))

    scraper.start_scraping(url='http://example.com')

    assert 'http://example.com/exclude/page' not in db.links


def test_start_scraping_survives_request_exception(monkeypatch):
    """
    The crawl loop must not crash when ``session.get`` raises a network error.

    A :class:`requests.RequestException` injected on the main fetch should be
    caught: the offending link is marked as visited, no page is stored, and the
    loop terminates cleanly instead of propagating the exception.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture used to patch network and
            progress-bar dependencies.
    """
    db = ListDB()
    scraper = Scraper(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
        max_retries=0,
    )

    def boom(url, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(scraper.session, 'get', boom)
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    class DummyTqdm:
        def __init__(self, *a, **k):
            self.total = k.get('total', 0)

        def update(self, n):
            pass

        def refresh(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(tqdm, 'tqdm', lambda *a, **k: DummyTqdm(*a, **k))

    # Should not raise despite the injected network failure.
    scraper.start_scraping(url='http://example.com/page')

    # The failing link is marked visited so the loop terminates, and no page
    # was scraped.
    assert ('http://example.com/page',) not in db.get_unvisited_links()
    assert db.get_visited_links_count() == 1
    assert db.pages == []


class FakeResp:
    """Minimal stand-in for ``requests.Response`` used in retry tests."""

    def __init__(self, status_code, text='', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {'content-type': 'text/html'}


def _make_scraper(db, **kwargs):
    """Build a Scraper with sensible test defaults."""
    params = dict(
        base_url='http://example.com',
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    params.update(kwargs)
    return Scraper(**params)


def test_get_with_retry_succeeds_after_429(monkeypatch):
    """A 429 followed by a 200 should retry once and return the success."""
    db = DummyDB()
    scraper = _make_scraper(db, max_retries=3)

    responses = [FakeResp(429), FakeResp(200, text='ok')]
    calls = {'i': 0}

    def fake_get(url, **kwargs):
        resp = responses[calls['i']]
        calls['i'] += 1
        return resp

    slept = []
    monkeypatch.setattr(scraper.session, 'get', fake_get)
    monkeypatch.setattr('crawler_to_md.scraper.time.sleep', lambda s: slept.append(s))

    response = scraper._get_with_retry('http://example.com')

    assert response.status_code == 200
    assert calls['i'] == 2  # exactly one retry
    assert len(slept) == 1  # one backoff slept between attempts


def test_start_scraping_retries_429_then_scrapes(monkeypatch):
    """The crawl loop scrapes a page once a 429 clears, not skipping it."""
    db = ListDB()
    scraper = _make_scraper(db, max_retries=3)

    responses = [FakeResp(429), FakeResp(200, text='<html></html>')]
    calls = {'i': 0}

    def fake_get(url, **kwargs):
        resp = responses[min(calls['i'], len(responses) - 1)]
        calls['i'] += 1
        return resp

    monkeypatch.setattr(scraper.session, 'get', fake_get)
    monkeypatch.setattr('crawler_to_md.scraper.time.sleep', lambda s: None)
    monkeypatch.setattr(Scraper, 'fetch_links', lambda self, url, html=None: set())
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    scraper.start_scraping(url='http://example.com/page')

    # The page was eventually scraped (not skipped because of the initial 429).
    assert db.pages and db.pages[0][0] == 'http://example.com/page'
    assert db.get_visited_links_count() == 1


def test_retry_after_header_respected(monkeypatch):
    """A numeric Retry-After header dictates the backoff sleep duration."""
    db = DummyDB()
    scraper = _make_scraper(db, max_retries=2)

    responses = [
        FakeResp(503, headers={'content-type': 'text/html', 'Retry-After': '7'}),
        FakeResp(200, text='ok'),
    ]
    calls = {'i': 0}

    def fake_get(url, **kwargs):
        resp = responses[calls['i']]
        calls['i'] += 1
        return resp

    slept = []
    monkeypatch.setattr(scraper.session, 'get', fake_get)
    monkeypatch.setattr('crawler_to_md.scraper.time.sleep', lambda s: slept.append(s))

    response = scraper._get_with_retry('http://example.com')

    assert response.status_code == 200
    assert slept == [7.0]


def test_timeout_passed_through(monkeypatch):
    """The configured timeout is forwarded to every session.get call."""
    db = DummyDB()
    scraper = _make_scraper(db, timeout=42)

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResp(200, text='ok')

    monkeypatch.setattr(scraper.session, 'get', fake_get)
    scraper._get_with_retry('http://example.com')

    assert captured.get('timeout') == 42


def test_max_pages_enforced(monkeypatch):
    """No more than max_pages pages are scraped even when more are discovered."""
    db = DatabaseManager(':memory:')
    scraper = _make_scraper(db, max_pages=2)

    html = (
        '<html><body>'
        '<a href="/p1">1</a><a href="/p2">2</a>'
        '<a href="/p3">3</a><a href="/p4">4</a>'
        '</body></html>'
    )
    monkeypatch.setattr(
        scraper.session, 'get', lambda url, **k: FakeResp(200, text=html)
    )
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    scraper.start_scraping(url='http://example.com')

    assert len(db.get_all_pages()) == 2


def test_max_depth_limits_discovery(monkeypatch):
    """max_depth=0 crawls only seeds; max_depth=1 discovers one level."""
    html = '<html><body><a href="/child">c</a></body></html>'

    db0 = DatabaseManager(':memory:')
    scraper0 = _make_scraper(db0, max_depth=0)
    monkeypatch.setattr(
        scraper0.session, 'get', lambda url, **k: FakeResp(200, text=html)
    )
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )
    scraper0.start_scraping(url='http://example.com')
    # Only the seed is ever inserted; the child is never discovered.
    assert db0.get_links_count() == 1

    db1 = DatabaseManager(':memory:')
    scraper1 = _make_scraper(db1, max_depth=1)
    monkeypatch.setattr(
        scraper1.session, 'get', lambda url, **k: FakeResp(200, text=html)
    )
    scraper1.start_scraping(url='http://example.com')
    # Seed (depth 0) plus its one discovered child (depth 1).
    assert db1.get_links_count() == 2


def test_max_time_stops_loop(monkeypatch):
    """The crawl halts once max_time elapses, leaving discovered pages unscraped."""
    db = DatabaseManager(':memory:')
    scraper = _make_scraper(db, max_time=10)

    html = '<html><body><a href="/p1">1</a><a href="/p2">2</a></body></html>'
    monkeypatch.setattr(
        scraper.session, 'get', lambda url, **k: FakeResp(200, text=html)
    )
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    # Fake monotonic-ish clock: start_time=0, crawl_start=0, first bound check
    # 0 (under limit), second iteration's check 100 (over limit -> stop).
    times = iter([0, 0, 0, 100])
    monkeypatch.setattr('crawler_to_md.scraper.time.time', lambda: next(times, 100))

    scraper.start_scraping(url='http://example.com')

    # Only the seed page was scraped before the time bound tripped.
    assert len(db.get_all_pages()) == 1
