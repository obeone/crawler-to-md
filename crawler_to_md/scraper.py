import asyncio
import copy
import json
import logging
import mimetypes
import os
import random
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
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

# Cap on how many nested sitemap files are followed from a sitemap index, to
# bound work on pathological or recursive sitemap trees.
_MAX_SITEMAP_DEPTH = 5


def _default_user_agent():
    """
    Build the default descriptive User-Agent string for the crawler.

    The version is resolved from the installed package metadata when available,
    falling back to ``0.0.0`` for editable/unbuilt checkouts.

    Returns:
        str: A descriptive User-Agent such as
        ``"crawler-to-md/1.2.3 (+https://github.com/obeone/crawler-to-md)"``.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            package_version = version("crawler-to-md")
        except PackageNotFoundError:
            package_version = "0.0.0"
    except Exception:  # pragma: no cover - importlib always present on 3.10+
        package_version = "0.0.0"
    return (
        f"crawler-to-md/{package_version} "
        "(+https://github.com/obeone/crawler-to-md)"
    )


class _RenderedResponse:
    """
    Minimal response-like wrapper around HTML produced by JS rendering.

    Exposes the small subset of the ``requests``/``httpx`` response interface
    consumed by the crawl loops (``status_code``, ``headers``, ``text``,
    ``content``) so rendered pages flow through the same processing path as
    fetched HTML responses.
    """

    def __init__(self, html):
        """
        Wrap rendered HTML in a response-like object.

        Args:
            html (str | None): The rendered HTML, or ``None`` if rendering
                produced no content (treated as a non-success status).
        """
        self.status_code = 200 if html is not None else 599
        self.text = html or ""
        self.content = (html or "").encode("utf-8")
        self.headers = {"content-type": "text/html"}


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
        concurrency=1,
        ignore_robots=False,
        user_agent=None,
        sitemap=False,
        extract="none",
        render=False,
        headers=None,
        cookies=None,
        auth=None,
        allow_types=None,
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
            concurrency (int, optional): Number of concurrent fetches for the
                async crawl path. ``1`` (the default) behaves exactly like the
                synchronous path; values greater than ``1`` fetch in parallel.
            ignore_robots (bool, optional): When ``False`` (the default), the
                crawler honors each host's ``robots.txt`` and skips disallowed
                URLs. Set ``True`` to ignore robots rules entirely.
            user_agent (str, optional): User-Agent string sent on every request
                and used for robots evaluation. Defaults to a descriptive UA
                built from the package version.
            sitemap (bool, optional): When ``True``, seed the frontier from the
                host's ``/sitemap.xml`` (following sitemap indexes) before
                crawling. Defaults to ``False``.
            extract ({"none", "readability"}, optional): Content extraction
                strategy. ``"readability"`` uses ``trafilatura`` (optional
                ``readability`` extra) to extract the main content before
                Markdown conversion. Defaults to ``"none"``.
            render (bool, optional): When ``True``, fetch the JS-rendered HTML
                via Playwright (optional ``render`` extra) instead of a plain
                HTTP GET. Defaults to ``False``.
            headers (list[str] | dict | None, optional): Extra request headers
                as ``"Key: Value"`` strings (or a mapping). Applied to both the
                sync session and the async client.
            cookies (list[str] | dict | None, optional): Cookies as ``"key=value"``
                strings (or a mapping). Applied to both transports.
            auth (str | None, optional): HTTP basic-auth credentials as
                ``"user:pass"``. Applied to both transports.
            allow_types (list[str] | None, optional): Additional content-type
                base values (e.g. ``"application/pdf"``) to ingest via MarkItDown
                in addition to HTML. Links are only discovered from HTML pages.

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
        self.concurrency = max(1, concurrency)

        # Crawl-intelligence configuration.
        self.ignore_robots = ignore_robots
        self.user_agent = user_agent or _default_user_agent()
        self.sitemap = sitemap
        self.extract = extract or "none"
        self.render = render
        self.allow_types = {
            t.split(";")[0].strip().lower() for t in (allow_types or []) if t
        }
        # Per-host cache of parsed robots rules (``None`` means "allow all").
        self._robots_cache = {}

        # Build request headers/cookies/auth shared by both transports. The
        # descriptive User-Agent is applied first so an explicit ``--header
        # 'User-Agent: ...'`` can still override it.
        self._headers = {"User-Agent": self.user_agent}
        self._headers.update(self._build_headers(headers))
        self._cookies = self._build_cookies(cookies)
        self._auth = self._build_auth(auth)

        self.session = requests.Session()
        self.session.headers.update(self._headers)
        if self._cookies:
            self.session.cookies.update(self._cookies)
        if self._auth:
            self.session.auth = self._auth
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.proxy = proxy

        self.include_filters = include_filters or []
        self.exclude_filters = exclude_filters or []

        if proxy:
            self._test_proxy()

    @staticmethod
    def _build_headers(headers):
        """
        Normalize the ``headers`` argument into a header dictionary.

        Accepts either a mapping or a list of ``"Key: Value"`` strings. The
        configured User-Agent is added by the caller; user-supplied headers may
        override it.

        Args:
            headers (list[str] | dict | None): Raw header specification.

        Returns:
            dict[str, str]: The parsed headers (empty dict if none provided).
        """
        result = {}
        if not headers:
            return result
        if isinstance(headers, dict):
            return {str(k): str(v) for k, v in headers.items()}
        for item in headers:
            if ":" in item:
                key, _, value = item.partition(":")
                result[key.strip()] = value.strip()
            else:
                logger.warning("Ignoring malformed header (expected 'K: V'): %s", item)
        return result

    @staticmethod
    def _build_cookies(cookies):
        """
        Normalize the ``cookies`` argument into a cookie dictionary.

        Accepts either a mapping or a list of ``"key=value"`` strings.

        Args:
            cookies (list[str] | dict | None): Raw cookie specification.

        Returns:
            dict[str, str]: The parsed cookies (empty dict if none provided).
        """
        result = {}
        if not cookies:
            return result
        if isinstance(cookies, dict):
            return {str(k): str(v) for k, v in cookies.items()}
        for item in cookies:
            if "=" in item:
                key, _, value = item.partition("=")
                result[key.strip()] = value.strip()
            else:
                logger.warning("Ignoring malformed cookie (expected 'k=v'): %s", item)
        return result

    @staticmethod
    def _build_auth(auth):
        """
        Normalize the ``auth`` argument into a ``(user, password)`` tuple.

        Args:
            auth (str | tuple | None): ``"user:pass"`` string or a 2-tuple.

        Returns:
            tuple[str, str] | None: The credential pair, or ``None`` when no
            authentication is configured.
        """
        if not auth:
            return None
        if isinstance(auth, (tuple, list)) and len(auth) == 2:
            return (str(auth[0]), str(auth[1]))
        user, _, password = str(auth).partition(":")
        return (user, password)

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

    @staticmethod
    def _robots_host_key(url):
        """
        Return the ``scheme://netloc`` key used to cache robots rules per host.

        Args:
            url (str): Any URL on the target host.

        Returns:
            str: The origin key (e.g. ``"https://example.com"``).
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @staticmethod
    def _robots_url(url):
        """
        Build the ``robots.txt`` URL for the host of ``url``.

        Args:
            url (str): Any URL on the target host.

        Returns:
            str: The absolute ``robots.txt`` URL for that host.
        """
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _parser_from_text(self, text):
        """
        Build a :class:`urllib.robotparser.RobotFileParser` from rules text.

        Args:
            text (str): The body of a ``robots.txt`` file.

        Returns:
            urllib.robotparser.RobotFileParser: A parser primed with the rules.
        """
        parser = robotparser.RobotFileParser()
        parser.parse((text or "").splitlines())
        return parser

    def _robots_allowed(self, url):
        """
        Check whether ``url`` may be fetched according to the host's robots.txt.

        Robots files are fetched once per host through the synchronous session
        and cached. Any fetch/parse failure or non-200 response is treated as
        "allow all" (cached as ``None``), matching common crawler behavior.

        Args:
            url (str): The URL to check.

        Returns:
            bool: ``True`` if fetching is permitted (or robots is unavailable),
            ``False`` if the host explicitly disallows ``url``.
        """
        key = self._robots_host_key(url)
        if key not in self._robots_cache:
            parser = None
            try:
                response = self.session.get(
                    self._robots_url(url), timeout=self.timeout
                )
                if response is not None and response.status_code == 200:
                    parser = self._parser_from_text(response.text)
            except requests.RequestException as exc:
                logger.debug("Could not fetch robots.txt for %s: %s", key, exc)
            self._robots_cache[key] = parser
        parser = self._robots_cache[key]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    async def _arobots_allowed(self, client, url):
        """
        Async counterpart of :meth:`_robots_allowed` using the async client.

        Shares the same per-host cache so robots is fetched at most once per
        host regardless of which crawl path is active.

        Args:
            client (httpx.AsyncClient): The async client used to fetch robots.
            url (str): The URL to check.

        Returns:
            bool: ``True`` if fetching is permitted, ``False`` otherwise.
        """
        key = self._robots_host_key(url)
        if key not in self._robots_cache:
            parser = None
            try:
                response = await client.get(self._robots_url(url))
                if response is not None and response.status_code == 200:
                    parser = self._parser_from_text(response.text)
            except httpx.RequestError as exc:
                logger.debug("Could not fetch robots.txt for %s: %s", key, exc)
            self._robots_cache[key] = parser
        parser = self._robots_cache[key]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def _sitemap_base_url(self):
        """
        Determine the origin used to locate the default ``sitemap.xml``.

        Returns:
            str: The ``scheme://netloc`` origin derived from ``base_url``.
        """
        parsed = urlparse(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _collect_sitemap_urls(self, sitemap_url, seen, depth=0):
        """
        Recursively collect page URLs from a sitemap or sitemap index.

        Tolerates missing files, non-200/204 responses, empty bodies, and
        non-XML content by returning an empty list rather than raising.

        Args:
            sitemap_url (str): URL of the sitemap (or sitemap index) to fetch.
            seen (set[str]): Set of already-fetched sitemap URLs (cycle guard).
            depth (int): Current recursion depth into nested sitemap indexes.

        Returns:
            list[str]: The ``<loc>`` page URLs discovered (deepest-first order
            is not guaranteed; duplicates are possible and filtered later).
        """
        if depth > _MAX_SITEMAP_DEPTH or sitemap_url in seen:
            return []
        seen.add(sitemap_url)
        try:
            response = self.session.get(sitemap_url, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("Sitemap fetch failed for %s: %s", sitemap_url, exc)
            return []
        if (
            response is None
            or response.status_code != 200
            or not getattr(response, "content", b"")
        ):
            logger.debug("No usable sitemap at %s", sitemap_url)
            return []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            logger.warning("Sitemap parse failed for %s: %s", sitemap_url, exc)
            return []

        locs = [
            element.text.strip()
            for element in root.iter()
            if element.tag.split("}")[-1].lower() == "loc" and element.text
        ]
        root_tag = root.tag.split("}")[-1].lower()
        if root_tag == "sitemapindex":
            urls = []
            for child in locs:
                urls.extend(self._collect_sitemap_urls(child, seen, depth + 1))
            return urls
        return locs

    def _seed_from_sitemap(self):
        """
        Seed the crawl frontier from the host's ``sitemap.xml``.

        Discovered URLs are validated via :meth:`is_valid_link`, canonicalized,
        and inserted at depth 0. Missing or malformed sitemaps are ignored.

        Returns:
            int: The number of valid URLs seeded from the sitemap.
        """
        sitemap_url = urljoin(self._sitemap_base_url() + "/", "sitemap.xml")
        logger.info("Seeding frontier from sitemap %s", sitemap_url)
        discovered = self._collect_sitemap_urls(sitemap_url, set())
        seeded = []
        for candidate in discovered:
            if self.is_valid_link(candidate):
                seeded.append(utils.canonicalize_url(candidate))
        if seeded:
            self.db_manager.insert_link(utils.deduplicate_list(seeded), depth=0)
        logger.info("Seeded %d URL(s) from sitemap", len(seeded))
        return len(seeded)

    def _import_trafilatura(self):
        """
        Lazily import ``trafilatura`` for readability extraction.

        Returns:
            module: The imported ``trafilatura`` module.

        Raises:
            RuntimeError: If the optional ``readability`` extra is not installed.
        """
        try:
            import trafilatura
        except ImportError as exc:
            raise RuntimeError(
                "Readability extraction requires the 'readability' extra. "
                "Install it with: pip install crawler-to-md[readability]"
            ) from exc
        return trafilatura

    def _scrape_readability(self, html, url):
        """
        Extract the main content of ``html`` as Markdown via ``trafilatura``.

        Args:
            html (str): The raw HTML of the page.
            url (str): The source URL (used for logging and metadata).

        Returns:
            tuple[str | None, dict | None]: ``(markdown, metadata)`` or
            ``(None, None)`` if no main content could be extracted.

        Raises:
            RuntimeError: If the optional ``readability`` extra is missing.
        """
        trafilatura = self._import_trafilatura()
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string if soup.title else ""
        content = trafilatura.extract(
            html, output_format="markdown", include_comments=False
        )
        if not content or not content.strip():
            logger.warning("Readability extraction produced no content for %s", url)
            return None, None
        return content, {"title": title}

    def _render_sync(self, url):
        """
        Fetch the JS-rendered HTML of ``url`` using Playwright (sync API).

        Args:
            url (str): The URL to render.

        Returns:
            str: The rendered HTML.

        Raises:
            RuntimeError: If the optional ``render`` extra (or its browsers) is
            missing, or if rendering fails. The message explains how to install
            the extra and the browser binaries.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "JS rendering requires the 'render' extra. Install it with: "
                "pip install crawler-to-md[render]"
            ) from exc
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(user_agent=self.user_agent)
                    page.goto(url, timeout=self.timeout * 1000)
                    return page.content()
                finally:
                    browser.close()
        except Exception as exc:
            raise RuntimeError(
                f"JS rendering failed for {url}: {exc}. Ensure the Playwright "
                "browsers are installed (run: playwright install chromium)."
            ) from exc

    async def _render_async(self, url):
        """
        Fetch the JS-rendered HTML of ``url`` using Playwright (async API).

        Args:
            url (str): The URL to render.

        Returns:
            str: The rendered HTML.

        Raises:
            RuntimeError: If the optional ``render`` extra (or its browsers) is
            missing, or if rendering fails.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "JS rendering requires the 'render' extra. Install it with: "
                "pip install crawler-to-md[render]"
            ) from exc
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                try:
                    page = await browser.new_page(user_agent=self.user_agent)
                    await page.goto(url, timeout=self.timeout * 1000)
                    return await page.content()
                finally:
                    await browser.close()
        except Exception as exc:
            raise RuntimeError(
                f"JS rendering failed for {url}: {exc}. Ensure the Playwright "
                "browsers are installed (run: playwright install chromium)."
            ) from exc

    def _convert_binary(self, content, content_type):
        """
        Convert non-HTML bytes to Markdown via MarkItDown using a temp file.

        Args:
            content (bytes): The raw response body.
            content_type (str): The response content-type (used to pick a
                sensible temp-file suffix so MarkItDown selects a converter).

        Returns:
            str: The Markdown produced by MarkItDown (possibly empty).
        """
        base = content_type.split(";")[0].strip().lower()
        suffix = mimetypes.guess_extension(base) or ""
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, suffix=suffix
        ) as tmp:
            tmp.write(content or b"")
            tmp_path = tmp.name
        try:
            return str(MarkItDown().convert(tmp_path))
        finally:
            os.remove(tmp_path)

    def _store_and_discover(self, html, url, depth, urls_list, pbar):
        """
        Scrape an HTML page, persist it, and enqueue newly discovered links.

        Args:
            html (str): The page HTML.
            url (str): The page URL.
            depth (int): The crawl depth of this page.
            urls_list (list | None): The predefined URL list, if any. When set,
                no new links are discovered.
            pbar (tqdm.tqdm): Progress bar whose total grows with new links.
        """
        content, metadata = self.scrape_page(html, url)
        self.db_manager.insert_page(url, content, json.dumps(metadata))

        discover = self.max_depth < 0 or depth < self.max_depth
        if urls_list or not discover:
            return
        new_links = self.fetch_links(html=html, url=url)
        real_new_links_count = 0
        for new_url in new_links:
            canonical = utils.canonicalize_url(new_url)
            if self.db_manager.insert_link(canonical, depth=depth + 1):
                real_new_links_count += 1
                logger.debug("Inserted new link %s into the database", canonical)
        if real_new_links_count:
            pbar.total += real_new_links_count
            pbar.refresh()

    def _store_binary(self, url, content, content_type):
        """
        Convert and persist a non-HTML document; no link discovery is performed.

        Args:
            url (str): The document URL.
            content (bytes): The raw response body.
            content_type (str): The response content-type.
        """
        markdown = self._convert_binary(content, content_type)
        metadata = {"title": url, "content_type": content_type}
        self.db_manager.insert_page(url, markdown, json.dumps(metadata))

    def _process_response(self, url, response, depth, urls_list, pbar):
        """
        Persist a fetched response, dispatching by content type.

        HTML responses are scraped and may discover new links. Responses whose
        content type is listed in ``allow_types`` are ingested as non-HTML
        documents (no discovery). The link is always marked visited.

        Args:
            url (str): The fetched URL.
            response: A response-like object exposing ``status_code``,
                ``headers``, ``text`` and ``content`` (``requests``/``httpx``
                response or :class:`_RenderedResponse`), or ``None``.
            depth (int): The crawl depth of this URL.
            urls_list (list | None): The predefined URL list, if any.
            pbar (tqdm.tqdm): Progress bar to update on link discovery.

        Returns:
            bool: ``True`` if a page/document was stored (counts toward the
            ``max_pages`` bound), ``False`` if the response was skipped.
        """
        if response is None or response.status_code != 200:
            self.db_manager.mark_link_visited(url)
            logger.info("Skipping link %s due to invalid status code", url)
            return False

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            self._store_and_discover(response.text, url, depth, urls_list, pbar)
            self.db_manager.mark_link_visited(url)
            return True

        base = content_type.split(";")[0].strip().lower()
        if base in self.allow_types:
            self._store_binary(url, response.content, content_type)
            self.db_manager.mark_link_visited(url)
            return True

        self.db_manager.mark_link_visited(url)
        logger.info(
            "Skipping link %s due to unsupported content type %s", url, content_type
        )
        return False

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

        # Readability extraction bypasses the include/exclude + MarkItDown
        # pipeline and lets trafilatura isolate the main content directly.
        if self.extract == "readability":
            return self._scrape_readability(html, url)

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

        # Optionally seed additional URLs from the host's sitemap.
        if self.sitemap:
            self._seed_from_sitemap()

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

                # Honor robots.txt unless explicitly disabled.
                if not self.ignore_robots and not self._robots_allowed(url):
                    logger.info("Skipping %s (disallowed by robots.txt)", url)
                    self.db_manager.mark_link_visited(url)
                    continue

                # Obtain the page. JS rendering substitutes a plain GET with a
                # rendered-HTML response; otherwise fetch with retry/backoff.
                # Network failures that survive all retries must not crash the
                # crawl loop: log, mark visited, and move on to the next link.
                if self.render:
                    response = _RenderedResponse(self._render_sync(url))
                else:
                    try:
                        response = self._get_with_retry(url)
                    except requests.RequestException as exc:
                        logger.warning("Failed to fetch %s: %s", url, exc)
                        self.db_manager.mark_link_visited(url)
                        continue

                # Increment request count for rate limiting
                request_count += 1

                # Persist the response (HTML or an allowed non-HTML document),
                # marking the link visited and counting stored pages.
                if self._process_response(url, response, depth, urls_list, pbar):
                    scraped_count += 1

            # Break the outer loop too when a crawl bound has been reached.
            if stop:
                break

        # Close the progress bar upon completion of the scraping process
        pbar.close()

    def _make_async_client(self):
        """
        Create the ``httpx.AsyncClient`` used by the async crawl path.

        Centralized so tests can monkeypatch it to inject a mock transport.
        ``follow_redirects=True`` mirrors the redirect-following behavior of the
        synchronous ``requests`` session.

        Returns:
            httpx.AsyncClient: A configured async HTTP client.
        """
        return httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            proxy=self.proxy,
            headers=self._headers or None,
            cookies=self._cookies or None,
            auth=self._auth,
        )

    async def _aget_with_retry(self, client, url):
        """
        Async counterpart of :meth:`_get_with_retry`, mirroring its contract.

        Retries on transient httpx transport errors and retryable HTTP statuses
        (429 and 5xx, see :data:`_RETRYABLE_STATUS`) using exponential backoff
        with jitter, honoring the ``Retry-After`` header. The link is *not*
        marked visited here.

        Args:
            client (httpx.AsyncClient): The client used to issue the request.
            url (str): The URL to fetch.

        Returns:
            httpx.Response | None: The final response. If every attempt failed
            with a retryable status, the last response is returned.

        Raises:
            httpx.RequestError: If a transport error persists after the final
            attempt.
        """
        last_response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(url)
            except httpx.RequestError as exc:
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
                await asyncio.sleep(wait)
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
                await asyncio.sleep(wait)
                continue

            return response

        return last_response

    async def _afetch_one(self, client, url, semaphore):
        """
        Fetch a single URL within the concurrency semaphore.

        Honors the configured ``delay`` between requests for politeness. Any
        persistent transport error is captured and returned rather than raised
        so a single failure cannot abort the whole batch.

        Args:
            client (httpx.AsyncClient): The async client.
            url (str): The URL to fetch.
            semaphore (asyncio.Semaphore): Bounds the number of in-flight fetches.

        Returns:
            tuple[str, httpx.Response | None, Exception | None]: ``(url,
            response, error)`` where exactly one of ``response``/``error`` is set
            on failure (``error`` set, ``response`` ``None``).
        """
        async with semaphore:
            if self.delay > 0:
                await asyncio.sleep(self.delay)
            if self.render:
                try:
                    return (url, _RenderedResponse(await self._render_async(url)), None)
                except RuntimeError as exc:
                    return (url, None, exc)
            try:
                response = await self._aget_with_retry(client, url)
                return (url, response, None)
            except httpx.RequestError as exc:
                return (url, None, exc)

    async def start_scraping_async(self, url=None, urls_list=None):
        """
        Asynchronous crawl that fetches concurrently while serializing DB access.

        Behaviorally mirrors :meth:`start_scraping`: identical seeding, canonical
        dedup, content-type filtering, retry/backoff, crawl bounds
        (``max_pages``/``max_depth``/``max_time``), rate limiting/delay, and
        upsert/visited semantics. The frontier is processed in
        ``concurrency``-sized batches: a batch of the shallowest unvisited links
        is fetched concurrently, then *every* database read/write is applied
        serially in this single coroutine so the SQLite connection is never used
        concurrently. With ``concurrency == 1`` this is equivalent to the
        synchronous path.

        Args:
            url (str, optional): A single URL to start scraping from.
            urls_list (list, optional): A list of URLs to scrape.
        """
        # Seed the frontier (serial DB access).
        urls = urls_list or []
        if urls:
            validated_urls = []
            for url_item in urls:
                if not self.is_valid_link(url_item):
                    logger.warning(f"Skipping invalid URL: {url_item}")
                    continue
                validated_urls.append(utils.canonicalize_url(url_item))
            self.db_manager.insert_link(validated_urls, depth=0)
        elif url:
            self.db_manager.insert_link(utils.canonicalize_url(url), depth=0)

        # Optionally seed additional URLs from the host's sitemap.
        if self.sitemap:
            self._seed_from_sitemap()

        logger.info(
            "Starting async scraping process (concurrency=%d)", self.concurrency
        )

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

        semaphore = asyncio.Semaphore(self.concurrency)
        client = self._make_async_client()
        try:
            async with client:
                while not stop:
                    # Serial DB read of the current frontier (BFS order).
                    unvisited_links = self.db_manager.get_unvisited_links()
                    if not unvisited_links:
                        logger.info("No more links to visit. Exiting.")
                        break

                    # Time bound: check before scheduling a new batch.
                    if (
                        self.max_time > 0
                        and (time.time() - crawl_start) >= self.max_time
                    ):
                        logger.info(
                            "Reached max time (%.0fs). Stopping crawl.",
                            self.max_time,
                        )
                        break

                    # Rate limit: enforce the per-minute window before a batch.
                    if self.rate_limit > 0 and request_count >= self.rate_limit:
                        elapsed = time.time() - start_time
                        sleep_time = 60 - elapsed
                        if sleep_time > 0:
                            logger.debug(
                                "Rate limit reached, sleeping for %s seconds",
                                sleep_time,
                            )
                            await asyncio.sleep(sleep_time)
                        request_count = 0
                        start_time = time.time()

                    # Take a concurrency-sized batch of the shallowest links.
                    batch = unvisited_links[: self.concurrency]
                    depth_by_url = {
                        link[0]: (link[1] if len(link) > 1 else 0) for link in batch
                    }

                    # Honor robots.txt before fetching: drop disallowed URLs
                    # from the batch (robots is fetched at most once per host).
                    allowed_batch = []
                    for link in batch:
                        candidate = link[0]
                        if not self.ignore_robots and not await self._arobots_allowed(
                            client, candidate
                        ):
                            logger.info(
                                "Skipping %s (disallowed by robots.txt)", candidate
                            )
                            self.db_manager.mark_link_visited(candidate)
                            pbar.update(1)
                        else:
                            allowed_batch.append(link)
                    if not allowed_batch:
                        continue

                    # Fetch the batch concurrently (DB untouched here).
                    results = await asyncio.gather(
                        *(
                            self._afetch_one(client, link[0], semaphore)
                            for link in allowed_batch
                        )
                    )
                    request_count += len(results)

                    # Apply every database update serially in this coroutine.
                    for fetched_url, response, error in results:
                        pbar.update(1)
                        depth = depth_by_url.get(fetched_url, 0)

                        # Page bound: stop once enough pages have been scraped.
                        if self.max_pages > 0 and scraped_count >= self.max_pages:
                            logger.info(
                                "Reached max pages (%d). Stopping crawl.",
                                self.max_pages,
                            )
                            stop = True
                            break

                        # Persistent transport/render error: mark visited, skip.
                        if error is not None:
                            logger.warning(
                                "Failed to fetch %s: %s", fetched_url, error
                            )
                            self.db_manager.mark_link_visited(fetched_url)
                            continue

                        # Persist the response (HTML or an allowed non-HTML
                        # document); marks visited and discovers links for HTML.
                        if self._process_response(
                            fetched_url, response, depth, urls_list, pbar
                        ):
                            scraped_count += 1
        finally:
            pbar.close()
