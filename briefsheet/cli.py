"""Command-line use: python -m briefsheet FLIGHT_PLAN.pdf [--mel SHEET.xlsx ...] [--mel-book MEL.pdf ...]

Everything is read from the flight plan and the MEL sheets; only the gate
position and the passenger load of each leg are asked for. The MEL book pages of
the open items are attached when MEL books are given (or remembered); wind charts
are attached with --wind.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import mel, melbook, windcharts
from .builder import build_briefing, briefing_date
from .flightplan import FlightPlanError, parse_flight_plan
from .notams import flight_remarks
from .output import OutputError, write_outputs
from .settings import Settings


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m briefsheet",
        description="Generate the Flight Crew Briefing Sheet from a flight plan PDF and the MEL sheets. "
                    "Run without arguments to open the window.")
    parser.add_argument("flight_plan", nargs="?", help="flight plan brief (PDF)")
    parser.add_argument("--mel", action="append", default=[], metavar="XLSX",
                        help="MEL status workbook (repeat for B737 and ATR); defaults to the remembered sheets")
    parser.add_argument("--mel-book", action="append", default=[], metavar="PDF",
                        help="MEL book (repeat for B737 and ATR); defaults to the remembered books")
    parser.add_argument("--save-mel", action="store_true",
                        help="remember the --mel workbooks and --mel-book books for next time")
    parser.add_argument("--no-mel-pages", action="store_true", help="do not attach the MEL book pages")
    parser.add_argument("--wind", action="append", default=[], metavar="HOURS",
                        help="B737 flights: attach the Area A FL100 wind charts, 'auto' (those valid from 3 h "
                             "before departure to 3 h after arrival) or forecast hours, e.g. --wind 6 --wind 12")
    parser.add_argument("--mel-sheet", metavar="NAME", help='use this worksheet, e.g. "26TH SEPTEMBER 2026"')
    parser.add_argument("--gate", help="gate position (asked for if omitted)")
    parser.add_argument("--pax", action="append", metavar="C/Y", help="pax load, once per leg in order")
    parser.add_argument("--cargo", help="cargo (default TBA)")
    parser.add_argument("--route", help="route text instead of the ATC routes and flight times of the flight plan")
    parser.add_argument("--out", metavar="DIR", help="output folder (default: the flight plan's folder)")
    parser.add_argument("--no-append", action="store_true", help="do not write the flight plan + sheet package")
    parser.add_argument("--gui", action="store_true", help="open the window")
    args = parser.parse_args(argv)

    if args.gui or not args.flight_plan:
        from .gui import main as gui_main
        return gui_main(args.flight_plan)

    if hasattr(sys.stdout, "reconfigure"):   # NOTAM and MEL text may hold characters the console cannot show
        sys.stdout.reconfigure(errors="replace")
    settings = Settings.load()
    mel_paths = args.mel or settings.mel_paths
    book_paths = args.mel_book or settings.mel_book_paths
    if args.save_mel and (args.mel or args.mel_book):
        if args.mel:
            settings.mel_paths = [str(Path(p).resolve()) for p in args.mel]
        if args.mel_book:
            settings.mel_book_paths = [str(Path(p).resolve()) for p in args.mel_book]
        settings.save()
    wind_hours = []
    for value in args.wind:
        for part in value.replace(",", " ").split():
            if part.lower() == "auto":
                wind_hours.append("auto")
            elif part.isdigit() and int(part) in windcharts.HOURS:
                wind_hours.append(int(part))
            else:
                parser.error(f"--wind takes 'auto' or the forecast hours {', '.join(map(str, windcharts.HOURS))}")
    if not mel_paths:
        parser.error("attach the MEL sheets first: --mel \"B737 MEL SHEET.xlsx\" --mel \"ATR MEL SHEET.xlsx\" "
                     "(add --save-mel to remember them)")

    try:
        fp = parse_flight_plan(args.flight_plan)
    except (FlightPlanError, OSError) as exc:
        print(f"Cannot read the flight plan: {exc}", file=sys.stderr)
        return 1

    print(f"Flight plan : {Path(args.flight_plan).name}")
    for leg in fp.legs:
        alts = " & ".join(leg.alternates) or "NIL"
        print(f"  {leg.flight:<8} {leg.dep_icao}-{leg.dest_icao}  {leg.date_text}  9Y-{leg.registration}  "
              f"ALTN {alts}  FUEL {leg.total_fuel}")
    for warning in fp.warnings:
        print(f"  WARNING: {warning}")

    workbooks = []
    for path in mel_paths:
        try:
            workbooks.append(mel.load_workbook(path))
        except Exception as exc:  # unreadable or missing workbook
            print(f"  WARNING: cannot read MEL sheet {path}: {exc}")
    day = briefing_date(fp, settings.utc_offset_hours)
    lookups = [mel.lookup(workbooks, reg, day, args.mel_sheet) for reg in fp.registrations]
    for lk in lookups:
        if not lk.found:
            print(f"  WARNING: 9Y-{lk.registration} is not in the attached MEL sheets - M.E.L ITEMS left blank")
            continue
        note = "" if lk.exact_date else f"  (no sheet for {day:%d/%m/%y}; latest sheet used)"
        items = "; ".join(i.briefing_text for i in lk.items) or "NIL REPORTED"
        print(f"MEL 9Y-{lk.registration}: {items}\n  from {lk.source}{note}")
    attachments = []
    if lookups and not args.no_mel_pages and any(lk.items for lk in lookups):
        books = []
        for path in book_paths:
            try:
                books.append(melbook.load_book(path))
            except Exception as exc:
                print(f"  WARNING: cannot read MEL book {path}: {exc}")
        if not books:
            print("MEL book pages: no MEL book given (--mel-book) - not attached")
        else:
            entries = melbook.item_pages(books, lookups, fp)
            for entry in entries:
                print(f"  MEL book 9Y-{entry.registration} {entry.note}")
            attachments.append(melbook.pages_pdf(entries))
    b737 = any(melbook.fleet_of_type(leg.aircraft_type, leg.equipment) == "B737" for leg in fp.legs)
    if wind_hours and not b737:
        print("Wind charts : not attached - wind charts are for B737 flights only")
    elif wind_hours:
        charts, errors = windcharts.fetch_charts()
        for error in errors:
            print(f"  WARNING: {error}")
        hours = set(h for h in wind_hours if h != "auto")
        if "auto" in wind_hours:
            hours.update(windcharts.suggested_hours(charts, fp))
        chosen = [c for c in charts if c.hour in hours]
        print("Wind charts : " + (", ".join(c.label for c in chosen) or
                                  "none valid from 3 h before departure to 3 h after arrival"))
        if chosen:
            attachments.append(windcharts.charts_pdf(chosen))

    remarks = flight_remarks(fp)
    print(f"NOTAMs: {len(remarks)} closure/outage item(s) added to the remarks")
    for remark in remarks:
        print(f"  - {remark}")

    gate = args.gate if args.gate is not None else _ask("Gate position: ")
    pax = list(args.pax or [])
    for leg in fp.legs[len(pax):]:
        pax.append(_ask(f"PAX load {leg.flight} {leg.sector} (C/Y): "))
    pax = [p or "TBA" for p in pax[:len(fp.legs)]]

    kwargs = {}
    if args.cargo:
        kwargs["cargo"] = args.cargo.upper()
    if args.route:
        kwargs["route"] = args.route.upper()
    data = build_briefing(fp, lookups, gate=gate.upper() or "TBA", pax=pax,
                          utc_offset_hours=settings.utc_offset_hours, dispatcher=settings.dispatcher, **kwargs)
    try:
        written = write_outputs(args.flight_plan, data, args.out or settings.output_dir or None,
                                append=not args.no_append, attachments=attachments)
    except OutputError as exc:
        print(exc, file=sys.stderr)
        return 1
    for path in written:
        print(f"Saved: {path}")
    return 0
