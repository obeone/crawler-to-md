from src.database_manager import DatabaseManager
from src.scraper import Scraper


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
    scraper = Scraper(base_url='https://example.com', exclude_patterns=['/exclude'], db_manager=db)
    assert scraper.is_valid_link('https://example.com/page')
    assert not scraper.is_valid_link('https://example.com/exclude/page')
    assert not scraper.is_valid_link('https://other.com/')


def test_fetch_links():
    db = DummyDB()
    scraper = Scraper(base_url='https://example.com', exclude_patterns=['/exclude'], db_manager=db)
    html = '''<html><body>
    <a href="https://example.com/page1">1</a>
    <a href="/page2">2</a>
    <a href="https://example.com/exclude/hidden">3</a>
    </body></html>'''
    links = scraper.fetch_links(url='https://example.com', html=html)
    assert links == {'https://example.com/page1', 'https://example.com/page2'}


def test_scrape_page_parses_content_and_metadata():
    db = DummyDB()
    scraper = Scraper(base_url='http://example.com', exclude_patterns=[], db_manager=db)
    html = '<html><head><title>Test</title></head><body><p>Hello</p></body></html>'
    content, metadata = scraper.scrape_page(html, 'http://example.com/test')
    assert 'Hello' in content
    assert metadata.get('title') == 'Test'
    assert metadata.get('url') == 'http://example.com/test'

import requests
import tqdm

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
    monkeypatch.setattr(Scraper, 'scrape_page', lambda self, html, url: ('# MD', {'url': url}))

    class DummyResp:
        status_code = 200
        headers = {'content-type': 'text/html'}
        content = b'<html></html>'

    monkeypatch.setattr(requests, 'get', lambda url: DummyResp())

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
