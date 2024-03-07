# Web Scraper to Markdown

This project is a Python-based web scraper that fetches content from specified URLs and exports the data into Markdown and JSON formats. It's designed to be lightweight and easily extendable.

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

```bash
pip install -r requirements.txt
```

## Usage

To start the web scraper, run:

```bash
python main.py --url <URL> [--output-folder ./output] [--cache-folder ./cache] [--base-url <BASE_URL>] [--exclude-url <EXCLUDE_URL>]
```

- `--url`: Base URL to start scraping (required).
- `--output-folder`: Output folder for the markdown file (default: `./output`).
- `--cache-folder`: Cache folder for storing the database (default: `./cache`).
- `--base-url`: Base URL for filtering links.
- `--exclude-url`: Exclude URLs containing this string. Can be used multiple times for multiple patterns.

## Docker Support

A `Dockerfile` is included for containerizing the application. Build and run the Docker container using:

```bash
docker build -t web-scraper .
docker run -v $(pwd)/output:/app/output -v $(pwd)/cache:/app/cache web-scraper --url <URL>
```

## Ignored Files

Certain directories and files are ignored by git, Docker, and custom scripts to keep the workspace clean and secure:

- Temporary and development directories (`/old`, `/old2`, `/.venv`, etc.).
- Cache and output directories (`/cache`, `/output`).
- Python bytecode (`__pycache__`).

Refer to `.gitignore`, `.dockerignore`, and `.cursorignore` for the complete list.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any bugs or feature requests.

