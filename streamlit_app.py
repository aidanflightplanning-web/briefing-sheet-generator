"""Web version of the Flight Crew Briefing Sheet Generator.

    streamlit run streamlit_app.py

Upload the MEL status workbooks and the flight plan brief; every field except
the gate position and the passenger loads is filled in automatically and can
be reviewed before generating. Uploaded files are processed in memory for the
current browser session only.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import asdict

import pypdfium2 as pdfium
import streamlit as st
from PIL import Image

from briefsheet import mel
from briefsheet.builder import CHECKLIST_ITEMS, BriefingData, briefing_date, build_briefing, mel_text
from briefsheet.flightplan import FlightPlan, parse_flight_plan
from briefsheet.notams import flight_remarks
from briefsheet.output import output_names, package_pdf
from briefsheet.render import asset, render_briefing

UTC_OFFSET_HOURS = -4.0  # dispatch office local time (Trinidad); dates the brief and picks the MEL sheet
LABELS = {
    "aircraft_reg": "Aircraft reg 9Y-", "flight_no": "Flight # BW", "mel_items": "M.E.L items",
    "cargo": "Cargo", "route": "Route", "wx_departure": "WX @ departure station",
    "wx_destination": "WX @ destination", "wx_alternate": "WX @ alternate", "sigmet_info": "SIGMET info",
    "enroute_airport": "Enroute airport", "flight_plan_fuel": "Flight plan fuel", "alt_filed": "Alt filed",
    "additional_info": "Additional information", "dispatcher": "Dispatcher", "date": "Date",
}
TEXT_AREAS = {"mel_items", "wx_departure", "wx_destination", "wx_alternate", "sigmet_info", "additional_info"}
KEEP_CASE = {"wx_departure", "wx_destination", "wx_alternate", "sigmet_info"}

st.set_page_config(page_title="Flight Crew Briefing Sheet", page_icon=Image.open(asset("icon.ico")), layout="wide")
st.markdown("<style>textarea {font-family: ui-monospace, SFMono-Regular, Consolas, monospace !important;}</style>",
            unsafe_allow_html=True)
state = st.session_state


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure(key: str, value) -> None:
    """Widget values are dropped when a widget isn't shown; restore them from the flight plan."""
    if key not in state:
        state[key] = value


def read_workbooks(files) -> list[mel.MelWorkbook]:
    """Parse each uploaded MEL workbook once per session; forget removed ones."""
    parsed = state.get("workbooks", {})
    current, books = {}, []
    for upload in files:
        data = upload.getvalue()
        key = digest(data)
        if key not in parsed:
            try:
                parsed[key] = mel.load_workbook(data, name=upload.name)
            except Exception as exc:
                st.error(f"Cannot read {upload.name}: {exc}")
                continue
        current[key] = parsed[key]
        books.append(parsed[key])
    state.workbooks = current
    return books


def read_flight_plan(upload) -> FlightPlan:
    """Parse the flight plan; a new flight plan resets every field."""
    data = upload.getvalue()
    key = digest(data)
    if state.get("fp_key") != key:
        fp = parse_flight_plan(data, name=upload.name)
        state.fp_key, state.fp, state.fp_bytes = key, fp, data
        state.initial = build_briefing(fp, utc_offset_hours=UTC_OFFSET_HOURS)
        for name in LABELS:
            state[f"f_{name}"] = getattr(state.initial, name)
        for item in CHECKLIST_ITEMS:
            state[f"c_{item}"] = state.initial.checklist[item]
        state.gate = ""
        for i in range(len(fp.legs)):
            state[f"pax_{i}"] = ""
        for stale in ("mel_sheet", "mel_key", "output"):
            state.pop(stale, None)
    return state.fp


def mel_status(books: list[mel.MelWorkbook], fp: FlightPlan, day) -> list[mel.MelLookup]:
    st.markdown("**MEL**")
    if not books:
        st.warning("Upload the MEL sheets (step 1) – the M.E.L items are read from them.")
        return []
    lookups = [mel.lookup(books, reg, day) for reg in fp.registrations]
    auto = next((lk for lk in lookups if lk.found), None)
    if auto:
        names = [s.name for s in auto.workbook.sheets]
        if state.get("mel_sheet") not in names:
            state.mel_sheet = auto.sheet.name
        chosen = st.selectbox("MEL sheet used", names, key="mel_sheet")
        if chosen != auto.sheet.name:
            lookups = [mel.lookup(books, reg, day, chosen) for reg in fp.registrations]
    for lk in lookups:
        if not lk.found:
            st.error(f"9Y-{lk.registration} is not in the uploaded MEL sheets – type its M.E.L items below.")
            continue
        count = len(lk.items)
        result = f"{count} open item{'s' if count != 1 else ''}" if count else "NIL REPORTED"
        st.success(f"9Y-{lk.registration}: **{result}**  \n{lk.workbook.path.name} › {lk.sheet.name}")
        if not lk.exact_date:
            gap = f", {(day - lk.sheet.date).days} days earlier" if lk.sheet.date and lk.sheet.date < day else ""
            st.warning(f"This workbook has no sheet for {day:%d/%m/%y}; the newest earlier sheet "
                       f"({lk.sheet.name}{gap}) is used. Upload the current workbook if there is one.")
    return lookups


def field(container, name: str) -> None:
    key = f"f_{name}"
    ensure(key, getattr(state.initial, name))
    if name in TEXT_AREAS:
        lines = str(state[key]).count("\n") + 2
        container.text_area(LABELS[name], key=key, height=max(72, min(24 * lines + 14, 420)))
    else:
        container.text_input(LABELS[name], key=key)


def collect(fp: FlightPlan) -> BriefingData:
    data = BriefingData()
    for name in LABELS:
        value = str(state.get(f"f_{name}", "")).strip("\n")
        setattr(data, name, value if name in KEEP_CASE else value.upper())
    data.checklist = {item: bool(state.get(f"c_{item}")) for item in CHECKLIST_ITEMS}
    data.gate = state.get("gate", "").strip().upper() or "TBA"
    data.pax_load = " / ".join(state.get(f"pax_{i}", "").strip().upper() or "TBA" for i in range(len(fp.legs)))
    return data


def previews(pdf: bytes) -> list[bytes]:
    doc = pdfium.PdfDocument(pdf)
    try:
        images = []
        for i in range(len(doc)):
            buffer = io.BytesIO()
            doc[i].render(scale=1.5).to_pil().save(buffer, format="PNG")
            images.append(buffer.getvalue())
        return images
    finally:
        doc.close()


# --- page --------------------------------------------------------------------
st.image(str(asset("logo.png")), width=150)
st.title("Flight Crew Briefing Sheet")
st.caption("Upload the MEL sheets and the flight plan brief. Everything is filled in automatically except the gate "
           "position and passenger loads. Files are processed in memory for this session and are not stored.")

col_mel, col_fp = st.columns(2, gap="large")
mel_files = col_mel.file_uploader("**1 · MEL sheets** (B737 / ATR status workbooks)", type=["xlsx", "xlsm"],
                                  accept_multiple_files=True)
fp_file = col_fp.file_uploader("**2 · Flight plan brief** (PDF)", type=["pdf"])
books = read_workbooks(mel_files or [])
if fp_file is None:
    st.info("Upload a flight plan brief to start.")
    st.stop()
try:
    fp = read_flight_plan(fp_file)
except Exception as exc:
    st.error(f"Could not read {fp_file.name}: {exc}")
    st.stop()

day = briefing_date(fp, UTC_OFFSET_HOURS)
with st.container(border=True):
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("**Flight plan**")
        notam_items = len(flight_remarks(fp))
        st.markdown("  \n".join(f"`{leg.flight}` {leg.dep_icao}–{leg.dest_icao} · {leg.date_text} · "
                                f"9Y-{leg.registration}" for leg in fp.legs) + f"  \nBriefing date **{day:%d/%m/%y}**"
                    f"  \nNOTAMs: **{notam_items}** closure/outage item{'' if notam_items == 1 else 's'} added to "
                    "Additional information")
        for warning in fp.warnings:
            st.warning(warning)
    with right:
        lookups = mel_status(books, fp, day)

mel_key = (tuple(sorted(state.workbooks)), state.get("mel_sheet"), state.fp_key)
if state.get("mel_key") != mel_key or "f_mel_items" not in state:
    state["f_mel_items"] = mel_text(lookups)
    state.mel_key = mel_key

st.subheader("3 · Not on the flight plan")
columns = st.columns(min(len(fp.legs), 4) + 1)
ensure("gate", "")
columns[0].text_input("Gate position", key="gate", placeholder="e.g. 13")
for i, leg in enumerate(fp.legs):
    ensure(f"pax_{i}", "")
    columns[i % 4 + 1].text_input(f"PAX load {leg.flight} {leg.sector}", key=f"pax_{i}", placeholder="C/Y, e.g. 2/11")

st.subheader("4 · Review")
st.caption("Filled in from the flight plan and the MEL sheet. Every field can be edited.")
for column, item in zip(st.columns(len(CHECKLIST_ITEMS)), CHECKLIST_ITEMS):
    ensure(f"c_{item}", state.initial.checklist[item])
    column.checkbox(item, key=f"c_{item}")
for names, widths in ((("aircraft_reg", "flight_no", "cargo", "route"), (1, 1, 1, 2)), (("mel_items",), (1,)),
                      (("wx_departure", "wx_destination"), (1, 1)), (("wx_alternate", "sigmet_info"), (1, 1)),
                      (("enroute_airport", "flight_plan_fuel", "alt_filed"), (1, 1, 1)),
                      (("additional_info",), (1,)), (("dispatcher", "date"), (1, 1))):
    for column, name in zip(st.columns(widths), names):
        field(column, name)

st.subheader("5 · Generate")
data = collect(fp)
blank = ([] if state.get("gate", "").strip() else ["gate position"]) + [
    f"PAX load {leg.flight} {leg.sector}" for i, leg in enumerate(fp.legs) if not state.get(f"pax_{i}", "").strip()]
if blank:
    st.warning("Blank, printed as TBA: " + ", ".join(blank))
unchecked = [lk.registration for lk in lookups if not lk.found]
if not books:
    st.error("Upload the MEL sheets first (step 1).")
elif unchecked and not data.mel_items.strip():
    st.warning(f"9Y-{', 9Y-'.join(unchecked)} was not found in the MEL sheets and the M.E.L items box is empty.")

signature = digest(repr(sorted(asdict(data).items())).encode())
if st.button("Generate briefing sheet", type="primary", disabled=not books, width="stretch"):
    with st.spinner("Generating…"):
        buffer = io.BytesIO()
        render_briefing(data, buffer)
        sheet = buffer.getvalue()
        state.output = {"signature": signature, "sheet": sheet, "package": package_pdf(state.fp_bytes, sheet),
                        "previews": previews(sheet)}

output = state.get("output")
if output and output["signature"] == signature:
    sheet_name, package_name = output_names(fp_file.name)
    first, second = st.columns(2)
    first.download_button("Download briefing sheet", output["sheet"], file_name=sheet_name, mime="application/pdf",
                          type="primary", icon=":material/download:", width="stretch", on_click="ignore")
    second.download_button("Download flight plan + briefing sheet", output["package"], file_name=package_name,
                           mime="application/pdf", icon=":material/download:", width="stretch", on_click="ignore")
    _, middle, _ = st.columns([1, 4, 1])
    for page in output["previews"]:
        middle.image(page, width="stretch")
elif output:
    st.info("A field changed after the sheet was generated – generate it again to download.")
