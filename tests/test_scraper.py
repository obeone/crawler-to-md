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
