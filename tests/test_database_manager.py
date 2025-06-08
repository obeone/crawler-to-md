import os
import tempfile
from src.database_manager import DatabaseManager


def test_database_operations():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, 'test.db')
        db = DatabaseManager(db_path)

        # Insert link and verify count
        assert db.insert_link('http://example.com') is True
        assert db.get_links_count() == 1
        assert db.get_unvisited_links() == [('http://example.com',)]

        # Mark link visited
        db.mark_link_visited('http://example.com')
        assert db.get_visited_links_count() == 1
        assert db.get_unvisited_links() == []

        # Insert page and read back
        db.insert_page('http://example.com', 'content', '{}')
        pages = db.get_all_pages()
        assert pages == [('http://example.com', 'content', '{}')]
