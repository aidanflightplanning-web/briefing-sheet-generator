"""Draws the Flight Crew Briefing Sheet (form SOC001) with ReportLab.

Every coordinate is in points measured from the TOP of a Letter page and was
taken from the Word template (Briefsheet.pdf), so the output lines up with the
original form: same fonts and sizes, 0.48 pt borders, grey label column,
11.52 pt line pitch, logo, "Wheels UP!" watermark and SOC001 footer.

Row heights follow the template: a row is as tall as its label, its value
text or the template's minimum for that row, whichever is largest. Labels are
top-aligned (justified like the Word form); values are centred vertically.
Rows that do not fit move to the next page, as in the multi-page examples.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .builder import NIL_MEL, BriefingData

PAGE_W, PAGE_H = letter

# Table geometry (x positions and border thickness)
BORDER = 0.48
X_OUT_L, X_LABEL, X_DIV, X_VALUE, X_RIGHT, X_OUT_R = 72.02, 72.50, 163.49, 163.97, 572.52, 573.00
LABEL_X, LABEL_END = 77.66, 158.30
VALUE_X, VALUE_END = 169.13, 567.36
GRAY = 0.851

# Text metrics (Word renders 10 pt Arial as 9.96 pt on an 11.52 pt line). Word
# positions glyphs with pixel-rounded widths, on average 0.13 pt tighter per
# character than the font's own metrics; the same spacing is applied here.
SIZE = 9.96
CHAR_SPACE = -0.13
LINE = 11.52
BASELINE = 9.36            # first baseline below the top of a cell
HANGING_INDENT = 36.0      # MEL continuation lines, bulleted text
BULLET_INDENT = 18.0

# Vertical layout
FIRST_TABLE_TOP = 95.30    # top border of the logo row on page 1
NEXT_TABLE_TOP = 72.00     # table continues here on later pages
BOTTOM = 708.0             # rows must end above the footer rule
DISPATCHER_GAP = 25.92     # table bottom -> dispatcher baseline
DISPATCHER_NEW_PAGE_BASELINE = 82.46

SEPARATOR = "       /       "   # between legs in PAX LOAD, FUEL and ALT FILED
FOOTER = "FORM NBR SOC001  Revision 1 \u2013 7 Jan 2021"


@dataclass(frozen=True)
class Fonts:
    regular: str
    bold: str
    signature: str


_FONT_FILES = {
    "Briefsheet-Arial": (("arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "Arimo-Regular.ttf"), "Helvetica"),
    "Briefsheet-Arial-Bold": (("arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "Arimo-Bold.ttf"),
                              "Helvetica-Bold"),
    "Briefsheet-Calibri-Bold": (("calibrib.ttf", "Carlito-Bold.ttf"), "Helvetica-Bold"),
}
_fonts: Fonts | None = None


def _font_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    if os.environ.get("LOCALAPPDATA"):
        dirs.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts")
    return dirs + [Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]


def _font_trees() -> list[Path]:
    """Linux font folders, searched recursively (e.g. Streamlit Community Cloud)."""
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
            Path.home() / ".local" / "share" / "fonts"]


def _font_candidates(files: tuple[str, ...]):
    """Font files in order of preference: Arial/Calibri first, then their metric clones."""
    for file in files:
        for folder in _font_dirs():
            if (folder / file).is_file():
                yield folder / file
        for tree in _font_trees():
            if tree.is_dir():
                for dirpath, _, names in os.walk(tree):
                    if file in names:
                        yield Path(dirpath) / file


def get_fonts() -> Fonts:
    """Register Arial / Arial Bold / Calibri Bold, or their metric-compatible clones
    (Liberation Sans, Carlito); Helvetica if none are installed."""
    global _fonts
    if _fonts is None:
        chosen = {}
        for name, (files, fallback) in _FONT_FILES.items():
            chosen[name] = fallback
            for path in _font_candidates(files):
                try:
                    pdfmetrics.registerFont(TTFont(name, str(path)))
                except Exception:
                    continue
                chosen[name] = name
                break
        _fonts = Fonts(chosen["Briefsheet-Arial"], chosen["Briefsheet-Arial-Bold"], chosen["Briefsheet-Calibri-Bold"])
    return _fonts


def asset(name: str) -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return Path(getattr(sys, "_MEIPASS", "")) / "briefsheet" / "assets" / name
    return Path(__file__).with_name("assets") / name


# --- value text layout -------------------------------------------------------

@dataclass
class Para:
    text: str
    first: float = 0.0       # indent of the first line
    rest: float = 0.0        # indent of wrapped lines
    bullet: bool = False


@dataclass
class Line:
    x: float
    text: str
    bullet: bool = False


def _char_space(font: str, size: float) -> float:
    return CHAR_SPACE * size / SIZE if font == get_fonts().regular else 0.0


def _width(text: str, font: str, size: float = SIZE) -> float:
    return pdfmetrics.stringWidth(text, font, size) + _char_space(font, size) * len(text)


def _wrap(text: str, first: float, rest: float, font: str) -> list[tuple[float, str]]:
    width = VALUE_END - VALUE_X
    lines: list[tuple[float, str]] = []
    current, indent = "", first
    for token in re.findall(r"\S+|\s+", text):
        if token.isspace():
            current += token
            continue
        if current.strip() and _width(current + token, font) > width - indent:
            lines.append((indent, current.rstrip()))
            current, indent = token, rest
        else:
            current += token
        while len(current) > 1 and _width(current, font) > width - indent:  # one over-long word
            cut = len(current) - 1
            while cut > 1 and _width(current[:cut], font) > width - indent:
                cut -= 1
            lines.append((indent, current[:cut]))
            current, indent = current[cut:], rest
    lines.append((indent, current.rstrip()))
    return lines


def _plain(text: str, font: str) -> list[Para]:
    return [Para(line.strip()) for line in (text or "").strip("\n").split("\n")]


def _separated(text: str, font: str) -> list[Para]:
    parts = [p.strip() for p in re.split(r"\s+/\s+", (text or "").strip())]
    return [Para(SEPARATOR.join(parts))]


def _mel(text: str, font: str) -> list[Para]:
    paras = []
    for line in (text or "").strip("\n").split("\n"):
        line = line.strip()
        paras.append(Para(line, 0.0, 0.0 if line.upper() == NIL_MEL else HANGING_INDENT))
    return paras


def _preformatted(text: str, font: str) -> list[Para]:
    """TAFs and SIGMETs: leading spaces are kept as indentation."""
    paras = []
    for line in (text or "").strip("\n").split("\n"):
        body = line.lstrip(" ")
        indent = _width(line[:len(line) - len(body)], font)
        paras.append(Para(body.rstrip(), indent, indent + _width("  ", font)))
    return paras


def _bullets(text: str, font: str) -> list[Para]:
    """Point form for several items, or for a single item written with a bullet ("\u2022 TTPP ...")."""
    marker = re.compile(r"^[\u2022*-]\s+(?=\S)")
    items = [line.strip() for line in (text or "").split("\n") if line.strip()]
    if len(items) <= 1 and not any(marker.match(item) for item in items):
        return [Para(items[0] if items else "-")]
    return [Para(marker.sub("", item), HANGING_INDENT, HANGING_INDENT, bullet=True) for item in items]


def _layout(paras: list[Para], font: str) -> list[Line]:
    lines = []
    for para in paras:
        for k, (x, text) in enumerate(_wrap(para.text, para.first, para.rest, font)):
            lines.append(Line(x, text, para.bullet and k == 0))
    return lines


# field, label lines (text, justified), value style, template minimum height
ROWS = [
    ("aircraft_reg", [("AIRCRAFT REG", True), ("9Y-", False)], _plain, 0.0),
    ("flight_no", [("FLIGHT\u00a0# BW", True)], _plain, 17.52),
    ("gate", [("GATE POSITION", False)], _plain, 19.80),
    ("pax_load", [("PAX LOAD", False)], _separated, 19.94),
    ("mel_items", [("M.E.L ITEMS", False)], _mel, 19.80),
    ("cargo", [("CARGO", False)], _plain, 18.48),
    ("route", [("ROUTE", False)], _plain, 25.44),
    ("wx_departure", [("WX @", True), ("DEPARTURE", False), ("STATION", False)], _preformatted, 0.0),
    ("wx_destination", [("WX @", True), ("DESTINATION", False)], _preformatted, 0.0),
    ("wx_alternate", [("WX @", True), ("ALTERNATE", False)], _preformatted, 0.0),
    ("sigmet_info", [("SIGMET INFO", False)], _preformatted, 12.36),
    ("enroute_airport", [("ENROUTE", False), ("AIRPORT", False)], _plain, 0.0),
    ("flight_plan_fuel", [("FLIGHT PLAN", True), ("FUEL", False)], _separated, 0.0),
    ("alt_filed", [("ALT FILED", False)], _separated, 11.54),
    ("additional_info", [("ADDITIONAL", False), ("INFORMATION", False)], _bullets, 0.0),
]

CHECKBOXES = [  # name, box x, text x, row
    ("CFP", 173.81, 192.65, 0), ("NOTAMS", 276.31, 295.03, 0), ("00Z", 349.51, 368.35, 0),
    ("12Z", 395.14, 413.98, 0), ("METARS/TAFS", 173.81, 192.65, 1), ("MAP", 276.31, 295.03, 1),
    ("06Z", 349.51, 368.35, 1), ("18Z", 395.14, 413.98, 1),
]


class _Sheet:
    def __init__(self, out: str | Path | BinaryIO, data: BriefingData, fonts: Fonts):
        self.fonts = fonts
        self.c = canvas.Canvas(out if hasattr(out, "write") else str(out), pagesize=letter)
        self.c.setTitle("Flight Crew Briefing Sheet")
        self.c.setSubject(f"BW {data.flight_no} {data.date}".strip())
        self.c.setAuthor(data.dispatcher or "Caribbean Airlines Flight Dispatch")
        self.c.setCreator("Briefing Sheet Generator")
        self.rows_on_page = 0
        self.pages = 1
        self._page_background()

    # drawing primitives (top-down coordinates) --------------------------------
    def _rect(self, x0: float, top: float, x1: float, bottom: float, gray: float = 0.0):
        self.c.setFillGray(gray)
        self.c.rect(x0, PAGE_H - bottom, x1 - x0, bottom - top, stroke=0, fill=1)

    def _text(self, x: float, baseline: float, text: str, font: str, size: float = SIZE):
        self.c.setFillGray(0)
        self.c.setFont(font, size)
        self.c.drawString(x, PAGE_H - baseline, text, charSpace=_char_space(font, size))

    def _page_background(self):
        self.c.drawImage(str(asset("watermark.jpg")), 72.0, PAGE_H - 502.9, width=467.7, height=223.1)
        self._rect(72.0, 710.65, 540.0, 711.60)
        self._text(72.02, 731.14, FOOTER, self.fonts.bold, 9.0)

    def new_page(self):
        self.c.showPage()
        self.pages += 1
        self.rows_on_page = 0
        self._page_background()

    def save(self):
        self.c.showPage()
        self.c.save()

    # fixed parts of the form --------------------------------------------------
    def title(self):
        self._text(224.45, 89.66, "Flight Crew Briefing Sheet", self.fonts.bold, 14.04)

    def logo_row(self, y: float) -> float:
        top, bottom = y + BORDER, y + BORDER + 42.0
        self._rect(X_OUT_L, y, X_OUT_R, top)
        self._rect(X_OUT_L, top, X_LABEL, bottom)
        self._rect(X_RIGHT, top, X_OUT_R, bottom)
        self._rect(X_OUT_L, bottom, X_OUT_R, bottom + BORDER)
        self.c.drawImage(str(asset("logo.png")), 276.7, PAGE_H - 137.8, width=91.5, height=42.0, mask="auto")
        self.rows_on_page += 1
        return bottom

    def _frame(self, y: float, top: float, bottom: float):
        self._rect(X_OUT_L, y, X_OUT_R, top)
        self._rect(X_OUT_L, top, X_LABEL, bottom)
        self._rect(X_LABEL, top, X_DIV, bottom, GRAY)
        self._rect(X_DIV, top, X_VALUE, bottom)
        self._rect(X_RIGHT, top, X_OUT_R, bottom)
        self._rect(X_OUT_L, bottom, X_OUT_R, bottom + BORDER)

    def _checkbox(self, x: float, top: float, checked: bool):
        self.c.setStrokeGray(0)
        self.c.setLineWidth(0.72)
        self.c.rect(x, PAGE_H - top - 10.32, 10.32, 10.32, stroke=1, fill=0)
        if checked:
            self.c.setLineWidth(0.48)
            x0, x1, y0, y1 = x - 0.12, x + 10.44, PAGE_H - (top - 0.12), PAGE_H - (top + 10.44)
            self.c.line(x0, y0, x1, y1)
            self.c.line(x0, y1, x1, y0)

    def checklist_row(self, y: float, checks: dict[str, bool]) -> float:
        top = y + BORDER
        bottom = top + 38.04
        self._frame(y, top, bottom)
        f = self.fonts.regular
        self._text(LABEL_X, top + 11.28, "DOCUMENT", f, 12.0)
        self._text(LABEL_X, top + 25.08, "CHECKLIST", f, 12.0)
        self._text(361.0, top + 10.32, "SIG & WIND CHARTS", f, 11.04)
        for name, box_x, text_x, row in CHECKBOXES:
            self._checkbox(box_x, top + (13.92, 26.52)[row], bool(checks.get(name)))
            self._text(text_x, top + (23.04, 35.64)[row], name, f, 11.04)
        self.rows_on_page += 1
        return bottom

    # table rows ---------------------------------------------------------------
    def _label(self, top: float, lines: list[tuple[str, bool]]):
        f = self.fonts.regular
        for i, (text, justify) in enumerate(lines):
            baseline = top + BASELINE + i * LINE
            words = [w.replace("\u00a0", " ") for w in text.split(" ")]
            if justify and len(words) > 1:
                widths = [_width(w, f) for w in words]
                gap = (LABEL_END - LABEL_X - sum(widths)) / (len(words) - 1)
                x = LABEL_X
                for word, w in zip(words, widths):
                    self._text(x, baseline, word, f)
                    x += w + gap
            else:
                self._text(LABEL_X, baseline, " ".join(words), f)

    def _draw_row(self, y: float, label, lines: list[Line], height: float, center: bool) -> float:
        top = y + BORDER
        bottom = top + height
        self._frame(y, top, bottom)
        self._label(top, label)
        value_top = top + ((height - len(lines) * LINE) / 2 if center else 0.0)
        f = self.fonts.regular
        for i, line in enumerate(lines):
            baseline = value_top + BASELINE + i * LINE
            if line.bullet:  # Word's list bullet is the Symbol-font dot
                self._text(VALUE_X + BULLET_INDENT, baseline, "\u2022", "Symbol")
            if line.text:
                self._text(VALUE_X + line.x, baseline, line.text, f)
        self.rows_on_page += 1
        return bottom

    def row(self, y: float, label, lines: list[Line], min_height: float, center: bool = True) -> float:
        height = max(min_height, len(label) * LINE, len(lines) * LINE)
        if y + height + 2 * BORDER > BOTTOM and self.rows_on_page:
            self.new_page()
            y = NEXT_TABLE_TOP
        room = BOTTOM - y - 2 * BORDER
        if height > room:  # taller than a whole page: continue the text on the next page
            n = max(len(label), int(room // LINE))
            y = self._draw_row(y, label, lines[:n], n * LINE, center=False)
            self.new_page()
            return self.row(NEXT_TABLE_TOP, [], lines[n:], 0.0, center=False)
        return self._draw_row(y, label, lines, height, center)

    def dispatcher_line(self, y: float, name: str, date_text: str):
        baseline = y + BORDER + DISPATCHER_GAP
        if baseline + 2.96 > BOTTOM:
            self.new_page()
            baseline = DISPATCHER_NEW_PAGE_BASELINE
        f, size = self.fonts.signature, 11.04
        for x, text in ((72.02, f"DISPATCHER: {name}".rstrip()), (434.14, f"DATE:  {date_text}".rstrip())):
            self._text(x, baseline, text, f, size)
            self._rect(x, baseline + 1.20, x + _width(text, f, size), baseline + 1.92)  # underline


def render_briefing(data: BriefingData, out: str | Path | BinaryIO) -> int:
    """Write the briefing sheet PDF to a file path or a binary stream. Returns the number of pages."""
    fonts = get_fonts()
    sheet = _Sheet(out, data, fonts)
    sheet.title()
    y = sheet.logo_row(FIRST_TABLE_TOP)
    y = sheet.checklist_row(y, data.checklist)
    for field_name, label, style, min_height in ROWS:
        lines = _layout(style(getattr(data, field_name), fonts.regular), fonts.regular)
        y = sheet.row(y, label, lines, min_height)
    sheet.dispatcher_line(y, data.dispatcher, data.date)
    sheet.save()
    return sheet.pages
