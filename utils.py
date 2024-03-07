import logging  # Add log messages
from urllib.parse import urlparse, urlunparse

def url_to_filename(url):
    """
    Convert a URL to a valid filename.

    Args:
    url (str): The input URL.

    Returns:
    str: The converted filename.
    """
    parsed_url = urlparse(url)
    logging.debug(f"Parsing URL: {url}")  # Add log message
    
    # Combine the network and path without the query or fragment
    base_filename = parsed_url.netloc + parsed_url.path
    filename = base_filename.replace('/', '_').replace('.', '_')
    # Remove redundant underscores (useful if you have '__' in your string)
    filename = '_'.join(filter(None, filename.split('_')))
    
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
    logging.debug(f"Parsing URL: {url}")  # Add log message
    
    # Extract the path segments and remove the last segment
    path_segments = parsed_url.path.rsplit('/', 1)[0]
    
    # Recombine the components into a complete URL without the last path segment
    dirname_url = urlunparse((
        parsed_url.scheme,  # Protocol (http, https, etc.)
        parsed_url.netloc,  # Domain name and port
        path_segments,      # Path without the last segment
        '',                 # Parameters; empty here
        '',                 # Query; empty here
        '',                 # Fragment; empty here
    ))
    
    # Ensure it ends with '/'
    if not dirname_url.endswith('/'):
        dirname_url += '/'
    
    return dirname_url
