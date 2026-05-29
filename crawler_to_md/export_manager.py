import json
import logging
import os

from . import rag
from .database_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Actionable error shown when the Parquet/vector export is requested without
# the optional ``vector`` extra installed.
VECTOR_MISSING_MESSAGE = (
    "Vector/Parquet export requires the optional 'vector' extra. "
    "Install it with: pip install crawler-to-md[vector]"
)


def _yaml_escape(value):
    """
    Render ``value`` as a safe single-line YAML scalar.

    Strings are double-quoted with backslashes and quotes escaped so that
    titles or URLs containing special characters cannot break the frontmatter
    block. Non-string values are emitted via ``str`` (used for integers).

    Args:
        value: The value to serialise.

    Returns:
        str: A YAML-safe scalar representation of ``value``.
    """
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return str(value)


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

        # Run cleanup once after the loop instead of on every iteration to avoid
        # O(n^2) reprocessing of the accumulated content.
        return self._cleanup_markdown(final_content)

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

    def _build_frontmatter(self, url, content, metadata_dict, fetched_at):
        """
        Build a YAML frontmatter block for a single page.

        The block always carries ``url``, ``title``, ``fetched_at`` and
        ``word_count``. ``token_count`` is included only when the optional
        ``rag`` extra (tiktoken) is installed, so a bare installation simply
        omits that key rather than failing.

        Args:
            url (str): The page URL.
            content (str): The page Markdown content.
            metadata_dict (dict): Parsed page metadata (may contain ``title``).
            fetched_at (str or None): ISO timestamp of the last fetch, if known.

        Returns:
            str: A YAML frontmatter block terminated by a trailing newline.
        """
        title = metadata_dict.get("title") or url
        word_count = len((content or "").split())

        lines = ["---"]
        lines.append(f"url: {_yaml_escape(url)}")
        lines.append(f"title: {_yaml_escape(title)}")
        if fetched_at:
            lines.append(f"fetched_at: {_yaml_escape(fetched_at)}")
        lines.append(f"word_count: {word_count}")

        try:
            token_count = rag.count_tokens(content)
        except ImportError:
            token_count = None
        if token_count is not None:
            lines.append(f"token_count: {token_count}")

        lines.append("---")
        return "\n".join(lines) + "\n\n"

    def export_individual_markdown(self, output_folder, base_url=None,
                                   frontmatter=True):
        """
        Export each page individually as Markdown, preserving the URL's structure.

        Args:
            output_folder (str): The base output folder where the files will be saved.
            base_url (str or None): Base URL to remove for creating the path.
            frontmatter (bool): When ``True`` (the default), prepend a per-page
                YAML frontmatter block (url, title, fetched_at, word_count and,
                if the ``rag`` extra is installed, token_count). When ``False``,
                the previous behaviour (raw content only) is preserved.

        Returns:
            str: The folder the individual files were written to.
        """
        pages = self.db_manager.get_all_pages_full()
        # Add 'files/' to the output folder and create it if it doesn't exist
        output_folder = os.path.join(output_folder, "files")

        os.makedirs(output_folder, exist_ok=True)
        for url, content, metadata, _content_hash, fetched_at in pages:
            logger.debug(f"Exporting individual Markdown for URL: {url}")

            metadata_dict = json.loads(metadata) if metadata else {}

            # Remove base_url from parsed URL if provided
            display_url = url
            if base_url:
                display_url = display_url.replace(base_url, "")

            # Parse the URL to determine the folder and filename
            parsed_url = display_url.replace("https://", "").replace("http://", "")
            if parsed_url.endswith("/") or parsed_url == "":
                file_path = os.path.join(output_folder, parsed_url, "index.md")
            else:
                file_path = os.path.join(output_folder, parsed_url + ".md")

            # Ensure directories exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            body = content or ""
            if frontmatter:
                body = self._build_frontmatter(
                    url, content, metadata_dict, fetched_at
                ) + body

            # Write the Markdown content
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(body)
                logger.debug(f"Markdown exported to {file_path}")

        return output_folder

    def export_to_jsonl(self, output_path):
        """
        Export the pages as JSON Lines (one record per line).

        Each non-empty page is emitted as a single-line JSON object with
        ``url``, ``content`` (cleaned) and ``metadata`` (null values stripped),
        matching the structure of :meth:`export_to_json` but in a
        streaming-friendly, AI-ingestion-ready format.

        Args:
            output_path (str): Destination path for the ``.jsonl`` file.
        """
        pages = self.db_manager.get_all_pages()
        with open(output_path, "w", encoding="utf-8") as jsonl_file:
            for url, content, metadata in pages:
                if content is None:
                    continue  # Skip empty pages

                cleaned = self._cleanup_markdown(content)
                filtered_metadata = {
                    k: v for k, v in json.loads(metadata).items() if v is not None
                }
                record = {
                    "url": url,
                    "content": cleaned,
                    "metadata": filtered_metadata,
                }
                jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"Exported pages to JSONL file: {output_path}")

    def export_to_llms(self, output_folder):
        """
        Export ``llms.txt`` and ``llms-full.txt`` for LLM consumption.

        Follows the emerging `llms.txt convention <https://llmstxt.org/>`_:

        * ``llms.txt`` — an H1 title, an optional blockquote summary and a
          ``## Pages`` section listing every page as a Markdown link.
        * ``llms-full.txt`` — the H1 title followed by the full content of every
          page, separated by horizontal rules.

        Args:
            output_folder (str): Folder the two files are written to.

        Returns:
            tuple[str, str]: The ``(llms.txt, llms-full.txt)`` paths written.
        """
        pages = self.db_manager.get_all_pages()
        title = self.title or "Site"

        index_path = os.path.join(output_folder, "llms.txt")
        full_path = os.path.join(output_folder, "llms-full.txt")

        index_lines = [f"# {title}", ""]
        index_lines.append(f"> Index of {len(pages)} crawled pages.")
        index_lines.append("")
        index_lines.append("## Pages")
        index_lines.append("")

        full_lines = [f"# {title}", ""]

        for url, content, metadata in pages:
            if content is None:
                continue  # Skip empty pages

            metadata_dict = json.loads(metadata) if metadata else {}
            page_title = metadata_dict.get("title") or url
            index_lines.append(f"- [{page_title}]({url})")

            full_lines.append(f"## {page_title}")
            full_lines.append(f"<{url}>")
            full_lines.append("")
            full_lines.append(self._cleanup_markdown(content))
            full_lines.append("")
            full_lines.append("---")
            full_lines.append("")

        with open(index_path, "w", encoding="utf-8") as index_file:
            index_file.write("\n".join(index_lines) + "\n")
        with open(full_path, "w", encoding="utf-8") as full_file:
            full_file.write("\n".join(full_lines) + "\n")

        logger.info(f"Exported llms.txt index to {index_path}")
        logger.info(f"Exported llms-full.txt content to {full_path}")
        return index_path, full_path

    def export_chunks_jsonl(self, output_path, chunk_size, chunk_overlap=0):
        """
        Export token-aware RAG chunks as JSON Lines.

        Each page's content is split into overlapping, token-bounded chunks via
        :func:`crawler_to_md.rag.chunk_text` and emitted one record per line as
        ``{url, chunk_index, content, token_count}``.

        Args:
            output_path (str): Destination path for the ``chunks.jsonl`` file.
            chunk_size (int): Maximum tokens per chunk (must be ``> 0``).
            chunk_overlap (int): Tokens shared between consecutive chunks.

        Returns:
            int: The total number of chunk records written.

        Raises:
            ValueError: If ``chunk_size`` is not a positive integer.
            ImportError: If the ``rag`` extra (tiktoken) is not installed.
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size must be a positive integer to chunk")

        encoder = rag.get_encoder()
        pages = self.db_manager.get_all_pages()
        total = 0
        with open(output_path, "w", encoding="utf-8") as chunk_file:
            for url, content, _metadata in pages:
                if content is None:
                    continue  # Skip empty pages

                cleaned = self._cleanup_markdown(content)
                chunks = rag.chunk_text(
                    cleaned, chunk_size, chunk_overlap, encoder=encoder
                )
                for index, (chunk_content, token_count) in enumerate(chunks):
                    record = {
                        "url": url,
                        "chunk_index": index,
                        "content": chunk_content,
                        "token_count": token_count,
                    }
                    chunk_file.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )
                    total += 1
        logger.info(
            f"Exported {total} RAG chunks to JSONL file: {output_path}"
        )
        return total

    def export_to_vectors(self, output_path, chunk_size=0, chunk_overlap=0):
        """
        Export pages (optionally chunked) to a Parquet file via pyarrow.

        Parquet is the portable deliverable; pushing the rows into a managed
        vector store is left as a documented follow-up. When ``chunk_size`` is
        greater than zero, rows are chunk-level
        ``(url, chunk_index, content, token_count)``; otherwise they are
        page-level ``(url, content, metadata, token_count)`` where
        ``token_count`` uses tiktoken if available and a labelled estimate
        otherwise.

        Args:
            output_path (str): Destination path for the ``.parquet`` file.
            chunk_size (int): When ``> 0``, emit token-aware chunk rows
                (requires the ``rag`` extra). Defaults to ``0`` (page rows).
            chunk_overlap (int): Tokens shared between consecutive chunks when
                chunking is enabled.

        Returns:
            int: The number of rows written.

        Raises:
            ImportError: If the ``vector`` extra (pyarrow) is not installed, or
                the ``rag`` extra is missing while ``chunk_size > 0``.
        """
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise ImportError(VECTOR_MISSING_MESSAGE) from exc

        pages = self.db_manager.get_all_pages()

        if chunk_size > 0:
            encoder = rag.get_encoder()
            urls, indices, contents, token_counts = [], [], [], []
            for url, content, _metadata in pages:
                if content is None:
                    continue
                cleaned = self._cleanup_markdown(content)
                chunks = rag.chunk_text(
                    cleaned, chunk_size, chunk_overlap, encoder=encoder
                )
                for index, (chunk_content, token_count) in enumerate(chunks):
                    urls.append(url)
                    indices.append(index)
                    contents.append(chunk_content)
                    token_counts.append(token_count)
            table = pa.table(
                {
                    "url": urls,
                    "chunk_index": indices,
                    "content": contents,
                    "token_count": token_counts,
                }
            )
        else:
            urls, contents, metadatas, token_counts = [], [], [], []
            for url, content, metadata in pages:
                if content is None:
                    continue
                cleaned = self._cleanup_markdown(content)
                token_count, _method = rag.estimate_tokens(cleaned)
                urls.append(url)
                contents.append(cleaned)
                metadatas.append(metadata or "{}")
                token_counts.append(token_count)
            table = pa.table(
                {
                    "url": urls,
                    "content": contents,
                    "metadata": metadatas,
                    "token_count": token_counts,
                }
            )

        pq.write_table(table, output_path)
        logger.info(
            f"Exported {table.num_rows} rows to Parquet file: {output_path}"
        )
        return table.num_rows

    def compute_token_totals(self):
        """
        Compute total token usage across the whole crawled corpus.

        Uses tiktoken for an exact count when the ``rag`` extra is installed,
        otherwise a clearly labelled word-based estimate so the figure is still
        meaningful on a bare installation.

        Returns:
            tuple[int, str, int]: ``(total_tokens, method, page_count)`` where
            ``method`` is ``"tiktoken"`` or ``"word-estimate"`` and
            ``page_count`` counts the non-empty pages measured.
        """
        pages = self.db_manager.get_all_pages()
        total_tokens = 0
        method = "tiktoken"
        page_count = 0
        for _url, content, _metadata in pages:
            if content is None:
                continue
            tokens, method = rag.estimate_tokens(content)
            total_tokens += tokens
            page_count += 1
        return total_tokens, method, page_count
