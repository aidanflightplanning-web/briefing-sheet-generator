"""Writes the briefing sheet PDF and the flight plan package with the sheet appended."""

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


def package_pdf(flight_plan: str | Path | bytes, briefsheet: str | Path | bytes) -> bytes:
    """Flight plan pages followed by the briefing sheet; a sheet attached earlier is replaced."""
    from pypdf import PdfReader, PdfWriter

    def reader(source):
        return PdfReader(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source))

    writer = PdfWriter()
    for text, page in zip(extract_pages(flight_plan), reader(flight_plan).pages):
        if not BRIEFSHEET_PAGE_RE.search(text):
            writer.add_page(page)
    for page in reader(briefsheet).pages:
        writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


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
                  append: bool = True) -> list[Path]:
    """Render the briefing sheet (and optionally the combined package). Returns the files written."""
    sheet_path, package_path = output_paths(flight_plan, output_dir)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=sheet_path.parent)
    os.close(fd)
    render_briefing(data, tmp)
    _replace(Path(tmp), sheet_path)
    written = [sheet_path]
    if append:
        append_to_flight_plan(Path(flight_plan), sheet_path, package_path)
        written.append(package_path)
    return written
