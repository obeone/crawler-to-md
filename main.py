import log_setup

log_setup.setup_logging()

import argparse
import logging
import utils
from database_manager import DatabaseManager
from export_manager import ExportManager
from scraper import Scraper
import os

logger = logging.getLogger(__name__)


def main():
    logger.info("Starting the web scraper application.")
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Web Scraper to Markdown")
    parser.add_argument("--url", "-u", required=True, help="Base URL to start scraping")
    parser.add_argument(
        "--output-folder",
        "-o",
        help="Output folder for the markdown file",
        default="./output",
    )
    parser.add_argument(
        "--cache-folder",
        "-c",
        help="Cache folder for storing database",
        default="./cache",
    )
    parser.add_argument(
        "--base-url",
        "-b",
        help="Base URL for filtering links. Defaults to the URL base",
    )
    parser.add_argument(
        "--title", "-t", help="Final title of the markdown file. Defaults to the URL"
    )
    parser.add_argument(
        "--exclude",
        "-e",
        action="append",
        help="Exclude URLs containing this string",
        default=[],
    )
    args = parser.parse_args()

    logger.debug(f"Command line arguments parsed: {args}")

    output = os.path.join(args.output_folder, utils.url_to_filename(args.url))
    # Create the output folder if it does not exist
    if not os.path.exists(output):
        logger.info(f"Creating output folder at {output}")
        os.makedirs(output)

    # Create the cache folder if it does not exist
    if not os.path.exists(args.cache_folder):
        logger.info(f"Creating cache folder at {args.cache_folder}")
        os.makedirs(args.cache_folder)

    # If no base url, set it to the url base
    if not args.base_url:
        args.base_url = utils.url_dirname(args.url)
        logger.debug(f"No base URL provided. Setting base URL to {args.base_url}")

    # If no title, set it to the url base
    if not args.title:
        args.title = args.url
        logger.debug(f"No title provided. Setting title to {args.title}")

    # Initialize managers
    db_manager = DatabaseManager(
        os.path.join(args.cache_folder, utils.url_to_filename(args.url) + ".sqlite")
    )
    logger.info("DatabaseManager initialized.")
    scraper = Scraper(args.url, args.exclude, db_manager)
    logger.info("Scraper initialized.")

    # Start the scraping process
    logger.info(f"Starting the scraping process for URL: {args.url}")
    scraper.start_scraping(args.url)

    # After the scraping process is completed in the main function
    export_manager = ExportManager(db_manager, args.title)
    logger.info("ExportManager initialized.")
    export_manager.export_to_markdown(os.path.join(output, "markdown.md"))
    logger.info("Export to markdown completed.")
    export_manager.export_to_json(os.path.join(output, "json.json"))
    logger.info("Export to JSON completed.")


if __name__ == "__main__":
    main()
