# Plugin system

`crawler-to-md` exposes an entry-point-based plugin architecture. The pipeline
is described by four typed protocols (defined in `crawler_to_md/plugins.py`),
and implementations are discovered through Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/).

All first-party features ship as plugins, and third parties can add their own by
declaring entry points in the same groups — no fork required.

## Protocols

Each protocol is a `typing.Protocol` with a `name` attribute (its registry key)
and a single method.

| Group | Entry-point group | Protocol | Method |
| --- | --- | --- | --- |
| Formatters | `crawler_to_md.formatters` | `Formatter` | `export(manager, output_path, **options)` |
| Filters | `crawler_to_md.filters` | `Filter` | `is_allowed(url) -> bool` |
| Processors | `crawler_to_md.processors` | `Processor` | `process(html, url) -> str` |
| Fetchers | `crawler_to_md.fetchers` | `Fetcher` | `fetch(url)` |

- **Formatter** — renders the crawled corpus to disk. Receives the live
  `ExportManager` (database connection + run title) and a destination path.
- **Filter** — decides whether a discovered URL belongs in the crawl frontier.
- **Processor** — transforms a page's HTML before Markdown conversion.
- **Fetcher** — retrieves a URL and returns a response-like object exposing
  `status_code`, `headers`, `text` and `content`.

## First-party implementations

These are registered as entry points in `pyproject.toml` and are also built into
the registry, so they are always available even before the distribution metadata
is refreshed.

- **Formatters**: `markdown`, `json`, `jsonl`, `llms`, `individual`, `chunks`,
  `vectors` — each delegates to the corresponding `ExportManager.export_to_*`
  method, so output is byte-identical to calling that method directly.
- **Filters**: `url-pattern` — the canonical include/exclude URL filter
  (mirrors `Scraper.is_valid_link`).
- **Processors**: `noop` — pass-through (returns HTML unchanged).
- **Fetchers**: `requests` — a `requests`-session GET; via
  `RequestsFetcher.from_scraper(...)` it reuses the scraper's retry/backoff GET.

## Using the registry

```python
from crawler_to_md.plugins import get_registry

registry = get_registry()

registry.names("formatters")          # -> ['chunks', 'individual', 'json', ...]
registry.get("formatters", "markdown")  # -> the MarkdownFormatter class
formatter = registry.create("formatters", "markdown")  # -> an instance
```

`ExportManager` re-expresses every export through the registry:

```python
manager.export_with("markdown", "out.md")
manager.export_with("individual", "out/", base_url="https://example.com")
manager.export_with("chunks", "chunks.jsonl", chunk_size=512, chunk_overlap=64)
```

Discovery is defensive: a missing distribution, an absent group, or an
individual plugin that fails to import is logged and skipped — it never raises.
Results are cached per group; call `registry.clear_cache()` (or
`discover(group, refresh=True)`) to force a re-scan.

## Registering a third-party plugin

Declare an entry point in your own package's `pyproject.toml`, pointing at a
class that implements the relevant protocol:

```toml
[project.entry-points."crawler_to_md.formatters"]
my-format = "my_package.exporters:MyFormatter"

[project.entry-points."crawler_to_md.filters"]
my-filter = "my_package.filters:MyFilter"

[project.entry-points."crawler_to_md.processors"]
my-processor = "my_package.processors:MyProcessor"

[project.entry-points."crawler_to_md.fetchers"]
my-fetcher = "my_package.fetchers:MyFetcher"
```

A minimal formatter:

```python
class MyFormatter:
    name = "my-format"

    def export(self, manager, output_path, **options):
        pages = manager.db_manager.get_all_pages()
        with open(output_path, "w", encoding="utf-8") as handle:
            for url, content, _metadata in pages:
                handle.write(f"{url}\n")
        return len(pages)
```

Once your package is installed, the plugin is discovered automatically and an
entry-point name overrides a built-in of the same name. See
`tests/sample_plugin.py` for a worked example exercised end-to-end in the test
suite.
