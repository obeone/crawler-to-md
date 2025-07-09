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
    """
    Test that disabling both markdown and JSON exports via CLI flags prevents export methods from being called.
    """
    calls = _run_cli(monkeypatch, tmp_path, ["--no-markdown", "--no-json"])
    assert calls["md"] is False
    assert calls["json"] is False


def test_cli_proxy_option(monkeypatch, tmp_path):
    """
    Test that the CLI correctly passes the --proxy option to the Scraper constructor.
    
    Verifies that when the CLI is invoked with a proxy URL, the Scraper instance receives the correct proxy argument.
    """
    captured = {}

    def fake_init(
        self,
        base_url,
        exclude_patterns,
        db_manager,
        rate_limit=0,
        delay=0,
        proxy=None,
    ):
        """
        A replacement initializer for the Scraper class that captures the value of the 'proxy' argument for testing purposes.
        
        Parameters:
            base_url: The base URL for scraping.
            exclude_patterns: Patterns to exclude from scraping.
            db_manager: Database manager instance.
            rate_limit: Optional rate limit for requests.
            delay: Optional delay between requests.
            proxy: Proxy URL to be captured for verification in tests.
        """
        captured['proxy'] = proxy

    monkeypatch.setattr(Scraper, '__init__', fake_init)
    monkeypatch.setattr(Scraper, 'start_scraping', lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, 'export_to_markdown', lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, 'export_to_json', lambda *a, **k: None)

    cache_folder = tmp_path / 'cache'
    args = [
        'prog',
        '--url',
        'http://example.com',
        '--output-folder',
        str(tmp_path),
        '--cache-folder',
        str(cache_folder),
        '--proxy',
        'http://proxy:8080',
    ]
    monkeypatch.setattr(sys, 'argv', args)
    cli.main()
    assert captured.get('proxy') == 'http://proxy:8080'

