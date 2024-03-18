# Web Scraper to Markdown

This project is a Python-based web scraper that fetches content from specified URLs and exports the data into Markdown and JSON formats. It's designed to be lightweight and easily extendable.

## How it works

The web scraper starts by fetching content and metadata from the specified base URL (with `--base-url` option if provided, or the "dirname" of the URL if not). It then recursively follows links from the base URL to scrape additional content. The `--exclude` option allows excluding specific URLs containing a given string. 

The program outputs the scraped data into one Markdown and one JSON files. The Markdown file contains concatenated content from the scraped pages, with **adjusted headers to remain semantically valid**. The JSON file contains the URL, content, and filtered metadata of each page.

## Example

```shell
python main.py --url https://www.talos.dev/v1.6/ --base-url https://www.talos.dev/v1.6/ --exclude _print --title "Talos Documentation v1.6"
```

You will find in `output/www_talos_dev_v1_6` two files: `markdown.md` and `json.json`.

Extract of the `markdown.md` file :
```markdown
<!--
title: Welcome
description: Welcome Welcome to the Talos documentation. If you are just getting familiar with Talos, we recommend starting here: What is Talos: a quick …
date: 2024-01-01
categories: []
tags: []
pagetype: website
-->
# Talos Documentation v1.6

## Welcome
Welcome to the Talos documentation. If you are just getting familiar with Talos, we recommend starting here:
[What is Talos](/v1.6/introduction/what-is-talos/): a quick description of Talos [Quickstart](/v1.6/introduction/quickstart/): the fastest way to get a Talos cluster up and running [Getting Started](/v1.6/introduction/getting-started/): a long-form, guided tour of getting a full Talos cluster deployed
...
```

Extract of the `json.json` file :

```json
[
    {
        "url": "https://www.talos.dev/v1.6/",
        "content": "# Welcome\n## Welcome\nWelcome to the Talos documentation. If you are just getting familiar with Talos, we recommend starting here:\n[What is Talos](/v1.6/introduction/what-is-talos/): a quick description of Talos [Quickstart](/v1.6/introduction/quickstart/): the fastest way to get a Talos cluster up and running [Getting Started](/v1.6/introduction/getting-started/): a long-form, guided tour of getting a full Talos cluster deployed...",
        "metadata": {
            "title": "Welcome",
            "description": "Welcome Welcome to the Talos documentation. If you are just getting familiar with Talos, we recommend starting here: What is Talos: a quick …",
            "date": "2024-01-01",
            "categories": [],
            "tags": [],
            "pagetype": "website"
        }
    },
```

## Features

- Scrapes web pages for content and metadata.
- Exports scraped data to Markdown and JSON files.
- Utilizes SQLite for efficient data management.
- Configurable through command-line arguments.

## Requirements

To run this project, you need Python 3.12 and the following packages:

- requests
- beautifulsoup4
- trafilatura
- coloredlogs

Install them using:

```shell
pip install -r requirements.txt
```

## Usage

To start the web scraper, run:

```shell
python main.py --url <URL> [--output-folder ./output] [--cache-folder ./cache] [--base-url <BASE_URL>] [--exclude <KEYWORD_IN_URL>]
```

- `--url`: Base URL to start scraping (required).
- `--output-folder`: Output folder for the markdown file (default: `./output`).
- `--cache-folder`: Cache folder for storing the database (default: `./cache`).
- `--base-url`: Base URL for filtering links (default: "dirname" of the URL).
- `--exclude`: Exclude URLs containing this string. Can be used multiple times for multiple patterns.

## Docker Support

### Using pre-built images

Pre-built images are available for these platform :

- linux/amd64
- linux/arm64
- linux/i386
- linux/armhf

To use it :

```shell
docker run --rm -v $(pwd)/output:/app/output ghcr.io/obeone/crawler-to-md --url <URL>
```

(Image is available on Docker Hub too, [obeoneorg/crawler-to-md](https://hub.docker.com/r/obeoneorg/crawler-to-md))

### Building from source

A `Dockerfile` is included for containerizing the application. Build and run the Docker container using:

```shell
docker build -t crawler-to-md .
docker run --rm -v $(pwd)/output:/app/output crawler-to-md --url <URL>
```

## Ignored Files

Certain directories and files are ignored by git, Docker, and custom scripts to keep the workspace clean and secure:

- Temporary and development directories (`/old`, `/old2`, `/.venv`, etc.).
- Cache and output directories (`/cache`, `/output`).
- Python bytecode (`__pycache__`).

Refer to `.gitignore`, `.dockerignore`, and `.cursorignore` for the complete list.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.

