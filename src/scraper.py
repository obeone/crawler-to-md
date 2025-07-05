import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urldefrag
from . import log_setup
from markitdown import MarkItDown
import json
from .database_manager import DatabaseManager
from tqdm import tqdm
import time
import tempfile
import os


logger = log_setup.get_logger()
logger.name = "Scraper"


class Scraper:
    def __init__(self, base_url, exclude_patterns, db_manager: DatabaseManager, rate_limit=0, delay=0):
        """
        Initialize the Scraper object with base URL, exclude patterns, and database manager.
        Log the initialization process.

        Args:
        base_url (str): The base URL to start scraping from.
        exclude_patterns (list): List of patterns to exclude from scraping.
        db_manager (DatabaseManager): The database manager object for storing scraped data.
        rate_limit (int): Maximum number of requests per minute.
        delay (float): Delay between requests in seconds.
        """
        logger.debug(f"Initializing Scraper with base URL: {base_url}")
        self.base_url = base_url
        self.exclude_patterns = exclude_patterns or []
        self.db_manager = db_manager
        self.rate_limit = rate_limit
        self.delay = delay

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
        Retrieve all valid links from a specified URL or provided HTML content.
        
        If HTML content is not provided, sends a GET request to the URL and parses the response. Extracts anchor tags, normalizes and filters links based on validity criteria, and returns a set of valid links. Returns an empty list if the request fails.
        
        Parameters:
            url (str): The URL to extract links from.
            html (str, optional): HTML content to parse instead of fetching from the URL.
        
        Returns:
            set: A set of valid, normalized links found on the page.
        """
        logger.debug(f"Fetching links from {url}")
        try:
            if not html:
                # Send a GET request to the URL
                response = requests.get(url)
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
            links = [urljoin(url, a.get("href")) for a in soup.find_all("a", href=True)]
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
        Extracts the main content and page title from HTML, converting the content to Markdown format.
        
        Parameters:
            html (str): The HTML content of the page.
            url (str): The URL of the page being scraped.
        
        Returns:
            tuple: A tuple containing the Markdown-formatted content (str) and a metadata dictionary with the page title. Returns (None, None) if an error occurs during extraction.
        """
        logger.info(f"Scraping page {url}")

        try:
            # Parse the content using BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            
            # Extract title from the page
            title = soup.title.string if soup.title else ""
            
            metadata = {"title": title}
            
            # Convert the HTML to Markdown
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix=".html") as tmp:
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
        Start the scraping workflow from a single URL or a list of URLs, managing link validation, progress tracking, rate limiting, and database integration.
        
        If a list of URLs is provided, only valid URLs are processed. The method iteratively fetches unvisited links from the database, retrieves their content, extracts and stores page data and metadata, discovers new links (unless working from a predefined list), and marks links as visited. Progress is tracked with a progress bar, and optional rate limiting and request delays are enforced.
        """
        # Validate and insert the provided URLs into the database
        if urls_list:
            # Iterate through the list to check for valid URLs
            for url in urls_list:
                if not self.is_valid_link(url):
                    logger.warning(f"Skipping invalid URL: {url}")
                    urls_list.remove(url)  # Remove invalid URLs from the list

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
                            logger.debug(f"Rate limit reached, sleeping for {sleep_time} seconds")
                            time.sleep(sleep_time)
                        # Reset the rate limit tracker
                        request_count = 0
                        start_time = time.time()

                # Wait for the specified self.delay before making the next request
                if self.delay > 0:
                    logger.debug(f"self.delaying for {self.delay} seconds before next request")
                    time.sleep(self.delay)

                pbar.update(1)  # Update the progress bar
                url = link[0]  # Extract the URL from the link tuple

                # Attempt to fetch the page content
                response = requests.get(url)

                # Increment request count for rate limiting
                request_count += 1

                # Check for a successful response and correct content type
                if response.status_code != 200 or not response.headers.get(
                    "content-type", ""
                ).startswith("text/html"):
                    # Mark the link as visited and log the reason for skipping
                    self.db_manager.mark_link_visited(url)
                    logger.info(
                        f"Skipping link {url} due to invalid status code or content type"
                    )
                    continue

                # Extract the HTML content from the response
                html = response.text

                # Scrape the page for content and metadata
                content, metadata = self.scrape_page(html, url)

                # Insert the scraped data into the database
                self.db_manager.insert_page(url, content, json.dumps(metadata))

                # Fetch and insert new links found on the page, if not working from a predefined list
                if not urls_list:
                    new_links = self.fetch_links(html=html, url=url)

                    # Count and insert new links into the database
                    real_new_links_count = 0
                    for new_url in new_links:
                        if self.db_manager.insert_link(new_url):
                            real_new_links_count += 1
                            logger.debug(f"Inserted new link {new_url} into the database")

                    # Update the progress bar total with the count of new links
                    if real_new_links_count:
                        pbar.total += real_new_links_count
                        pbar.refresh()

                # Mark the current link as visited in the database
                self.db_manager.mark_link_visited(url)

        # Close the progress bar upon completion of the scraping process
        pbar.close()
