"""Finds the pages of an MEL item in the MEL book (the B737-8 or the ATR 72-600 MEL PDF).

Each item of the MEL starts with its number as a heading, for example::

    Page 52-11.1                       Page 73-2
    52-11-01                           73-15-01 FUEL HEATER
    52-11-01-01                         73-15-01A LOW Fuel Temperature Reported (A)
    Left Main Cabin Door ...           ...  - OR -  73-15-01C High Fuel Temperature ...

and runs on until the next item heading. Pages that only carry "(Cont'd)" text belong
to the item before them. Tables of contents, the preamble and other front matter are
not item pages, and "INTENTIONALLY BLANK" pages are never attached.

An MEL number on the MEL sheet selects the pages of that item and of its sub-items:
``23-11-01`` gives every page of 23-11-01 (23-11-01-01, 23-11-01-01B ...), while
``73-15-01C`` gives only the page that shows 73-15-01C. A number that is not in the
book falls back to its parent item (``74-00-01-01B`` -> ``74-00-01-01``). Sub-items
marked for other aircraft only, such as "(CUB ONLY)", are left out.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from .pdftext import extract_pages

NUMBER = r"\d{2}-\d{2}-\d{2}(?:-\d{2})?[A-Z]?"
HEADING_RE = re.compile(rf"^\s*({NUMBER})(?![\w-])(.*)$")
NUMBER_RE = re.compile(rf"(?<![\w-])({NUMBER})(?![\w-])")
PAGE_LABEL_RE = re.compile(r"\bPage\s+(\S+)\s*$")
ITEM_PAGE_LABEL_RE = re.compile(r"^\d{2}-\d+(?:[.\-]\d+)?$")       # 52-11.1, 77-3 (not TOC.52-1)
CONTINUED_RE = re.compile(r"\bCONT(?:[’'`]?D|INUED)\b", re.I)
BLANK_RE = re.compile(r"\bINTENTIONALLY\s+(?:LEFT\s+)?BLANK\b", re.I)
TOC_RE = re.compile(r"\bTABLE OF CONTENTS\b|\.{8,}", re.I)
TABLE_HEADER_RE = re.compile(r"\bInterval\s+Installed\b|\bRI\s+NI\s+NR\b", re.I)
MAX_TITLE_LINES = 4
REG = r"(?:9Y-?)?[A-Z]{3}"
ONLY_RE = re.compile(rf"\(\s*({REG}(?:\s*(?:,|&|/|AND)\s*{REG})*)\s*(?:\)\s*)?ONLY\b")
CROSS_REF_RE = re.compile(r"\b9Y-([A-Z]{3})\b")


def normalise(number: str) -> str:
    """'25-28-01a ' -> '25-28-01A'."""
    return re.sub(r"\s+", "", number).upper()


def parents(number: str) -> list[str]:
    """'74-00-01-01B' -> ['74-00-01-01B', '74-00-01-01', '74-00-01']."""
    chain = [number]
    while True:
        n = chain[-1]
        if n[-1].isalpha():
            chain.append(n[:-1])
        elif n.count("-") > 2:
            chain.append(n.rsplit("-", 1)[0])
        else:
            return chain


def covers(heading: str, number: str) -> bool:
    """Does the heading `heading` belong to MEL item `number` (the item itself or a sub-item)?"""
    if heading == number:
        return True
    return heading.startswith(number) and (heading[len(number)] == "-" or
                                           (heading[len(number)].isalpha() and not number[-1].isalpha()))


@dataclass
class BookPage:
    index: int                 # 0-based page index in the PDF
    label: str                 # printed page number, e.g. "52-11.1"
    items: list[str]           # MEL numbers on the page (headings and continued items)
    only: dict[str, set[str]] = field(default_factory=dict)   # item -> registrations it is limited to
    blank: bool = False


@dataclass
class MelBookMatch:
    number: str                # as on the MEL sheet
    matched: str               # the number found in the book ('' when not found)
    pages: list[int]           # 0-based page indexes

    @property
    def exact(self) -> bool:
        return self.matched == normalise(self.number)


@dataclass
class MelBook:
    name: str
    fleet: str                 # "B737" / "ATR" / ""
    title: str
    page_count: int
    pages: list[BookPage]
    registrations: set[str]    # aircraft listed in the book (cross reference table), without 9Y-
    source: Path | bytes = field(repr=False, default=b"")

    def find(self, number: str, registration: str = "") -> MelBookMatch:
        reg = re.sub(r"^9Y-?", "", registration.upper())
        for candidate in parents(normalise(number)):
            found = [p.index for p in self.pages if not p.blank and self._applies(p, candidate, reg)]
            if found:
                return MelBookMatch(number, candidate, found)
        return MelBookMatch(number, "", [])

    @staticmethod
    def _applies(page: BookPage, number: str, reg: str) -> bool:
        hits = [h for h in page.items if covers(h, number)]
        if not hits:
            return False
        if not reg:
            return True
        # Leave the page out only when every matching sub-item is limited to other aircraft.
        return any(not page.only.get(h) or reg in page.only[h] for h in hits)

    def pdf_bytes(self) -> bytes:
        return self.source if isinstance(self.source, (bytes, bytearray)) else Path(self.source).read_bytes()


def _fleet(text: str) -> str:
    upper = text.upper()
    if "ATR 72" in upper or "ATR72" in upper or "-ATR-" in upper:
        return "ATR"
    if "737" in upper:
        return "B737"
    return ""


def _registrations(text: str) -> set[str]:
    return set(CROSS_REF_RE.findall(text))


def _parse(texts: list[str]) -> tuple[list[BookPage], str]:
    pages: list[BookPage] = []
    previous: list[str] = []
    title = ""
    for index, text in enumerate(texts):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not title and lines:
            title = " ".join(lines[:6])
        label_at = next((i for i, l in enumerate(lines[:12]) if PAGE_LABEL_RE.search(l)), None)
        label = PAGE_LABEL_RE.search(lines[label_at]).group(1) if label_at is not None else ""
        header = " ".join(lines[:label_at + 1]) if label_at is not None else ""
        if not ITEM_PAGE_LABEL_RE.match(label) or TOC_RE.search(header) or TOC_RE.search(text[:600]):
            previous = []
            continue
        body = lines[label_at + 1:]
        page = BookPage(index, label, [], blank=bool(BLANK_RE.search(" ".join(body[:4]))) and len(body) <= 4)
        if page.blank:
            pages.append(page)
            previous = []
            continue
        block: list[str] = []      # headings of the item being titled, until its table header
        title_lines = 0
        for n, line in enumerate(body):
            m = HEADING_RE.match(line)
            if m:
                number, title = m.group(1), m.group(2)
                if number not in page.items:
                    page.items.append(number)
                if CONTINUED_RE.search(title):
                    block = []
                    continue
                block.append(number)
                title_lines = 0
            elif n == 0:
                # The page opens with text, not a heading: it continues the item(s) of the page before.
                continued = NUMBER_RE.findall(line) if CONTINUED_RE.search(line) else []
                for number in continued or previous:
                    if number not in page.items:
                        page.items.append(number)
                continue
            elif TABLE_HEADER_RE.search(line) or CONTINUED_RE.search(line) or title_lines >= MAX_TITLE_LINES:
                block = []
                continue
            else:
                title = line
                title_lines += 1
            # "(CUB ONLY)" in an item's title limits that item (and the headings above it) to those aircraft.
            only = ONLY_RE.search(title.upper()) if block else None
            if only:
                regs = {re.sub(r"^9Y-?", "", r) for r in re.findall(REG, only.group(1))}
                for number in block:
                    page.only[number] = regs
        pages.append(page)
        previous = page.items
    return pages, title


_cache: dict[str, MelBook] = {}
MAX_CACHED = 4


def load_book(source: str | Path | bytes, name: str | None = None) -> MelBook:
    """Index an MEL book PDF (cached by file and modification time, or by content)."""
    if isinstance(source, (bytes, bytearray)):
        key = hashlib.sha256(source).hexdigest()
        label = name or "MEL book.pdf"
    else:
        path = Path(source)
        key = f"{path.resolve()}|{path.stat().st_mtime}|{path.stat().st_size}"
        label = name or path.name
        source = path
    if key in _cache:
        _cache[key] = _cache.pop(key)  # most recently used last
        return _cache[key]
    texts = extract_pages(bytes(source) if isinstance(source, (bytes, bytearray)) else source)
    pages, title = _parse(texts)
    if not pages:
        raise ValueError("no MEL items found – is this an MEL book?")
    front = "\n".join(texts[:120])
    book = MelBook(name=label, fleet=_fleet(label + " " + title) or _fleet(front), title=title,
                   page_count=len(texts), pages=pages, registrations=_registrations(front), source=source)
    _cache[key] = book
    while len(_cache) > MAX_CACHED:  # uploaded books are held in memory: keep only the latest few
        _cache.pop(next(iter(_cache)))
    return book


def fleet_of_type(aircraft_type: str, equipment: str = "") -> str:
    """'AT76' / 'ATR72' -> 'ATR'; 'B38M' / 'B737' -> 'B737'."""
    text = f"{aircraft_type} {equipment}".upper()
    if re.search(r"\bAT[R0-9]", text):
        return "ATR"
    if re.search(r"\bB3[0-9]|\b73[0-9]|\bB7M", text):
        return "B737"
    return ""


def book_for(books: list[MelBook], registration: str, fleet: str) -> MelBook | None:
    """The MEL book for an aircraft: the one listing the registration, else the one for its type."""
    reg = re.sub(r"^9Y-?", "", registration.upper())
    listed = [b for b in books if reg in b.registrations]
    if listed:
        return listed[0]
    return next((b for b in books if fleet and b.fleet == fleet), None)


@dataclass
class ItemPages:
    """The MEL book pages for one open item of the MEL sheet."""

    registration: str
    number: str                # as on the MEL sheet
    book: MelBook | None
    match: MelBookMatch | None

    @property
    def pages(self) -> list[int]:
        return self.match.pages if self.match else []

    @property
    def labels(self) -> list[str]:
        by_index = {p.index: p.label for p in self.book.pages} if self.book else {}
        return [by_index.get(i, str(i + 1)) for i in self.pages]

    @property
    def note(self) -> str:
        if not self.book:
            return f"{self.number}: no MEL book attached for 9Y-{self.registration}"
        if not self.pages:
            return f"{self.number}: not found in {self.book.name}"
        pages = ", ".join(self.labels)
        word = "page" if len(self.pages) == 1 else "pages"
        if not self.match.exact:
            return f"{self.number}: not in the book as such – item {self.match.matched}, {word} {pages}"
        return f"{self.number}: {word} {pages}"


def item_pages(books: list[MelBook], lookups, fp=None) -> list[ItemPages]:
    """MEL book pages for every open item in the MEL lookups (mel.MelLookup) of the flight.

    The book is the one whose cross-reference table lists the registration, otherwise the
    one for the aircraft type of the flight plan (B38M -> B737, AT76 -> ATR) or of the
    MEL workbook the aircraft was found in."""
    result = []
    for lk in lookups:
        if not lk.found or not lk.items:
            continue
        legs = [leg for leg in (fp.legs if fp else []) if leg.registration == lk.registration]
        fleet = next((f for f in (fleet_of_type(leg.aircraft_type, leg.equipment) for leg in legs) if f), "")
        book = book_for(books, lk.registration, fleet or (lk.workbook.fleet if lk.workbook else ""))
        for item in lk.items:
            match = book.find(item.number, lk.registration) if book else None
            result.append(ItemPages(lk.registration, item.number, book, match))
    return result


def pages_pdf(items: list[ItemPages]) -> bytes | None:
    """The pages of the items, in MEL sheet order, each page once. None when there are none."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    readers: dict[int, PdfReader] = {}
    seen: set[tuple[int, int]] = set()
    for entry in items:
        if not entry.book:
            continue
        reader = readers.get(id(entry.book))
        if reader is None:
            reader = readers[id(entry.book)] = PdfReader(io.BytesIO(entry.book.pdf_bytes()))
        for i in entry.pages:
            if (id(entry.book), i) not in seen and 0 <= i < len(reader.pages):
                writer.add_page(reader.pages[i])
                seen.add((id(entry.book), i))
    if not seen:
        return None
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
