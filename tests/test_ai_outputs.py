"""
Tests for Wave 2b AI-ready output formats (§5).

Covers JSONL export, YAML frontmatter on individual Markdown, llms.txt /
llms-full.txt, RAG chunking (rag extra + missing-extra error), Parquet vector
export (vector extra + missing-extra error), token accounting and the
end-of-run summary printed by ``cli.main``.
"""

import builtins
import json
import sys

import pytest

from crawler_to_md import cli, rag
from crawler_to_md.database_manager import DatabaseManager
from crawler_to_md.export_manager import (
    VECTOR_MISSING_MESSAGE,
    ExportManager,
)
from crawler_to_md.scraper import Scraper


def _populated_db():
    """
    Build an in-memory database with two non-empty pages and one empty one.

    Returns:
        DatabaseManager: A ready-to-export database manager.
    """
    db = DatabaseManager(":memory:")
    db.insert_page(
        "http://example.com/a",
        "# Alpha\n\nThe quick brown fox jumps over the lazy dog.",
        json.dumps({"title": "Alpha Page"}),
    )
    db.insert_page(
        "http://example.com/b",
        "# Bravo\n\nAnother paragraph with several words here.",
        json.dumps({"title": "Bravo Page"}),
    )
    db.insert_page("http://example.com/empty", None, "{}")
    return db


# ---------------------------------------------------------------------------
# 2.7 JSONL export
# ---------------------------------------------------------------------------


def test_export_jsonl_round_trips_records(tmp_path):
    db = _populated_db()
    exporter = ExportManager(db, title="Site")
    out = tmp_path / "out.jsonl"

    exporter.export_to_jsonl(str(out))

    lines = out.read_text(encoding="utf-8").splitlines()
    # Two non-empty pages; the None-content page is skipped.
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    urls = {r["url"] for r in records}
    assert urls == {"http://example.com/a", "http://example.com/b"}
    for record in records:
        assert set(record.keys()) == {"url", "content", "metadata"}
        assert record["content"]
        assert "title" in record["metadata"]


# ---------------------------------------------------------------------------
# 2.8 YAML frontmatter on individual Markdown
# ---------------------------------------------------------------------------


def _parse_frontmatter(text):
    """
    Extract the YAML frontmatter key/value lines from a Markdown document.

    Returns:
        dict[str, str]: Mapping of frontmatter keys to their raw string values.
    """
    assert text.startswith("---\n")
    end = text.index("\n---", 4)
    block = text[4:end]
    parsed = {}
    for line in block.splitlines():
        key, _, value = line.partition(":")
        parsed[key.strip()] = value.strip()
    return parsed


def test_individual_markdown_has_frontmatter(tmp_path):
    db = _populated_db()
    exporter = ExportManager(db, title="Site")

    exporter.export_individual_markdown(str(tmp_path))

    page = tmp_path / "files" / "example.com" / "a.md"
    text = page.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert "url" in fm and "example.com/a" in fm["url"]
    assert fm["title"] == '"Alpha Page"'
    assert "fetched_at" in fm
    assert int(fm["word_count"]) > 0
    # Body content is preserved after the frontmatter block.
    assert "# Alpha" in text


def test_individual_markdown_frontmatter_can_be_disabled(tmp_path):
    db = _populated_db()
    exporter = ExportManager(db, title="Site")

    exporter.export_individual_markdown(str(tmp_path), frontmatter=False)

    page = tmp_path / "files" / "example.com" / "a.md"
    text = page.read_text(encoding="utf-8")
    assert not text.startswith("---")
    assert text.startswith("# Alpha")


# ---------------------------------------------------------------------------
# 2.9 llms.txt / llms-full.txt
# ---------------------------------------------------------------------------


def test_export_llms_produces_index_and_full(tmp_path):
    db = _populated_db()
    exporter = ExportManager(db, title="My Site")

    index_path, full_path = exporter.export_to_llms(str(tmp_path))

    index = open(index_path, encoding="utf-8").read()
    full = open(full_path, encoding="utf-8").read()

    assert index.startswith("# My Site")
    assert "## Pages" in index
    assert "[Alpha Page](http://example.com/a)" in index
    assert "[Bravo Page](http://example.com/b)" in index

    assert full.startswith("# My Site")
    assert "quick brown fox" in full
    assert "Another paragraph" in full


# ---------------------------------------------------------------------------
# 2.10 RAG chunking (rag extra) + missing-extra error
# ---------------------------------------------------------------------------


def test_chunks_jsonl_with_tiktoken(tmp_path):
    pytest.importorskip("tiktoken")
    db = _populated_db()
    exporter = ExportManager(db, title="Site")
    out = tmp_path / "chunks.jsonl"

    total = exporter.export_chunks_jsonl(str(out), chunk_size=8, chunk_overlap=2)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert total == len(lines) >= 2
    for line in lines:
        record = json.loads(line)
        assert set(record.keys()) == {
            "url",
            "chunk_index",
            "content",
            "token_count",
        }
        assert record["token_count"] > 0


def test_chunks_jsonl_missing_extra_raises(tmp_path, monkeypatch):
    def _raise():
        raise ImportError(rag.RAG_MISSING_MESSAGE)

    monkeypatch.setattr(rag, "_load_tiktoken", _raise)

    db = _populated_db()
    exporter = ExportManager(db, title="Site")
    with pytest.raises(ImportError, match="rag"):
        exporter.export_chunks_jsonl(
            str(tmp_path / "chunks.jsonl"), chunk_size=8
        )


# ---------------------------------------------------------------------------
# 2.12 Vector / Parquet export (vector extra) + missing-extra error
# ---------------------------------------------------------------------------


def test_export_vectors_with_pyarrow(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    db = _populated_db()
    exporter = ExportManager(db, title="Site")
    out = tmp_path / "vectors.parquet"

    rows = exporter.export_to_vectors(str(out))

    assert rows == 2
    table = pq.read_table(str(out))
    assert set(table.column_names) == {
        "url",
        "content",
        "metadata",
        "token_count",
    }
    assert table.num_rows == 2


def test_export_vectors_missing_extra_raises(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError("No module named 'pyarrow'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    db = _populated_db()
    exporter = ExportManager(db, title="Site")
    with pytest.raises(ImportError, match="vector"):
        exporter.export_to_vectors(str(tmp_path / "vectors.parquet"))

    assert "vector" in VECTOR_MISSING_MESSAGE


# ---------------------------------------------------------------------------
# 2.11 Token accounting
# ---------------------------------------------------------------------------


def test_compute_token_totals_word_estimate(monkeypatch):
    # Force the tiktoken-free path so the labelled estimate is exercised.
    def _raise():
        raise ImportError(rag.RAG_MISSING_MESSAGE)

    monkeypatch.setattr(rag, "_load_tiktoken", _raise)

    db = _populated_db()
    exporter = ExportManager(db, title="Site")
    total, method, page_count = exporter.compute_token_totals()

    assert method == "word-estimate"
    assert total > 0
    assert page_count == 2


def test_estimate_tokens_labels_method():
    count, method = rag.estimate_tokens("one two three four")
    assert count > 0
    assert method in {"tiktoken", "word-estimate"}


# ---------------------------------------------------------------------------
# 2.13 Run summary printed by cli.main
# ---------------------------------------------------------------------------


def test_cli_prints_run_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Scraper, "start_scraping", lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, "export_to_markdown", lambda *a, **k: None)
    monkeypatch.setattr(ExportManager, "export_to_json", lambda *a, **k: None)

    cache_folder = tmp_path / "cache"
    args = [
        "prog",
        "--url",
        "http://example.com",
        "--output-folder",
        str(tmp_path),
        "--cache-folder",
        str(cache_folder),
    ]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()

    out = capsys.readouterr().out
    assert "Run summary" in out
    assert "Pages scraped" in out
    assert "Total tokens" in out
    assert "Duration" in out
