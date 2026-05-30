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
        assert db.get_unvisited_links() == [('http://example.com', 0)]

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
    assert set(db.get_unvisited_links()) == {('http://a', 0), ('http://b', 0)}


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


def test_insert_page_upsert_only_rewrites_on_change():
    """
    insert_page upserts: new content writes, identical content is a no-op.

    The return value reports whether content was (re)written, and metadata is
    only rewritten when the content hash changes (content drives the hash).
    """
    db = DatabaseManager(':memory:')

    # New page -> written.
    assert db.insert_page('http://a', 'v1', '{"k": 1}') is True
    assert db.get_page('http://a')[1] == 'v1'

    # Same content -> no rewrite, even if metadata differs.
    assert db.insert_page('http://a', 'v1', '{"k": 999}') is False
    assert db.get_page('http://a')[1] == 'v1'
    assert db.get_page('http://a')[2] == '{"k": 1}'  # metadata unchanged

    # Changed content -> rewritten, metadata updated too.
    assert db.insert_page('http://a', 'v2', '{"k": 2}') is True
    assert db.get_page('http://a')[1] == 'v2'
    assert db.get_page('http://a')[2] == '{"k": 2}'


def test_insert_page_always_refreshes_fetched_at():
    """fetched_at is set on insert and refreshed even when content is unchanged."""
    db = DatabaseManager(':memory:')
    db.insert_page('http://a', 'v1', '{}')
    first_fetched = db.get_page('http://a')[4]
    assert first_fetched is not None
    # Re-insert identical content; fetched_at must still be populated.
    db.insert_page('http://a', 'v1', '{}')
    assert db.get_page('http://a')[4] is not None


def test_migration_adds_columns_to_legacy_db(tmp_path):
    """
    Opening a pre-Wave-1 database adds the new columns without losing data.

    A legacy schema (no content_hash/fetched_at/depth) is created directly,
    then opened through DatabaseManager which must migrate it additively.
    """
    db_path = str(tmp_path / 'legacy.sqlite')
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE pages (url TEXT PRIMARY KEY, content TEXT, metadata TEXT)"
    )
    conn.execute("CREATE TABLE links (url TEXT PRIMARY KEY, visited BOOLEAN)")
    conn.execute(
        "INSERT INTO pages (url, content, metadata) VALUES "
        "('http://a', 'old', '{}')"
    )
    conn.execute("INSERT INTO links (url, visited) VALUES ('http://a', 0)")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_path)
    try:
        page_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(pages)")}
        link_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(links)")}
        assert {'content_hash', 'fetched_at'} <= page_cols
        assert 'depth' in link_cols

        # Existing data is preserved.
        assert db.get_page('http://a')[1] == 'old'
        assert db.get_unvisited_links() == [('http://a', 0)]

        # Upsert works against the migrated legacy row (hash was NULL).
        assert db.insert_page('http://a', 'old', '{}') is True
        assert db.insert_page('http://a', 'old', '{}') is False
    finally:
        db.close()
