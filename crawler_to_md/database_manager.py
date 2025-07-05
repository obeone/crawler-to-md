import logging
import sqlite3

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path):
        """
        Initialize the DatabaseManager object with the database path and create tables.

        Args:
        db_path (str): The path to the SQLite database file.
        """
        logger.debug(f"Connecting to the database at {db_path}")
        self.conn = sqlite3.connect(db_path)
        self.create_tables()

    def create_tables(self):
        """
        Create tables 'pages' and 'links' if they do not exist in the database.
        """
        with self.conn:
            logger.debug("Creating tables 'pages' and 'links' if they do not exist")
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS pages (
                          url TEXT PRIMARY KEY,
                          content TEXT,
                          metadata TEXT)"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS links (
                          url TEXT PRIMARY KEY,
                          visited BOOLEAN)"""
            )

    def insert_page(self, url, content, metadata):
        """
        Insert a new page into the 'pages' table.

        Args:
        url (str): The URL of the page.
        content (str): The content of the page.
        metadata (str): The metadata of the page.
        """
        with self.conn:
            logger.debug(f"Inserting a new page with URL: {url}")
            self.conn.execute(
                "INSERT OR IGNORE INTO pages (url, content, metadata) VALUES (?, ?, ?)",
                (url, content, metadata),
            )

    def insert_link(self, url, visited=False):
        """
        Insert a new link into the 'links' table if it does not exist.

        Args:
        url (str | List[str]): The URL or list of URLs of the link(s).
        visited (bool): The status of the link (default is False).

        Returns:
        bool: True if the link is inserted, False if it already exists.
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
                    "INSERT OR IGNORE INTO links (url, visited) VALUES (?, ?)",
                    (link, visited),
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
        Retrieve all unvisited links from the 'links' table.

        Returns:
        list: List of unvisited links.
        """
        with self.conn:
            logger.debug("Retrieving all unvisited links")
            cursor = self.conn.execute("SELECT url FROM links WHERE visited = FALSE")
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

    def __del__(self):
        """
        Close the database connection when the object is deleted.
        """
        logger.debug("Closing the database connection")
        self.conn.close()
