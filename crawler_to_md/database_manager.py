import hashlib
import logging
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _utcnow_iso():
    """
    Return the current UTC time as an ISO 8601 string.

    Returns:
        str: The current UTC timestamp (e.g. ``"2026-05-29T12:34:56.789+00:00"``).
    """
    return datetime.now(timezone.utc).isoformat()


def _content_hash(content):
    """
    Compute a stable SHA-256 hash of page content.

    Args:
        content (str | None): The page content. ``None`` is treated as an
            empty string so that missing content hashes deterministically.

    Returns:
        str: The hexadecimal SHA-256 digest of the content.
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


class DatabaseManager:
    def __init__(self, db_path):
        """
        Initialize the DatabaseManager object with the database path and create tables.

        Args:
        db_path (str): The path to the SQLite database file.
        """
        logger.debug(f"Connecting to the database at {db_path}")
        self.conn = sqlite3.connect(db_path)
        # Enable Write-Ahead Logging for better concurrency and crash safety.
        # WAL is not supported for in-memory databases, so skip it there.
        if db_path != ":memory:":
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error as exc:
                logger.warning("Could not enable WAL journal mode: %s", exc)
        self.create_tables()

    def create_tables(self):
        """
        Create tables 'pages' and 'links' if they do not exist in the database.

        For databases created before Wave 1, the additive columns introduced
        for content refresh (``content_hash``, ``fetched_at``) and crawl bounds
        (``depth``) are added via a guarded migration so existing user caches
        keep working without data loss.
        """
        with self.conn:
            logger.debug("Creating tables 'pages' and 'links' if they do not exist")
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS pages (
                          url TEXT PRIMARY KEY,
                          content TEXT,
                          metadata TEXT,
                          content_hash TEXT,
                          fetched_at TEXT)"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS links (
                          url TEXT PRIMARY KEY,
                          visited BOOLEAN,
                          depth INTEGER DEFAULT 0)"""
            )
            self._ensure_columns(
                "pages",
                {"content_hash": "content_hash TEXT", "fetched_at": "fetched_at TEXT"},
            )
            self._ensure_columns("links", {"depth": "depth INTEGER DEFAULT 0"})

    def _ensure_columns(self, table, columns):
        """
        Ensure that ``table`` contains every column in ``columns``.

        Missing columns are added with ``ALTER TABLE ... ADD COLUMN``. This is
        the safe, additive migration path for SQLite, which cannot add multiple
        columns in a single statement and offers no ``IF NOT EXISTS`` clause.

        Args:
            table (str): Name of the table to migrate. Must be a trusted,
                hard-coded identifier (never user input).
            columns (dict[str, str]): Mapping of column name to the column
                definition fragment used in the ``ADD COLUMN`` statement.
        """
        existing = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                logger.debug("Adding column %s to table %s", name, table)
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def insert_page(self, url, content, metadata):
        """
        Insert or refresh a page in the 'pages' table.

        Performs an upsert keyed on ``url``: a new page is inserted, while an
        existing page only has its ``content``/``metadata`` rewritten when the
        SHA-256 hash of ``content`` differs from the stored hash. The
        ``fetched_at`` timestamp is always refreshed so callers can tell when a
        page was last seen, even if its content was unchanged.

        Args:
            url (str): The URL of the page.
            content (str | None): The content of the page.
            metadata (str): The metadata of the page (JSON-encoded string).

        Returns:
            bool: ``True`` if the content was inserted or changed, ``False`` if
            the page already existed with identical content (only
            ``fetched_at`` refreshed).
        """
        content_hash = _content_hash(content)
        fetched_at = _utcnow_iso()
        with self.conn:
            cur = self.conn.execute(
                "SELECT content_hash FROM pages WHERE url = ?", (url,)
            )
            row = cur.fetchone()
            changed = row is None or row[0] != content_hash
            logger.debug(
                "Upserting page %s (changed=%s)", url, changed
            )
            self.conn.execute(
                """
                INSERT INTO pages (url, content, metadata, content_hash, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content = CASE
                        WHEN pages.content_hash IS NOT excluded.content_hash
                        THEN excluded.content ELSE pages.content END,
                    metadata = CASE
                        WHEN pages.content_hash IS NOT excluded.content_hash
                        THEN excluded.metadata ELSE pages.metadata END,
                    content_hash = excluded.content_hash,
                    fetched_at = excluded.fetched_at
                """,
                (url, content, metadata, content_hash, fetched_at),
            )
            return changed

    def insert_link(self, url, visited=False, depth=0):
        """
        Insert a new link into the 'links' table if it does not exist.

        Args:
            url (str | List[str]): The URL or list of URLs of the link(s).
            visited (bool): The status of the link (default is False).
            depth (int): Crawl depth of the link(s) relative to the seed URLs
                (seeds are depth 0, links discovered on them depth 1, ...).
                Defaults to ``0``.

        Returns:
            bool: True if at least one link is inserted, False if all already
            exist.
        """
        if isinstance(url, str):
            urls = [url]
        elif isinstance(url, list):
            urls = url
        else:
            raise ValueError("URL must be a string or a list of strings")

        count = 0
        with self.conn:
            for link in urls:
                logger.debug(f"Inserting a new link with URL: {link}")
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO links (url, visited, depth) "
                    "VALUES (?, ?, ?)",
                    (link, visited, depth),
                )
                if cur.rowcount > 0:
                    count += 1

            return count > 0

    def mark_link_visited(self, url):
        """
        Mark a link as visited in the 'links' table.

        Args:
        url (str): The URL of the link to mark as visited.
        """
        with self.conn:
            logger.debug(f"Marking link as visited with URL: {url}")
            self.conn.execute("UPDATE links SET visited = TRUE WHERE url = ?", (url,))

    def get_unvisited_links(self):
        """
        Retrieve all unvisited links from the 'links' table, shallowest first.

        Returns:
            list[tuple[str, int]]: List of ``(url, depth)`` tuples for every
            unvisited link, ordered by ascending depth so the crawl proceeds
            breadth-first.
        """
        with self.conn:
            logger.debug("Retrieving all unvisited links")
            cursor = self.conn.execute(
                "SELECT url, depth FROM links WHERE visited = FALSE "
                "ORDER BY depth ASC"
            )
            return cursor.fetchall()

    def get_links_count(self):
        """
        Retrieve the total number of links in the 'links' table.

        Returns:
        int: The total number of links.
        """
        with self.conn:
            logger.debug("Retrieving the total number of links")
            cursor = self.conn.execute("SELECT COUNT(*) FROM links")
            return cursor.fetchone()[0]

    def get_visited_links_count(self):
        """
        Retrieve the total number of visited links in the 'links' table.

        Returns:
        int: The total number of visited links.
        """
        with self.conn:
            logger.debug("Retrieving the total number of visited links")
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM links WHERE visited = TRUE"
            )
            return cursor.fetchone()[0]

    def get_all_pages(self):
        """
        Retrieve all pages from the 'pages' table.

        Returns:
        list: List of tuples containing page URL, content, and metadata.
        """
        with self.conn:
            logger.debug("Retrieving all pages")
            cursor = self.conn.execute("SELECT url, content, metadata FROM pages")
            return cursor.fetchall()

    def get_all_pages_full(self):
        """
        Retrieve all pages with their refresh metadata.

        Unlike :meth:`get_all_pages`, this returns the extra columns added in
        Wave 1 so callers that need provenance (e.g. YAML frontmatter) can
        access ``fetched_at`` without a per-URL lookup. It is additive: the
        legacy three-column accessor is preserved for existing callers.

        Returns:
            list[tuple]: List of ``(url, content, metadata, content_hash,
            fetched_at)`` tuples for every stored page.
        """
        with self.conn:
            logger.debug("Retrieving all pages with refresh metadata")
            cursor = self.conn.execute(
                "SELECT url, content, metadata, content_hash, fetched_at FROM pages"
            )
            return cursor.fetchall()

    def get_page(self, url):
        """
        Retrieve a single page row by URL.

        Args:
            url (str): The URL of the page to fetch.

        Returns:
            tuple | None: ``(url, content, metadata, content_hash, fetched_at)``
            if the page exists, otherwise ``None``.
        """
        with self.conn:
            cursor = self.conn.execute(
                "SELECT url, content, metadata, content_hash, fetched_at "
                "FROM pages WHERE url = ?",
                (url,),
            )
            return cursor.fetchone()

    def close(self):
        """
        Close the underlying SQLite connection if it is still open.

        This method is idempotent: calling it more than once, or after the
        connection has already been closed, is safe and has no effect.
        """
        conn = getattr(self, "conn", None)
        if conn is not None:
            logger.debug("Closing the database connection")
            conn.close()
            self.conn = None

    def __enter__(self):
        """
        Enter the runtime context and return the manager itself.

        Returns:
            DatabaseManager: This instance, ready for use within a ``with`` block.
        """
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Exit the runtime context, ensuring the database connection is closed.

        Args:
            exc_type (type | None): Exception type raised in the context, if any.
            exc_value (BaseException | None): Exception instance raised, if any.
            traceback (types.TracebackType | None): Traceback associated with the
                exception, if any.

        Returns:
            bool: ``False`` so that any exception raised within the context is
            propagated rather than suppressed.
        """
        self.close()
        return False

    def __del__(self):
        """
        Close the database connection when the object is garbage collected.

        Acts as a safety net only; the connection is guarded with
        :func:`getattr` so that a partially initialized instance (where
        ``conn`` was never assigned) does not raise during deletion.
        """
        self.close()
