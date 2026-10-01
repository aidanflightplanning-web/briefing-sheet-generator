"""Text extraction from flight plan PDFs."""

from __future__ import annotations

import ctypes
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StyledLine:
    """A line of text with the font size and left edge of its first character.

    The NOTAM pages rely on these: airport names and category headings are set
    in a larger font than the NOTAM text, and the columns have fixed positions.
    `size` is 0 when the engine cannot report it (pdfplumber fallback).
    """

    text: str
    size: float = 0.0
    x: float = 0.0


def _open(source: str | Path | bytes):
    import pypdfium2 as pdfium

    return pdfium.PdfDocument(bytes(source) if isinstance(source, (bytes, bytearray)) else str(source))


def extract_pages(source: str | Path | bytes) -> list[str]:
    """Return the text of every page, one string per page.

    `source` is a file path or the PDF's bytes (e.g. an upload in the web app).
    pypdfium2 is used because it is ~50x faster than pdfplumber on a full
    brief; pdfplumber is only a fallback.
    """
    try:
        pdf = _open(source)
    except ImportError:  # pragma: no cover - fallback engine
        import pdfplumber

        in_memory = isinstance(source, (bytes, bytearray))
        with pdfplumber.open(io.BytesIO(source) if in_memory else str(source)) as plumber:
            return [(page.extract_text() or "") for page in plumber.pages]
    try:
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            # pdfium reports a hyphen that ends a line as U+FFFE and joins the two lines
            # (e.g. "... VALID 240205/240605 KKCI-" + next line); restore both.
            pages.append(textpage.get_text_range().replace("￾", "-\r\n"))
            textpage.close()
            page.close()
        return pages
    finally:
        pdf.close()


def extract_styled_pages(source: str | Path | bytes) -> list[list[StyledLine]]:
    """Return every page as lines of text with font size and position."""
    try:
        import pypdfium2.raw as pdfium_c

        pdf = _open(source)
    except ImportError:  # pragma: no cover - fallback engine, no style information
        return [[StyledLine(line) for line in text.splitlines()] for text in extract_pages(source)]

    left, right, bottom, top = (ctypes.c_double() for _ in range(4))
    try:
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            lines: list[StyledLine] = []
            chars: list[str] = []
            size = x = None

            def flush():
                nonlocal chars, size, x
                if chars:
                    lines.append(StyledLine("".join(chars), size or 0.0, x or 0.0))
                chars, size, x = [], None, None

            for index in range(textpage.count_chars()):
                code = pdfium_c.FPDFText_GetUnicode(textpage, index)
                char = chr(code)
                if char in "\r\n":
                    flush()
                elif code in (0x02, 0xFFFE):  # hyphen at the end of a line: the line break was swallowed
                    chars.append("-")
                    flush()
                else:
                    if size is None and not char.isspace():
                        size = round(pdfium_c.FPDFText_GetFontSize(textpage, index), 1)
                        pdfium_c.FPDFText_GetCharBox(textpage, index, left, right, bottom, top)
                        x = round(left.value, 1)
                    chars.append(char)
            flush()
            pages.append(lines)
            textpage.close()
            page.close()
        return pages
    finally:
        pdf.close()
