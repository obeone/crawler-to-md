import logging
import re
from xml.etree import ElementTree as ET

# Initialize logger for this module.
logger = logging.getLogger(__name__)

class ParserManager:
    """
    Manages the conversion of XML documents to Markdown format.

    This class supports specific XML elements like <quote> and <code>, and it can handle
    nested elements such as lists within lists and paragraphs within table cells, converting
    them accurately to Markdown format.
    """

    def __init__(self, xml_string: str) -> None:
        """
        Initializes the ParserManager with an XML string.

        Args:
            xml_string (str): The XML document as a string.
        """
        self.xml_string = xml_string

    def parse(self) -> str:
        """
        Converts the XML string to Markdown format.

        Parses the XML document using ElementTree, converts it to Markdown by traversing
        the XML tree, and reformats the resulting Markdown to remove excessive newlines.

        Returns:
            The converted Markdown string.
        """
        # Parse the XML string into an ElementTree object.
        self.root = ET.fromstring(self.xml_string)
        # Convert the root element to Markdown.
        md = self._parse_element(self.root)

        # Reformat the Markdown to remove excessive newlines.
        md = re.sub(r"\n{2,}", "\n\n", md)
        md = self._reformat_markdown(md)

        return md.strip()

    def _parse_element(self, element: ET.Element, level: int = 0) -> str:
        """
        Recursively converts an XML element and its children to Markdown.

        Depending on the tag of the element, different conversion functions are called.
        Text from the element's tail is also appended to the Markdown result.

        Args:
            element (ET.Element): The XML element to convert.
            level (int): The current nesting level, used for formatting.

        Returns:
            The Markdown representation of the element.
        """
        # Initialize the Markdown result for this element.
        markdown = ""
        # Convert the element based on its tag.
        if element.tag == "doc":
            markdown = self._parse_doc(element)
        elif element.tag == "main":
            markdown = self._parse_main(element)
        elif element.tag == "code":
            markdown = self._handle_code(element)
        elif element.tag in ["quote", "td", "th"]:
            markdown = self._handle_quote(element)
        elif element.tag in ["head", "p", "list", "item", "ref", "hi", "table", "lb"]:
            markdown = self._element_to_markdown(element, level)
        elif element.tag == "comments":
            markdown = ""  # Comments are ignored.
        else:
            # Log and ignore unknown elements.
            self._log_unknown_element(element)
            markdown = ""

        # Append text from the element's tail, if present.
        tail_text = element.tail or ""
        if tail_text.strip():
            markdown += tail_text

        return markdown

    def _parse_doc(self, element: ET.Element) -> str:
        """
        Converts a <doc> element and its children to Markdown.

        Iterates over child elements, converting each to Markdown and joining the results.

        Args:
            element (ET.Element): The <doc> element to convert.

        Returns:
            The Markdown representation of the <doc> element.
        """
        # Convert child elements to Markdown and join the results.
        return "\n".join([self._parse_element(child) for child in element])

    def _parse_main(self, element: ET.Element) -> str:
        """
        Converts a <main> element and its children to Markdown.

        Similar to _parse_doc, but specifically for <main> elements.

        Args:
            element (ET.Element): The <main> element to convert.

        Returns:
            The Markdown representation of the <main> element.
        """
        # Convert child elements to Markdown and join the results.
        return "\n".join([self._parse_element(child) for child in element])

    def _handle_code(self, element: ET.Element) -> str:
        """
        Converts a <code> element to Markdown.

        Formats the text as a code block or inline code based on its content.

        Args:
            element (ET.Element): The <code> element to convert.

        Returns:
            The Markdown representation of the <code> element.
        """
        # Extract text from the <code> element.
        text = "".join(element.itertext())
        # Format as a code block or inline code based on content.
        if "\n" in text or len(text) > 80:
            return f"```{text}```\n"
        else:
            return f"`{text}`"

    def _handle_quote(self, element: ET.Element) -> str:
        """
        Converts a <quote>, <td>, or <th> element to Markdown.

        Formats the text as a blockquote or table cell content.

        Args:
            element (ET.Element): The element to convert.

        Returns:
            The Markdown representation of the element.
        """
        # Format the element's text as a blockquote.
        return f"> {element.text}\n"

    def _process_text(self, text: str) -> str:
        """
        Processes and cleans up text for Markdown formatting.

        Strips whitespace and ensures the text is not just whitespace.

        Args:
            text (str): The text to process.

        Returns:
            The processed text.
        """
        # Strip whitespace and return the text if it's not just whitespace.
        return text.strip() if text and not text.isspace() else ""

    def _element_to_markdown(self, element: ET.Element, level: int) -> str:
        """
        Converts various XML elements to their Markdown representations.

        Handles elements like <head>, <p>, <list>, etc., formatting them based on their type and nesting level.

        Args:
            element (ET.Element): The element to convert.
            level (int): The current nesting level for formatting.

        Returns:
            The Markdown representation of the element.
        """
        # Initialize the Markdown result for this element.
        markdown = ""
        # Convert the element based on its tag and nesting level.
        if element.tag == "head":
            markdown = self._format_heading(element)
        elif element.tag == "p":
            content_parts = [self._process_text(element.text or "")]
            content_parts.extend(self._parse_element(child, level) for child in element)
            content = "".join(filter(None, content_parts)).strip()
            markdown = f"{self._process_text(content)}\n\n"
        elif element.tag == "list":
            prefix = "\n" if level > 0 else ""
            markdown_items = [self._parse_element(child, level + 1) for child in element]
            markdown = prefix + "\n".join(markdown_items) + "\n"
        elif element.tag == "item":
            content_parts = [self._process_text(element.text or "")]
            content_parts.extend(self._parse_element(child, level) for child in element)
            content = "".join(filter(None, content_parts)).strip()
            indent = "  " * (level - 1)
            markdown = f"{indent}- {content}\n"
        elif element.tag == "ref":
            text = self._process_text(element.text or "")
            markdown = f"[{text}]({element.get('target', '')})"
            if markdown and not markdown.startswith(" "):
                markdown = " " + markdown
        elif element.tag == "hi":
            markdown = f"**{''.join(element.itertext())}**"
        elif element.tag == "lb":
            markdown = "\n"
        elif element.tag == "table":
            markdown = self._convert_table_to_markdown(element)
        return markdown

    def _format_heading(self, element: ET.Element) -> str:
        """
        Formats a heading element (<head>) to Markdown.

        Determines the heading level from the element's attributes and formats accordingly.

        Args:
            element (ET.Element): The heading element to format.

        Returns:
            The Markdown representation of the heading.
        """
        # Determine the heading level from the element's attributes.
        rend = element.get("rend", "")
        level = int(rend[-1]) if rend and rend[-1].isdigit() else 1
        # Format the heading with the appropriate number of '#' characters.
        return "#" * level + f" {self._process_text(element.text or "")}\n\n"

    def _convert_table_to_markdown(self, table: ET.Element) -> str:
        """
        Converts a <table> element and its children to Markdown table format.

        Processes each row and cell, formatting headers and content appropriately.

        Args:
            table (ET.Element): The <table> element to convert.

        Returns:
            The Markdown representation of the table.
        """
        # Initialize variables for processing the table.
        markdown = ""
        header_row_processed = False
        # Process each row in the table.
        for row in table:
            row_cells = []
            # Determine if the current row is a header row.
            is_header_row = all(cell.get("role") == "head" for cell in row if cell.tag == "cell")
            # Process each cell in the row.
            for cell in row:
                if cell.tag == "cell":
                    # Handle <code> elements within cells.
                    code_elements = cell.findall('.//code')
                    if code_elements:
                        cell_content = " ".join([f"`{self._process_text(' '.join(code.itertext())).strip()}`" for code in code_elements])
                    else:
                        # Handle paragraphs within cells.
                        paragraphs = cell.findall('div')
                        if paragraphs:
                            cell_content = " ".join([self._process_text(" ".join(p.itertext())).strip() for p in paragraphs])
                        else:
                            # Process cell text directly.
                            cell_content = self._process_text(" ".join(cell.itertext())).strip().replace("\n", " ")
                    row_cells.append(cell_content)
            # Format the row as Markdown, adding header syntax if necessary.
            if is_header_row and not header_row_processed:
                markdown += "| " + " | ".join(row_cells) + " |\n"
                markdown += "|---" * len(row_cells) + "|\n"
                header_row_processed = True
            else:
                markdown += "| " + " | ".join(row_cells) + " |\n"
        return markdown.strip()

    def _log_unknown_element(self, element: ET.Element) -> None:
        """
        Logs a warning for unknown XML elements encountered during parsing.

        Args:
            element (ET.Element): The unknown element.
        """
        # Log a warning with the tag of the unknown element.
        logger.warning(f"Unknown XML element encountered: <{element.tag}>")

    def _split_line(self, line: str) -> list:
        """
        Splits a line into multiple lines to adhere to a maximum line length.

        This function is used for reformatting Markdown text to ensure lines do not exceed
        a certain length, taking into account Markdown formatting characters.

        Args:
            line (str): The line to split.

        Returns:
            A list of split lines.
        """
        # Define the maximum line length.
        MAX_LENGTH = 80
        # Split the line based on Markdown formatting characters.
        parts = re.split(r"(\*\*.*?\*\*|\[.*?\]\(.*?\))", line)
        new_lines = []
        current_line = ""
        # Process each part, splitting into new lines as necessary.
        for part in parts:
            if not part:
                continue
            # Handle formatted parts directly.
            if re.match(r"\*\*.*?\*\*|\[.*?\]\(.*?\)", part):
                if len(current_line) + len(part) > MAX_LENGTH:
                    new_lines.append(current_line.rstrip())
                    current_line = part
                else:
                    current_line += part
            else:
                # Split unformatted parts by space and process each word.
                words = part.split(" ")
                for word in words:
                    if len(current_line) + len(word) + 1 > MAX_LENGTH:
                        new_lines.append(current_line.rstrip())
                        current_line = word
                    else:
                        if current_line:
                            current_line += " " + word
                        else:
                            current_line = word
        if current_line:
            new_lines.append(current_line.rstrip())
        return new_lines

    def _reformat_markdown(self, md_text: str) -> str:
        """
        Reformats Markdown text to improve readability and adhere to line length limits.

        Processes each line of the Markdown text, splitting long lines and adding
        additional line breaks as necessary for list items and table formatting.

        Args:
            md_text (str): The Markdown text to reformat.

        Returns:
            The reformatted Markdown text.
        """
        # Split the Markdown text into lines for processing.
        lines = md_text.split("\n")
        new_md_text = []
        previous_line_was_list = False
        inside_table = False
        # Process each line, reformatting as necessary.
        for line in lines:
            if line.strip().startswith("|"):
                inside_table = True
            elif line.strip() == "":
                inside_table = False
            # Split long lines outside of tables.
            if len(line) > 80 and not inside_table:
                reformatted_lines = self._split_line(line)
                for reformatted_line in reformatted_lines:
                    if reformatted_line.strip().startswith("-") and previous_line_was_list:
                        new_md_text.append("")
                    new_md_text.append(reformatted_line)
                    previous_line_was_list = reformatted_line.strip().startswith("-")
            else:
                if line.strip().startswith("-") and previous_line_was_list:
                    new_md_text.append("")
                new_md_text.append(line.rstrip())
                previous_line_was_list = line.strip().startswith("-")
        return "\n".join(new_md_text)
