import json
import sys

import pytest

from crawler_to_md import cli, crawl, utils
from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.export_manager import ExportManager
from crawler_to_md.scraper import Scraper


def test_inject_default_subcommand_legacy():
    """Bare/legacy invocations are routed to the implicit ``crawl`` subcommand."""
    assert cli._inject_default_subcommand(["--url", "x"]) == ["crawl", "--url", "x"]
    assert cli._inject_default_subcommand(["crawl", "--url", "x"]) == [
        "crawl",
        "--url",
        "x",
    ]
    assert cli._inject_default_subcommand(["export", "--url", "x"]) == [
        "export",
        "--url",
        "x",
    ]
    assert cli._inject_default_subcommand(["mcp"]) == ["mcp"]
    assert cli._inject_default_subcommand([]) == ["crawl"]


def test_cli_explicit_crawl_subcommand(monkeypatch, tmp_path):
    """The explicit ``crawl`` subcommand exports like the legacy default path."""
    calls = {"md": False, "json": False}
    monkeypatch.setattr(
        ExportManager,
        "export_to_markdown",
        lambda self, p: calls.__setitem__("md", True),
    )
    monkeypatch.setattr(
        ExportManager,
        "export_to_json",
        lambda self, p: calls.__setitem__("json", True),
    )
    monkeypatch.setattr(Scraper, "start_scraping", lambda *a, **k: None)

    args = [
        "prog",
        "crawl",
        "--url",
        "http://example.com",
        "--output-folder",
        str(tmp_path),
        "--cache-folder",
        str(tmp_path / "cache"),
    ]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()
    assert calls["md"] is True
    assert calls["json"] is True


def test_cli_config_file_applied_and_overridden(monkeypatch, tmp_path):
    """Config-file values feed the crawl, and explicit CLI flags override them."""
    captured = {}

    def fake_init(
        self,
        base_url,
        exclude_patterns,
        include_url_patterns,
        db_manager,
        **kwargs,
    ):
        captured.clear()
        captured.update(kwargs)

    monkeypatch.setattr(Scraper, "__init__", fake_init)
    monkeypatch.setattr(Scraper, "start_scraping", lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, "export_to_markdown", lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, "export_to_json", lambda *a, **k: None)

    config_file = tmp_path / "crawler-to-md.toml"
    config_file.write_text("max_pages = 7\nrate_limit = 12\n")

    base = [
        "prog",
        "crawl",
        "--url",
        "http://example.com",
        "--output-folder",
        str(tmp_path),
        "--cache-folder",
        str(tmp_path / "cache"),
        "--config",
        str(config_file),
    ]
    monkeypatch.setattr(sys, "argv", base)
    cli.main()
    assert captured["max_pages"] == 7
    assert captured["rate_limit"] == 12

    monkeypatch.setattr(sys, "argv", base + ["--max-pages", "3"])
    cli.main()
    assert captured["max_pages"] == 3
    # rate_limit is not overridden on the CLI, so the file value persists.
    assert captured["rate_limit"] == 12


def test_export_subcommand_from_cache(monkeypatch, tmp_path):
    """The ``export`` subcommand re-exports from an existing cache, no crawling."""
    cache = tmp_path / "cache"
    cache.mkdir()
    db_name = utils.url_to_filename("http://example.com") + ".sqlite"
    db = DatabaseManager(str(cache / db_name))
    db.insert_page(
        "http://example.com",
        "# Page\n\nHello body",
        json.dumps({"title": "Page"}),
    )
    db.insert_link("http://example.com", visited=True)
    db.close()

    out = tmp_path / "out"
    args = [
        "prog",
        "export",
        "--url",
        "http://example.com",
        "--cache-folder",
        str(cache),
        "--output-folder",
        str(out),
    ]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()

    md_files = list(out.rglob("*.md"))
    json_files = list(out.rglob("*.json"))
    assert md_files, "expected a markdown export"
    assert json_files, "expected a json export"
    assert any("Hello body" in path.read_text() for path in md_files)


def test_export_subcommand_missing_cache(monkeypatch, tmp_path):
    """Exporting against a non-existent cache fails with a clean usage error."""
    args = [
        "prog",
        "export",
        "--url",
        "http://example.com",
        "--cache-folder",
        str(tmp_path / "nope"),
        "--output-folder",
        str(tmp_path / "out"),
    ]
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit):
        cli.main()


def test_crawl_library_returns_pages(monkeypatch, tmp_path):
    """The library ``crawl()`` runs with no argv and returns structured pages."""

    def fake_scrape(self, url=None, urls_list=None):
        target = url or (urls_list[0] if urls_list else None)
        self.db_manager.insert_page(
            target, "# Hello\n\nWorld", json.dumps({"title": "Hello"})
        )
        self.db_manager.insert_link(target, visited=True)

    monkeypatch.setattr(Scraper, "start_scraping", fake_scrape)

    result = crawl("http://example.com", cache_folder=str(tmp_path / "cache"))
    assert result.pages
    assert result.pages[0]["content"].startswith("# Hello")
    assert result.pages[0]["metadata"]["title"] == "Hello"
    assert result.stats.pages_stored == 1
    # Library default: no compiled exports are written.
    assert result.exports == {}


def test_crawl_library_no_url_raises_without_exit():
    """The library path raises ``ValueError`` instead of calling ``sys.exit``."""
    with pytest.raises(ValueError):
        crawl()
