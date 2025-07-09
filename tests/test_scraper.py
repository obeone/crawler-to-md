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

    def insert_link(self, url, visited=False):
        return True

    def get_unvisited_links(self):
        return []

    def mark_link_visited(self, url):
        pass


def test_is_valid_link():
    db = DummyDB()
    scraper = Scraper(
        base_url='https://example.com', exclude_patterns=['/exclude'], db_manager=db
    )
    assert scraper.is_valid_link('https://example.com/page')
    assert not scraper.is_valid_link('https://example.com/exclude/page')
    assert not scraper.is_valid_link('https://other.com/')


def test_fetch_links():
    db = DummyDB()
    scraper = Scraper(
        base_url='https://example.com', exclude_patterns=['/exclude'], db_manager=db
    )
    html = '''<html><body>
    <a href="https://example.com/page1">1</a>
    <a href="/page2">2</a>
    <a href="https://example.com/exclude/hidden">3</a>
    </body></html>'''
    links = scraper.fetch_links(url='https://example.com', html=html)
    assert links == {'https://example.com/page1', 'https://example.com/page2'}




@patch('os.remove')
@patch('tempfile.NamedTemporaryFile')
def test_scrape_page_parses_content_and_metadata(mock_tempfile, mock_os_remove):
    # Arrange
    mock_file = MagicMock()
    mock_file.name = "dummy_path"
    mock_tempfile.return_value.__enter__.return_value = mock_file

    db = DummyDB()
    scraper = Scraper(base_url='http://example.com', exclude_patterns=[], db_manager=db)
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
    scraper = Scraper(base_url='http://example.com', exclude_patterns=[], db_manager=db)
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



class ListDB(DummyDB):
    def __init__(self):
        self.links = []
        self.visited = set()
        self.pages = []

    def insert_link(self, url, visited=False):
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
    scraper = Scraper(base_url='http://example.com', exclude_patterns=[], db_manager=db)

    monkeypatch.setattr(Scraper, 'fetch_links', lambda self, url, html=None: set())
    monkeypatch.setattr(
        Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url})
    )

    class DummyResp:
        status_code = 200
        headers = {'content-type': 'text/html'}
        content = b'<html></html>'
        text = '<html></html>'

    monkeypatch.setattr(scraper.session, 'get', lambda url: DummyResp())

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
        base_url='http://example.com', exclude_patterns=[], db_manager=db, proxy='http://proxy:8080'
    )
    assert scraper.session.proxies.get('http') == 'http://proxy:8080'
    assert scraper.session.proxies.get('https') == 'http://proxy:8080'


def test_scraper_socks_proxy_initialization(monkeypatch):
    db = DummyDB()
    proxy = 'socks5://localhost:9050'
    monkeypatch.setattr(Scraper, '_test_proxy', lambda self: None)
    scraper = Scraper(
        base_url='http://example.com', exclude_patterns=[], db_manager=db, proxy=proxy
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
            base_url='http://example.com', exclude_patterns=[], db_manager=db, proxy='http://proxy:8080'
        )


def test_scrape_page_returns_none_for_empty_content(monkeypatch):
    db = DummyDB()
    scraper = Scraper(base_url='http://example.com', exclude_patterns=[], db_manager=db)
    html = '<html><body></body></html>'

    with patch('crawler_to_md.scraper.MarkItDown') as mock_markdown:
        mock_markdown.return_value.convert.return_value = ''
        content, metadata = scraper.scrape_page(html, 'http://example.com/empty')

    assert content is None
    assert metadata is None
