"""crawler-to-md: crawl websites and export their content as Markdown/JSON.

Besides the ``crawler-to-md`` command-line tool, the package exposes a small,
side-effect-free library API. Import :func:`crawl` to run a crawl
programmatically and receive a structured :class:`~crawler_to_md.core.CrawlResult`
(pages plus statistics) with no argument parsing and no process exit. The core
component classes are re-exported for advanced use.

Example:
    >>> from crawler_to_md import crawl
    >>> result = crawl("https://example.com", max_pages=10)
    >>> len(result.pages)
    10
"""

import tempfile
from typing import Optional

from .core import CrawlConfig, CrawlResult, CrawlStats, run_crawl, run_export
from .database_manager import DatabaseManager
from .export_manager import ExportManager
from .scraper import Scraper

__all__ = [
    "crawl",
    "CrawlConfig",
    "CrawlResult",
    "CrawlStats",
    "run_crawl",
    "run_export",
    "Scraper",
    "ExportManager",
    "DatabaseManager",
]


def crawl(url: Optional[str] = None, *, urls=None, **options) -> CrawlResult:
    """Crawl a website programmatically and return structured results.

    This is the clean library entry point: it parses no command-line
    arguments, performs no CLI-only side effects (no printing, no
    ``sys.exit``), and never writes export files unless the caller explicitly
    asks for them. The crawled pages are always returned in
    :attr:`CrawlResult.pages`.

    Sensible library defaults differ from the CLI: compiled Markdown and JSON
    exports are disabled, and an isolated temporary directory is used for the
    SQLite cache unless ``cache_folder`` is supplied. Any field of
    :class:`~crawler_to_md.core.CrawlConfig` may be passed as a keyword
    override (for example ``max_pages``, ``max_depth``, ``concurrency``,
    ``include_url``, ``output_folder`` together with ``no_markdown=False`` to
    write artefacts).

    Args:
        url (str | None): The base URL to start crawling from.
        urls (Iterable[str] | None): An explicit list of seed URLs. Either
            ``url`` or ``urls`` must be provided.
        **options: Keyword overrides mapped onto
            :class:`~crawler_to_md.core.CrawlConfig`.

    Returns:
        CrawlResult: The crawled pages, aggregate statistics, and the paths of
        any exports that were written.

    Raises:
        TypeError: If an unknown configuration option is supplied.
        ValueError: If neither ``url`` nor ``urls`` is provided, or if scraper
            construction fails (e.g. an unreachable proxy).
    """
    options.setdefault("no_markdown", True)
    options.setdefault("no_json", True)
    if not options.get("cache_folder"):
        options["cache_folder"] = tempfile.mkdtemp(prefix="crawler-to-md-")
    config = CrawlConfig(url=url, urls_list=list(urls or []), **options)
    return run_crawl(config)
