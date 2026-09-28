"""Turns a parsed flight plan and MEL lookup into the briefing sheet fields.

Every field is plain text so it can be reviewed and edited before printing.
Multi-leg values (pax, fuel, alternates) are separated by " / ".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .flightplan import FlightPlan
from .mel import MelLookup
from .taf import format_taf

DEFAULT_ROUTE = "STANDARD COMPANY ROUTINGS"
DEFAULT_CARGO = "TBA"
NIL_MEL = "NIL REPORTED"
NIL_SIGMET = "NIL EN RTE"
CHECKLIST_ITEMS = ("CFP", "METARS/TAFS", "NOTAMS", "MAP", "00Z", "06Z", "12Z", "18Z")
DEFAULT_CHECKLIST = {"CFP": True, "METARS/TAFS": True, "NOTAMS": True,
                     "MAP": False, "00Z": False, "06Z": False, "12Z": False, "18Z": False}
LOADSHEET_RE = re.compile(r"LOAD\s*SHEET\s+TO\s+CONFIRM")


@dataclass
class BriefingData:
    aircraft_reg: str = ""
    flight_no: str = ""
    gate: str = ""
    pax_load: str = ""
    mel_items: str = NIL_MEL
    cargo: str = DEFAULT_CARGO
    route: str = DEFAULT_ROUTE
    wx_departure: str = ""
    wx_destination: str = ""
    wx_alternate: str = ""
    sigmet_info: str = NIL_SIGMET
    enroute_airport: str = "N/A"
    flight_plan_fuel: str = ""
    alt_filed: str = ""
    additional_info: str = "-"
    dispatcher: str = ""
    date: str = ""
    checklist: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_CHECKLIST))


def briefing_date(fp: FlightPlan, utc_offset_hours: float = -4.0) -> date:
    """Local date the brief was prepared (the brief is timestamped in UTC)."""
    if fp.briefing_generated:
        return (fp.briefing_generated + timedelta(hours=utc_offset_hours)).date()
    return (datetime.now(timezone.utc) + timedelta(hours=utc_offset_hours)).date()


def round_up_100(kg: int) -> int:
    return int(math.ceil(kg / 100.0) * 100)


def flight_numbers(fp: FlightPlan) -> str:
    numbers = []
    for leg in fp.legs:
        if leg.number not in numbers:
            numbers.append(leg.number)
    # One- and two-digit flights are written in four-digit form (BW 0005); others as filed (476).
    return "-".join(f"{n:04d}" if n < 100 else str(n) for n in numbers)


def _wx_block(fp: FlightPlan, icao: str) -> list[str]:
    if icao in fp.tafs:
        return format_taf(fp.tafs[icao])
    lines = [f"NO TAF AVBL FOR {icao}"]
    if icao in fp.metars:
        lines.append(fp.metars[icao])
    return lines


def _join_blocks(blocks: list[list[str]]) -> str:
    out: list[str] = []
    for block in blocks:
        if out:
            out.append("")
        out.extend(block)
    return "\n".join(out)


def weather_sections(fp: FlightPlan) -> tuple[str, str, str]:
    """TAFs for the departure station, the destinations and the alternates.

    A destination back at the departure station is not repeated, and an
    alternate already shown above is referred to with "SEE XXXX ABV".
    """
    if not fp.legs:
        return "", "", ""
    departure = fp.legs[0].dep_icao
    shown = [departure]

    dest_blocks = []
    for leg in fp.legs:
        if leg.dest_icao and leg.dest_icao not in shown:
            dest_blocks.append(_wx_block(fp, leg.dest_icao))
            shown.append(leg.dest_icao)

    alt_blocks, alts_seen = [], []
    for leg in fp.legs:
        for alt in leg.alternates:
            if alt in alts_seen:
                continue
            alts_seen.append(alt)
            alt_blocks.append([f"SEE {alt} ABV"] if alt in shown else _wx_block(fp, alt))

    return "\n".join(_wx_block(fp, departure)), _join_blocks(dest_blocks), _join_blocks(alt_blocks)


def sigmet_text(fp: FlightPlan) -> str:
    if not fp.sigmets:
        return NIL_SIGMET
    # Header line flush left, continuation lines indented one space (as on the example sheets).
    return _join_blocks([[block[0]] + [" " + line for line in block[1:]] for block in fp.sigmets])


def enroute_airports(fp: FlightPlan) -> str:
    """ETP airports (excluding the departure/destination ends), or N/A."""
    ends = {leg.dep_icao for leg in fp.legs} | {leg.dest_icao for leg in fp.legs}
    airports: list[str] = []
    for leg in fp.legs:
        for pair in leg.etps:
            for apt in pair:
                if apt not in ends and apt not in airports:
                    airports.append(apt)
    return ", ".join(airports) if airports else "N/A"


def fuel_text(fp: FlightPlan) -> str:
    parts = []
    for leg in fp.legs:
        value = f"{round_up_100(leg.total_fuel)}KG" if leg.total_fuel else "TBA"
        if LOADSHEET_RE.search(" ".join(leg.remarks)):
            value += "-LOADSHEET TO CONFIRM"
        parts.append(value)
    return " / ".join(parts)


def alternates_text(fp: FlightPlan) -> str:
    return " / ".join(" & ".join(leg.alternates) or "NIL" for leg in fp.legs)


def additional_info(fp: FlightPlan) -> str:
    """Dispatcher remarks (RMKS) from each leg, one per line; '-' when there are none."""
    items = []
    for leg in fp.legs:
        text = re.sub(r"\s+", " ", " ".join(leg.remarks)).strip()
        # A "LOADSHEET TO CONFIRM" note is shown against that leg's fuel figure instead.
        text = " - ".join(p for p in re.split(r"\s+-\s+", text) if p and not LOADSHEET_RE.search(p))
        if not text:
            continue
        if len(fp.legs) > 1:
            text += f" EX {leg.orig}"
        items.append(text)
    return "\n".join(items) if items else "-"


def mel_text(lookups: list[MelLookup]) -> str:
    """MEL items for the sheet, or '' when an aircraft could not be checked."""
    if not lookups or any(not lk.found for lk in lookups):
        return ""
    prefix = len(lookups) > 1
    lines = []
    for lk in lookups:
        texts = [item.briefing_text for item in lk.items] or ([NIL_MEL] if prefix else [])
        lines.extend(f"9Y-{lk.registration}: {t}" if prefix else t for t in texts)
    return "\n".join(lines) if lines else NIL_MEL


def build_briefing(fp: FlightPlan, mel_lookups: list[MelLookup] | None = None, *,
                   gate: str = "", pax: list[str] | None = None,
                   cargo: str = DEFAULT_CARGO, route: str = DEFAULT_ROUTE,
                   utc_offset_hours: float = -4.0, dispatcher: str = "") -> BriefingData:
    wx_dep, wx_dest, wx_alt = weather_sections(fp)
    pax = pax or []
    return BriefingData(
        aircraft_reg=" / ".join(fp.registrations),
        flight_no=flight_numbers(fp),
        gate=gate,
        pax_load=" / ".join(p.strip() for p in pax),
        mel_items=mel_text(mel_lookups or []),
        cargo=cargo,
        route=route,
        wx_departure=wx_dep,
        wx_destination=wx_dest,
        wx_alternate=wx_alt,
        sigmet_info=sigmet_text(fp),
        enroute_airport=enroute_airports(fp),
        flight_plan_fuel=fuel_text(fp),
        alt_filed=alternates_text(fp),
        additional_info=additional_info(fp),
        dispatcher=fp.dispatcher or dispatcher,
        date=briefing_date(fp, utc_offset_hours).strftime("%d/%m/%y"),
    )
