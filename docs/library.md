# Library API

`crawler-to-md` is importable as a library. It has no CLI side effects: it
performs no argument parsing, does not print to stdout, and never calls
`sys.exit`. Errors propagate as standard Python exceptions.

---

## Import surface

```python
from crawler_to_md import (
    crawl,           # high-level entry point
    CrawlConfig,     # declarative configuration dataclass
    CrawlResult,     # returned by crawl() / run_crawl() / run_export()
    CrawlStats,      # aggregate run statistics (nested in CrawlResult)
    run_crawl,       # lower-level orchestration: build config → crawl → export
    run_export,      # re-run exports from an existing cache, no crawl
    Scraper,         # HTTP fetch + link-discovery engine
    ExportManager,   # corpus export (Markdown, JSON, JSONL, llms.txt, …)
    DatabaseManager, # SQLite wrapper (crawl frontier + page store)
)
```

All names above are in `__all__` and are stable public API.

---

## `crawl()`

```python
def crawl(
    url: str | None = None,
    *,
    urls: Iterable[str] | None = None,
    **options,
) -> CrawlResult:
```

The simplest entry point. Pass a single URL or an iterable of seed URLs, plus
any `CrawlConfig` field as a keyword argument.

**Library defaults differ from the CLI defaults:**

- `no_markdown=True` — no compiled `.md` file is written unless you opt in.
- `no_json=True` — no compiled `.json` file is written unless you opt in.
- `cache_folder` — an isolated temporary directory is used unless you supply
  one; the directory is not cleaned up automatically (use `tempfile.TemporaryDirectory`
  if you need that).

**Raises:**

- `TypeError` — an unknown keyword argument was passed.
- `ValueError` — neither `url` nor `urls` was supplied, or scraper construction
  failed (e.g. an unreachable proxy).

---

## Keyword options (`**options`)

Any field of `CrawlConfig` may be passed as a keyword argument to `crawl()`.
The table below lists the most useful ones with their types and defaults.

### Input

| Option | Type | Default | Description |
|---|---|---|---|
| `url` | `str \| None` | `None` | Single seed URL (positional-or-keyword) |
| `urls` | `Iterable[str] \| None` | `None` | Iterable of seed URLs |
| `base_url` | `str \| None` | derived | Restrict crawl to URLs starting with this prefix |

### Output

| Option | Type | Default | Description |
|---|---|---|---|
| `output_folder` | `str` | `"./output"` | Root directory for exported artefacts |
| `cache_folder` | `str` | temp dir | SQLite cache directory |
| `overwrite_cache` | `bool` | `False` | Remove existing cache before crawling |
| `title` | `str \| None` | seed URL | Title for compiled exports |
| `no_markdown` | `bool` | `True`* | Disable compiled `.md` output |
| `no_json` | `bool` | `True`* | Disable compiled `.json` output |
| `export_individual` | `bool` | `False` | One Markdown file per page |
| `frontmatter` | `bool` | `True` | YAML frontmatter on individual files |
| `export_jsonl` | `bool` | `False` | JSON Lines export |
| `export_llms` | `bool` | `False` | `llms.txt` + `llms-full.txt` export |
| `chunk_size` | `int` | `0` | RAG chunk size in tokens (`0` = off); needs `[rag]` |
| `chunk_overlap` | `int` | `0` | Token overlap between chunks |
| `export_vectors` | `bool` | `False` | Parquet export; needs `[vector]` |

*Library-only default (CLI default is `False`).

### Crawl control

| Option | Type | Default | Description |
|---|---|---|---|
| `exclude_url` | `list[str]` | `[]` | Skip URLs containing any of these substrings |
| `include_url` | `list[str]` | `[]` | Keep only URLs containing one of these substrings |
| `max_pages` | `int` | `0` | Stop after N pages (`0` = unlimited) |
| `max_depth` | `int` | `-1` | Max link-discovery depth (`-1` = unlimited) |
| `max_time` | `float` | `0` | Max wall-clock time in seconds (`0` = unlimited) |
| `rate_limit` | `int` | `0` | Max requests/minute (`0` = no limit) |
| `delay` | `float` | `0` | Seconds between requests |
| `concurrency` | `int` | `1` | Concurrent fetches (`1` = sync, `N>1` = async) |
| `proxy` | `str \| None` | `None` | HTTP or SOCKS proxy URL |

### Network / auth

| Option | Type | Default | Description |
|---|---|---|---|
| `timeout` | `float` | `15` | Per-request timeout in seconds |
| `max_retries` | `int` | `3` | Retries on timeout / 429 / 5xx |
| `user_agent` | `str \| None` | `None` | Custom User-Agent string |
| `header` | `list[str]` | `[]` | Extra headers as `"Key: Value"` strings |
| `cookie` | `list[str]` | `[]` | Cookies as `"key=value"` strings |
| `auth` | `str \| None` | `None` | HTTP Basic-auth as `"user:pass"` |

### Content shaping

| Option | Type | Default | Description |
|---|---|---|---|
| `include` | `list[str]` | `[]` | CSS-like selectors to keep before conversion |
| `exclude` | `list[str]` | `[]` | CSS-like selectors to remove before conversion |
| `extract` | `str` | `"none"` | `"none"` or `"readability"` (needs `[readability]`) |
| `render` | `bool` | `False` | JS rendering via Playwright (needs `[render]`) |
| `sitemap` | `bool` | `False` | Seed frontier from `/sitemap.xml` |
| `ignore_robots` | `bool` | `False` | Bypass `robots.txt` |
| `allow_types` | `list[str]` | `[]` | Extra MIME types for MarkItDown ingestion |

---

## `CrawlResult`

`crawl()`, `run_crawl()`, and `run_export()` all return a `CrawlResult`
dataclass with three fields:

```python
@dataclass
class CrawlResult:
    pages:   list[dict]       # one dict per stored page
    stats:   CrawlStats       # aggregate run statistics
    exports: dict[str, Any]   # paths of artefacts actually written
```

### `pages`

A list of dicts. Each dict has exactly these keys:

```python
{
    "url":      str,   # the page URL
    "content":  str,   # Markdown content of the page
    "metadata": dict,  # decoded JSON metadata (title, fetched_at, …)
}
```

### `stats` — `CrawlStats`

```python
@dataclass
class CrawlStats:
    links_discovered: int    # total URLs added to the frontier
    pages_scraped:    int    # URLs marked as visited
    pages_stored:     int    # pages with non-empty content in the DB
    content_bytes:    int    # total UTF-8 byte size of stored content
    total_tokens:     int    # total token count across the corpus
    token_method:     str    # "tiktoken" (exact) or "word-estimate"
    duration:         float  # wall-clock duration of the run in seconds
```

### `exports`

A dict mapping export name to path(s) written. Only exports that were
actually requested appear. Known keys:

| Key | Value |
|---|---|
| `"markdown"` | path to the compiled `.md` file |
| `"json"` | path to the compiled `.json` file |
| `"individual"` | path to the `files/` folder containing per-page files |
| `"jsonl"` | path to the `.jsonl` file |
| `"llms"` | `tuple[str, str]` — paths to `llms.txt` and `llms-full.txt` |
| `"chunks"` | path to the `chunks.jsonl` file |
| `"vectors"` | path to the `.parquet` file |
| `"errors"` | `dict[str, str]` — export name → error message for failed optional exports |

---

## `run_crawl()` and `run_export()`

For cases where you need full control over the configuration, use these
lower-level functions directly:

```python
from crawler_to_md import run_crawl, run_export, CrawlConfig

config = CrawlConfig(
    url="https://docs.example.com",
    max_pages=100,
    no_markdown=False,
    no_json=True,
    export_llms=True,
)
result = run_crawl(config)

# Re-run exports without re-crawling:
config.export_jsonl = True
result2 = run_export(config)
```

`run_export()` raises `ValueError` if no cache database exists for the URL.

---

## Worked examples

### Basic crawl — iterate over pages in memory

```python
from crawler_to_md import crawl

result = crawl("https://docs.example.com", max_pages=50)

for page in result.pages:
    print(page["url"], len(page["content"]))

print(
    f"{result.stats.pages_stored} pages, "
    f"{result.stats.total_tokens} tokens "
    f"({result.stats.token_method}), "
    f"{result.stats.duration:.1f}s"
)
```

### Crawl and write JSONL + llms.txt

```python
from crawler_to_md import crawl

result = crawl(
    "https://docs.example.com",
    max_pages=200,
    no_markdown=True,
    no_json=True,
    export_jsonl=True,
    export_llms=True,
    output_folder="./exports",
)

print("JSONL written to:", result.exports["jsonl"])
print("llms.txt at:     ", result.exports["llms"][0])
print("llms-full.txt at:", result.exports["llms"][1])
```

### Async crawl with concurrency and RAG chunking

```python
from crawler_to_md import crawl

result = crawl(
    "https://docs.example.com",
    concurrency=8,          # async httpx engine
    max_pages=500,
    max_time=120,           # cap at 2 minutes
    chunk_size=512,
    chunk_overlap=64,
    output_folder="./rag-export",
)

print(f"Chunks written to: {result.exports['chunks']}")
print(f"Errors (if any):   {result.exports.get('errors', {})}")
```

---

## Notes

- `crawl()` never calls `sys.exit` and never writes exports unless you
  explicitly enable them (all export flags default to off in library mode,
  with `no_markdown=True` and `no_json=True`).
- The `cache_folder` temporary directory created by the library is not
  cleaned up automatically. Wrap the call in a `tempfile.TemporaryDirectory`
  context manager if you need guaranteed cleanup.
- `CrawlResult.pages` is a `list[dict]` — access fields with `page["url"]`,
  not `page.url`.
