"""MCP (Model Context Protocol) server exposing crawler-to-md as tools.

The server exposes two tools over stdio:

* ``crawl`` — crawl a site (or single page) and return the structured pages
  plus run statistics.
* ``fetch_as_markdown`` — fetch a single URL and return its Markdown content.

The official MCP Python SDK is an **optional** dependency (the ``mcp`` extra).
This module is importable without it: the SDK is imported lazily and a clear,
actionable error is raised only when the server is actually constructed. The
underlying tool logic lives in plain callables (:func:`crawl_tool` and
:func:`fetch_as_markdown`) so it can be tested without the SDK installed.
"""

import logging
from typing import Any, Optional

from . import crawl
from .core import CrawlResult

logger = logging.getLogger(__name__)

# Actionable error shown when the MCP server is constructed without the
# optional ``mcp`` extra installed.
MCP_MISSING_MESSAGE = (
    "The MCP server requires the optional 'mcp' extra. "
    "Install it with: pip install crawler-to-md[mcp]"
)


def _import_fastmcp():
    """Lazily import the MCP SDK's ``FastMCP`` server class.

    Returns:
        type: The ``mcp.server.fastmcp.FastMCP`` class.

    Raises:
        RuntimeError: If the optional ``mcp`` extra is not installed, with a
            message explaining how to install it.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise RuntimeError(MCP_MISSING_MESSAGE) from exc
    return FastMCP


def crawl_tool(url: str, options: Optional[dict] = None) -> dict:
    """Crawl ``url`` and return a JSON-serialisable summary of the result.

    Args:
        url (str): The base URL to crawl.
        options (dict | None): Optional keyword overrides forwarded to
            :func:`crawler_to_md.crawl` (e.g. ``max_pages``, ``max_depth``,
            ``concurrency``, ``include_url``).

    Returns:
        dict: ``{"pages": [...], "stats": {...}}`` where ``pages`` is the list
        of ``{"url", "content", "metadata"}`` records and ``stats`` is the
        aggregate run statistics.
    """
    result: CrawlResult = crawl(url, **(options or {}))
    return {
        "pages": result.pages,
        "stats": {
            "links_discovered": result.stats.links_discovered,
            "pages_scraped": result.stats.pages_scraped,
            "pages_stored": result.stats.pages_stored,
            "content_bytes": result.stats.content_bytes,
            "total_tokens": result.stats.total_tokens,
            "token_method": result.stats.token_method,
            "duration": result.stats.duration,
        },
    }


def fetch_as_markdown(url: str, options: Optional[dict] = None) -> str:
    """Fetch a single URL and return its Markdown content.

    No link discovery is performed: the crawl is bounded to one page at depth
    zero so only ``url`` itself is fetched and converted.

    Args:
        url (str): The URL to fetch and convert.
        options (dict | None): Optional keyword overrides forwarded to
            :func:`crawler_to_md.crawl` (e.g. ``timeout``, ``user_agent``,
            ``render``).

    Returns:
        str: The Markdown content of the page.

    Raises:
        RuntimeError: If no content could be fetched from ``url``.
    """
    opts: dict[str, Any] = dict(options or {})
    opts.setdefault("max_pages", 1)
    opts.setdefault("max_depth", 0)
    result: CrawlResult = crawl(url, **opts)
    for page in result.pages:
        if page.get("content"):
            return page["content"]
    raise RuntimeError(f"No content could be fetched from {url}")


def build_server():
    """Construct the MCP server with the ``crawl`` and ``fetch_as_markdown`` tools.

    Returns:
        FastMCP: A configured MCP server instance ready to ``run()``.

    Raises:
        RuntimeError: If the optional ``mcp`` extra is not installed.
    """
    fast_mcp = _import_fastmcp()
    server = fast_mcp("crawler-to-md")

    @server.tool()
    def crawl(url: str, options: Optional[dict] = None) -> dict:
        """Crawl a site or page and return its pages and run statistics."""
        return crawl_tool(url, options)

    @server.tool(name="fetch_as_markdown")
    def fetch(url: str, options: Optional[dict] = None) -> str:
        """Fetch a single URL and return its Markdown content."""
        return fetch_as_markdown(url, options)

    return server


def serve() -> None:
    """Build and run the MCP server over stdio (blocking).

    Raises:
        RuntimeError: If the optional ``mcp`` extra is not installed.
    """
    server = build_server()
    logger.info("Starting crawler-to-md MCP server over stdio")
    server.run()
