# crawler-to-md 🌐✍️

This Python-based web scraper fetches content from URLs and exports it into Markdown and JSON formats, specifically designed for simplicity, extensibility, and for uploading JSON files to GPT models. It is ideal for those looking to leverage web content for AI training or analysis. 🤖💡

## 🚀 Quick Start

(Or even better, **[use Docker!](#-docker-support) 🐳**)

### Recommended installation using pipx (isolated environment)

```shell
pipx install crawler-to-md
```

### Alternatively, install with pip

```shell
pip install crawler-to-md
```

Then run the scraper:

```shell
crawler-to-md --url https://www.example.com
```

## 🌟 Features

- Scrapes web pages for content and metadata. 📄
- Filters links by base URL. 🔍
- Excludes URLs containing certain strings. ❌
- Automatically finds links or can use a file of URLs to scrape. 🔗
- Rate limiting and delay support. 🕘
- Exports data to Markdown and JSON, ready for GPT uploads. 📤
- Exports each page as an individual Markdown file if `--export-individual` is used. 📝
- Uses SQLite for efficient data management. 📊
- Configurable via command-line arguments or a `crawler-to-md.toml` config file. ⚙️
- Include or exclude specific HTML elements using CSS-like selectors (#id, .class, tag) during Markdown conversion. 🧩
- **Robustness**: automatic retries with exponential backoff, configurable timeouts, crawl bounds. 🔁
- **Concurrency**: async `httpx` engine for parallel fetching (`--concurrency N`). ⚡
- **Crawl intelligence**: robots.txt compliance, sitemap seeding, boilerplate extraction, JS rendering. 🧠
- **AI-ready outputs**: JSONL, llms.txt/llms-full.txt, YAML frontmatter, RAG chunks, Parquet vectors. 🤖
- **MCP server**: expose crawl tools to AI agents via the Model Context Protocol. 🔌
- **Library API**: use `from crawler_to_md import crawl` in your own code. 📦
- **Plugin system**: extend formatters, filters, processors, and fetchers via Python entry points. 🔧
- Docker support. 🐳

## 📋 Requirements

Python 3.10 or higher is required.

Project dependencies are managed with `pyproject.toml`. Install the core package with:

```shell
pip install crawler-to-md
```

### Optional extras

Heavy or niche features ship as optional extras so the core stays lightweight:

| Extra | Install | Enables |
|---|---|---|
| `readability` | `pip install crawler-to-md[readability]` | Boilerplate extraction via trafilatura (`--extract readability`) |
| `render` | `pip install crawler-to-md[render]` | JS rendering via Playwright (`--render`). After install run `playwright install chromium`. |
| `rag` | `pip install crawler-to-md[rag]` | Token-aware RAG chunking via tiktoken (`--chunk-size`/`--chunk-overlap`); exact token counts in the run summary |
| `vector` | `pip install crawler-to-md[vector]` | Parquet vector export via pyarrow (`--export-vectors`) |
| `mcp` | `pip install crawler-to-md[mcp]` | MCP server (`crawler-to-md mcp`) |
| `dev` | `pip install crawler-to-md[dev]` | pytest, ruff, pytest-cov |

Extras can be combined:

```shell
pip install crawler-to-md[rag,vector]
pip install crawler-to-md[readability,render,mcp]
```

## 🛠 Usage

### Subcommands

crawler-to-md now uses subcommands. The legacy `crawler-to-md --url ...` invocation is fully preserved — when no subcommand is given the tool defaults to `crawl`.

```shell
crawler-to-md crawl   --url <URL> [options]   # crawl a site and export
crawler-to-md export  --url <URL> [options]   # re-export from an existing cache (no re-crawl)
crawler-to-md mcp                             # start the MCP server over stdio
```

### Config file

Place a `crawler-to-md.toml` file in your working directory and it is discovered automatically. Pass `--config path/to/file.toml` to use a different location. CLI flags always override config file values.

```toml
# crawler-to-md.toml — example
url = "https://docs.example.com"
output-folder = "./docs-export"
concurrency = 4
max-pages = 200
export-llms = true
chunk-size = 512
chunk-overlap = 64
```

### `crawl` — full option reference

```shell
crawler-to-md crawl --url <URL> [--urls-file <FILE>] [options]
```

#### Input / output

- `--url`, `-u`: The starting URL. 🌍
- `--urls-file`: Path to a file containing URLs to scrape, one URL per line. If `-`, read from stdin. 📁
- `--output-folder`, `-o`: Where to save output files (default: `./output`). 📂
- `--cache-folder`, `-c`: Where to store the SQLite database (default: `~/.cache/crawler-to-md`). 💾
- `--base-url`, `-b`: Filter links by base URL (default: URL's base). 🔎
- `--title`, `-t`: Title for the output files. Defaults to the URL. 🏷️
- `--config`: Path to a `crawler-to-md.toml` config file. Auto-discovered in CWD when omitted. ⚙️

#### Crawl control

- `--overwrite-cache`, `-w`: Overwrite existing cache database before scraping. 🧹
- `--exclude-url`, `-e`: Exclude URLs containing this string (repeatable). ❌
- `--include-url`, `-I`: Include only URLs containing this string (repeatable). ✅
- `--rate-limit`, `-rl`: Maximum number of requests per minute (default: 0, no limit). ⏱️
- `--delay`, `-d`: Delay between requests in seconds (default: 0). 🕒
- `--proxy`, `-p`: Proxy URL for HTTP or SOCKS requests. 🌐

#### HTML filtering

- `--include`, `-i`: CSS-like selector (#id, .class, tag) to include before Markdown conversion (repeatable). ✅
- `--exclude`, `-x`: CSS-like selector (#id, .class, tag) to exclude before Markdown conversion (repeatable). 🚫

#### Robustness

- `--timeout`: Per-request timeout in seconds (default: `15`). ⏳
- `--max-retries`: Maximum retries on transient failures — timeouts, 429, 5xx — with exponential backoff (default: `3`). 🔁
- `--max-pages`: Stop after scraping this many pages (`0` = unlimited). 📏
- `--max-depth`: Maximum link-discovery depth (`-1` = unlimited). 🌊
- `--max-time`: Maximum wall-clock crawl time in seconds (`0` = unlimited). ⏰

#### Concurrency

- `--concurrency N`: Number of parallel fetches. `1` (default) uses the synchronous engine; `N > 1` enables the async `httpx` engine with a bounded semaphore. Per-host politeness (rate limit, delay) is preserved in async mode. ⚡

#### Intelligence

- `--ignore-robots`: Disable robots.txt compliance (robots.txt is **honored by default**). 🤖
- `--user-agent`: Custom User-Agent string sent on every request. 🪪
- `--sitemap`: Seed the crawl frontier from the host's `/sitemap.xml` before crawling. 🗺️
- `--extract {none,readability}`: Content-extraction strategy. `readability` uses trafilatura to strip boilerplate (requires `pip install crawler-to-md[readability]`). Default: `none`. 🧹
- `--render`: Fetch JS-rendered HTML via Playwright (requires `pip install crawler-to-md[render]` and `playwright install chromium`). Off by default. 🎭
- `--header "Key: Value"`: Extra request header (repeatable). 📬
- `--cookie "key=value"`: Request cookie (repeatable). 🍪
- `--auth user:pass`: HTTP Basic authentication credentials. 🔑
- `--allow-types application/pdf`: Additional MIME types to ingest via MarkItDown — e.g. `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (repeatable). 📎

#### Output formats

- `--export-individual`, `-ei`: Export each page as an individual Markdown file. 📝
- `--frontmatter` / `--no-frontmatter`: Prepend YAML frontmatter (url, title, fetched_at, word_count, token_count) to individual Markdown files. On by default. 🗂️
- `--no-markdown`: Skip generation of the compiled Markdown file. 🚫
- `--no-json`: Skip generation of the compiled JSON file. 🚫
- `--export-jsonl`: Export pages as JSON Lines — one `{url, content, metadata}` record per line. 🗃️
- `--export-llms`: Export `llms.txt` (page index) and `llms-full.txt` (full content) in the emerging LLM-friendly format. 🤖
- `--chunk-size N`: Split pages into RAG chunks of `N` tokens (0 = disabled). Requires `pip install crawler-to-md[rag]`. 🧩
- `--chunk-overlap N`: Token overlap between consecutive chunks (used when `--chunk-size > 0`). 🔗
- `--export-vectors`: Export pages to a Parquet file for downstream vector indexing. Requires `pip install crawler-to-md[vector]`. 📊

#### Run summary

Every run prints an end-of-run summary to stdout:

```
Run summary
  Links discovered : 142
  Pages scraped    : 98
  Pages stored     : 98
  Content bytes    : 1048576
  Total tokens     : 210340 (estimated)
  Duration         : 34.21s
```

Token counts are exact when the `rag` extra is installed (tiktoken), or estimated otherwise.

### `export` — re-export without re-crawling

Re-run any combination of export formats from an existing cache database without hitting the network again. Accepts all the same output flags as `crawl`.

```shell
crawler-to-md export --url https://docs.example.com \
  --export-llms --export-jsonl --chunk-size 512 --chunk-overlap 64
```

### `mcp` — MCP server

Expose crawl tools to AI agents and orchestrators that speak the [Model Context Protocol](https://modelcontextprotocol.io/) over stdio.

```shell
# requires the mcp extra
pip install crawler-to-md[mcp]
crawler-to-md mcp
```

Tools exposed: `crawl` and `fetch_as_markdown`.

### 📚 Log level

By default, the `WARN` level is used. Change it with the `LOG_LEVEL` environment variable:

```shell
LOG_LEVEL=INFO crawler-to-md --url https://example.com
```

## 📦 Library API

Use `crawler_to_md` as a library — no CLI side effects, no `sys.argv` parsing.

```python
from crawler_to_md import crawl

result = crawl("https://docs.example.com", max_pages=50, concurrency=4)

for page in result.pages:
    print(page.url, len(page.content))

print(f"Scraped {result.stats.pages_scraped} pages in {result.stats.duration:.1f}s")
```

`crawl()` returns a `CrawlResult` object with:

- `result.pages` — list of scraped pages (url, content, metadata)
- `result.stats` — aggregate run statistics (pages scraped, bytes, tokens, duration)
- `result.exports` — paths of any files written (if export options are passed)

## 🔧 Plugin System

crawler-to-md exposes an entry-point-based plugin architecture for all four pipeline stages. See **[docs/plugins.md](docs/plugins.md)** for the full reference.

### Entry-point groups

| Stage | Group | Protocol method |
|---|---|---|
| **Formatter** | `crawler_to_md.formatters` | `export(manager, output_path, **options)` |
| **Filter** | `crawler_to_md.filters` | `is_allowed(url) -> bool` |
| **Processor** | `crawler_to_md.processors` | `process(html, url) -> str` |
| **Fetcher** | `crawler_to_md.fetchers` | `fetch(url)` |

All built-in output formats ship as first-party formatters (`markdown`, `json`, `jsonl`, `llms`, `individual`, `chunks`, `vectors`) and are wired live through the registry. Register your own by declaring an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."crawler_to_md.formatters"]
my-format = "my_package.exporters:MyFormatter"
```

Once your package is installed, the plugin is discovered automatically. See `tests/sample_plugin.py` for a worked end-to-end example.

> **Note**: The filter, processor, and fetcher plugin protocols and registries are defined and tested, but are not yet consumed by the crawl loop — see [Known Limitations](#-known-limitations--follow-ups).

## 🐳 Docker Support

Run with Docker:

```shell
docker run --rm \
  -v $(pwd)/output:/app/output \
  -v cache:/home/app/.cache/crawler-to-md \
  ghcr.io/obeone/crawler-to-md --url <URL>
```

Build from source:

```shell
docker build -t crawler-to-md .

docker run --rm \
  -v $(pwd)/output:/app/output \
  crawler-to-md --url <URL>
```

## ⚠️ Known Limitations / Follow-ups

- **Filter/processor/fetcher plugin protocols** are fully defined and tested but are not yet consumed by the crawl loop. Formatters are wired live; the other three stages are available for extension and will be integrated in a future release.
- **Sitemap parsing** uses the stdlib `xml.etree.ElementTree`. For untrusted or adversarially crafted sitemaps, consider using `defusedxml` as a drop-in replacement to guard against XML DoS attacks (billion-laughs).

## 🤝 Contributing

Contributions are welcome! Feel free to submit pull requests or open issues. 🌟
