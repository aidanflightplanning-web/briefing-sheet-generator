"""NOTAM screening for the briefing sheet remarks.

Reads the NOTAM pages of the brief and picks out, for the departure,
destination, alternate and en-route alternate (ETP) airports of each leg, the
NOTAMs that report

* the aerodrome or its control tower closed,
* a runway closed, or
* a navigation aid or instrument approach out of service,

and that are in force between one hour before departure and one hour after
arrival (plus the diversion time for alternates).

Layout of a NOTAM page (as extracted by pdfium): airport names and category
headings are in a larger font than the NOTAM text, and each NOTAM comes as

    A1512/26 30SEP26      number and start date
    0300                  start time
    03OCT26               end date, or "UFN <text>" / "PERM <text>"
    1000                  end time
    0300 - 1000           (optional daily schedule, then the text)
    RWY 10/28 CLSD ...

Company notices read "00001 WIE UFN <text>". This is an aid for the dispatcher:
anything not recognised as a closure or outage is left to the NOTAM pages.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .pdftext import StyledLine

MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
          "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
MONTH_NAMES = {number: name for name, number in MONTHS.items()}
MARGIN = timedelta(hours=1)

AIRPORT_RE = re.compile(r"^.+ \((?P<icao>[A-Z]{4})/[A-Z0-9]{3}\),")
START_RE = re.compile(r"^(?P<number>\d{2}/\d{3}|[A-Z]\d{4}/\d{2}|\d{5}) (?P<rest>\d{2}[A-Z]{3}\d{2}|WIE\b.*)$")
DATE_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})$")
TIME_RE = re.compile(r"^(\d{2})(\d{2})$")
OPEN_END_RE = re.compile(r"^(UFN|PERM)\b\s*(.*)$")
NOT_A_NOTAM_RE = re.compile(r"^(?:SEE ABOVE|ELEV\. .*|NO OPERATIONAL NOTAMS ON FILE FOR [A-Z]{4})$")

DAILY_RE = re.compile(r"^(?:DLY|DAILY)?\s*(\d{4}\s*-\s*\d{4}(?:\s+\d{4}\s*-\s*\d{4})*)$")
LIMITS_RE = re.compile(r"^(?:(?:SFC|GND|FL\d+|\d+ ?(?:FT|M)\b.*?) / (?:UNL|FL\d+|\d+ ?(?:FT|M)\b.*)|F\) .+ G\) .+)$")
FAA_PREFIX_RE = re.compile(r"^(?:[A-Z]{3,4} )?\d{2}/\d{3} (?:\([A-Z]\d{4}/\d{2}\) )?")
FAA_VALIDITY_RE = re.compile(r"\s*\d{10}-(?:\d{10}(?:EST)?|PERM)$")

# --- what counts as a closure or outage ---------------------------------------
CLOSED = r"(?:CLSD|CLOSED)"
OUTAGE = (r"(?:U/S|UNSERVICEABLE|OUT OF (?:SERVICE|SVC)|OTS|NOT AVBL|UNAVBL|UNAVAILABLE|NOT AVAILABLE|UNUSABLE|"
          r"NOT USABLE|WITHDRAWN|DECOMMISSIONED|SHUT ?DOWN|OFF AIR|ON TEST|DO NOT USE|UNREL(?:IABLE)?|INOP(?:ERATIVE)?)")
NAVAID = (r"(?:D?VOR(?:/DME|TAC)?|VORTAC|TACAN|DME|NDB|ILS|LOC|LLZ|LOCALI[SZ]ER|GP|G/P|GLIDE ?(?:PATH|SLOPE)|"
          r"LOM|LMM|GNSS|GPS|GBAS|MLS)")


def _within(limit: int, barred: str = "") -> str:
    """Up to `limit` characters of the same sentence (a decimal point does not end it),
    not running into any of the `barred` words."""
    bar = rf"(?!\b(?:{barred})\b)" if barred else ""
    return rf"(?:{bar}(?!\.(?:\s|$)).){{0,{limit}}}?"


# The brief files every NOTAM under a category heading. These categories are never a closure or
# navaid/approach outage: taxiways, aprons, stands, lighting and visual aids (PAPI, approach lights),
# markings and signs, obstacles, marker beacons (an ILS stays usable without them) and services.
MINOR_CATEGORY_RE = re.compile(r"TAXIWAY|APRON|PARKING|\bSTANDS?\b|MARKING|\bLIGHT|INDICATOR|OBSTACLE|MARKER|"
                               r"\bFIRE\b|FUEL|METEOROLOGICAL|TRANSMISSOMETER|\bWIND\b")
# Procedure amendments quote navaids that are out of service; the outage itself has its own NOTAM.
PROCEDURE_CATEGORY_RE = re.compile(r"PROCEDURE|DEPARTURE|ARRIVAL|MINIMA|CLEARANCE ALTITUDE")
NAVAID_CATEGORY_RE = re.compile(r"\b(?:ILS|LOCALI[SZ]ER|GLIDE PATH|LOCATOR|VOR|VORTAC|TACAN|DME|"
                                r"DISTANCE MEASURING|RADIO BEACON|RADIO NAVIGATION|MICROWAVE LANDING|GNSS)\b")
# US-style NOTAMs open with their subject: "PHL TWY S BTN TWY D AND APCH END RWY 27R CLSD" is a taxiway.
MINOR_SUBJECT_RE = re.compile(r"^(?:[A-Z0-9]{3,4} )?(?:TWY|TAXIWAY|TXL|TAXILANE|APN|APRON|OBST)\b")

AD_CLOSED_RE = re.compile(rf"\b(?:AD|AP|ARPT|AIRPORT|AERODROME|AIRFIELD)\b{_within(40)}\b{CLOSED}\b")
AD_HEADING_CLOSED_RE = re.compile(rf"^(?:[A-Z0-9]{{3,4}} )?{CLOSED}\b")
TOWER_CLOSED_RE = re.compile(rf"\b(?:TWR|CONTROL TOWER|ATCT)\b{_within(40)}\b{CLOSED}\b")
RWY_CLOSED_RE = re.compile(rf"\b(?:RWY|RUNWAY)\s*\d{{2}}[LRC]?(?:/\d{{2}}[LRC]?)?"
                           rf"{_within(60, 'TWY|TAXIWAY|APN|APRON|EXIT|RESA')}\b{CLOSED}\b")
NAVAID_OUT_RE = re.compile(rf"\b{NAVAID}\b{_within(80)}(?<![A-Z]){OUTAGE}(?![A-Z])")
MARKER_OUT_RE = re.compile(rf"\b(?:IM|MM|OM|(?:INNER|MIDDLE|OUTER) MARKER)\s+{OUTAGE}(?![A-Z])")
OUTAGE_RE = re.compile(rf"(?<![A-Z]){OUTAGE}(?![A-Z])")
APPROACH_OUT_RE = re.compile(      # the approach procedure itself; "APCH END RWY 35" is a place, "APCH LGT" lighting
    rf"\b(?:APCH|APPROACH|IAP)\b(?!\s+(?:END|LGT|LIGHT|LIGHTS|LIGHTING|CTL|CONTROL)\b){_within(60)}(?<![A-Z])"
    r"(?:NOT AVBL|UNAVBL|UNAVAILABLE|NOT AVAILABLE|SUSPENDED|WITHDRAWN|CANCELLED|NOT AUTH(?:ORI[SZ]ED)?|U/S)(?![A-Z])"
    r"|\bPROC(?:EDURE)? NA\b")     # US wording for a whole procedure; "... APCH NA BLW 200FT" is only a note
MAX_TEXT = 240   # longer NOTAM texts are cut in the remark; the number points to the full text


@dataclass
class Notam:
    airport: str
    number: str
    start: datetime | None = None      # None: with immediate effect (WIE)
    end: datetime | None = None        # None: until further notice or permanent
    open_end: str = ""                 # "UFN" or "PERM" when there is no end
    category: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def daily(self) -> list[tuple[int, int]] | None:
        """Daily active periods in minutes UTC when the text opens with a plain daily schedule."""
        if not self.lines:
            return None
        m = DAILY_RE.match(self.lines[0])
        if not m:
            return None
        periods = []
        for a, b in re.findall(r"(\d{4})\s*-\s*(\d{4})", m.group(1)):
            periods.append((int(a[:2]) * 60 + int(a[2:]), int(b[:2]) * 60 + int(b[2:])))
        return periods

    @property
    def text(self) -> str:
        """The NOTAM text on one line, without the schedule, vertical limits and FAA bookkeeping."""
        lines = self.lines[1:] if self.daily else self.lines
        text = " ".join(line for line in lines if not LIMITS_RE.match(line))
        text = re.sub(r"\s+", " ", text.replace("’", "'").replace("‘", "'")).strip()
        return FAA_VALIDITY_RE.sub("", FAA_PREFIX_RE.sub("", text)).strip()

    @property
    def kind(self) -> str | None:
        """'AD CLSD', 'TWR CLSD', 'RWY CLSD', 'NAVAID' or 'APCH' for closures/outages; None otherwise."""
        text, category = self.text, self.category
        if MINOR_CATEGORY_RE.search(category) or MINOR_SUBJECT_RE.match(text):
            return None
        # "AD CLSD ...", or under the AERODROME heading a text that simply opens with "CLSD ..."
        if AD_CLOSED_RE.search(text) or (category == "AERODROME" and AD_HEADING_CLOSED_RE.match(text)):
            return "TWR CLSD" if TOWER_CLOSED_RE.search(text) else "AD CLSD"
        if TOWER_CLOSED_RE.search(text):
            return "TWR CLSD"
        if RWY_CLOSED_RE.search(text):
            return "RWY CLSD"
        if not PROCEDURE_CATEGORY_RE.search(category) and not MARKER_OUT_RE.search(text) and (
                NAVAID_OUT_RE.search(text) or (NAVAID_CATEGORY_RE.search(category) and OUTAGE_RE.search(text))):
            return "NAVAID"
        if APPROACH_OUT_RE.search(text):
            return "APCH"
        return None

    def active(self, begin: datetime, finish: datetime) -> bool:
        """In force at some time between `begin` and `finish`?"""
        if self.start and self.start > finish:
            return False
        if self.end and self.end < begin:
            return False
        daily = self.daily
        if not daily:
            return True   # no schedule, or one too detailed to interpret: assume in force throughout
        first = max(begin, self.start) if self.start else begin
        last = min(finish, self.end) if self.end else finish
        day = datetime(first.year, first.month, first.day) - timedelta(days=1)
        while day <= last:
            for a, b in daily:
                on = day + timedelta(minutes=a)
                off = day + timedelta(minutes=b) + (timedelta(days=1) if b <= a else timedelta())
                if on <= last and off >= first:
                    return True
            day += timedelta(days=1)
        return False

    @property
    def timeframe(self) -> str:
        def stamp(moment: datetime, with_z: bool = True) -> str:   # "30SEP26 0300Z", as on the NOTAM pages
            return f"{moment.day:02d}{MONTH_NAMES[moment.month]}{moment:%y} {moment:%H%M}" + ("Z" if with_z else "")

        if self.start and self.end and self.start.date() == self.end.date():
            frame = f"{stamp(self.start, False)}-{self.end:%H%M}Z"
        else:
            frame = f"{stamp(self.start) if self.start else 'WIE'}-{stamp(self.end) if self.end else self.open_end or 'UFN'}"
        if self.daily:
            frame += " DLY " + " ".join(f"{a // 60:02d}{a % 60:02d}-{b // 60:02d}{b % 60:02d}" for a, b in self.daily)
        return frame

    @property
    def remark(self) -> str:
        text = self.text
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT].rsplit(" ", 1)[0] + " ..."
        return f"{self.airport} {self.timeframe}: {text} [{self.number}]"


def _moment(day: str, clock: str) -> datetime | None:
    d, t = DATE_RE.match(day), TIME_RE.match(clock)
    if not (d and t and d.group(2) in MONTHS):
        return None
    hour, minute = int(t.group(1)), int(t.group(2))
    extra = timedelta(days=1) if hour == 24 else timedelta()
    try:
        return datetime(2000 + int(d.group(3)), MONTHS[d.group(2)], int(d.group(1)), hour % 24, minute) + extra
    except ValueError:
        return None


def parse_notams(pages: list[list[StyledLine]]) -> dict[str, list[Notam]]:
    """NOTAMs by airport (ICAO code) from the NOTAM pages of the brief."""
    lines = [StyledLine(re.sub(r"\s+", " ", line.text).strip(), line.size, line.x) for page in pages for line in page]
    lines = [line for line in lines if line.text]
    rows = [line.size for line in lines if line.size and (START_RE.match(line.text) or TIME_RE.match(line.text))]
    if not rows:
        return {}   # no NOTAMs, or no font information (fallback text engine)
    body = Counter(rows).most_common(1)[0][0]

    notams: dict[str, list[Notam]] = {}
    airport, category = "", ""
    current: Notam | None = None
    expect, pending_day = "", ""

    def close():
        nonlocal current, expect
        if current and current.airport:
            notams.setdefault(current.airport, []).append(current)
        current, expect = None, ""

    for line in lines:
        text = line.text
        if abs(line.size - body) > 0.9:
            if line.size < body or line.size > body + 2.6:
                continue                          # page title, column captions, page numbers
            m = AIRPORT_RE.match(text)            # heading: airport name or NOTAM category
            if m and m.group("icao") == airport:
                continue                          # repeated at the top of a page: same airport goes on
            close()
            if m:
                airport, category = m.group("icao"), ""
            else:
                category = text
            continue
        if text == "SEE ABOVE" or (current is None and NOT_A_NOTAM_RE.match(text)):
            close()
            continue
        start = START_RE.match(text) if line.x < 100 else None
        if start:
            close()
            current = Notam(airport, start.group("number"), category=category)
            rest = start.group("rest")
            if rest.startswith("WIE"):
                tail = OPEN_END_RE.match(rest[3:].strip())
                if tail:
                    current.open_end = tail.group(1)
                    if tail.group(2):
                        current.lines.append(tail.group(2))
                    expect = "text"
                else:
                    expect = "end"
            else:
                pending_day, expect = rest, "start time"
            continue
        if current is None:
            continue
        if expect == "start time" and TIME_RE.match(text):
            current.start, expect = _moment(pending_day, text), "end"
        elif expect == "end" and DATE_RE.match(text):
            pending_day, expect = text, "end time"
        elif expect == "end" and OPEN_END_RE.match(text):
            tail = OPEN_END_RE.match(text)
            current.open_end, expect = tail.group(1), "text"
            if tail.group(2):
                current.lines.append(tail.group(2))
        elif expect == "end time" and TIME_RE.match(text):
            current.end, expect = _moment(pending_day, text), "text"
        else:
            current.lines.append(text)
            expect = "text"
    close()
    return notams


def flight_remarks(fp) -> list[str]:
    """Closure/outage NOTAMs in force for the flight, one remark per NOTAM, in flight order."""
    chosen: dict[tuple[str, str], Notam] = {}
    for leg in fp.legs:
        begin, finish = leg.departure, leg.arrival
        if not (begin and finish):
            continue
        enroute = [a for pair in leg.etps for a in pair if a not in (leg.dep_icao, leg.dest_icao)]
        diversions = dict(zip(leg.alternates, leg.alternate_minutes))
        for airport in dict.fromkeys([leg.dep_icao, leg.dest_icao, *leg.alternates, *enroute]):
            last = finish + timedelta(minutes=diversions.get(airport, 0)) + MARGIN
            for notam in fp.notams.get(airport, []):
                if notam.kind and notam.active(begin - MARGIN, last):
                    chosen.setdefault((airport, notam.number), notam)
    return [notam.remark for notam in chosen.values()]
