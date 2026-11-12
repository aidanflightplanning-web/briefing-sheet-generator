"""Writes the briefing sheet PDF and the flight plan package with the sheet appended.

Attachments (the MEL book pages of the open items, wind charts) follow the briefing
sheet in both files. Every page added here is tagged, so when a package is opened
again only the flight plan pages are kept and the sheet and attachments are replaced.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from pathlib import Path

from .builder import BriefingData
from .flightplan import BRIEFSHEET_PAGE_RE
from .pdftext import extract_pages
from .render import render_briefing

SUFFIXES = ("_WITH_BRIEFSHEET", "_BRIEFSHEET")
ADDED_PAGE_KEY = "/BriefingSheetGenerator"   # marks pages this program added


class OutputError(OSError):
    pass


def output_names(flight_plan_name: str) -> tuple[str, str]:
    """File names of (briefing sheet, flight plan + briefing sheet) for a flight plan file name."""
    stem = Path(flight_plan_name).stem
    for suffix in SUFFIXES:
        stem = re.sub(re.escape(suffix) + r"$", "", stem, flags=re.I)
    return f"{stem}_BRIEFSHEET.pdf", f"{stem}_WITH_BRIEFSHEET.pdf"


def output_paths(flight_plan: str | Path, output_dir: str | Path | None = None) -> tuple[Path, Path]:
    """(briefing sheet, flight plan + briefing sheet) paths for a flight plan PDF."""
    flight_plan = Path(flight_plan)
    folder = Path(output_dir) if output_dir else flight_plan.parent
    sheet, package = output_names(flight_plan.name)
    return folder / sheet, folder / package


def _reader(source):
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source))


def _write(writer) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def combine(briefsheet: bytes, attachments=()) -> bytes:
    """The briefing sheet followed by the attachments (PDF bytes; empty ones are skipped)."""
    from pypdf import PdfWriter
    from pypdf.generic import BooleanObject, NameObject

    writer = PdfWriter()
    for source in (briefsheet, *attachments):
        if not source:
            continue
        for page in _reader(source).pages:
            writer.add_page(page)[NameObject(ADDED_PAGE_KEY)] = BooleanObject(True)
    return _write(writer)


def package_pdf(flight_plan: str | Path | bytes, briefsheet: str | Path | bytes) -> bytes:
    """Flight plan pages followed by the briefing sheet (and its attachments); a sheet and
    attachments added earlier are replaced."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for text, page in zip(extract_pages(flight_plan), _reader(flight_plan).pages):
        if not BRIEFSHEET_PAGE_RE.search(text) and ADDED_PAGE_KEY not in page:
            writer.add_page(page)
    for page in _reader(briefsheet).pages:
        writer.add_page(page)
    return _write(writer)


def _replace(tmp: Path, target: Path) -> None:
    try:
        os.replace(tmp, target)
    except PermissionError as exc:
        tmp.unlink(missing_ok=True)
        raise OutputError(f"{target.name} is open in another program. Close it and try again.") from exc


def append_to_flight_plan(flight_plan: Path, briefsheet: Path, target: Path) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=target.parent)
    with os.fdopen(fd, "wb") as fh:
        fh.write(package_pdf(flight_plan, briefsheet))
    _replace(Path(tmp), target)


def write_outputs(flight_plan: str | Path, data: BriefingData, output_dir: str | Path | None = None,
                  append: bool = True, attachments=()) -> list[Path]:
    """Render the briefing sheet with its attachments (and optionally the combined package).
    Returns the files written."""
    sheet_path, package_path = output_paths(flight_plan, output_dir)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    render_briefing(data, buffer)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=sheet_path.parent)
    with os.fdopen(fd, "wb") as fh:
        fh.write(combine(buffer.getvalue(), attachments))
    _replace(Path(tmp), sheet_path)
    written = [sheet_path]
    if append:
        append_to_flight_plan(Path(flight_plan), sheet_path, package_path)
        written.append(package_path)
    return written
