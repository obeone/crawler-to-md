import pytest

from crawler_to_md import mcp_server
from crawler_to_md.core import CrawlResult, CrawlStats


def test_mcp_missing_extra(monkeypatch):
    """Building the server without the ``mcp`` extra raises a clear error."""

    def boom():
        raise RuntimeError(mcp_server.MCP_MISSING_MESSAGE)

    monkeypatch.setattr(mcp_server, "_import_fastmcp", boom)
    with pytest.raises(RuntimeError, match=r"crawler-to-md\[mcp\]"):
        mcp_server.build_server()


def test_mcp_crawl_tool(monkeypatch):
    """The ``crawl`` tool callable returns serialisable pages and stats."""
    fake = CrawlResult(
        pages=[{"url": "http://x", "content": "# Hi", "metadata": {}}],
        stats=CrawlStats(links_discovered=1, pages_scraped=1, pages_stored=1),
    )
    monkeypatch.setattr(mcp_server, "crawl", lambda url, **options: fake)

    result = mcp_server.crawl_tool("http://x")
    assert result["pages"][0]["content"] == "# Hi"
    assert result["stats"]["pages_stored"] == 1


def test_mcp_fetch_as_markdown(monkeypatch):
    """``fetch_as_markdown`` returns content and bounds the crawl to one page."""
    fake = CrawlResult(
        pages=[{"url": "http://x", "content": "# Hi", "metadata": {}}],
        stats=CrawlStats(),
    )
    captured = {}

    def fake_crawl(url, **options):
        captured.update(options)
        return fake

    monkeypatch.setattr(mcp_server, "crawl", fake_crawl)
    assert mcp_server.fetch_as_markdown("http://x") == "# Hi"
    assert captured["max_pages"] == 1
    assert captured["max_depth"] == 0


def test_mcp_fetch_as_markdown_no_content(monkeypatch):
    """``fetch_as_markdown`` raises when no content could be fetched."""
    fake = CrawlResult(pages=[], stats=CrawlStats())
    monkeypatch.setattr(mcp_server, "crawl", lambda url, **options: fake)
    with pytest.raises(RuntimeError):
        mcp_server.fetch_as_markdown("http://x")


def test_mcp_build_server_with_sdk():
    """When the SDK is installed, the server constructs in-process (smoke test)."""
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    assert server is not None
