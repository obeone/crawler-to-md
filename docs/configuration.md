# Configuration reference

crawler-to-md can be configured through a TOML file, through CLI flags, or
through environment variables. The three sources are layered in this priority
order (highest wins):

```
CLI flags  >  crawler-to-md.toml  >  built-in defaults
```

---

## Config file auto-discovery

When no `--config` flag is passed, the tool looks for `crawler-to-md.toml` in
the current working directory. If the file exists it is loaded automatically.
To use a file at a different path, pass `--config path/to/file.toml` explicitly.

Keys in the TOML file may use either hyphens (`max-pages`) or underscores
(`max_pages`); both map to the same option.

---

## LOG_LEVEL environment variable

Logging verbosity is controlled by the `LOG_LEVEL` environment variable.
The default level is `WARN`. Accepted values are the standard Python level
names: `DEBUG`, `INFO`, `WARNING` / `WARN`, `ERROR`, `CRITICAL`.

```shell
LOG_LEVEL=INFO crawler-to-md --url https://example.com
```

---

## Complete annotated example

Copy this file to `crawler-to-md.toml` in your working directory, then
uncomment and adjust the keys you need. CLI flags override every value shown
here.

```toml
# crawler-to-md.toml
# All keys are optional. Uncomment to override the default.

# ── Input ────────────────────────────────────────────────────────────────────
# url = "https://docs.example.com"        # single seed URL
# urls-file = "urls.txt"                  # file of seed URLs (one per line); "-" = stdin

# ── Output ───────────────────────────────────────────────────────────────────
# output-folder = "./output"              # directory for exported artefacts
# cache-folder  = "~/.cache/crawler-to-md"  # directory for SQLite databases

# ── Identity ─────────────────────────────────────────────────────────────────
# base-url = "https://docs.example.com"  # restrict crawl to URLs starting here
                                          # (derived from seed URL when omitted)
# title = "My Site Docs"                  # title for compiled exports
                                          # (defaults to the seed URL)

# ── Crawl control ────────────────────────────────────────────────────────────
# overwrite-cache = false                 # remove existing cache DB before crawling
# exclude-url = ["/tag/", "/author/"]     # skip URLs containing any of these strings
# include-url = ["/docs/"]               # keep only URLs containing one of these strings
# rate-limit  = 0                         # max requests/minute (0 = no limit)
# delay       = 0                         # seconds between requests
# proxy       = "http://proxy:8080"       # HTTP or SOCKS proxy URL

# ── HTML filtering (applied before Markdown conversion) ──────────────────────
# include = ["main", ".content", "#article"]  # CSS-like selectors to keep
# exclude = ["nav", ".sidebar", "footer"]     # CSS-like selectors to remove

# ── Robustness ───────────────────────────────────────────────────────────────
# timeout     = 15                        # per-request timeout in seconds
# max-retries = 3                         # retries on transient failures (timeout/429/5xx)
# max-pages   = 0                         # stop after N pages (0 = unlimited)
# max-depth   = -1                        # max link-discovery depth (-1 = unlimited)
# max-time    = 0                         # max wall-clock crawl time in seconds (0 = unlimited)

# ── Concurrency ──────────────────────────────────────────────────────────────
# concurrency = 1                         # 1 = synchronous; N > 1 = async with bounded parallelism

# ── Intelligence ─────────────────────────────────────────────────────────────
# ignore-robots = false                   # bypass robots.txt (honoured by default)
# user-agent    = "MyBot/1.0"             # custom User-Agent string
# sitemap       = false                   # seed frontier from /sitemap.xml
# extract       = "none"                  # "none" or "readability" (needs [readability] extra)
# render        = false                   # JS rendering via Playwright (needs [render] extra)
# header        = ["X-API-Key: secret"]   # extra request headers (list, repeatable on CLI)
# cookie        = ["session=abc123"]      # cookies as "key=value" strings
# auth          = "user:pass"             # HTTP Basic-auth credentials
# allow-types   = ["application/pdf"]     # extra MIME types to ingest via MarkItDown

# ── Output formats ───────────────────────────────────────────────────────────
# export-individual = false               # one Markdown file per page
# frontmatter       = true                # YAML frontmatter on individual files
# no-markdown       = false               # disable the compiled .md output
# no-json           = false               # disable the compiled .json output
# export-jsonl      = false               # JSON Lines export (one record per line)
# export-llms       = false               # llms.txt + llms-full.txt (llmstxt.org convention)
# chunk-size        = 0                   # RAG chunk size in tokens (0 = disabled); needs [rag]
# chunk-overlap     = 0                   # token overlap between consecutive chunks
# export-vectors    = false               # Parquet export for vector indexing; needs [vector]
```

---

## Key reference

### Input / output

| Key | Type | Default | Description |
|---|---|---|---|
| `url` | string | — | Single seed URL |
| `urls-file` | string | — | Path to a file of seed URLs (one per line); `"-"` reads stdin |
| `output-folder` | string | `"./output"` | Root directory for exported artefacts |
| `cache-folder` | string | `"~/.cache/crawler-to-md"` | Directory for SQLite cache databases |
| `base-url` | string | derived from seed URL | Restrict crawl to URLs with this prefix |
| `title` | string | seed URL | Title for compiled Markdown/JSON outputs |

### Crawl control

| Key | Type | Default | Description |
|---|---|---|---|
| `overwrite-cache` | bool | `false` | Remove existing cache database before crawling |
| `exclude-url` | list[string] | `[]` | Skip URLs containing any listed substring |
| `include-url` | list[string] | `[]` | Keep only URLs containing at least one listed substring |
| `rate-limit` | int | `0` | Max requests per minute (`0` = no limit) |
| `delay` | float | `0` | Seconds to wait between requests |
| `proxy` | string | — | HTTP or SOCKS proxy URL |

### HTML filtering

| Key | Type | Default | Description |
|---|---|---|---|
| `include` | list[string] | `[]` | CSS-like selectors (`#id`, `.class`, `tag`) to keep before conversion |
| `exclude` | list[string] | `[]` | CSS-like selectors to remove before conversion |

### Robustness

| Key | Type | Default | Description |
|---|---|---|---|
| `timeout` | float | `15` | Per-request timeout in seconds |
| `max-retries` | int | `3` | Retries on timeout, 429, or 5xx responses |
| `max-pages` | int | `0` | Stop after N pages scraped (`0` = unlimited) |
| `max-depth` | int | `-1` | Max link-discovery depth (`-1` = unlimited) |
| `max-time` | float | `0` | Max wall-clock crawl time in seconds (`0` = unlimited) |

### Concurrency

| Key | Type | Default | Description |
|---|---|---|---|
| `concurrency` | int | `1` | Number of concurrent fetches (`1` = synchronous path) |

### Intelligence

| Key | Type | Default | Description |
|---|---|---|---|
| `ignore-robots` | bool | `false` | Bypass `robots.txt` (honoured by default) |
| `user-agent` | string | — | Custom User-Agent string on every request |
| `sitemap` | bool | `false` | Seed the frontier from the host's `/sitemap.xml` |
| `extract` | string | `"none"` | Content extraction strategy: `"none"` or `"readability"` (needs `[readability]` extra) |
| `render` | bool | `false` | Fetch JS-rendered HTML via Playwright (needs `[render]` extra + `playwright install chromium`) |
| `header` | list[string] | `[]` | Extra request headers as `"Key: Value"` strings |
| `cookie` | list[string] | `[]` | Request cookies as `"key=value"` strings |
| `auth` | string | — | HTTP Basic-auth credentials as `"user:pass"` |
| `allow-types` | list[string] | `[]` | Extra MIME types to ingest via MarkItDown (e.g. `"application/pdf"`) |

### Output formats

| Key | Type | Default | Description |
|---|---|---|---|
| `export-individual` | bool | `false` | Export each page as an individual Markdown file |
| `frontmatter` | bool | `true` | Prepend YAML frontmatter to individual Markdown exports |
| `no-markdown` | bool | `false` | Disable the compiled `.md` file |
| `no-json` | bool | `false` | Disable the compiled `.json` file |
| `export-jsonl` | bool | `false` | Export as JSON Lines (one `{url, content, metadata}` per line) |
| `export-llms` | bool | `false` | Export `llms.txt` (index) + `llms-full.txt` (full content) |
| `chunk-size` | int | `0` | RAG chunk size in tokens (`0` = disabled); requires `[rag]` extra |
| `chunk-overlap` | int | `0` | Token overlap between consecutive RAG chunks |
| `export-vectors` | bool | `false` | Export to a Parquet file for vector indexing; requires `[vector]` extra |

---

## Notes

- The `export` subcommand accepts the same output-format keys but not the
  crawl-control keys (it reads from an existing cache database).
- The `mcp` subcommand ignores the config file entirely.
- When `urls-file` is set, the `url` key is ignored.
