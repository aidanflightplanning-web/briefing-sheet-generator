"""Plain-text extraction from flight plan PDFs."""

from __future__ import annotations

import io
from pathlib import Path


def extract_pages(source: str | Path | bytes) -> list[str]:
    """Return the text of every page, one string per page.

    `source` is a file path or the PDF's bytes (e.g. an upload in the web app).
    pypdfium2 is used because it is ~50x faster than pdfplumber on a full
    brief; pdfplumber is only a fallback. The two engines agree on everything
    the briefing sheet needs (flight plan, weather and SIGMET pages); they only
    order the columns of the NOTAM tables differently.
    """
    in_memory = isinstance(source, (bytes, bytearray))
    try:
        import pypdfium2 as pdfium
    except ImportError:  # pragma: no cover - fallback engine
        pdfium = None

    if pdfium is not None:
        pdf = pdfium.PdfDocument(bytes(source) if in_memory else str(source))
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

    import pdfplumber  # pragma: no cover

    with pdfplumber.open(io.BytesIO(source) if in_memory else str(source)) as pdf:  # pragma: no cover
        return [(page.extract_text() or "") for page in pdf.pages]
