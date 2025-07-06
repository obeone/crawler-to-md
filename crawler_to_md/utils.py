from urllib.parse import urlparse, urlunparse

from . import log_setup

logger = log_setup.get_logger()
logger.name = "utils"


def randomstring_to_filename(random_string):
    """
    Convert a random string to a valid filename.

    Args:
        random_string (str): The input random string.

    Returns:
        str: The converted filename.
    """
    # Sanitize characters that are not A-Za-z0-9_-
    valid_chars = "-_."
    filename = "".join(
        c if c.isalnum() or c in valid_chars else "_" if c == " " else ""
        for c in random_string
    )

    return filename


def url_to_filename(url):
    """
    Convert a URL to a valid filename, ensuring it is a string type to avoid TypeError.

    Args:
        url (str): The input URL.

    Returns:
        str: The converted filename.
    """
    # Ensure the URL is a string to prevent TypeError when performing string operations
    if not isinstance(url, str):
        raise ValueError("URL must be a string")

    parsed_url = urlparse(url)
    logger.debug(f"Parsing URL: {url}")  # Log the URL being parsed

    # Combine the network location and path,
    # replacing slashes and periods with underscores
    base_filename = parsed_url.netloc + parsed_url.path
    filename = base_filename.replace("/", "_").replace(".", "_")

    # Remove consecutive underscores for a cleaner filename
    filename = "_".join(filter(None, filename.split("_")))

    return filename


def url_dirname(url):
    """
    Extracts the directory name from the URL.

    Args:
        url (str): The input URL.

    Returns:
        str: The URL with the last path segment removed and ending with '/'.
    """
    parsed_url = urlparse(url)
    logger.debug(f"Parsing URL: {url}")  # Add log message

    # Extract the path segments and remove the last segment
    path_segments = parsed_url.path.rsplit("/", 1)[0]

    # Recombine the components into a complete URL without the last path segment
    dirname_url = urlunparse(
        (
            parsed_url.scheme,  # Protocol (http, https, etc.)
            parsed_url.netloc,  # Domain name and port
            path_segments,  # Path without the last segment
            "",  # Parameters; empty here
            "",  # Query; empty here
            "",  # Fragment; empty here
        )
    )

    # Ensure it ends with '/'
    if not dirname_url.endswith("/"):
        dirname_url += "/"

    return dirname_url


# Start Generation Here
def deduplicate_list(input_list):
    """
    Deduplicates a list while preserving the original order of elements.

    Args:
        input_list (list): The input list to be deduplicated.

    Returns:
        list: The deduplicated list.
    """
    seen = set()
    deduplicated_list = [x for x in input_list if not (x in seen or seen.add(x))]
    return deduplicated_list
