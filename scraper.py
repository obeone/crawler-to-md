import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urldefrag
import logging
import trafilatura
import json
from database_manager import DatabaseManager

logger = logging.getLogger(__name__)

class Scraper:
    def __init__(self, base_url, exclude_patterns, db_manager: DatabaseManager):
        """
        Initialize the Scraper object with base URL, exclude patterns, and database manager.
        Log the initialization process.

        Args:
        base_url (str): The base URL to start scraping from.
        exclude_patterns (list): List of patterns to exclude from scraping.
        db_manager (DatabaseManager): The database manager object for storing scraped data.
        """
        logger.debug(f"Initializing Scraper with base URL: {base_url}")
        self.base_url = base_url
        self.exclude_patterns = exclude_patterns or []
        self.db_manager = db_manager

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
        if not link.startswith(self.base_url):
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
        logger.debug(f'Fetching links from {url}')
        try:
            if not html:
                # Send a GET request to the URL
                response = requests.get(url)
                if response.status_code != 200:
                    logger.warning(f'Failed to fetch {url} with status code {response.status_code}')
                    return []
                else:
                    content = response.content
            else:
                content = html

            # Parse the content using BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            # Extract all anchor tags and join the URLs
            links = [urljoin(url, a.get('href')) for a in soup.find_all('a', href=True)]
            # Remove fragments and filter valid links
            links = [urldefrag(link)[0] for link in links if self.is_valid_link(urldefrag(link)[0])]
            # Log the number of valid links found
            logger.debug(f"Found {len(links)} valid links on {url}")
            return set(links)
        except requests.RequestException as e:
            logger.error(f'Error fetching {url}: {e}')
            return []

    def scrape_page(self, url):
        """
        Scrape the content and metadata from the given URL.
        Log the scraping process and outcome.

        Args:
        url (str): The URL to scrape.

        Returns:
        tuple: A tuple containing the raw content, the extracted content and metadata of the page.
        """
        logger.info(f'Scraping page {url}')
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            content = trafilatura.extract(downloaded, include_formatting=True, include_links=True, include_tables=True)
            metadata = trafilatura.metadata.extract_metadata(downloaded).as_dict()
            logger.debug(f"Successfully scraped content and metadata from {url}")
            return downloaded, content, metadata
        else:
            logger.warning(f'Failed to download or extract content from {url}')
            return None, None, None

    def start_scraping(self, url):
        """
        Start the scraping process from the given URL.
        Log the start and end of the scraping process.

        Args:
        url (str): The URL to start scraping from.
        """
        logger.info(f"Starting scraping process from {url}")
        self.db_manager.insert_link(url)
            
        while True:
            unvisited_links = self.db_manager.get_unvisited_links()
            if not unvisited_links:
                logger.info('No more links to visit. Exiting.')
                break
            for link in unvisited_links:
                url = link[0]
                raw, content, metadata = self.scrape_page(url)
                self.db_manager.insert_page(url, content, json.dumps(metadata))
                new_links = self.fetch_links(url=url, html=raw)
                
                for new_url in new_links:
                    self.db_manager.insert_link(new_url)
                    logger.debug(f"Inserted new link {new_url} into the database")
                self.db_manager.mark_link_visited(url)

