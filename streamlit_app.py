"""Web version of the Flight Crew Briefing Sheet Generator.

    streamlit run streamlit_app.py

Upload the MEL status workbooks and the flight plan; every field except the
gate position and the passenger loads is filled in automatically and can be
reviewed before generating. The MEL pages of the open items are attached from the
MEL books stored on the site (see stored_books); wind charts (Area A, FL100) can be
ticked at the bottom. Uploaded files are processed in memory for the current
browser session only.
"""

from __future__ import annotations

import hashlib
import io
import re
import urllib.request
import zipfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote, urlparse

import pypdfium2 as pdfium
import streamlit as st
from PIL import Image

from briefsheet import mel, melbook, windcharts
from briefsheet.builder import CHECKLIST_ITEMS, BriefingData, briefing_date, build_briefing, mel_text
from briefsheet.flightplan import FlightPlan, parse_flight_plan
from briefsheet.notams import flight_remarks
from briefsheet.output import combine, output_names, package_pdf
from briefsheet.render import asset, render_briefing

UTC_OFFSET_HOURS = -4.0  # dispatch office local time (Trinidad); dates the brief and picks the MEL sheet
BOOKS_DIR = Path(__file__).resolve().parent / "mel_books"   # MEL books kept on this PC (not in git)
BOOKS_REPO = "aidanflightplanning-web/briefing-sheet-mel-books"  # MEL books online (public GitHub repository)
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


def _get(url: str, token: str, accept: str = "") -> bytes:
    """Download from the location named in the app's secrets; the token goes only there."""
    headers = {"User-Agent": "BriefingSheetGenerator/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        return response.read()


@st.cache_data(ttl=600, show_spinner=False)
def _github_pdfs(repo: str, token: str) -> tuple[tuple[str, str, str], ...]:
    """(name, contents URL, version) of each PDF in the (private) GitHub repository, checked
    every 10 minutes, so a new revision pushed there is picked up without a restart."""
    import json

    listing = json.loads(_get(f"https://api.github.com/repos/{repo}/contents/", token,
                              "application/vnd.github+json"))
    return tuple((item["name"], item["url"], item["sha"]) for item in listing
                 if item.get("type") == "file" and item["name"].lower().endswith(".pdf"))


@st.cache_data(ttl=600, show_spinner=False)
def _github_version(repo: str) -> str:
    """Latest commit of a public GitHub repository, checked every 10 minutes through the git
    protocol (not the GitHub API, which allows few requests without a token)."""
    data = _get(f"https://github.com/{repo}.git/info/refs?service=git-upload-pack", "")
    m = re.search(rb"([0-9a-f]{40}) HEAD\x00", data) or re.search(rb"([0-9a-f]{40}) refs/heads/main\b", data)
    if not m:
        raise ValueError("no main branch")
    return m.group(1).decode()


def _book_sources() -> tuple[tuple, tuple, str, list[str]]:
    """What identifies the stored books: the PDFs in the mel_books folder (name, size, time),
    else every PDF in the public BOOKS_REPO repository (by its latest commit). The app's
    secrets can name another location in a [mel_books] section: github_repo = "owner/name"
    (with token = "..." for a private one) and/or urls = [...]."""
    files = tuple((p.name, p.stat().st_size, p.stat().st_mtime) for p in sorted(BOOKS_DIR.glob("*.pdf")))
    try:
        config = dict(st.secrets.get("mel_books", {}))
    except Exception:  # no secrets file
        config = {}
    token, errors = str(config.get("token", "")), []
    remote = [(unquote(Path(urlparse(url).path).name) or "MEL book.pdf", url, "") for url in config.get("urls", ())]
    repo = str(config.get("github_repo", "")) or ("" if files else BOOKS_REPO)
    if repo and token:
        try:
            remote += _github_pdfs(repo, token)
        except Exception as exc:
            errors.append(f"cannot list the MEL books in {repo}: {exc}")
    elif repo and not files:
        try:
            version = _github_version(repo)
            remote.append(("", f"https://codeload.github.com/{repo}/zip/{version}", version))
        except Exception as exc:
            errors.append(f"cannot reach the MEL books in {repo}: {exc}")
    local = {name for name, _, _ in files}
    return files, tuple(r for r in remote if r[0] not in local), token, errors


@st.cache_resource(max_entries=2, show_spinner="Loading the stored MEL books…")
def stored_books(files: tuple, remote: tuple, token: str) -> tuple[list[melbook.MelBook], list[str]]:
    """MEL books kept on the site, loaded once for all sessions (again only when a file
    changes): PDFs in the mel_books folder next to the app and the files in the private
    location named in the app's secrets."""
    books, errors = [], []
    for name, _, _ in files:
        try:
            books.append(melbook.load_book(BOOKS_DIR / name))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    for name, url, _ in remote:
        try:
            if urlparse(url).netloc == "codeload.github.com":   # the whole repository as a zip
                with zipfile.ZipFile(io.BytesIO(_get(url, ""))) as archive:
                    for entry in sorted(archive.namelist()):
                        if entry.lower().endswith(".pdf"):
                            books.append(melbook.load_book(archive.read(entry), name=entry.rsplit("/", 1)[-1]))
                continue
            accept = "application/vnd.github.raw" if urlparse(url).netloc == "api.github.com" else ""
            books.append(melbook.load_book(_get(url, token, accept), name=name))
        except Exception as exc:
            errors.append(f"{name or url}: {exc}")
    return books, errors


def read_books(files) -> list[melbook.MelBook]:
    """Index each uploaded MEL book once per session; forget removed ones."""
    parsed = state.get("books", {})
    current, books = {}, []
    for upload in files:
        data = upload.getvalue()
        key = digest(data)
        if key not in parsed:
            try:
                with st.spinner(f"Reading {upload.name}…"):
                    parsed[key] = melbook.load_book(data, name=upload.name)
            except Exception as exc:
                st.error(f"Cannot read {upload.name}: {exc}")
                continue
        current[key] = parsed[key]
        books.append(parsed[key])
    state.books = current
    return books


@st.cache_data(ttl=300, show_spinner="Downloading the wind charts from aviationweather.gov…")
def wind_charts() -> tuple[list[windcharts.WindChart], list[str], dict[int, bytes]]:
    charts, errors = windcharts.fetch_charts()
    return charts, errors, {c.hour: c.thumbnail(420) for c in charts}


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
        for stale in ("mel_sheet", "mel_key", "output", "wind_key"):
            state.pop(stale, None)
    return state.fp


def book_status(books: list[melbook.MelBook], lookups: list[mel.MelLookup], fp: FlightPlan):
    """MEL book pages for the open items (empty when switched off or there are none)."""
    if not any(lk.items for lk in lookups):
        return []
    if not st.toggle("Attach the MEL book pages of open items", value=True, key="attach_pages"):
        return []
    if not books:
        st.info("Upload the MEL books (PDF) in step 1 to attach the MEL pages of the open items.")
        return []
    entries = melbook.item_pages(books, lookups, fp)
    count = len({(id(e.book), i) for e in entries for i in e.pages})
    notes = "  \n".join(f"`{e.note}`" for e in entries)
    (st.warning if any(not e.pages for e in entries) else st.success)(
        f"MEL book pages attached: **{count}**  \n{notes}")
    return entries


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
st.caption("Upload the MEL sheets and the flight plan. Everything is filled in automatically except the gate "
           "position and passenger loads. Uploaded files are processed in memory for this session and are not stored.")

col_mel, col_fp = st.columns(2, gap="large")
mel_files = col_mel.file_uploader("**1 · MEL sheets** (B737 / ATR status workbooks)", type=["xlsx", "xlsm"],
                                  accept_multiple_files=True)
local_books, remote_books, book_token, source_errors = _book_sources()
on_site, book_errors = stored_books(local_books, remote_books, book_token)
book_errors = source_errors + book_errors
if on_site:
    col_mel.markdown("**MEL books** stored on the site  \n" + "  \n".join(
        f":material/check: {b.fleet or 'MEL'} · {b.page_count} pages · {b.name}" for b in on_site))
    with col_mel.expander("Use another MEL book revision for this session"):
        book_files = st.file_uploader("MEL book (PDF) – used instead of the stored one of the same type",
                                      type=["pdf"], accept_multiple_files=True)
else:
    book_files = col_mel.file_uploader(
        "**MEL books** (B737 / ATR MEL, PDF – to attach the MEL pages of open items)", type=["pdf"],
        accept_multiple_files=True)
for error in book_errors:
    col_mel.warning(f"Stored MEL book not loaded – {error}")
fp_file = col_fp.file_uploader("**2 · Flight Plan** (PDF)", type=["pdf"])
books = read_workbooks(mel_files or [])
uploaded_books = read_books(book_files or [])
replaced = {b.fleet for b in uploaded_books}
mel_books = uploaded_books + [b for b in on_site if not b.fleet or b.fleet not in replaced]
if fp_file is None:
    st.info("Upload a flight plan to start.")
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
        book_pages = book_status(mel_books, lookups, fp)

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

st.subheader("5 · Wind charts")
st.caption(f"{windcharts.AREA}, {windcharts.LEVEL}, from [aviationweather.gov]({windcharts.PAGE_URL}). "
           "Ticked charts are attached as US Letter pages. For B737 flights the charts in force during the "
           "flight are ticked.")
charts, chart_errors, thumbs = wind_charts()
for error in chart_errors:
    st.warning(error)
if charts:
    b737 = any(melbook.fleet_of_type(leg.aircraft_type, leg.equipment) == "B737" for leg in fp.legs)
    wind_key = (state.fp_key, tuple((c.hour, c.run) for c in charts))
    if state.get("wind_key") != wind_key:
        suggested = set(windcharts.suggested_hours(charts, fp)) if b737 else set()
        for chart in charts:
            state[f"wind_{chart.hour}"] = chart.hour in suggested
        state.wind_key = wind_key
    runs = windcharts.run_summary(charts)
    (st.warning if runs.startswith("Update") else st.caption)(
        f"{runs} · downloaded {charts[0].retrieved:%H%MZ}")
    for column, chart in zip(st.columns(len(charts)), charts):
        ensure(f"wind_{chart.hour}", False)
        column.image(thumbs[chart.hour], width="stretch")
        valid = f"{chart.valid:%H%MZ %a %d %b}".upper() if chart.valid else "valid time unknown"
        column.checkbox(f"+{chart.hour:02d} h · {valid}", key=f"wind_{chart.hour}")
        column.markdown(f"[Full size]({chart.url})")
elif not chart_errors:
    st.info("No wind charts available.")
if st.button("Refresh wind charts", icon=":material/refresh:"):
    wind_charts.clear()
    st.rerun()
selected_charts = [c for c in charts if state.get(f"wind_{c.hour}")]

st.subheader("6 · Generate")
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

book_page_keys = [(e.book.name, i) for e in book_pages for i in e.pages]
chart_keys = [(c.hour, c.run) for c in selected_charts]
signature = digest(repr((sorted(asdict(data).items()), book_page_keys, chart_keys)).encode())
if st.button("Generate briefing sheet", type="primary", disabled=not books, width="stretch"):
    with st.spinner("Generating…"):
        buffer = io.BytesIO()
        render_briefing(data, buffer)
        attachments = [melbook.pages_pdf(book_pages) if book_pages else None,
                       windcharts.charts_pdf(selected_charts) if selected_charts else None]
        sheet = combine(buffer.getvalue(), attachments)
        added = ([f"{len(set(book_page_keys))} MEL book page{'s' if len(set(book_page_keys)) != 1 else ''}"]
                 if book_page_keys else []) + \
                ([f"{len(selected_charts)} wind chart{'s' if len(selected_charts) != 1 else ''}"]
                 if selected_charts else [])
        state.output = {"signature": signature, "sheet": sheet, "package": package_pdf(state.fp_bytes, sheet),
                        "previews": previews(sheet), "added": added}

output = state.get("output")
if output and output["signature"] == signature:
    sheet_name, package_name = output_names(fp_file.name)
    first, second = st.columns(2)
    first.download_button("Download briefing sheet", output["sheet"], file_name=sheet_name, mime="application/pdf",
                          type="primary", icon=":material/download:", width="stretch", on_click="ignore")
    second.download_button("Download flight plan + briefing sheet", output["package"], file_name=package_name,
                           mime="application/pdf", icon=":material/download:", width="stretch", on_click="ignore")
    if output.get("added"):
        st.caption("Attached after the briefing sheet: " + " and ".join(output["added"]) +
                   " (in both downloads and in the preview below).")
    _, middle, _ = st.columns([1, 4, 1])
    for page in output["previews"]:
        middle.image(page, width="stretch")
elif output:
    st.info("A field changed after the sheet was generated – generate it again to download.")
