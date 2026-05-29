import os
import sqlite3
import tempfile

import pytest

from crawler_to_md.database_manager import DatabaseManager


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


def test_insert_link_duplicates_and_list():
    db = DatabaseManager(':memory:')
    assert db.insert_link('http://a') is True
    # duplicate single link should return False
    assert db.insert_link('http://a') is False
    # insert list with one new and one duplicate
    assert db.insert_link(['http://b', 'http://a']) is True
    # total links should be 2
    assert db.get_links_count() == 2
    assert set(db.get_unvisited_links()) == {('http://a',), ('http://b',)}


def test_context_manager_closes_connection():
    """
    Using DatabaseManager as a context manager closes the connection on exit.

    Inside the ``with`` block the database is usable; once the block exits the
    underlying connection is closed (``self.conn`` set to ``None``) and any
    further query raises, proving the resource was released.
    """
    with DatabaseManager(':memory:') as db:
        assert db.insert_link('http://example.com') is True
        assert db.get_links_count() == 1
        conn = db.conn
        assert conn is not None

    # After the context exits the connection is released.
    assert db.conn is None
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_close_is_idempotent():
    """Calling ``close`` multiple times is safe and does not raise."""
    db = DatabaseManager(':memory:')
    db.close()
    # A second close must be a no-op rather than an error.
    db.close()
    assert db.conn is None
