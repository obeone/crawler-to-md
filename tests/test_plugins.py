"""
Tests for the Wave 2.5 entry-point-based plugin system.

Covers protocol conformance, defensive registry discovery, first-party
implementations for every group, an example third-party-style formatter
discovered through an injected entry point and exercised end-to-end, and parity
between the registry-driven export path and the direct ``ExportManager``
methods (proving zero behaviour change).
"""

import json
from importlib.metadata import EntryPoint

import pytest

from crawler_to_md import plugins
from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.export_manager import ExportManager
from crawler_to_md.plugins import (
    Fetcher,
    Filter,
    Formatter,
    NoOpProcessor,
    PluginRegistry,
    Processor,
    RequestsFetcher,
    UrlPatternFilter,
    get_registry,
)
from crawler_to_md.scraper import Scraper

FIRST_PARTY_FORMATTERS = {
    "markdown",
    "json",
    "jsonl",
    "llms",
    "individual",
    "chunks",
    "vectors",
}


def _populated_db():
    """Build an in-memory database with two non-empty pages."""
    db = DatabaseManager(":memory:")
    db.insert_page(
        "http://example.com/a",
        "# Alpha\n\nThe quick brown fox.",
        json.dumps({"title": "Alpha Page"}),
    )
    db.insert_page(
        "http://example.com/b",
        "# Bravo\n\nAnother paragraph here.",
        json.dumps({"title": "Bravo Page"}),
    )
    return db


# ---------------------------------------------------------------------------
# Registry discovery of first-party plugins
# ---------------------------------------------------------------------------


def test_registry_discovers_first_party_formatters():
    registry = PluginRegistry()
    formatters = registry.discover("formatters")
    assert FIRST_PARTY_FORMATTERS <= set(formatters)
    # Every discovered formatter conforms to the Formatter protocol.
    for obj in formatters.values():
        instance = obj() if isinstance(obj, type) else obj
        assert isinstance(instance, Formatter)


def test_each_group_has_first_party_impl():
    registry = PluginRegistry()
    assert isinstance(registry.create("filters", "url-pattern"), Filter)
    assert isinstance(registry.create("processors", "noop"), Processor)
    assert isinstance(registry.create("fetchers", "requests"), Fetcher)


def test_unknown_group_raises():
    registry = PluginRegistry()
    with pytest.raises(KeyError):
        registry.discover("nonsense")


def test_get_returns_none_for_unknown_name():
    registry = PluginRegistry()
    assert registry.get("formatters", "does-not-exist") is None


def test_create_unknown_name_raises():
    registry = PluginRegistry()
    with pytest.raises(KeyError):
        registry.create("formatters", "does-not-exist")


# ---------------------------------------------------------------------------
# Defensive discovery
# ---------------------------------------------------------------------------


def test_discovery_tolerates_entry_point_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("metadata exploded")

    monkeypatch.setattr(plugins, "entry_points", _boom)
    registry = PluginRegistry()
    # Built-ins remain available and no exception escapes.
    formatters = registry.discover("formatters")
    assert FIRST_PARTY_FORMATTERS <= set(formatters)


def test_discovery_skips_broken_plugin(monkeypatch):
    broken = EntryPoint(
        name="broken",
        value="crawler_to_md.does_not_exist:Missing",
        group="crawler_to_md.formatters",
    )

    def _fake_entry_points(*, group):
        return [broken] if group == "crawler_to_md.formatters" else []

    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points)
    registry = PluginRegistry()
    formatters = registry.discover("formatters", refresh=True)
    # The broken plugin is skipped; built-ins survive.
    assert "broken" not in formatters
    assert FIRST_PARTY_FORMATTERS <= set(formatters)


def test_discovery_is_cached(monkeypatch):
    calls = {"n": 0}

    def _counting_entry_points(*, group):
        calls["n"] += 1
        return []

    monkeypatch.setattr(plugins, "entry_points", _counting_entry_points)
    registry = PluginRegistry()
    registry.discover("formatters")
    registry.discover("formatters")
    assert calls["n"] == 1
    registry.discover("formatters", refresh=True)
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Third-party-style formatter discovered via an injected entry point
# ---------------------------------------------------------------------------


def test_entry_point_formatter_discovered_and_used_end_to_end(monkeypatch, tmp_path):
    sample_ep = EntryPoint(
        name="sample",
        value="tests.sample_plugin:SampleFormatter",
        group="crawler_to_md.formatters",
    )

    def _fake_entry_points(*, group):
        return [sample_ep] if group == "crawler_to_md.formatters" else []

    monkeypatch.setattr(plugins, "entry_points", _fake_entry_points)

    registry = PluginRegistry()
    formatters = registry.discover("formatters", refresh=True)
    # Discovered alongside the built-ins.
    assert "sample" in formatters
    assert FIRST_PARTY_FORMATTERS <= set(formatters)

    # Used end-to-end through a real ExportManager.
    db = _populated_db()
    manager = ExportManager(db, title="Site")
    formatter = registry.create("formatters", "sample")
    out = tmp_path / "sample.txt"
    count = formatter.export(manager, str(out))

    assert count == 2
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# sample-plugin export")
    assert "http://example.com/a" in text
    assert "http://example.com/b" in text


# ---------------------------------------------------------------------------
# First-party filter / fetcher behaviour
# ---------------------------------------------------------------------------


def test_url_pattern_filter_matches_scraper():
    db = DatabaseManager(":memory:")
    scraper = Scraper(
        base_url="http://example.com",
        exclude_patterns=["/private"],
        include_url_patterns=["/docs"],
        db_manager=db,
    )
    plugin_filter = UrlPatternFilter.from_scraper(scraper)

    candidates = [
        "http://example.com/docs/intro",
        "http://example.com/docs/private/secret",
        "http://other.com/docs/intro",
        "http://example.com/blog/post",
        "http://example.com/docs/intro?utm_source=x",
    ]
    for url in candidates:
        assert plugin_filter.is_allowed(url) == scraper.is_valid_link(url)


def test_url_pattern_filter_default_allows_everything():
    assert UrlPatternFilter().is_allowed("http://anything.example/x")


def test_noop_processor_returns_html_unchanged():
    processor = NoOpProcessor()
    html = "<html><body>hi</body></html>"
    assert processor.process(html, "http://example.com") == html


def test_requests_fetcher_from_scraper_delegates(monkeypatch):
    db = DatabaseManager(":memory:")
    scraper = Scraper(
        base_url="http://example.com",
        exclude_patterns=[],
        include_url_patterns=[],
        db_manager=db,
    )
    sentinel = object()
    captured = {}

    def _fake_get_with_retry(url):
        captured["url"] = url
        return sentinel

    monkeypatch.setattr(scraper, "_get_with_retry", _fake_get_with_retry)
    fetcher = RequestsFetcher.from_scraper(scraper)
    result = fetcher.fetch("http://example.com/page")

    assert result is sentinel
    assert captured["url"] == "http://example.com/page"


# ---------------------------------------------------------------------------
# Registry-driven export parity (zero behaviour change)
# ---------------------------------------------------------------------------


def test_export_with_markdown_matches_direct(tmp_path):
    db = _populated_db()
    manager = ExportManager(db, title="Site")

    direct = tmp_path / "direct.md"
    via_registry = tmp_path / "registry.md"
    manager.export_to_markdown(str(direct))
    manager.export_with("markdown", str(via_registry))

    assert via_registry.read_text(encoding="utf-8") == direct.read_text(
        encoding="utf-8"
    )


def test_export_with_json_matches_direct(tmp_path):
    db = _populated_db()
    manager = ExportManager(db, title="Site")

    direct = tmp_path / "direct.json"
    via_registry = tmp_path / "registry.json"
    manager.export_to_json(str(direct))
    manager.export_with("json", str(via_registry))

    assert json.loads(via_registry.read_text(encoding="utf-8")) == json.loads(
        direct.read_text(encoding="utf-8")
    )


def test_export_with_unknown_formatter_raises(tmp_path):
    db = _populated_db()
    manager = ExportManager(db, title="Site")
    with pytest.raises(KeyError):
        manager.export_with("nope", str(tmp_path / "x"))


def test_default_registry_is_shared():
    assert get_registry() is plugins.registry
