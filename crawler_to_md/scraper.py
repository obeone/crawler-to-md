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
        Initializes a Scraper instance with base URL, exclusion patterns, database manager, and optional rate limiting, delay, and proxy settings.
        
        Parameters:
            base_url (str): The root URL from which scraping begins.
            exclude_patterns (list): URL patterns to exclude from scraping.
            rate_limit (int): Maximum number of requests allowed per minute.
            delay (float): Time in seconds to wait between requests.
            proxy (str, optional): Proxy URL to route HTTP requests through.
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

    def is_valid_link(self, link):
        """
        Determine whether a given URL is eligible for scraping based on the base URL and exclusion patterns.
        
        A link is considered valid if it starts with the configured base URL and does not contain any of the specified exclusion patterns.
        
        Parameters:
            link (str): The URL to validate.
        
        Returns:
            bool: True if the link is valid for scraping; False otherwise.
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
        Retrieve all valid links from a specified URL or provided HTML content.
        
        If HTML is not provided, the method fetches the page content using an HTTP GET request. Extracts and resolves all anchor tag links, removes URL fragments, and filters them using the link validation logic. Returns a set of valid links found on the page. Returns an empty list if the request fails.
         
        Parameters:
            url (str): The URL to extract links from.
            html (str, optional): HTML content to parse instead of fetching from the URL.
        
        Returns:
            set: A set of valid, filtered links found on the page, or an empty set if none are found or on error.
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

            logger.debug(f"Successfully scraped content and metadata from {url}")
            return markdown, metadata

        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return None, None

    def start_scraping(self, url=None, urls_list=[]):
        """
        Starts the web scraping process from a given URL or list of URLs, managing progress, rate limiting, and database integration.
        
        If a list of URLs is provided, only valid URLs are inserted into the database; otherwise, a single URL is used as the starting point. The method iteratively fetches unvisited links from the database, retrieves and processes each page, stores scraped content and metadata, and discovers new links to continue scraping (unless a predefined list is used). Progress is tracked with a progress bar, and rate limiting and delays are enforced as configured. The process continues until all discovered links have been visited.
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
