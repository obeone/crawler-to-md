import copy
import json
import logging
import os
import random
import tempfile
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urldefrag, urljoin

import requests
from bs4 import BeautifulSoup, Tag
from markitdown import MarkItDown
from tqdm import tqdm

from . import utils
from .database_manager import DatabaseManager

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry with backoff (rate limiting and
# transient server errors).
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Upper bound for a single backoff sleep, in seconds, to avoid pathological waits.
_MAX_BACKOFF = 30.0


class Scraper:
    def __init__(
        self,
        base_url,
        exclude_patterns,
        include_url_patterns,
        db_manager: DatabaseManager,
        rate_limit=0,
        delay=0,
        proxy=None,
        include_filters=None,
        exclude_filters=None,
        timeout=15,
        max_retries=3,
        max_pages=0,
        max_depth=-1,
        max_time=0,
    ):
        """
        Initialize the Scraper object and log the initialization process.

        Args:
            base_url (str): The base URL to start scraping from.
            exclude_patterns (list): List of URL patterns to exclude from scraping.
            include_url_patterns (list): List of URL patterns that must be
                present for a link to be scraped.
            db_manager (DatabaseManager): The database manager object.
            rate_limit (int): Maximum number of requests per minute.
            delay (float): Delay between requests in seconds.
            proxy (str, optional): Proxy URL for HTTP or SOCKS requests.
            include_filters (list, optional): CSS-like selectors (#id, .class, tag)
                of elements to include before Markdown conversion.
            exclude_filters (list, optional): CSS-like selectors (#id, .class, tag)
                of elements to exclude before Markdown conversion.
            timeout (float, optional): Timeout in seconds applied to every HTTP
                request issued by the scraper. Defaults to ``15``.
            max_retries (int, optional): Maximum number of retries on transient
                failures (connection/timeout errors, HTTP 429 and 5xx) before
                giving up on a URL. Defaults to ``3``.
            max_pages (int, optional): Maximum number of pages to scrape;
                ``0`` means unlimited. Defaults to ``0``.
            max_depth (int, optional): Maximum crawl depth for link discovery;
                ``-1`` means unlimited. Seeds are depth 0. Defaults to ``-1``.
            max_time (float, optional): Maximum wall-clock time for the crawl in
                seconds; ``0`` means unlimited. Defaults to ``0``.

        Raises:
            ValueError: If a proxy is provided but unreachable.
        """
        logger.debug(f"Initializing Scraper with base URL: {base_url}")
        self.base_url = base_url
        self.exclude_patterns = exclude_patterns or []
        self.include_url_patterns = include_url_patterns or []
        self.db_manager = db_manager
        self.rate_limit = rate_limit
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.max_time = max_time
        self.session = requests.Session()
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.proxy = proxy

        self.include_filters = include_filters or []
        self.exclude_filters = exclude_filters or []

        if proxy:
            self._test_proxy()

    def _test_proxy(self):
        """
        Ensure the configured proxy is reachable.

        Raises:
            ValueError: If the proxy cannot fetch the base URL.
        """
        try:
            self.session.head(self.base_url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ValueError(f"Proxy unreachable: {exc}") from exc

    def _backoff_delay(self, attempt):
        """
        Compute an exponential backoff delay with jitter for a retry attempt.

        Args:
            attempt (int): Zero-based index of the failed attempt.

        Returns:
            float: Delay in seconds, capped at :data:`_MAX_BACKOFF`, with a
            small random jitter added to avoid thundering-herd retries.
        """
        base = min(_MAX_BACKOFF, 0.5 * (2 ** attempt))
        jitter = random.uniform(0, base * 0.1)
        return base + jitter

    def _retry_after(self, response):
        """
        Parse the ``Retry-After`` header of a response into a delay in seconds.

        Supports both the integer-seconds and HTTP-date forms of the header.

        Args:
            response (requests.Response): The HTTP response to inspect.

        Returns:
            float | None: The requested delay in seconds (never negative), or
            ``None`` if the header is absent or unparseable.
        """
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
        try:
            retry_dt = parsedate_to_datetime(value)
            now = datetime.now(retry_dt.tzinfo)
            return max(0.0, (retry_dt - now).total_seconds())
        except (TypeError, ValueError):
            return None

    def _get_with_retry(self, url):
        """
        Perform a GET request for ``url`` with retry and exponential backoff.

        Transient connection/timeout errors and retryable HTTP statuses
        (429 and 5xx, see :data:`_RETRYABLE_STATUS`) trigger a retry, honoring
        the ``Retry-After`` header when present. The link is *not* marked as
        visited here; callers decide what to do with the final response once
        retries are exhausted.

        Args:
            url (str): The URL to fetch.

        Returns:
            requests.Response | None: The final response. If every attempt
            failed with a retryable status, the last response is returned so
            the caller can inspect its status code.

        Raises:
            requests.RequestException: If a connection/timeout error persists
            after the final attempt.
        """
        last_response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    logger.warning(
                        "Giving up on %s after %d attempt(s): %s",
                        url,
                        attempt + 1,
                        exc,
                    )
                    raise
                wait = self._backoff_delay(attempt)
                logger.debug(
                    "Connection error for %s (attempt %d/%d): %s; retrying in "
                    "%.2fs",
                    url,
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                    wait,
                )
                time.sleep(wait)
                continue

            if response.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                wait = self._retry_after(response)
                if wait is None:
                    wait = self._backoff_delay(attempt)
                logger.debug(
                    "Retryable status %d for %s (attempt %d/%d); retrying in "
                    "%.2fs",
                    response.status_code,
                    url,
                    attempt + 1,
                    self.max_retries + 1,
                    wait,
                )
                last_response = response
                time.sleep(wait)
                continue

            return response

        return last_response

    def _find_elements(self, soup: BeautifulSoup, selector: str):
        """
        Locate elements in the soup using a CSS-like selector.

        Args:
            soup (BeautifulSoup): Parsed HTML document.
            selector (str): Selector in the form of '#id', '.class', or tag name.

        Returns:
            list[Tag]: List of matching elements.
        """
        if selector.startswith("#"):
            element = soup.find(id=selector[1:])
            return [element] if element else []
        if selector.startswith("."):
            return soup.find_all(class_=selector[1:])
        return soup.find_all(selector)

    def is_valid_link(self, link):
        """
        Check if the given link is valid for scraping.
        Log the result of the validation.

        Args:
            link (str): The link to be checked.

        Returns:
            bool: True if the link is valid, False otherwise.
        """
        # Compare canonical forms so that equivalent URLs (differing only by
        # default port, tracking params, query order, etc.) validate identically.
        canonical = utils.canonicalize_url(link)
        valid = True
        if self.base_url and not canonical.startswith(
            utils.canonicalize_url(self.base_url)
        ):
            valid = False
        if self.include_url_patterns and not any(
            pattern in canonical for pattern in self.include_url_patterns
        ):
            valid = False
        for pattern in self.exclude_patterns:
            if pattern in canonical:
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
                # Send a GET request to the URL, retrying on transient failures.
                response = self._get_with_retry(url)
                if response is None or response.status_code != 200:
                    status = response.status_code if response is not None else "none"
                    logger.warning(
                        f"Failed to fetch {url} with status code {status}"
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

            if self.include_filters:
                # Create a new soup to hold the included elements
                new_soup = BeautifulSoup("", "html.parser")
                # Ensure the new soup has a body tag if it's a full HTML document
                if soup.find("body"):
                    body = new_soup.new_tag("body")
                    new_soup.append(body)
                else:
                    body = new_soup

                elements = []
                for selector in self.include_filters:
                    elements.extend(self._find_elements(soup, selector))

                # Append a copy of each element to the new soup to maintain structure
                for el in elements:
                    body.append(copy.copy(el))
                soup = new_soup

            for selector in self.exclude_filters:
                for element in self._find_elements(soup, selector):
                    element.decompose()

            # Extract title from the page
            title = soup.title.string if soup.title else ""

            metadata = {"title": title}

            filtered_html = str(soup)
            # Convert the HTML to Markdown
            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, suffix=".html"
            ) as tmp:
                tmp.write(filtered_html)
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

    def start_scraping(self, url=None, urls_list=None):
        """
        Initiates the scraping process for a single URL or a list of URLs.
        It validates URLs, logs the scraping process, and manages the
        progress of scraping through the database.

        Args:
            url (str, optional): A single URL to start scraping from. Defaults to None.
            urls_list (list, optional): A list of URLs to scrape.
        """
        # Validate, canonicalize, and seed the provided URLs at depth 0.
        urls = urls_list or []
        if urls:
            # Build a new list of valid URLs without modifying the original list
            validated_urls = []
            for url_item in urls:
                if not self.is_valid_link(url_item):
                    logger.warning(f"Skipping invalid URL: {url_item}")
                    continue
                validated_urls.append(utils.canonicalize_url(url_item))

            # Insert the validated list of URLs into the database
            self.db_manager.insert_link(validated_urls, depth=0)
        elif url:
            # Insert a single canonicalized URL if provided
            self.db_manager.insert_link(utils.canonicalize_url(url), depth=0)

        # Log the start of the scraping process
        logger.info("Starting scraping process")

        # Initialize a progress bar to track scraping progress
        pbar = tqdm(
            total=self.db_manager.get_links_count(),
            initial=self.db_manager.get_visited_links_count(),
            desc="Scraping",
            unit="link",
        )

        # Rate-limit and crawl-bound tracking state.
        request_count = 0
        start_time = time.time()
        crawl_start = time.time()
        scraped_count = 0
        stop = False

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
                # Enforce crawl bounds before issuing any further request.
                if self.max_pages > 0 and scraped_count >= self.max_pages:
                    logger.info(
                        "Reached max pages (%d). Stopping crawl.", self.max_pages
                    )
                    stop = True
                    break
                if (
                    self.max_time > 0
                    and (time.time() - crawl_start) >= self.max_time
                ):
                    logger.info(
                        "Reached max time (%.0fs). Stopping crawl.", self.max_time
                    )
                    stop = True
                    break

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
                depth = link[1] if len(link) > 1 else 0  # Crawl depth of the link

                # Attempt to fetch the page content with retry/backoff. Network
                # failures that survive all retries must not crash the crawl
                # loop: log, mark visited, and move on to the next link.
                try:
                    response = self._get_with_retry(url)
                except requests.RequestException as exc:
                    logger.warning("Failed to fetch %s: %s", url, exc)
                    self.db_manager.mark_link_visited(url)
                    continue

                # Increment request count for rate limiting
                request_count += 1

                # Check for a successful response and correct content type. A
                # retryable status that survived all retries lands here and is
                # only now marked visited (not before retries were exhausted).
                if (
                    response is None
                    or response.status_code != 200
                    or not response.headers.get("content-type", "").startswith(
                        "text/html"
                    )
                ):
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
                scraped_count += 1

                # Fetch and insert new links found on the page, if not working
                # from a predefined list and still within the depth bound.
                discover = self.max_depth < 0 or depth < self.max_depth
                if not urls_list and discover:
                    new_links = self.fetch_links(html=html, url=url)

                    # Count and insert new links into the database at depth+1.
                    real_new_links_count = 0
                    for new_url in new_links:
                        canonical = utils.canonicalize_url(new_url)
                        if self.db_manager.insert_link(canonical, depth=depth + 1):
                            real_new_links_count += 1
                            logger.debug(
                                f"Inserted new link {canonical} into the database"
                            )

                    # Update the progress bar total with the count of new links
                    if real_new_links_count:
                        pbar.total += real_new_links_count
                        pbar.refresh()

                # Mark the current link as visited in the database
                self.db_manager.mark_link_visited(url)

            # Break the outer loop too when a crawl bound has been reached.
            if stop:
                break

        # Close the progress bar upon completion of the scraping process
        pbar.close()
