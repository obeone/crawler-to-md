import json
import os

from . import log_setup
from .database_manager import DatabaseManager

logger = log_setup.get_logger()
logger.name = "export_manager"


class ExportManager:
    def __init__(self, db_manager: DatabaseManager, title=None):
        """
        Initialize the ExportManager with a DatabaseManager instance.

        Args:
            db_manager (DatabaseManager): The DatabaseManager instance for exporting.
        """
        self.db_manager = db_manager
        self.title = title
        logger.info("ExportManager initialized.")  # Add log message

    def _adjust_headers(self, content, level_increment=1):
        """
        Adjust the header levels in the Markdown content.
        The goal is to transform the Markdown content to remain semantically
        valid despite the concatenation.

        Args:
            content (str): The Markdown content to adjust.
            level_increment (int): The increment value for adjusting header levels.

        Returns:
            str: The adjusted Markdown content.
        """
        new_content = ""
        for line in content.split("\n"):
            if line.startswith("#"):
                hashes = len(line.split(" ")[0])
                new_hashes = min(hashes + level_increment, 6)  # Limit to ######
                line = "\n" + "#" * new_hashes + line[hashes:] + "\n"
            new_content += line + "\n"
        return new_content

    def _cleanup_markdown(self, content):
        """
        Remove excessive newline characters from Markdown content.

        This method replaces sequences of three or more consecutive newline characters
        with exactly two newline characters, ensuring that there are no unnecessary
        blank lines in the output.

        Args:
            content (str): The Markdown content to be cleaned up.

        Returns:
            str: The cleaned-up Markdown content with reduced newline characters.
        """
        while "\n\n\n" in content:
            content = content.replace("\n\n\n", "\n\n")
        return content

    def _concatenate_markdown(self, pages):
        """
        Concatenate a list of Markdown files into one, with header adjustments.

        Args:
            pages (list): List of pages to concatenate.

        Returns:
            str: The concatenated Markdown content.
        """
        final_content = f"# {self.title}\n"
        for url, content, metadata in pages:
            if content is None:
                continue  # Skip empty pages

            filtered_metadata = {
                k: v for k, v in json.loads(metadata).items() if v is not None
            }

            # Prepare metadata as an HTML comment
            metadata_content = "<!--\n"
            metadata_content += f"URL: {url}\n"
            for key, value in filtered_metadata.items():
                metadata_content += f"{key}: {value}\n"
            metadata_content += "-->"

            # Adjust headers for subsequent files and add metadata
            adjusted_content = self._adjust_headers(content)

            final_content += (
                "\n" + metadata_content + "\n\n" + adjusted_content + "\n---"
            )  # Add a separator and metadata

            final_content = self._cleanup_markdown(final_content)

        return final_content

    def export_to_markdown(self, output_path):
        """
        Export the pages to a markdown file.

        Args:
            output_path (str): The path to the output markdown file.
        """
        pages = self.db_manager.get_all_pages()
        with open(output_path, "w", encoding="utf-8") as md_file:
            md_file.write(self._concatenate_markdown(pages))
        logger.info(f"Exported pages to markdown file: {output_path}")

    def export_to_json(self, output_path):
        """
        Export the pages to a JSON file.

        Args:
            output_path (str): The path to the output JSON file.
        """
        pages = self.db_manager.get_all_pages()
        with open(output_path, "w", encoding="utf-8") as json_file:
            # Filter metadata and strip null values
            data_to_export = []
            for url, content, metadata in pages:
                if content is None:
                    continue  # Skip empty pages

                content = self._cleanup_markdown(content)

                filtered_metadata = {
                    k: v for k, v in json.loads(metadata).items() if v is not None
                }
                data_to_export.append(
                    {"url": url, "content": content, "metadata": filtered_metadata}
                )
            json.dump(data_to_export, json_file, ensure_ascii=False, indent=4)
            # Log the successful export to JSON file
            logger.info(f"Exported pages to JSON file: {output_path}")

    def export_individual_markdown(self, output_folder, base_url=None):
        """
        Export each page individually as Markdown, preserving the URL's structure.

        Args:
            output_folder (str): The base output folder where the files will be saved.
            base_url (str or None): Base URL to remove for creating the path.
        """
        pages = self.db_manager.get_all_pages()
        # Add 'files/' to the output folder and create it if it doesn't exist
        output_folder = os.path.join(output_folder, "files")

        os.makedirs(output_folder, exist_ok=True)
        for page in pages:
            url, content, metadata = page
            logger.debug(f"Exporting individual Markdown for URL: {url}")

            # Remove base_url from parsed URL if provided
            if base_url:
                url = url.replace(base_url, "")

            # Parse the URL to determine the folder and filename
            parsed_url = url.replace("https://", "").replace("http://", "")
            if parsed_url.endswith("/") or parsed_url == "":
                file_path = os.path.join(output_folder, parsed_url, "index.md")
            else:
                file_path = os.path.join(output_folder, parsed_url + ".md")

            # Ensure directories exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Write the Markdown content
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)
                logger.debug(f"Markdown exported to {file_path}")

        return output_folder
