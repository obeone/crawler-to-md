# MCP server

crawler-to-md ships an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/)
server that exposes crawling as two tools an AI agent or orchestrator can call
directly over stdio.

---

## Installation

The MCP server requires the optional `mcp` extra, which pulls in the
`mcp` Python SDK (`fastmcp`):

```shell
pip install "crawler-to-md[mcp]"
```

---

## Launching the server

```shell
crawler-to-md mcp
```

The server runs over **stdio** (standard input / standard output) and blocks
until the client disconnects. It does not bind any network port.

---

## Tools

### `crawl`

Crawl a site or page and return its pages and run statistics.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `url` | `string` | yes | Base URL to crawl |
| `options` | `object \| null` | no | Keyword overrides forwarded to `crawler_to_md.crawl()` (e.g. `max_pages`, `max_depth`, `concurrency`, `include_url`) |

**Returns** `object`:

```json
{
  "pages": [
    {
      "url": "https://example.com/page",
      "content": "# Page title\n\nPage content…",
      "metadata": { "title": "Page title", "fetched_at": "2024-01-01T00:00:00" }
    }
  ],
  "stats": {
    "links_discovered": 42,
    "pages_scraped": 40,
    "pages_stored": 38,
    "content_bytes": 184320,
    "total_tokens": 46080,
    "token_method": "word-estimate",
    "duration": 12.4
  }
}
```

### `fetch_as_markdown`

Fetch a single URL and return its Markdown content. No link discovery is
performed: the crawl is bounded to one page at depth zero.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `url` | `string` | yes | URL to fetch and convert to Markdown |
| `options` | `object \| null` | no | Keyword overrides forwarded to `crawler_to_md.crawl()` (e.g. `timeout`, `user_agent`, `render`) |

**Returns** `string` — the Markdown content of the page.

**Raises** (surfaced as an MCP error): `RuntimeError` if no content could be
fetched from the URL.

---

## Wiring into an MCP client

Point your MCP client at the `crawler-to-md mcp` command. The exact config
format depends on the client; below is a typical Claude Desktop / agent config
snippet:

```json
{
  "mcpServers": {
    "crawler-to-md": {
      "command": "crawler-to-md",
      "args": ["mcp"]
    }
  }
}
```

If `crawler-to-md` is not on `PATH` (e.g. installed in a virtual environment),
use the absolute path to the executable:

```json
{
  "mcpServers": {
    "crawler-to-md": {
      "command": "/path/to/venv/bin/crawler-to-md",
      "args": ["mcp"]
    }
  }
}
```

With `uvx` (no permanent install needed):

```json
{
  "mcpServers": {
    "crawler-to-md": {
      "command": "uvx",
      "args": ["--extra", "mcp", "crawler-to-md", "mcp"]
    }
  }
}
```

---

## Implementation notes

- The server is built with `mcp.server.fastmcp.FastMCP` under the name
  `"crawler-to-md"`.
- The underlying tool logic lives in plain callables (`crawl_tool` and
  `fetch_as_markdown` in `crawler_to_md/mcp_server.py`) that can be imported
  and tested independently without the MCP SDK installed.
- If the `mcp` extra is missing and you run `crawler-to-md mcp`, the CLI
  prints a clear error message (`pip install crawler-to-md[mcp]`) and exits
  with code 1.
