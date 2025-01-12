from turtle import title
import log_setup
import os
import argparse
import utils
import sys

# Setup logging based on environment variable or default to WARN level before importing other modules.
log_level = os.getenv("LOG_LEVEL", "WARN")
log_setup.setup_logging(log_level)

from database_manager import DatabaseManager
from export_manager import ExportManager
from scraper import Scraper

logger = log_setup.get_logger()
logger.name = "main"


def main():
    """
    Main function to start the web scraper application.
    """
    logger.info("Starting the web scraper application.")
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Web Scraper to Markdown")
    parser.add_argument("--url", "-u", help="Base URL to start scraping")
    parser.add_argument("--urls-file", help="Path to a file containing URLs to scrape, one URL per line. If '-', read from stdin.")
    parser.add_argument("--output-folder", "-o", help="Output folder for the markdown file", default="./output")
    parser.add_argument("--cache-folder", "-c", help="Cache folder for storing database", default="./cache")
    parser.add_argument("--base-url", "-b", help="Base URL for filtering links. Defaults to the URL base")
    parser.add_argument("--title", "-t", help="Final title of the markdown file. Defaults to the URL")
    parser.add_argument("--exclude", "-e", action="append", help="Exclude URLs containing this string", default=[])
    parser.add_argument("--export-individual", "-ei", action="store_true", help="Export each page as an individual Markdown file", default=False)
    parser.add_argument("--rate-limit", "-rl", type=int, help="Maximum number of requests per minute", default=0)
    parser.add_argument("--delay", "-d", type=float, help="Delay between requests in seconds", default=0)

    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    
    args = parser.parse_args()
    logger.debug(f"Command line arguments parsed: {args}")

    # Read URLs from a file or stdin
    if args.urls_file:
        if args.urls_file == "-":
            print("Enter URLs, one per line (Ctrl-D to finish):")
            urls_list = [line.strip() for line in sys.stdin]
        else:
            with open(args.urls_file, "r") as file:
                urls_list = [line.strip() for line in file.readlines()]
                
        urls_list = utils.deduplicate_list(urls_list)
        args.url = None  # Ensure args.url is defined even if not used
    else:
        urls_list = []
        
    if not args.url and not urls_list:
        raise ValueError("No URL provided. Please provide either --url or --urls-file.")

    output = os.path.join(args.output_folder, utils.url_to_filename(args.url) if args.url else utils.url_to_filename(urls_list[0]))
    
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
        if not args.urls_file:
            args.base_url = utils.url_dirname(args.url if args.url else urls_list[0])
        logger.debug(f"No base URL provided. Setting base URL to {args.base_url}")

    # If no title, set it to the url base
    if not args.title:
        args.title = args.url if args.url else urls_list[0]
        logger.debug(f"No title provided. Setting title to {args.title}")

    # Initialize managers
    db_manager = DatabaseManager(os.path.join(args.cache_folder, utils.url_to_filename(args.url if args.url else urls_list[0]) + ".sqlite"))
    logger.info("DatabaseManager initialized.")

    scraper = Scraper(base_url=args.base_url, exclude_patterns=args.exclude, db_manager=db_manager, rate_limit=args.rate_limit, delay=args.delay)
    logger.info("Scraper initialized.")

    # Start the scraping process
    logger.info(f"Starting the scraping process for URL: {args.url}")
    scraper.start_scraping(url=args.url, urls_list=urls_list)

    output_name = utils.randomstring_to_filename(args.title)

    # After the scraping process is completed in the main function
    export_manager = ExportManager(db_manager, args.title)
    logger.info("ExportManager initialized.")
    
    export_manager.export_to_markdown(os.path.join(output, f"{output_name}.md"))
    logger.info("Export to markdown completed.")
    
    export_manager.export_to_json(os.path.join(output, f"{output_name}.json"))
    logger.info("Export to JSON completed.")
    
    if args.export_individual:
        logger.info("Export of individual pages...")
        output_folder_ei = export_manager.export_individual_markdown(output_folder=output, base_url=args.base_url if args.base_url else None)
        logger.info("Export of individual Markdown files completed.")
    
    markdown_path = os.path.join(output, f"{output_name}.md")
    json_path = os.path.join(output, f"{output_name}.json")
    print(f"\033[94m Markdown file generated at: \033[0m", markdown_path)
    print(f"\033[92m JSON file generated at: \033[0m", json_path)
    if args.export_individual:
        print(f"\033[95m Individual Markdown files exported to: \033[0m", output_folder_ei)


if __name__ == "__main__":
    main()
