import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

# Query parameters considered tracking noise and dropped during canonicalization.
# ``utm_*`` parameters are handled separately via a prefix check.
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_eid",
        "mc_cid",
        "_hsenc",
        "_hsmi",
    }
)

# Default ports that are redundant for their scheme and therefore stripped.
_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _is_tracking_param(key):
    """
    Determine whether a query-parameter key is a tracking parameter.

    Args:
        key (str): The query-parameter name.

    Returns:
        bool: ``True`` if the key is a known tracking parameter (``utm_*`` or a
        member of :data:`_TRACKING_PARAMS`), ``False`` otherwise.
    """
    lowered = key.lower()
    return lowered.startswith("utm_") or lowered in _TRACKING_PARAMS


def canonicalize_url(url):
    """
    Return a canonical form of ``url`` suitable for deduplicating equivalent URLs.

    The following normalizations are applied without altering the semantic
    target of the URL:

    - lowercase the scheme and host (path and query values keep their case);
    - strip the default port for the scheme (``80`` for HTTP, ``443`` for HTTPS);
    - drop tracking query parameters (``utm_*``, ``fbclid``, ``gclid``, ...);
    - sort the remaining query parameters for a stable ordering;
    - remove the fragment;
    - normalize an empty path to ``"/"``.

    Args:
        url (str): The URL to canonicalize.

    Returns:
        str: The canonicalized URL. Non-string input is returned unchanged.
    """
    if not isinstance(url, str):
        return url

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    # Split userinfo and host:port so only the host is lowercased.
    netloc = parsed.netloc
    userinfo = ""
    hostport = netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
        userinfo += "@"
    if ":" in hostport:
        host, _, port = hostport.partition(":")
    else:
        host, port = hostport, ""
    host = host.lower()
    if port and _DEFAULT_PORTS.get(scheme) == port:
        port = ""
    netloc = f"{userinfo}{host}:{port}" if port else f"{userinfo}{host}"

    # Normalize an empty path so "http://host" and "http://host/" collapse.
    path = parsed.path or "/"

    # Drop tracking parameters and sort the remainder for stability.
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in pairs if not _is_tracking_param(k)]
    filtered.sort()
    query = urlencode(filtered)

    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


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
