from urllib.parse import urljoin, urlparse
import re
from bs4 import BeautifulSoup
import log_setup

logger = log_setup.get_logger()
logger.name = "MarkdownEditor"

class MarkdownEditor:
    def __init__(self, base_url):
        """
        Initializes the MarkdownEditor with a base URL.

        Args:
            base_url (str): The base URL to be used for converting absolute URLs to relative ones.
        """
        self.base_url = base_url
        logger.debug(f"MarkdownEditor initialized with base URL: {self.base_url}")

    def replace_absolute_urls(self, markdown_content):
        """
        Replaces all absolute URLs in the given markdown content with their corresponding relative URLs.

        Args:
            markdown_content (str): The markdown content containing absolute URLs that need to be replaced.

        Returns:
            str: The modified markdown content with absolute URLs replaced by relative URLs.
        """
        logger.debug("Replacing absolute URLs with relative ones.")
        relative_markdown = re.sub(
            r"\[.*?\]\((https?://.*?)\)",
            lambda match: self._replace_url(match.group(0)),
            markdown_content
        )
        return relative_markdown

    def _replace_url(self, url):
        """
        Replaces an absolute URL with its corresponding relative URL.

        Args:
            url (str): The absolute URL to be replaced.

        Returns:
            str: The modified URL with the absolute path replaced by a relative path, if applicable.
        """
        logger.debug(f"Replacing URL: {url}")
        absolute_url = re.search(r"\((https?://.*?)\)", url).group(1)
        relative_path = self._get_relative_path(absolute_url)

        if relative_path:
            # Ensure local links have .md or index.md
            local_path = self._adjust_for_local_markdown(relative_path)
            logger.debug(f"Relative path adjusted: {local_path}")
            return f"[{re.search(r'\[.*?\]', url).group(0)}]({local_path})"
        else:
            logger.debug("No relative path found.")
            return url

    def _get_relative_path(self, absolute_url):
        """
        Determines the relative path of an absolute URL with respect to the base URL.

        Args:
            absolute_url (str): The absolute URL for which the relative path needs to be determined.

        Returns:
            str or None: The relative path of the absolute URL if it belongs to the same domain as the base URL, else None.
        """
        logger.debug(f"Determining relative path for: {absolute_url}")
        parsed_base = urlparse(self.base_url)
        parsed_url = urlparse(absolute_url)

        if (parsed_base.scheme == parsed_url.scheme) and (parsed_base.netloc == parsed_url.netloc):
            relative_path = parsed_url.path.lstrip('/')
            logger.debug(f"Relative path found: {relative_path}")
            return relative_path
        else:
            logger.debug("Relative path not found.")
            return None

    def _adjust_for_local_markdown(self, relative_path):
        """
        Adjusts a local path to end with .md or index.md if it does not already have one.
        Args:
            relative_path (str): The relative path of the URL that needs to be adjusted.

        Returns:
            str: The adjusted relative path ending with .md or index.md, if applicable.
        """
        logger.debug(f"Adjusting local path: {relative_path}")
        if relative_path.endswith('/'):
            adjusted_path = relative_path + 'index.md'
        else:
            adjusted_path = relative_path + '.md'
        logger.debug(f"Adjusted path: {adjusted_path}")
        return adjusted_path
