import json
from database_manager import DatabaseManager
import logging  # Add log messages


class ExportManager:
    def __init__(self, db_manager: DatabaseManager, title=None):
        """
        Initialize the ExportManager with a DatabaseManager instance.

        Args:
        db_manager (DatabaseManager): The DatabaseManager instance to be used for exporting.
        """
        self.db_manager = db_manager
        self.title = title
        logging.info("ExportManager initialized.")  # Add log message

    def _adjust_headers(self, content, level_increment=1):
        """
        Adjust the header levels in the Markdown content.
        The goal is to transform the Markdown content to remain semantically valid despite the concatenation.

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
                line = "#" * new_hashes + line[hashes:]
            new_content += line + "\n"
        return new_content

    def _concatenate_markdown(self, pages):
        """
        Concatenate a list of Markdown files into one, with header adjustments.

        Args:
        pages (list): List of pages to concatenate.

        Returns:
        str: The concatenated Markdown content.
        """
        final_content = f"# {self.title}\n\n"
        for url, content, metadata in pages:
            if content is None:
                continue  # Skip empty pages

            filtered_metadata = {
                k: v for k, v in json.loads(metadata).items() if v is not None
            }

            # Prepare metadata as an HTML comment
            metadata_content = f"<!--\n"
            metadata_content += f"URL: {url}\n"
            for key, value in filtered_metadata.items():
                metadata_content += f"{key}: {value}\n"
            metadata_content += "-->"

            # Adjust headers for subsequent files and add metadata
            adjusted_content = self._adjust_headers(content)

            final_content += (
                "\n\n" + metadata_content + "\n\n" + adjusted_content + "\n\n---"
            )  # Add a separator and metadata

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
        logging.info(
            f"Exported pages to markdown file: {output_path}"
        )  # Add log message

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

                filtered_metadata = {
                    k: v for k, v in json.loads(metadata).items() if v is not None
                }
                data_to_export.append(
                    {"url": url, "content": content, "metadata": filtered_metadata}
                )
            json.dump(data_to_export, json_file, ensure_ascii=False, indent=4)
            # Log the successful export to JSON file
            logging.info(f"Exported pages to JSON file: {output_path}")
