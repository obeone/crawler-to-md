import logging
import re
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


class ParserManager:
    """
    Manages the conversion of XML documents to Markdown format, supporting <quote> and <code> elements
    and now handling nested elements like lists within lists more accurately, including paragraphs within table cells.
    """

    def __init__(self, xml_string: str) -> None:
        self.xml_string = xml_string

    def parse(self) -> str:
        self.root = ET.fromstring(self.xml_string)
        md = self._parse_element(self.root)

        md = re.sub(r"\n{2,}", "\n\n", md)
        md = self._reformat_markdown(md)

        return md.strip()

    def _parse_element(self, element: ET.Element, level: int = 0) -> str:
        markdown = ""
        if element.tag == "doc":
            markdown = self._parse_doc(element)
        elif element.tag == "main":
            markdown = self._parse_main(element)
        elif element.tag == "code":
            markdown = self._handle_code(element)
        elif element.tag == "quote" or element.tag == "td" or element.tag == "th":
            markdown = self._handle_quote(element)
        elif element.tag in ["head", "p", "list", "item", "ref", "hi", "table", "lb"]:
            markdown = self._element_to_markdown(element, level)
        elif element.tag == "comments":
            markdown = ""  # Ignore comments
        else:
            self._log_unknown_element(element)
            markdown = ""

        tail_text = element.tail or ""
        if tail_text.strip():
            markdown += tail_text

        return markdown

    def _parse_doc(self, element: ET.Element) -> str:
        return "\n".join([self._parse_element(child) for child in element])

    def _parse_main(self, element: ET.Element) -> str:
        return "\n".join([self._parse_element(child) for child in element])

    def _handle_code(self, element: ET.Element) -> str:
        text = "".join(element.itertext())
        if "\n" in text or len(text) > 80:
            return f"```\n{text}\n```\n"
        else:
            return f" `{text}`"

    def _handle_quote(self, element: ET.Element) -> str:
        return f"> {element.text}\n"

    def _process_text(self, text):
        return text.strip() if text and not text.isspace() else ""

    def _element_to_markdown(self, element: ET.Element, level: int) -> str:
        markdown = ""
        if element.tag == "head":
            markdown = self._format_heading(element)
        elif element.tag == "p":
            content_parts = [self._process_text(element.text)]
            content_parts.extend(self._parse_element(child, level) for child in element)
            content = "".join(filter(None, content_parts)).strip()
            markdown = f"{self._process_text(content)}\n\n"
        elif element.tag == "list":
            prefix = "\n" if level > 0 else ""
            markdown_items = [self._parse_element(child, level + 1) for child in element]
            markdown = prefix + "\n".join(markdown_items) + "\n"
        elif element.tag == "item":
            content_parts = [self._process_text(element.text)]
            content_parts.extend(self._parse_element(child, level) for child in element)
            content = "".join(filter(None, content_parts)).strip()
            indent = "  " * (level - 1)
            markdown = f"{indent}- {content}\n"
        elif element.tag == "ref":
            text = self._process_text(element.text)
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
        rend = element.get("rend", "")
        level = int(rend[-1]) if rend and rend[-1].isdigit() else 1
        return "#" * level + f" {self._process_text(element.text)}\n\n"

    def _convert_table_to_markdown(self, table: ET.Element) -> str:
        markdown = ""
        header_row_processed = False
        for row in table:
            row_cells = []
            is_header_row = all(cell.get("role") == "head" for cell in row if cell.tag == "cell")

            for cell in row:
                if cell.tag == "cell":
                    code_elements = cell.findall('.//code')
                    if code_elements:
                        cell_content = " ".join([f"`{self._process_text(' '.join(code.itertext())).strip()}`" for code in code_elements])
                    else:
                        paragraphs = cell.findall('div')
                        if paragraphs:
                            cell_content = " ".join([self._process_text(" ".join(p.itertext())).strip() for p in paragraphs])
                        else:
                            cell_content = self._process_text(" ".join(cell.itertext())).strip().replace("\n", " ")
                    row_cells.append(cell_content)

            if is_header_row and not header_row_processed:
                markdown += "| " + " | ".join(row_cells) + " |\n"
                markdown += "|---" * len(row_cells) + "|\n"
                header_row_processed = True
            else:
                markdown += "| " + " | ".join(row_cells) + " |\n"

        return markdown.strip()
    def _log_unknown_element(self, element: ET.Element) -> None:
        logger.warning(f"Unknown XML element encountered: <{element.tag}>")

    def _split_line(self, line):
        MAX_LENGTH = 80
        parts = re.split(r"(\*\*.*?\*\*|\[.*?\]\(.*?\))", line)
        new_lines = []
        current_line = ""

        for part in parts:
            if not part:
                continue
            if re.match(r"\*\*.*?\*\*|\[.*?\]\(.*?\)", part):
                if len(current_line) + len(part) > MAX_LENGTH:
                    new_lines.append(current_line.rstrip())
                    current_line = part
                else:
                    current_line += part
            else:
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

    def _reformat_markdown(self, md_text):
        lines = md_text.split("\n")
        new_md_text = []
        previous_line_was_list = False
        inside_table = False

        for line in lines:
            if line.strip().startswith("|"):
                inside_table = True
            elif line.strip() == "":
                inside_table = False

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
