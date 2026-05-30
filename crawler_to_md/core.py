"""Shared crawl/export orchestration used by both the CLI and the library API.

This module centralises the wiring that turns a :class:`CrawlConfig` into a
crawl (and optional exports), returning a structured :class:`CrawlResult`. It
contains **no** argument parsing and performs **no** CLI-only side effects
(no printing, no ``sys.exit``); the CLI in :mod:`crawler_to_md.cli` is a thin
wrapper that builds a config, calls :func:`run_crawl`, and renders the result,
while the public :func:`crawler_to_md.crawl` helper reuses the same core.
"""

import dataclasses
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from . import utils
from .database_manager import DatabaseManager
from .export_manager import ExportManager
from .scraper import Scraper

logger = logging.getLogger(__name__)


@dataclass
class CrawlConfig:
    """Declarative configuration for a crawl or re-export run.

    The field names mirror the CLI flag destinations exactly so a parsed
    :class:`argparse.Namespace` can be mapped onto this dataclass field by
    field. Defaults match the CLI defaults, which keeps the library and CLI
    behaviour aligned.

    Attributes:
        url (str | None): Single base URL to start crawling from.
        urls_list (list[str]): Explicit list of seed URLs (mutually exclusive
            with ``url`` in practice; either may be supplied).
        output_folder (str): Root folder for exported artefacts.
        cache_folder (str): Folder holding the per-site SQLite cache database.
        overwrite_cache (bool): Remove an existing cache database before
            crawling.
        base_url (str | None): Base URL used for link filtering; derived from
            the seed URL when omitted (single-URL mode only).
        title (str | None): Title for the compiled outputs; defaults to the
            seed URL.
        exclude_url (list[str]): URL substrings to exclude.
        include_url (list[str]): URL substrings that must be present.
        export_individual (bool): Export each page as an individual Markdown
            file.
        rate_limit (int): Maximum requests per minute (``0`` = unlimited).
        delay (float): Delay between requests in seconds.
        proxy (str | None): Proxy URL for HTTP/SOCKS requests.
        no_markdown (bool): Disable the compiled Markdown export.
        no_json (bool): Disable the compiled JSON export.
        include (list[str]): CSS-like selectors to include before conversion.
        exclude (list[str]): CSS-like selectors to exclude before conversion.
        timeout (float): Per-request timeout in seconds.
        max_retries (int): Maximum retries on transient failures.
        max_pages (int): Maximum pages to scrape (``0`` = unlimited).
        max_depth (int): Maximum crawl depth (``-1`` = unlimited).
        max_time (float): Maximum wall-clock crawl time (``0`` = unlimited).
        concurrency (int): Concurrent fetches (``1`` = synchronous path).
        ignore_robots (bool): Ignore ``robots.txt`` rules.
        user_agent (str | None): User-Agent string for every request.
        sitemap (bool): Seed the frontier from ``/sitemap.xml``.
        extract (str): Content extraction strategy (``"none"`` or
            ``"readability"``).
        render (bool): Fetch JS-rendered HTML via Playwright.
        header (list[str]): Extra request headers as ``"Key: Value"`` strings.
        cookie (list[str]): Cookies as ``"key=value"`` strings.
        auth (str | None): HTTP basic-auth credentials as ``"user:pass"``.
        allow_types (list[str]): Additional content-types to ingest.
        export_jsonl (bool): Export pages as JSON Lines.
        export_llms (bool): Export ``llms.txt`` / ``llms-full.txt``.
        frontmatter (bool): Prepend YAML frontmatter to individual Markdown.
        chunk_size (int): RAG chunk size in tokens (``0`` = disabled).
        chunk_overlap (int): RAG chunk overlap in tokens.
        export_vectors (bool): Export pages to a Parquet file.
    """

    url: Optional[str] = None
    urls_list: list = field(default_factory=list)
    output_folder: str = "./output"
    cache_folder: str = "~/.cache/crawler-to-md"
    overwrite_cache: bool = False
    base_url: Optional[str] = None
    title: Optional[str] = None
    exclude_url: list = field(default_factory=list)
    include_url: list = field(default_factory=list)
    export_individual: bool = False
    rate_limit: int = 0
    delay: float = 0
    proxy: Optional[str] = None
    no_markdown: bool = False
    no_json: bool = False
    include: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    timeout: float = 15
    max_retries: int = 3
    max_pages: int = 0
    max_depth: int = -1
    max_time: float = 0
    concurrency: int = 1
    ignore_robots: bool = False
    user_agent: Optional[str] = None
    sitemap: bool = False
    extract: str = "none"
    render: bool = False
    header: list = field(default_factory=list)
    cookie: list = field(default_factory=list)
    auth: Optional[str] = None
    allow_types: list = field(default_factory=list)
    export_jsonl: bool = False
    export_llms: bool = False
    frontmatter: bool = True
    chunk_size: int = 0
    chunk_overlap: int = 0
    export_vectors: bool = False


@dataclass
class CrawlStats:
    """Aggregate statistics describing a completed crawl/export run.

    Attributes:
        links_discovered (int): Total links recorded in the frontier.
        pages_scraped (int): Number of links marked visited.
        pages_stored (int): Number of stored pages with non-empty content.
        content_bytes (int): Total UTF-8 byte size of stored content.
        total_tokens (int): Total token count across the corpus.
        token_method (str): How tokens were counted (``"tiktoken"`` or
            ``"word-estimate"``).
        duration (float): Wall-clock duration of the run in seconds.
    """

    links_discovered: int = 0
    pages_scraped: int = 0
    pages_stored: int = 0
    content_bytes: int = 0
    total_tokens: int = 0
    token_method: str = "word-estimate"
    duration: float = 0.0


@dataclass
class CrawlResult:
    """Structured result returned by :func:`run_crawl` and :func:`run_export`.

    Attributes:
        pages (list[dict]): One ``{"url", "content", "metadata"}`` entry per
            stored page (``metadata`` decoded to a ``dict``).
        stats (CrawlStats): Aggregate run statistics.
        exports (dict[str, Any]): Mapping of export name to the path(s) written
            (only the exports that were actually requested appear here).
    """

    pages: list = field(default_factory=list)
    stats: CrawlStats = field(default_factory=CrawlStats)
    exports: dict = field(default_factory=dict)


def _first_url(config: CrawlConfig) -> Optional[str]:
    """Return the primary seed URL for path/title derivation.

    Args:
        config (CrawlConfig): The run configuration.

    Returns:
        str | None: ``config.url`` when set, otherwise the first entry of
        ``config.urls_list``, or ``None`` if neither is provided.
    """
    if config.url:
        return config.url
    if config.urls_list:
        return config.urls_list[0]
    return None


def _apply_defaults(config: CrawlConfig, first_url: str) -> None:
    """Fill in the derived ``base_url`` and ``title`` defaults in place.

    Mirrors the legacy CLI behaviour: ``base_url`` is derived from the seed
    URL only in single-URL mode (when no explicit URL list is supplied), and
    ``title`` defaults to the seed URL.

    Args:
        config (CrawlConfig): The run configuration to mutate.
        first_url (str): The resolved primary seed URL.
    """
    if not config.base_url and not config.urls_list:
        config.base_url = utils.url_dirname(first_url)
        logger.debug("No base URL provided. Setting base URL to %s", config.base_url)
    if not config.title:
        config.title = first_url
        logger.debug("No title provided. Setting title to %s", config.title)


def _db_path(config: CrawlConfig, first_url: str) -> str:
    """Compute the SQLite cache path for ``first_url``.

    Args:
        config (CrawlConfig): The run configuration (provides ``cache_folder``).
        first_url (str): The resolved primary seed URL.

    Returns:
        str: Absolute-ish path to the per-site SQLite database file.
    """
    cache_folder = os.path.expanduser(config.cache_folder)
    return os.path.join(cache_folder, utils.url_to_filename(first_url) + ".sqlite")


def _build_scraper(config: CrawlConfig, db_manager: DatabaseManager) -> Scraper:
    """Construct a :class:`Scraper` from the configuration.

    Args:
        config (CrawlConfig): The run configuration.
        db_manager (DatabaseManager): The database manager to wire in.

    Returns:
        Scraper: A configured scraper instance.

    Raises:
        ValueError: Propagated from :class:`Scraper` when a proxy is provided
            but unreachable.
    """
    return Scraper(
        base_url=config.base_url,
        exclude_patterns=config.exclude_url,
        include_url_patterns=config.include_url,
        db_manager=db_manager,
        rate_limit=config.rate_limit,
        delay=config.delay,
        proxy=config.proxy,
        include_filters=config.include,
        exclude_filters=config.exclude,
        timeout=config.timeout,
        max_retries=config.max_retries,
        max_pages=config.max_pages,
        max_depth=config.max_depth,
        max_time=config.max_time,
        concurrency=config.concurrency,
        ignore_robots=config.ignore_robots,
        user_agent=config.user_agent,
        sitemap=config.sitemap,
        extract=config.extract,
        render=config.render,
        headers=config.header,
        cookies=config.cookie,
        auth=config.auth,
        allow_types=config.allow_types,
    )


def _wants_exports(config: CrawlConfig) -> bool:
    """Return whether any export artefact is requested by ``config``.

    Args:
        config (CrawlConfig): The run configuration.

    Returns:
        bool: ``True`` if at least one export will be written.
    """
    return any(
        (
            not config.no_markdown,
            not config.no_json,
            config.export_individual,
            config.export_jsonl,
            config.export_llms,
            config.chunk_size > 0,
            config.export_vectors,
        )
    )


def _run_exports(
    export_manager: ExportManager, config: CrawlConfig, output: str
) -> dict:
    """Run every requested export, returning a name → path(s) mapping.

    The output folder is created on demand. Optional-extra exports (RAG chunks
    and Parquet vectors) surface their :class:`ImportError` to the caller via a
    captured ``errors`` channel rather than aborting the whole run.

    Args:
        export_manager (ExportManager): The export manager bound to the cache.
        config (CrawlConfig): The run configuration.
        output (str): The per-site output folder.

    Returns:
        dict: Mapping of export name to the written path(s). A special
        ``"errors"`` key maps export names to error messages when an
        optional-extra export could not run.
    """
    exports: dict[str, Any] = {}
    errors: dict[str, str] = {}
    os.makedirs(output, exist_ok=True)
    output_name = utils.randomstring_to_filename(config.title)

    if not config.no_markdown:
        path = os.path.join(output, f"{output_name}.md")
        export_manager.export_to_markdown(path)
        exports["markdown"] = path

    if not config.no_json:
        path = os.path.join(output, f"{output_name}.json")
        export_manager.export_to_json(path)
        exports["json"] = path

    if config.export_individual:
        exports["individual"] = export_manager.export_individual_markdown(
            output_folder=output,
            base_url=config.base_url,
            frontmatter=config.frontmatter,
        )

    if config.export_jsonl:
        path = os.path.join(output, f"{output_name}.jsonl")
        export_manager.export_to_jsonl(path)
        exports["jsonl"] = path

    if config.export_llms:
        exports["llms"] = export_manager.export_to_llms(output)

    if config.chunk_size > 0:
        path = os.path.join(output, "chunks.jsonl")
        try:
            export_manager.export_chunks_jsonl(
                path, config.chunk_size, config.chunk_overlap
            )
            exports["chunks"] = path
        except ImportError as exc:
            errors["chunks"] = str(exc)

    if config.export_vectors:
        path = os.path.join(output, f"{output_name}.parquet")
        try:
            export_manager.export_to_vectors(
                path, config.chunk_size, config.chunk_overlap
            )
            exports["vectors"] = path
        except ImportError as exc:
            errors["vectors"] = str(exc)

    if errors:
        exports["errors"] = errors
    return exports


def _read_pages(db_manager: DatabaseManager) -> list:
    """Read all stored pages as structured dictionaries.

    Args:
        db_manager (DatabaseManager): The database manager to read from.

    Returns:
        list[dict]: One ``{"url", "content", "metadata"}`` entry per page,
        with ``metadata`` decoded from its JSON string to a ``dict``.
    """
    pages = []
    for url, content, metadata in db_manager.get_all_pages():
        try:
            decoded = json.loads(metadata) if metadata else {}
        except (TypeError, ValueError):
            decoded = {}
        pages.append({"url": url, "content": content, "metadata": decoded})
    return pages


def _compute_stats(
    db_manager: DatabaseManager, export_manager: ExportManager, duration: float
) -> CrawlStats:
    """Compute aggregate statistics for the run.

    Args:
        db_manager (DatabaseManager): Source of link/page counts.
        export_manager (ExportManager): Used to compute corpus token totals.
        duration (float): Wall-clock crawl duration in seconds.

    Returns:
        CrawlStats: The populated statistics record.
    """
    pages = db_manager.get_all_pages()
    page_count = sum(1 for _u, content, _m in pages if content is not None)
    total_bytes = sum(
        len((content or "").encode("utf-8")) for _u, content, _m in pages
    )
    total_tokens, method, _measured = export_manager.compute_token_totals()
    return CrawlStats(
        links_discovered=db_manager.get_links_count(),
        pages_scraped=db_manager.get_visited_links_count(),
        pages_stored=page_count,
        content_bytes=total_bytes,
        total_tokens=total_tokens,
        token_method=method,
        duration=duration,
    )


def run_crawl(config: CrawlConfig) -> CrawlResult:
    """Crawl according to ``config`` and run any requested exports.

    This is the single orchestration entry point shared by the CLI and the
    library API. It performs no printing and never calls ``sys.exit``; errors
    propagate as exceptions for the caller to handle.

    Args:
        config (CrawlConfig): The fully-resolved run configuration. Either
            ``config.url`` or ``config.urls_list`` must be set.

    Returns:
        CrawlResult: The crawled pages, aggregate statistics, and the paths of
        any exports that were written.

    Raises:
        ValueError: If no seed URL is provided, or if scraper construction
            fails (e.g. an unreachable proxy).
        OSError: If an existing cache database cannot be removed when
            ``overwrite_cache`` is set.
    """
    first_url = _first_url(config)
    if not first_url:
        raise ValueError("No URL provided. Provide either a URL or a URL list.")

    _apply_defaults(config, first_url)

    cache_folder = os.path.expanduser(config.cache_folder)
    os.makedirs(cache_folder, exist_ok=True)

    db_path = _db_path(config, first_url)
    if config.overwrite_cache and os.path.exists(db_path):
        logger.info("Removing existing cache database at %s", db_path)
        try:
            os.remove(db_path)
        except OSError as exc:
            logger.error("Failed to remove cache database at %s: %s", db_path, exc)
            raise

    db_manager = DatabaseManager(db_path)
    logger.info("DatabaseManager initialized.")

    scraper = _build_scraper(config, db_manager)
    logger.info("Scraper initialized.")

    start_time = time.perf_counter()
    logger.info("Starting the scraping process for URL: %s", config.url)
    if config.concurrency > 1:
        import asyncio

        asyncio.run(
            scraper.start_scraping_async(
                url=config.url, urls_list=config.urls_list
            )
        )
    else:
        scraper.start_scraping(url=config.url, urls_list=config.urls_list)

    export_manager = ExportManager(db_manager, config.title)
    exports: dict[str, Any] = {}
    if _wants_exports(config):
        output = os.path.join(
            config.output_folder, utils.url_to_filename(first_url)
        )
        exports = _run_exports(export_manager, config, output)

    duration = time.perf_counter() - start_time
    stats = _compute_stats(db_manager, export_manager, duration)
    pages = _read_pages(db_manager)
    db_manager.close()

    return CrawlResult(pages=pages, stats=stats, exports=exports)


def run_export(config: CrawlConfig) -> CrawlResult:
    """Re-run exports from an existing cache database without crawling.

    Args:
        config (CrawlConfig): The run configuration. Either ``config.url`` or
            ``config.urls_list`` must locate the existing cache database.

    Returns:
        CrawlResult: The stored pages, statistics, and written export paths.

    Raises:
        ValueError: If no seed URL is provided, or if no cache database exists
            at the derived path.
    """
    first_url = _first_url(config)
    if not first_url:
        raise ValueError("No URL provided. Provide either a URL or a URL list.")

    _apply_defaults(config, first_url)

    db_path = _db_path(config, first_url)
    if not os.path.exists(db_path):
        raise ValueError(
            f"No cache database found at {db_path}. Run a crawl first or "
            "point --cache-folder at the directory holding it."
        )

    db_manager = DatabaseManager(db_path)
    export_manager = ExportManager(db_manager, config.title)

    output = os.path.join(config.output_folder, utils.url_to_filename(first_url))
    exports = _run_exports(export_manager, config, output)

    stats = _compute_stats(db_manager, export_manager, 0.0)
    pages = _read_pages(db_manager)
    db_manager.close()

    return CrawlResult(pages=pages, stats=stats, exports=exports)


def config_from_namespace(args, urls_list: Optional[list] = None) -> CrawlConfig:
    """Build a :class:`CrawlConfig` from a parsed ``argparse`` namespace.

    Only attributes present on ``args`` overwrite the dataclass defaults, so a
    subparser that exposes a subset of flags (e.g. ``export``) still yields a
    valid configuration.

    Args:
        args (argparse.Namespace): The parsed command-line arguments.
        urls_list (list[str] | None): Pre-resolved seed URL list (from a URLs
            file or stdin). Defaults to an empty list.

    Returns:
        CrawlConfig: The populated configuration.
    """
    config = CrawlConfig()
    for f in dataclasses.fields(CrawlConfig):
        if f.name in ("url", "urls_list"):
            continue
        if hasattr(args, f.name):
            setattr(config, f.name, getattr(args, f.name))
    config.url = getattr(args, "url", None)
    config.urls_list = list(urls_list or [])
    return config
