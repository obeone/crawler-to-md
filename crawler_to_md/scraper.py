import json
import os
import tempfile
import time
from urllib.parse import urldefrag, urljoin

import requests
from bs4 import BeautifulSoup, Tag
from markitdown import MarkItDown
from tqdm import tqdm

from . import log_setup
from .database_manager import DatabaseManager

logger = log_setup.get_logger()
logger.name = "Scraper"


class Scraper:
    def __init__(
        self,
        base_url,
        exclude_patterns,
        db_manager: DatabaseManager,
        rate_limit=0,
        delay=0,
        proxy=None,
    ):
        """
        Initialize the Scraper object.
        Log the initialization process.

        Args:
            base_url (str): The base URL to start scraping from.
            exclude_patterns (list): List of patterns to exclude from scraping.
            db_manager (DatabaseManager): The database manager object.
            rate_limit (int): Maximum number of requests per minute.
            delay (float): Delay between requests in seconds.
            proxy (str, optional): Proxy URL for HTTP or SOCKS requests.

        Raises:
            ValueError: If a proxy is provided but unreachable.
        """
        logger.debug(f"Initializing Scraper with base URL: {base_url}")
        self.base_url = base_url
        self.exclude_patterns = exclude_patterns or []
        self.db_manager = db_manager
        self.rate_limit = rate_limit
        self.delay = delay
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.proxy = proxy

        if proxy:
            self._test_proxy()

    def _test_proxy(self):
        """
        Ensure the configured proxy is reachable.

        Raises:
            ValueError: If the proxy cannot fetch the base URL.
        """
        try:
            self.session.head(self.base_url, timeout=5)
        except requests.RequestException as exc:
            raise ValueError(f"Proxy unreachable: {exc}") from exc

    def is_valid_link(self, link):
        """
        Check if the given link is valid for scraping.
        Log the result of the validation.

        Args:
            link (str): The link to be checked.

        Returns:
            bool: True if the link is valid, False otherwise.
        """
        valid = True
        if self.base_url and not link.startswith(self.base_url):
            valid = False
        for pattern in self.exclude_patterns:
            if pattern in link:
                valid = False
        logger.debug(f"Link validation for {link}: {valid}")
        return valid

    def fetch_links(self, url, html=None):
        """
        Fetch all valid links from the given URL.
        Log the fetching process and outcome.

        Args:
            url (str): The URL to fetch links from.
            html (str, optional): The HTML content of the page.

        Returns:
            set: Set of valid links found on the page.
        """
        logger.debug(f"Fetching links from {url}")
        try:
            if not html:
                # Send a GET request to the URL
                response = self.session.get(url)
                if response.status_code != 200:
                    logger.warning(
                        f"Failed to fetch {url} with status code {response.status_code}"
                    )
                    return []
                else:
                    content = response.text
            else:
                content = html

            # Parse the content using BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            # Extract all anchor tags and join the URLs
            links = []
            for a in soup.find_all("a", href=True):
                if isinstance(a, Tag):
                    href = a.get("href")
                    if href:
                        if isinstance(href, list):
                            href = href[0]
                        links.append(urljoin(url, str(href)))

            # Remove fragments and filter valid links
            links = [
                urldefrag(link)[0]
                for link in links
                if self.is_valid_link(urldefrag(link)[0])
            ]
            # Log the number of valid links found
            logger.debug(f"Found {len(links)} valid links on {url}")
            return set(links)
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {e}")
            return []

    def scrape_page(self, html, url):
        """
        Scrape the content and metadata from the given URL.
        Log the scraping process and outcome.

        Args:
            html (str): The HTML content of the page.
            url (str): The URL to scrape.

        Returns:
            tuple: A tuple containing the extracted content and metadata of the page.
        """
        logger.info(f"Scraping page {url}")

        try:
            # Parse the content using BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Extract title from the page
            title = soup.title.string if soup.title else ""

            metadata = {"title": title}

            # Convert the HTML to Markdown
            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, suffix=".html"
            ) as tmp:
                tmp.write(html)
                tmp_path = tmp.name

            markdown = str(MarkItDown().convert(tmp_path))

            os.remove(tmp_path)

            if not markdown.strip():
                logger.warning("No content scraped from %s", url)
                return None, None

            logger.debug(
                "Successfully scraped content and metadata from %s", url
            )
            return markdown, metadata

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None, None

    def start_scraping(self, url=None, urls_list=[]):
        """
        Initiates the scraping process for a single URL or a list of URLs.
        It validates URLs, logs the scraping process, and manages the
        progress of scraping through the database.

        Args:
            url (str, optional): A single URL to start scraping from. Defaults to None.
            urls_list (list, optional): A list of URLs to scrape.
        """
        # Validate and insert the provided URLs into the database
        if urls_list:
            # Iterate through the list to check for valid URLs
            for url_item in urls_list:
                if not self.is_valid_link(url_item):
                    logger.warning(f"Skipping invalid URL: {url_item}")
                    urls_list.remove(url_item)  # Remove invalid URLs from the list

            # Insert the validated list of URLs into the database
            self.db_manager.insert_link(urls_list)
        elif url:
            # Insert a single URL if provided and valid
            self.db_manager.insert_link(url)

        # Log the start of the scraping process
        logger.info("Starting scraping process")

        # Initialize a progress bar to track scraping progress
        pbar = tqdm(
            total=self.db_manager.get_links_count(),
            initial=self.db_manager.get_visited_links_count(),
            desc="Scraping",
            unit="link",
        )

        # Initialize rate limit tracking variables
        request_count = 0
        start_time = time.time()

        # Begin the scraping loop
        while True:
            # Fetch a list of unvisited links from the database
            unvisited_links = self.db_manager.get_unvisited_links()

            # Exit the loop if there are no more links to visit
            if not unvisited_links:
                logger.info("No more links to visit. Exiting.")
                break

            # Process each unvisited link
            for link in unvisited_links:
                # Check rate limit
                if self.rate_limit > 0:
                    current_time = time.time()
                    elapsed_time = current_time - start_time
                    if request_count >= self.rate_limit:
                        sleep_time = 60 - elapsed_time
                        if sleep_time > 0:
                            logger.debug(
                                f"Rate limit reached, sleeping for {sleep_time} seconds"
                            )
                            time.sleep(sleep_time)
                        # Reset the rate limit tracker
                        request_count = 0
                        start_time = time.time()

                # Wait for the specified self.delay before making the next request
                if self.delay > 0:
                    logger.debug(
                        f"Delaying for {self.delay} seconds before next request"
                    )
                    time.sleep(self.delay)

                pbar.update(1)  # Update the progress bar
                url = link[0]  # Extract the URL from the link tuple

                # Attempt to fetch the page content
                response = self.session.get(url)

                # Increment request count for rate limiting
                request_count += 1

                # Check for a successful response and correct content type
                if response.status_code != 200 or not response.headers.get(
                    "content-type", ""
                ).startswith("text/html"):
                    # Mark the link as visited and log the reason for skipping
                    self.db_manager.mark_link_visited(url)
                    logger.info(
                        "Skipping link %s due to invalid status code or content type",
                        url,
                    )
                    continue

                # Extract the HTML content from the response
                html = response.text

                # Scrape the page for content and metadata
                content, metadata = self.scrape_page(html, url)

                # Insert the scraped data into the database
                self.db_manager.insert_page(url, content, json.dumps(metadata))

                # Fetch and insert new links found on the page,
                # if not working from a predefined list
                if not urls_list:
                    new_links = self.fetch_links(html=html, url=url)

                    # Count and insert new links into the database
                    real_new_links_count = 0
                    for new_url in new_links:
                        if self.db_manager.insert_link(new_url):
                            real_new_links_count += 1
                            logger.debug(
                                f"Inserted new link {new_url} into the database"
                            )

                    # Update the progress bar total with the count of new links
                    if real_new_links_count:
                        pbar.total += real_new_links_count
                        pbar.refresh()

                # Mark the current link as visited in the database
                self.db_manager.mark_link_visited(url)

        # Close the progress bar upon completion of the scraping process
        pbar.close()
