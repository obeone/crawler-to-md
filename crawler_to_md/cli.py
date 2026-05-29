import argparse
import logging
import os
import sys

try:  # Python 3.11+ ships tomllib in the stdlib.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from . import log_setup, utils
from .core import config_from_namespace, run_crawl, run_export

logger = logging.getLogger(__name__)

# Subcommands recognised at the top level. Anything else on the command line is
# treated as arguments to the implicit ``crawl`` subcommand for backward
# compatibility with the pre-subcommand ``crawler-to-md --url ...`` invocation.
KNOWN_SUBCOMMANDS = ("crawl", "export", "mcp")

# Default config file auto-discovered in the current working directory.
DEFAULT_CONFIG_FILENAME = "crawler-to-md.toml"


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


def _add_io_arguments(parser):
    """
    Add the input/output arguments shared by the ``crawl`` and ``export`` subcommands.

    Args:
        parser (argparse.ArgumentParser): The (sub)parser to populate.
    """
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
        "--config",
        help="Path to a crawler-to-md.toml config file (CLI flags override it). "
        f"Auto-discovered as ./{DEFAULT_CONFIG_FILENAME} when omitted.",
        default=None,
    )


def _add_export_arguments(parser):
    """
    Add the export-related arguments shared by ``crawl`` and ``export``.

    Args:
        parser (argparse.ArgumentParser): The (sub)parser to populate.
    """
    parser.add_argument(
        "--export-individual",
        "-ei",
        action="store_true",
        help="Export each page as an individual Markdown file",
        default=False,
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


def _add_crawl_only_arguments(parser):
    """
    Add the crawl-specific arguments (network, filtering, bounds).

    Args:
        parser (argparse.ArgumentParser): The ``crawl`` subparser to populate.
    """
    parser.add_argument(
        "--overwrite-cache",
        "-w",
        action="store_true",
        help="Overwrite existing cache database if present",
        default=False,
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


def build_parser():
    """
    Build the top-level argument parser and its subcommand parsers.

    The parser exposes three subcommands — ``crawl`` (the default), ``export``
    (re-run exports from an existing cache without crawling), and ``mcp`` (start
    the MCP server). Every legacy ``crawl`` flag is preserved.

    Returns:
        tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]: The
        top-level parser and a mapping of subcommand name to its subparser.
    """
    parser = argparse.ArgumentParser(description="Web Scraper to Markdown")
    subparsers = parser.add_subparsers(dest="command")

    crawl_parser = subparsers.add_parser(
        "crawl", help="Crawl a site and export its content (default)"
    )
    _add_io_arguments(crawl_parser)
    _add_crawl_only_arguments(crawl_parser)
    _add_export_arguments(crawl_parser)

    export_parser = subparsers.add_parser(
        "export", help="Re-run exports from an existing cache database"
    )
    _add_io_arguments(export_parser)
    _add_export_arguments(export_parser)

    subparsers.add_parser("mcp", help="Start the MCP server over stdio")

    return parser, {
        "crawl": crawl_parser,
        "export": export_parser,
    }


def _inject_default_subcommand(argv):
    """
    Inject the implicit ``crawl`` subcommand for legacy-style invocations.

    Preserves backward compatibility: ``crawler-to-md --url ...`` (no
    subcommand) behaves exactly as before by dispatching to ``crawl``. When the
    first token is a known subcommand or a top-level help flag, the argument
    list is returned unchanged.

    Args:
        argv (list[str]): The argument list excluding the program name.

    Returns:
        list[str]: The argument list with a subcommand guaranteed in front.
    """
    if not argv:
        return ["crawl"]
    first = argv[0]
    if first in KNOWN_SUBCOMMANDS or first in ("-h", "--help"):
        return list(argv)
    return ["crawl"] + list(argv)


def _extract_config_arg(argv):
    """
    Extract the value of ``--config`` from a raw argument list, if present.

    Args:
        argv (list[str]): The argument list to scan.

    Returns:
        str | None: The config path supplied via ``--config``/``--config=``, or
        ``None`` if the flag is absent.
    """
    for index, token in enumerate(argv):
        if token == "--config" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--config="):
            return token.split("=", 1)[1]
    return None


def _resolve_config_path(argv):
    """
    Resolve the config file path: explicit ``--config`` or CWD auto-discovery.

    Args:
        argv (list[str]): The argument list to scan for ``--config``.

    Returns:
        str | None: The path to use, or ``None`` when no config file applies.
    """
    explicit = _extract_config_arg(argv)
    if explicit:
        return explicit
    default = os.path.join(os.getcwd(), DEFAULT_CONFIG_FILENAME)
    if os.path.exists(default):
        return default
    return None


def _load_config_file(path):
    """
    Load a ``crawler-to-md.toml`` config file into a flag-keyed dictionary.

    Keys are normalised by replacing hyphens with underscores so that both
    ``max-pages`` and ``max_pages`` map onto the ``max_pages`` flag. Read or
    parse errors are logged and yield an empty mapping rather than aborting.

    Args:
        path (str): Path to the TOML config file.

    Returns:
        dict: Mapping of normalised flag name to its configured value.
    """
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Could not read config file %s: %s", path, exc)
        return {}
    logger.debug("Loaded configuration from %s", path)
    return {str(key).replace("-", "_"): value for key, value in data.items()}


def _apply_config_file(argv, command, subparsers_map):
    """
    Apply config-file values as subparser defaults so CLI flags still override them.

    Config values are installed via :meth:`argparse.ArgumentParser.set_defaults`
    on the active subparser. Because argparse only falls back to a default when
    the option is absent from the command line, any explicitly-passed CLI flag
    wins over the file value.

    Args:
        argv (list[str]): The argument list (used to resolve ``--config``).
        command (str): The active subcommand (``"crawl"`` or ``"export"``).
        subparsers_map (dict[str, argparse.ArgumentParser]): Subparser registry.
    """
    if command not in subparsers_map:
        return
    config_path = _resolve_config_path(argv)
    if not config_path:
        return
    file_values = _load_config_file(config_path)
    if not file_values:
        return
    subparser = subparsers_map[command]
    valid = {action.dest for action in subparser._actions}
    valid -= {"help", "config", "command"}
    overrides = {key: value for key, value in file_values.items() if key in valid}
    if overrides:
        subparser.set_defaults(**overrides)


def _resolve_urls(args, parser):
    """
    Resolve the seed URL list from ``--urls-file``/stdin and validate input.

    Args:
        args (argparse.Namespace): The parsed arguments.
        parser (argparse.ArgumentParser): Parser used to emit a usage error.

    Returns:
        list[str]: The deduplicated seed URL list (empty in single-URL mode).
    """
    urls_file = getattr(args, "urls_file", None)
    if urls_file:
        if urls_file == "-":
            print("Enter URLs, one per line (Ctrl-D to finish):")
            urls_list = [line.strip() for line in sys.stdin]
        else:
            with open(urls_file, "r") as file:
                urls_list = [line.strip() for line in file.readlines()]
        urls_list = utils.deduplicate_list(urls_list)
        args.url = None  # Ensure args.url is defined even if not used
    else:
        urls_list = []

    if not getattr(args, "url", None) and not urls_list:
        parser.error("No URL provided. Please provide either --url or --urls-file.")
    return urls_list


def _print_result(result):
    """
    Print the export file paths and the end-of-run summary to stdout.

    Args:
        result (crawler_to_md.core.CrawlResult): The completed run result.
    """
    exports = result.exports
    if "markdown" in exports:
        print("\033[94mMarkdown file generated at: \033[0m", exports["markdown"])
    if "json" in exports:
        print("\033[92mJSON file generated at: \033[0m", exports["json"])
    if "individual" in exports:
        print(
            "\033[95mIndividual Markdown files exported to: \033[0m",
            exports["individual"],
        )
    if "jsonl" in exports:
        print("\033[96mJSONL file generated at: \033[0m", exports["jsonl"])
    if "llms" in exports:
        print("\033[96mllms.txt files generated at: \033[0m", exports["llms"][0])
    if "chunks" in exports:
        print("\033[96mRAG chunks file generated at: \033[0m", exports["chunks"])
    if "vectors" in exports:
        print(
            "\033[96mParquet vectors file generated at: \033[0m", exports["vectors"]
        )
    for message in exports.get("errors", {}).values():
        print("\033[91m", message, "\033[0m")

    _print_run_summary(result.stats)


def _print_run_summary(stats):
    """
    Print an end-of-run summary report to stdout.

    Args:
        stats (crawler_to_md.core.CrawlStats): Aggregate run statistics.
    """
    print("\033[1m\nRun summary\033[0m")
    print(f"  Links discovered : {stats.links_discovered}")
    print(f"  Pages scraped    : {stats.pages_scraped}")
    print(f"  Pages stored     : {stats.pages_stored}")
    print(f"  Content bytes    : {stats.content_bytes}")
    print(f"  Total tokens     : {stats.total_tokens} ({stats.token_method})")
    print(f"  Duration         : {stats.duration:.2f}s")


def _run_mcp():
    """
    Start the MCP server, surfacing a clear error if the ``mcp`` extra is missing.
    """
    from . import mcp_server

    try:
        mcp_server.serve()
    except RuntimeError as exc:
        print("\033[91m", exc, "\033[0m")
        sys.exit(1)


def main():
    """
    Main entry point for the crawler-to-md command-line interface.

    Dispatches to one of the ``crawl`` (default), ``export`` or ``mcp``
    subcommands. Invocations without an explicit subcommand are routed to
    ``crawl`` for backward compatibility. The heavy lifting is delegated to the
    shared core orchestration in :mod:`crawler_to_md.core`.
    """
    configure_logging()
    logger.info("Starting the web scraper application.")

    argv = _inject_default_subcommand(sys.argv[1:])
    parser, subparsers_map = build_parser()

    command = argv[0] if argv else "crawl"
    _apply_config_file(argv, command, subparsers_map)

    try:
        import argcomplete

        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args = parser.parse_args(argv)
    logger.debug(f"Command line arguments parsed: {args}")

    if args.command == "mcp":
        _run_mcp()
        return

    urls_list = _resolve_urls(args, parser)
    config = config_from_namespace(args, urls_list)

    try:
        if args.command == "export":
            result = run_export(config)
        else:
            result = run_crawl(config)
    except ValueError as exc:
        parser.error(str(exc))
    except OSError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    _print_result(result)


if __name__ == "__main__":
    main()
