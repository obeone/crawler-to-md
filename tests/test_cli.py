import os
import sqlite3
import sys

import pytest

from crawler_to_md import cli, utils
from crawler_to_md.database_manager import DatabaseManager
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


def test_cli_proxy_option(monkeypatch, tmp_path):
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


def test_cli_proxy_short_option(monkeypatch, tmp_path):
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
        '-p',
        'http://proxy:8080',
    ]
    monkeypatch.setattr(sys, 'argv', args)
    cli.main()
    assert captured.get('proxy') == 'http://proxy:8080'


def test_cli_socks_proxy(monkeypatch, tmp_path):
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
        'socks5://localhost:9050',
    ]
    monkeypatch.setattr(sys, 'argv', args)
    cli.main()
    assert captured.get('proxy') == 'socks5://localhost:9050'


def test_cli_proxy_error(monkeypatch, tmp_path):
    def fake_init(*a, **k):
        raise ValueError('Proxy unreachable')

    monkeypatch.setattr(Scraper, '__init__', fake_init)
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
    with pytest.raises(SystemExit):
        cli.main()


def test_cli_overwrite_cache(monkeypatch, tmp_path):
    captured = {}

    def fake_init(self, db_path):
        captured['exists'] = os.path.exists(db_path)
        self.conn = sqlite3.connect(':memory:')

    monkeypatch.setattr(DatabaseManager, '__init__', fake_init)
    monkeypatch.setattr(ExportManager, 'export_to_markdown', lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, 'export_to_json', lambda *a, **k: None)
    monkeypatch.setattr(Scraper, 'start_scraping', lambda *a, **k: None)

    cache_folder = tmp_path / 'cache'
    db_name = utils.url_to_filename('http://example.com') + '.sqlite'
    db_path = cache_folder / db_name
    cache_folder.mkdir()
    db_path.write_text('dummy')

    args = [
        'prog',
        '--url',
        'http://example.com',
        '--output-folder',
        str(tmp_path),
        '--cache-folder',
        str(cache_folder),
        '--overwrite-cache',
    ]
    monkeypatch.setattr(sys, 'argv', args)
    cli.main()
    assert captured.get('exists') is False


def test_cli_overwrite_cache_short_option(monkeypatch, tmp_path):
    captured = {}

    def fake_init(self, db_path):
        captured['exists'] = os.path.exists(db_path)
        self.conn = sqlite3.connect(':memory:')

    monkeypatch.setattr(DatabaseManager, '__init__', fake_init)
    monkeypatch.setattr(ExportManager, 'export_to_markdown', lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, 'export_to_json', lambda *a, **k: None)
    monkeypatch.setattr(Scraper, 'start_scraping', lambda *a, **k: None)

    cache_folder = tmp_path / 'cache'
    db_name = utils.url_to_filename('http://example.com') + '.sqlite'
    db_path = cache_folder / db_name
    cache_folder.mkdir()
    db_path.write_text('dummy')

    args = [
        'prog',
        '--url',
        'http://example.com',
        '--output-folder',
        str(tmp_path),
        '--cache-folder',
        str(cache_folder),
        '-w',
    ]
    monkeypatch.setattr(sys, 'argv', args)
    cli.main()
    assert captured.get('exists') is False

