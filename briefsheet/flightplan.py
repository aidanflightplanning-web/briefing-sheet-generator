"""Parser for the Caribbean Airlines flight plan brief (the "CFP" package).

The brief is laid out as:

1. One operational flight plan per leg: RMKS, the FLTNO/DATE line, the nav
   log, the fuel breakdown, diversion routes, ETPs (long-haul only) and the
   ATC flight plan "(FPL-...)". A dispatch authorisation page may follow.
2. The weather section (DEPARTURE / ARRIVAL / OTHER METARs and TAFs).
3. The NOTAM section (pages headed "Briefing generated: ...").
4. The SIGMET section.

Only pages carrying the "BRIEF PAGE x OF y" header are read, so wind charts
and any previously attached briefing sheet are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .pdftext import extract_pages

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

BRIEF_PAGE_RE = re.compile(r"\bBRIEF PAGE \d+ OF \d+\b")
HEADER_FOOTER_RE = re.compile(r"^(?:.*\bBRIEF )?PAGE \d+ OF \d+$")
BRIEFSHEET_PAGE_RE = re.compile(r"Flight Crew Briefing Sheet|FORM NBR SOC001")

FLTNO_HEADER_RE = re.compile(r"^FLTNO\s*/\s*DATE\s+ORIG\s*/\s*DEST")
FLTNO_RE = re.compile(
    r"^(?P<flight>(?P<airline>[A-Z]{2,3})(?P<number>\d{1,4})[A-Z]?)\s*/\s*(?P<date>\d{2}[A-Z]{3})\s+"
    r"(?P<orig>[A-Z]{3,4})\s*/\s*(?P<dest>[A-Z]{3,4})\s+"
    r"(?:(?P<altn>[A-Z]{3,4})\s+)?"
    r"(?P<equip>[A-Z0-9]{2,4})\s*/\s*(?P<reg>[A-Z0-9-]{2,6})\b"
)
TOTAL_FUEL_RE = re.compile(r"^TOTAL FUEL REQUIRED\s+(?:[A-Z]\s+)?(?:\d{1,2}\.\d{2}\s+)?(\d{3,6})\b")
ETP_RE = re.compile(r"^([A-Z]{4}) TO ([A-Z]{4}) POSN\b")
SUITABILITY_RE = re.compile(r"^([A-Z]{4}) \d{2}:\d{2}Z TO \d{2}:\d{2}Z$")
PLAN_ID_RE = re.compile(r"^PLAN ID\s+(.+)$")
DISPATCHER_RE = re.compile(r"^DISPATCHER\s*(?:-|\.{2,})\s*([A-Z][A-Z .'-]*[A-Z])$")
BRIEFING_GENERATED_RE = re.compile(r"Briefing generated:\s*(\d{2})([A-Z]{3})(\d{2})\s+(\d{2})(\d{2})")
AIRPORT_CODES_RE = re.compile(r"\(([A-Z]{4})/([A-Z]{3})\)")

TAF_START_RE = re.compile(r"^TAF(?:\s+(?:AMD|COR|RTD|CNL))*\s+([A-Z]{4})\b")
METAR_START_RE = re.compile(r"^(?:METAR|SPECI)(?:\s+(?:COR|AUTO))*\s+([A-Z]{4})\b")
WX_LABEL_RE = re.compile(
    r"^(?:DEPARTURE|ARRIVAL|OTHER|ALTERNATES?|DESTINATION|EN[ -]?ROUTE|ETOPS|EDTO|ETP|TAKE[ -]?OFF|TKOF)\b"
)
WX_SECTION_START_RE = re.compile(r"^(?:DEPARTURE|ARRIVAL)$")
ISSUE_TIME_RE = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z\b")

SIGMET_HEADER_RE = re.compile(r"\bSIGMET\b.*\bVALID\s+\d{6}/\d{6}")
OTHER_PRODUCT_RE = re.compile(r"^(?:AIRMET|PIREP|UUA|UA|TCA|VAA|GAMET)\b")
NO_REPORTS_RE = re.compile(r"^NO\b.*\bFOUND\b")


@dataclass
class Leg:
    """One sector of the flight plan package."""

    flight: str               # e.g. "BWA476"
    airline: str              # "BWA"
    number: int               # 476
    date_text: str            # "26SEP"
    orig: str                 # IATA, e.g. "POS"
    dest: str                 # IATA, e.g. "HAV"
    altn: str                 # first alternate, IATA
    equipment: str            # "B737"
    registration: str         # "GUY" (without the 9Y- nationality prefix)
    remarks: list[str] = field(default_factory=list)
    total_fuel: int | None = None
    dep_icao: str = ""
    dest_icao: str = ""
    alternates: list[str] = field(default_factory=list)   # ICAO, from the ATC flight plan
    aircraft_type: str = ""   # ICAO type, e.g. "B38M"
    date_of_flight: date | None = None
    etps: list[tuple[str, str]] = field(default_factory=list)
    suitable_airports: list[str] = field(default_factory=list)
    plan_id: str = ""

    @property
    def sector(self) -> str:
        return f"{self.orig}-{self.dest}"

    @property
    def label(self) -> str:
        return f"{self.flight} {self.sector}"


@dataclass
class FlightPlan:
    path: Path
    legs: list[Leg]
    tafs: dict[str, str]
    metars: dict[str, str]
    sigmets: list[list[str]]
    briefing_generated: datetime | None
    dispatcher: str | None
    iata_to_icao: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    @property
    def registrations(self) -> list[str]:
        return _unique(leg.registration for leg in self.legs)

    @property
    def summary(self) -> str:
        legs = ", ".join(f"{leg.flight} {leg.sector} ({leg.date_text})" for leg in self.legs)
        regs = ", ".join(f"9Y-{r}" for r in self.registrations)
        return f"{legs} | {regs}"


class FlightPlanError(ValueError):
    pass


def _unique(items) -> list:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _clean(line: str) -> str:
    line = line.replace(" ", " ").replace("\t", " ")
    return re.sub(r" {2,}", " ", line).strip()


def _load_brief_pages(source: str | Path | bytes) -> list[list[str]]:
    texts = extract_pages(source)
    has_brief_header = any(BRIEF_PAGE_RE.search(t) for t in texts)
    pages = []
    for text in texts:
        if has_brief_header and not BRIEF_PAGE_RE.search(text):
            continue  # wind charts, previously attached briefing sheet, ...
        if not has_brief_header and BRIEFSHEET_PAGE_RE.search(text):
            continue
        lines = []
        for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = _clean(raw)
            if line and not HEADER_FOOTER_RE.match(line):
                lines.append(line)
        pages.append(lines)
    return pages


def _is_weather_start(line: str) -> bool:
    return bool(WX_SECTION_START_RE.match(line) or TAF_START_RE.match(line) or METAR_START_RE.match(line))


def _is_notam_page(lines: list[str]) -> bool:
    return any("Briefing generated:" in line or line.startswith("NTM No:") for line in lines)


def _parse_fpl(chunk: list[str]) -> tuple[dict, int] | tuple[None, int]:
    """Parse the ICAO flight plan message in a leg. Returns (fields, end index)."""
    start = next((i for i, line in enumerate(chunk) if line.startswith("(FPL-")), None)
    if start is None:
        return None, 0
    lines = []
    for line in chunk[start:]:
        lines.append(line)
        if line.endswith(")"):
            break
    items: list[str] = []
    for line in lines:
        if line.startswith("-") and items:
            items.append(line[1:].strip())
        elif items:
            items[-1] += " " + line
        else:
            items.append(line)

    fpl: dict = {"type": "", "dep": "", "dest": "", "alternates": [], "item18": ""}
    if len(items) > 1:
        fpl["type"] = items[1].split("/")[0].strip()
    dep_idx = None
    for i, item in enumerate(items[1:], start=1):
        if re.fullmatch(r"[A-Z]{4}\d{4}", item):
            fpl["dep"] = item[:4]
            dep_idx = i
            break
    if dep_idx is not None:
        for i in range(dep_idx + 1, len(items)):
            m = re.fullmatch(r"([A-Z]{4})\d{4}((?:\s+[A-Z]{4})*)", items[i].strip())
            if m:
                fpl["dest"] = m.group(1)
                fpl["alternates"] = m.group(2).split()
                fpl["item18"] = " ".join(items[i + 1:]).rstrip(")").strip()
                break
    item18 = fpl["item18"]
    if "ZZZZ" in fpl["alternates"]:
        m = re.search(r"\bALTN/(\S+)", item18)
        fpl["alternates"] = [a for a in fpl["alternates"] if a != "ZZZZ"] + ([m.group(1)] if m else [])
    m = re.search(r"\bDOF/(\d{2})(\d{2})(\d{2})\b", item18)
    fpl["dof"] = date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    m = re.search(r"\bREG/(\S+)", item18)
    fpl["reg"] = m.group(1) if m else ""
    return fpl, start + len(lines)


def _parse_legs(pre: list[str], warnings: list[str]) -> tuple[list[Leg], int]:
    """Parse every leg. Returns the legs and the index where the weather section starts."""
    headers = [i for i, line in enumerate(pre) if FLTNO_HEADER_RE.match(line)]
    if not headers:
        raise FlightPlanError("No flight plan legs found (missing 'FLTNO /DATE ORIG/DEST' line).")

    # Remarks sit between "RMKS" and the FLTNO header of their own leg.
    remark_starts, remarks = [], []
    for h in headers:
        j, found = h - 1, None
        while j >= 0 and h - j <= 20:
            if pre[j] == "RMKS":
                found = j
                break
            j -= 1
        if found is None:
            remark_starts.append(h)
            remarks.append([])
        else:
            remark_starts.append(found)
            remarks.append([line for line in pre[found + 1:h] if not line.upper().startswith("RAIM")])

    legs: list[Leg] = []
    body_end = len(pre)
    for k, h in enumerate(headers):
        end = remark_starts[k + 1] if k + 1 < len(headers) else len(pre)
        chunk = pre[h:end]
        m = FLTNO_RE.match(chunk[1]) if len(chunk) > 1 else None
        if not m:
            warnings.append(f"Could not read the flight line after header #{k + 1}.")
            continue
        leg = Leg(
            flight=m.group("flight"),
            airline=m.group("airline"),
            number=int(m.group("number")),
            date_text=m.group("date"),
            orig=m.group("orig"),
            dest=m.group("dest"),
            altn=m.group("altn") or "",
            equipment=m.group("equip"),
            registration=re.sub(r"^9Y-?", "", m.group("reg")),
            remarks=remarks[k],
        )
        fpl, fpl_end = _parse_fpl(chunk)
        if fpl:
            leg.aircraft_type = fpl["type"]
            leg.dep_icao = fpl["dep"]
            leg.dest_icao = fpl["dest"]
            leg.alternates = fpl["alternates"]
            leg.date_of_flight = fpl["dof"]
        else:
            warnings.append(f"{leg.label}: ATC flight plan (FPL) not found.")
        # The dispatch release/authorisation text after the FPL still belongs to the leg;
        # the leg ends where the weather section starts (only relevant for the last leg).
        leg_end = fpl_end if fpl else 2
        while leg_end < len(chunk) and not _is_weather_start(chunk[leg_end]):
            leg_end += 1
        for line in chunk[:leg_end]:
            if leg.total_fuel is None and (fm := TOTAL_FUEL_RE.match(line)):
                leg.total_fuel = int(fm.group(1))
            elif em := ETP_RE.match(line):
                leg.etps.append((em.group(1), em.group(2)))
            elif sm := SUITABILITY_RE.match(line):
                leg.suitable_airports.append(sm.group(1))
            elif not leg.plan_id and (pm := PLAN_ID_RE.match(line)):
                leg.plan_id = pm.group(1)
        if leg.total_fuel is None:
            warnings.append(f"{leg.label}: TOTAL FUEL REQUIRED not found.")
        legs.append(leg)
        if k == len(headers) - 1:
            body_end = h + leg_end
    return legs, body_end


def _issue_key(report: str) -> tuple:
    m = ISSUE_TIME_RE.search(report)
    return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)


def _parse_weather(lines: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    tafs: dict[str, str] = {}
    metars: dict[str, str] = {}
    kind = station = None
    buf: list[str] = []

    def flush():
        if kind and buf:
            report = re.sub(r"\s+", " ", " ".join(buf)).strip().rstrip("=").strip()
            store = tafs if kind == "TAF" else metars
            if station not in store or _issue_key(report) >= _issue_key(store[station]):
                store[station] = report

    for line in lines:
        taf_m, metar_m = TAF_START_RE.match(line), METAR_START_RE.match(line)
        if taf_m or metar_m:
            flush()
            kind, station, buf = ("TAF", taf_m.group(1), [line]) if taf_m else ("METAR", metar_m.group(1), [line])
        elif (WX_LABEL_RE.match(line) or "SEE ABOVE" in line or NO_REPORTS_RE.match(line)
              or SIGMET_HEADER_RE.search(line)):
            flush()
            kind, buf = None, []
        elif kind:
            buf.append(line)
    flush()
    return tafs, metars


def _parse_sigmets(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if SIGMET_HEADER_RE.search(line):
            current = [line]
            blocks.append(current)
        elif (NO_REPORTS_RE.match(line) or TAF_START_RE.match(line) or METAR_START_RE.match(line)
              or WX_LABEL_RE.match(line) or OTHER_PRODUCT_RE.match(line)):
            current = None
        elif current is not None:
            current.append(line)
    unique, seen = [], set()
    for block in blocks:
        key = re.sub(r"\s+", " ", " ".join(block))
        if key not in seen:
            seen.add(key)
            unique.append(block)
    return unique


def parse_flight_plan(source: str | Path | bytes, name: str | None = None) -> FlightPlan:
    """Parse a flight plan brief from a file path, or from the PDF's bytes (`name` names it)."""
    in_memory = isinstance(source, (bytes, bytearray))
    path = Path(name or "flight plan.pdf") if in_memory else Path(source)
    pages = _load_brief_pages(source)
    if not pages:
        raise FlightPlanError(f"No readable text in {path.name}.")

    flags = [_is_notam_page(p) for p in pages]
    if any(flags):
        first = flags.index(True)
        last = len(flags) - 1 - flags[::-1].index(True)
        pre = [line for page in pages[:first] for line in page]
        notam = [line for page, f in zip(pages, flags) if f for line in page]
        post = [line for page in pages[last + 1:] for line in page]
    else:
        pre = [line for page in pages for line in page]
        notam, post = [], []

    warnings: list[str] = []
    legs, body_end = _parse_legs(pre, warnings)
    weather_lines = pre[body_end:]
    tafs, metars = _parse_weather(weather_lines)
    sigmets = _parse_sigmets(weather_lines + post)

    generated = None
    for line in notam:
        if m := BRIEFING_GENERATED_RE.search(line):
            day, mon, yy, hh, mm = m.groups()
            if mon in MONTHS:
                generated = datetime(2000 + int(yy), MONTHS[mon], int(day), int(hh), int(mm))
            break

    iata_to_icao: dict[str, str] = {}
    for line in notam:
        for icao, iata in AIRPORT_CODES_RE.findall(line):
            iata_to_icao.setdefault(iata, icao)

    dispatcher = None
    for line in pre:
        if m := DISPATCHER_RE.match(line):
            dispatcher = m.group(1).strip()
            break

    for leg in legs:  # fall back to NOTAM airport headers when a leg has no FPL
        leg.dep_icao = leg.dep_icao or iata_to_icao.get(leg.orig, "")
        leg.dest_icao = leg.dest_icao or iata_to_icao.get(leg.dest, "")
        if not leg.alternates and leg.altn in iata_to_icao:
            leg.alternates = [iata_to_icao[leg.altn]]

    return FlightPlan(
        path=path,
        legs=legs,
        tafs=tafs,
        metars=metars,
        sigmets=sigmets,
        briefing_generated=generated,
        dispatcher=dispatcher,
        iata_to_icao=iata_to_icao,
        warnings=warnings,
    )
