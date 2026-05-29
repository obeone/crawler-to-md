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
- Configurable via command-line arguments. ⚙️
- Include or exclude specific HTML elements using CSS-like selectors (#id, .class, tag) during Markdown conversion. 🧩
- Docker support. 🐳

## 📋 Requirements

Python 3.10 or higher is required.

Project dependencies are managed with `pyproject.toml`. Install them with:

```shell
pip install .
```

## 🛠 Usage

Start scraping with the following command:

```shell
crawler-to-md --url <URL> [--output-folder ./output] [--cache-folder ./cache] [--overwrite-cache|-w] [--base-url <BASE_URL>] [--exclude-url <KEYWORD_IN_URL>] [--title <TITLE>] [--urls-file <URLS_FILE>] [-p <PROXY_URL>]
```

Options:

- `--url`, `-u`: The starting URL. 🌍
- `--urls-file`: Path to a file containing URLs to scrape, one URL per line. If '-', read from stdin. 📁
- `--output-folder`, `-o`: Where to save Markdown files (default: `./output`). 📂
- `--cache-folder`, `-c`: Where to store the database (default: `./cache`). 💾
- `--overwrite-cache`, `-w`: Overwrite existing cache database before scraping. 🧹
- `--base-url`, `-b`: Filter links by base URL (default: URL's base). 🔎
- `--title`, `-t`: Final title of the markdown file. Defaults to the URL. 🏷️
- `--exclude-url`, `-e`: Exclude URLs containing this string (repeatable). ❌
- `--export-individual`, `-ei`: Export each page as an individual Markdown file. 📝
- `--rate-limit`, `-rl`: Maximum number of requests per minute (default: 0, no rate limit). ⏱️
- `--delay`, `-d`: Delay between requests in seconds (default: 0, no delay). 🕒
- `--proxy`, `-p`: Proxy URL for HTTP or SOCKS requests. 🌐
- `--include`, `-i`: CSS-like selector (#id, .class, tag) to include before Markdown conversion (repeatable). ✅
- `--exclude`, `-x`: CSS-like selector (#id, .class, tag) to exclude before Markdown conversion (repeatable). 🚫

One of the `--url` or `--urls-file` options is required.

### 📚 Log level

By default, the `WARN` level is used. You can change it with the `LOG_LEVEL` environment variable.

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

## 🤝 Contributing

Contributions are welcome! Feel free to submit pull requests or open issues. 🌟
