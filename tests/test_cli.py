import sys
from crawler_to_md import cli
from crawler_to_md.export_manager import ExportManager
from crawler_to_md.scraper import Scraper


def _run_cli(monkeypatch, tmp_path, extra_args):
    calls = {"md": False, "json": False}

    def fake_export_markdown(self, path):
        calls["md"] = True

    def fake_export_json(self, path):
        calls["json"] = True

    monkeypatch.setattr(ExportManager, "export_to_markdown", fake_export_markdown)
    monkeypatch.setattr(ExportManager, "export_to_json", fake_export_json)
    monkeypatch.setattr(Scraper, "start_scraping", lambda *a, **k: None)

    cache_folder = tmp_path / "cache"
    args = [
        "prog",
        "--url",
        "http://example.com",
        "--output-folder",
        str(tmp_path),
        "--cache-folder",
        str(cache_folder),
    ] + extra_args

    monkeypatch.setattr(sys, "argv", args)
    cli.main()
    return calls


def test_cli_default_exports(monkeypatch, tmp_path):
    calls = _run_cli(monkeypatch, tmp_path, [])
    assert calls["md"] is True
    assert calls["json"] is True


def test_cli_disable_exports(monkeypatch, tmp_path):
    calls = _run_cli(monkeypatch, tmp_path, ["--no-markdown", "--no-json"])
    assert calls["md"] is False
    assert calls["json"] is False

