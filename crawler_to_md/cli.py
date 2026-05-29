import argparse
import asyncio
import logging
import os
import sys
import time

from . import log_setup, utils
from .database_manager import DatabaseManager
from .export_manager import ExportManager
from .scraper import Scraper

logger = logging.getLogger(__name__)


def configure_logging():
    """
    Configure application logging based on the environment.

    Reads the desired level from the ``LOG_LEVEL`` environment variable
    (defaulting to ``WARN``) and installs the Tqdm-aware coloredlogs handler
    on the root logger. This is invoked explicitly from :func:`main` rather
    than at import time so that importing the package never mutates global
    logging state as a side effect.
    """
    log_level = os.getenv("LOG_LEVEL", "WARN")
    log_setup.setup_logging(log_level)


def main():
    """
    Main function to start the web scraper application.

    This function parses command line arguments, initializes necessary components,
    and manages the scraping and exporting process.

    Raises:
        ValueError: If neither a URL nor a URLs file is provided.
    """
    configure_logging()
    logger.info("Starting the web scraper application.")


    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Web Scraper to Markdown")
    parser.add_argument("--url", "-u", help="Base URL to start scraping")
    parser.add_argument(
        "--urls-file",
        help="Path to a file containing URLs to scrape, one URL per line. "
        "If '-', read from stdin.",
    )
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
        default="~/.cache/crawler-to-md",
    )
    parser.add_argument(
        "--overwrite-cache",
        "-w",
        action="store_true",
        help="Overwrite existing cache database if present",
        default=False,
    )
    parser.add_argument(
        "--base-url",
        "-b",
        help="Base URL for filtering links. Defaults to the URL base",
    )
    parser.add_argument(
        "--title",
        "-t",
        help="Final title of the markdown file. Defaults to the URL",
    )
    parser.add_argument(
        "--exclude-url",
        "-e",
        action="append",
        help="Exclude URLs containing this string",
        default=[],
    )
    parser.add_argument(
        "--include-url",
        "-I",
        action="append",
        help="Include only URLs containing this string",
        default=[],
    )
    parser.add_argument(
        "--export-individual",
        "-ei",
        action="store_true",
        help="Export each page as an individual Markdown file",
        default=False,
    )
    parser.add_argument(
        "--rate-limit",
        "-rl",
        type=int,
        help="Maximum number of requests per minute",
        default=0,
    )
    parser.add_argument(
        "--delay",
        "-d",
        type=float,
        help="Delay between requests in seconds",
        default=0,
    )
    parser.add_argument(
        "--proxy",
        "-p",
        help="Proxy URL for HTTP or SOCKS requests",
        default=None,
    )
    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Disable generation of the compiled Markdown file",
        default=False,
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Disable generation of the compiled JSON file",
        default=False,
    )
    parser.add_argument(
        "--include",
        "-i",
        action="append",
        help=(
            "CSS-like selector (#id, .class, tag) to include before Markdown "
            "conversion. Repeatable."
        ),
        default=[],
    )
    parser.add_argument(
        "--exclude",
        "-x",
        action="append",
        help=(
            "CSS-like selector (#id, .class, tag) to exclude before Markdown "
            "conversion. Repeatable."
        ),
        default=[],
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Per-request timeout in seconds",
        default=15,
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        help="Maximum retries on transient failures (timeouts, 429, 5xx)",
        default=3,
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Maximum number of pages to scrape (0 = unlimited)",
        default=0,
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        help="Maximum crawl depth for link discovery (-1 = unlimited)",
        default=-1,
    )
    parser.add_argument(
        "--max-time",
        type=float,
        help="Maximum wall-clock crawl time in seconds (0 = unlimited)",
        default=0,
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        help="Number of concurrent fetches (1 = synchronous, the default)",
        default=1,
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Ignore robots.txt rules (robots is honored by default)",
        default=False,
    )
    parser.add_argument(
        "--user-agent",
        help="User-Agent string sent on every request (default: descriptive UA)",
        default=None,
    )
    parser.add_argument(
        "--sitemap",
        action="store_true",
        help="Seed the frontier from the host's /sitemap.xml before crawling",
        default=False,
    )
    parser.add_argument(
        "--extract",
        choices=["none", "readability"],
        help="Content extraction strategy (readability requires the "
        "'readability' extra)",
        default="none",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Fetch JS-rendered HTML via Playwright (requires the 'render' extra)",
        default=False,
    )
    parser.add_argument(
        "--header",
        action="append",
        help="Extra request header as 'Key: Value'. Repeatable.",
        default=[],
    )
    parser.add_argument(
        "--cookie",
        action="append",
        help="Request cookie as 'key=value'. Repeatable.",
        default=[],
    )
    parser.add_argument(
        "--auth",
        help="HTTP basic-auth credentials as 'user:pass'",
        default=None,
    )
    parser.add_argument(
        "--allow-types",
        action="append",
        help="Additional content-type to ingest via MarkItDown (e.g. "
        "application/pdf). Repeatable.",
        default=[],
    )
    parser.add_argument(
        "--export-jsonl",
        action="store_true",
        help="Export pages as JSON Lines (one {url, content, metadata} per line)",
        default=False,
    )
    parser.add_argument(
        "--export-llms",
        action="store_true",
        help="Export llms.txt (page index) and llms-full.txt (full content)",
        default=False,
    )
    parser.add_argument(
        "--frontmatter",
        action=argparse.BooleanOptionalAction,
        help="Prepend per-page YAML frontmatter to individual Markdown exports "
        "(on by default; disable with --no-frontmatter)",
        default=True,
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        help="RAG chunk size in tokens (0 = disabled). Requires the 'rag' extra.",
        default=0,
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        help="RAG chunk overlap in tokens (used when --chunk-size > 0)",
        default=0,
    )
    parser.add_argument(
        "--export-vectors",
        action="store_true",
        help="Export pages to a Parquet file. Requires the 'vector' extra.",
        default=False,
    )

    try:
        import argcomplete


        argcomplete.autocomplete(parser)
    except ImportError:
        pass


    args = parser.parse_args()
    logger.debug(f"Command line arguments parsed: {args}")

    # Expand user path for cache folder
    args.cache_folder = os.path.expanduser(args.cache_folder)

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
        parser.error("No URL provided. Please provide either --url or --urls-file.")

    first_url = args.url if args.url else urls_list[0]
    output = os.path.join(args.output_folder, utils.url_to_filename(first_url))

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
            args.base_url = utils.url_dirname(first_url)
        logger.debug(f"No base URL provided. Setting base URL to {args.base_url}")

    # If no title, set it to the url base
    if not args.title:
        args.title = first_url
        logger.debug(f"No title provided. Setting title to {args.title}")

    # Initialize managers
    db_path = os.path.join(
        args.cache_folder, utils.url_to_filename(first_url) + ".sqlite"
    )
    if args.overwrite_cache and os.path.exists(db_path):
        logger.info(f"Removing existing cache database at {db_path}")
        try:
            os.remove(db_path)
        except OSError as e:
            logger.error(f"Failed to remove cache database at {db_path}: {e}")
            sys.exit(1)
    db_manager = DatabaseManager(db_path)
    logger.info("DatabaseManager initialized.")

    try:
        scraper = Scraper(
            base_url=args.base_url,
            exclude_patterns=args.exclude_url,
            include_url_patterns=args.include_url,
            db_manager=db_manager,
            rate_limit=args.rate_limit,
            delay=args.delay,
            proxy=args.proxy,
            include_filters=args.include,
            exclude_filters=args.exclude,
            timeout=args.timeout,
            max_retries=args.max_retries,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            max_time=args.max_time,
            concurrency=args.concurrency,
            ignore_robots=args.ignore_robots,
            user_agent=args.user_agent,
            sitemap=args.sitemap,
            extract=args.extract,
            render=args.render,
            headers=args.header,
            cookies=args.cookie,
            auth=args.auth,
            allow_types=args.allow_types,
        )
    except ValueError as exc:
        parser.error(str(exc))
    logger.info("Scraper initialized.")

    # Start the scraping process. Concurrency > 1 selects the async crawl
    # engine; 1 (the default) uses the synchronous path for identical behavior.
    logger.info(f"Starting the scraping process for URL: {args.url}")
    start_time = time.perf_counter()
    if args.concurrency > 1:
        asyncio.run(
            scraper.start_scraping_async(url=args.url, urls_list=urls_list)
        )
    else:
        scraper.start_scraping(url=args.url, urls_list=urls_list)

    output_name = utils.randomstring_to_filename(args.title)

    # After the scraping process is completed in the main function
    export_manager = ExportManager(db_manager, args.title)
    logger.info("ExportManager initialized.")


    if not args.no_markdown:
        export_manager.export_to_markdown(os.path.join(output, f"{output_name}.md"))
        logger.info("Export to markdown completed.")

    if not args.no_json:
        export_manager.export_to_json(os.path.join(output, f"{output_name}.json"))
        logger.info("Export to JSON completed.")

    output_folder_ei = None
    if args.export_individual:
        logger.info("Export of individual pages...")
        output_folder_ei = export_manager.export_individual_markdown(
            output_folder=output,
            base_url=args.base_url,
            frontmatter=args.frontmatter,
        )
        logger.info("Export of individual Markdown files completed.")

    jsonl_path = os.path.join(output, f"{output_name}.jsonl")
    if args.export_jsonl:
        export_manager.export_to_jsonl(jsonl_path)
        logger.info("Export to JSONL completed.")

    llms_paths = None
    if args.export_llms:
        llms_paths = export_manager.export_to_llms(output)
        logger.info("Export to llms.txt completed.")

    chunks_path = os.path.join(output, "chunks.jsonl")
    chunk_count = None
    if args.chunk_size > 0:
        try:
            chunk_count = export_manager.export_chunks_jsonl(
                chunks_path, args.chunk_size, args.chunk_overlap
            )
            logger.info("Export of RAG chunks completed.")
        except ImportError as exc:
            print("\033[91m", exc, "\033[0m")

    vectors_path = os.path.join(output, f"{output_name}.parquet")
    vector_rows = None
    if args.export_vectors:
        try:
            vector_rows = export_manager.export_to_vectors(
                vectors_path, args.chunk_size, args.chunk_overlap
            )
            logger.info("Export to Parquet completed.")
        except ImportError as exc:
            print("\033[91m", exc, "\033[0m")

    markdown_path = os.path.join(output, f"{output_name}.md")
    json_path = os.path.join(output, f"{output_name}.json")
    if not args.no_markdown:
        print("\033[94mMarkdown file generated at: \033[0m", markdown_path)
    if not args.no_json:
        print("\033[92mJSON file generated at: \033[0m", json_path)
    if args.export_individual and output_folder_ei:
        print(
            "\033[95mIndividual Markdown files exported to: \033[0m",
            output_folder_ei,
        )
    if args.export_jsonl:
        print("\033[96mJSONL file generated at: \033[0m", jsonl_path)
    if args.export_llms and llms_paths:
        print("\033[96mllms.txt files generated at: \033[0m", llms_paths[0])
    if chunk_count is not None:
        print("\033[96mRAG chunks file generated at: \033[0m", chunks_path)
    if vector_rows is not None:
        print("\033[96mParquet vectors file generated at: \033[0m", vectors_path)

    duration = time.perf_counter() - start_time
    _print_run_summary(export_manager, db_manager, duration)


def _print_run_summary(export_manager, db_manager, duration):
    """
    Print an end-of-run summary report to stdout.

    The report covers the crawl frontier (total vs visited links), the corpus
    size (pages and bytes of content), total token usage (exact via tiktoken
    when the ``rag`` extra is installed, otherwise a labelled word-based
    estimate) and the wall-clock duration.

    Args:
        export_manager (ExportManager): Used to compute corpus token totals.
        db_manager (DatabaseManager): Source of link/page counts.
        duration (float): Wall-clock crawl duration in seconds.
    """
    total_links = db_manager.get_links_count()
    visited_links = db_manager.get_visited_links_count()
    pages = db_manager.get_all_pages()
    page_count = sum(1 for _u, content, _m in pages if content is not None)
    total_bytes = sum(
        len((content or "").encode("utf-8")) for _u, content, _m in pages
    )
    total_tokens, method, _measured = export_manager.compute_token_totals()

    print("\033[1m\nRun summary\033[0m")
    print(f"  Links discovered : {total_links}")
    print(f"  Pages scraped    : {visited_links}")
    print(f"  Pages stored     : {page_count}")
    print(f"  Content bytes    : {total_bytes}")
    print(f"  Total tokens     : {total_tokens} ({method})")
    print(f"  Duration         : {duration:.2f}s")


if __name__ == "__main__":
    main()
