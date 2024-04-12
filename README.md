# Web Scraper to Markdown

This Python-based web scraper fetches content from URLs and exports it into Markdown and JSON formats, specifically designed for simplicity, extensibility, and for uploading JSON files to GPT models. Ideal for those looking to leverage web content for AI training or analysis.

## Quick Start

(Or even better, [use Docker!](#docker-support))

```shell
git clone https://github.com/your-repo/crawler-to-md.git
cd crawler-to-md
pip install -r requirements.txt

python main.py --url https://www.example.com
```

## Features

- Scrapes web pages for content and metadata.
- Filters links by base URL.
- Excludes URLs containing certain strings.
- Automatically find links or can use a file of URLs to scrape.
- Exports data to Markdown and JSON, ready for GPT uploads.
- Uses SQLite for efficient data management.
- Configurable via command-line arguments.
- Docker support.

## Requirements

Python 3.12 and the following packages:

- requests
- beautifulsoup4
- trafilatura
- coloredlogs

Install with `pip install -r requirements.txt`.

## Usage

Start scraping with the following command:

```shell
python main.py --url <URL> [--output-folder ./output] [--cache-folder ./cache] [--base-url <BASE_URL>] [--exclude <KEYWORD_IN_URL>] [--title <TITLE>] [--urls-file <URLS_FILE>]
```

Options:
- `--url`: The starting URL.
- `--urls-file`: Path to a file containing URLs to scrape, one URL per line. If '-', read from stdin.
- `--output-folder`: Where to save Markdown files (default: `./output`).
- `--cache-folder`: Where to store the database (default: `./cache`).
- `--base-url`: Filter links by base URL (default: URL's base).
- `--exclude`: Exclude URLs containing this string (repeatable).
- `--title`: Final title of the markdown file. Defaults to the URL.

One of the `--url` or `--urls-file` is required.

### Log level

By default, `WARN` level is used. You can change it with the `LOG_LEVEL` environment variable.

## Docker Support

Run with Docker:

```shell
docker run --rm -v $(pwd)/output:/app/output -v cache:/app/cache ghcr.io/obeone/crawler-to-md --url <URL>
```

Build from source:

```shell
docker build -t crawler-to-md .
docker run --rm -v $(pwd)/output:/app/output crawler-to-md --url <URL>
```

## Contributing

Contributions are welcome! Feel free to submit pull requests or open issues.
