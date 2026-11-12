# Flight Crew Briefing Sheet Generator

Builds the Caribbean Airlines **Flight Crew Briefing Sheet (form SOC001)** from the
flight plan brief PDF and the monthly MEL status workbooks. The PDF reproduces the
Word form exactly: same layout, fonts, logo, "Wheels UP!" watermark and footer. Long
content continues on a second page, as in the Word form.

Only the **gate position** and the **passenger load of each leg** are entered by hand.
Everything else comes from the flight plan and the MEL sheet. B737 and ATR flight plans
are supported, including packages that cover a whole rotation (several legs).

Two attachments can follow the briefing sheet:

- the **MEL book pages** of the aircraft's open MEL items (can be switched off), and
- **wind/temperature charts** (Area A, FL100) from aviationweather.gov, ticked at the
  bottom of the screen, as US Letter pages.

It runs as a **web app** (Streamlit) or as a **Windows desktop app**. No flight plans, MEL
workbooks or MEL books are stored in this repository. The web app reads the MEL books
from a separate repository (see [MEL books on the web app](#mel-books-on-the-web-app)).

## Web app

1. Upload the **MEL sheets** (B737 and/or ATR workbooks). The MEL books are stored on the
   site; another revision can be uploaded for one session under *Use another MEL book
   revision*.
2. Upload the **Flight Plan** (PDF). All fields are filled in.
3. Enter the **gate** and the **PAX load (C/Y)** for each leg.
4. Check the review section (every field can be edited).
5. For a B737 flight, tick the **wind charts** to attach (the charts valid from 3 h before
   departure to 3 h after arrival are already ticked), then **Generate briefing sheet**.
6. Download the briefing sheet, or the flight plan with the sheet appended at the end.
   Both contain the attachments after the sheet; the preview shows every page.

Uploaded files are processed in memory for the browser session and are not saved.

**Run locally:** double-click `Run Web App Locally.bat` (or run `streamlit run streamlit_app.py`).
It opens http://localhost:8501 on this PC only, so changes can be tested before they are
pushed to GitHub and go live. Close the window to stop it.

### MEL books on the web app

The web app loads the MEL books once and uses them for every session, so they are not
uploaded each time:

- **On this PC** (`Run Web App Locally.bat`): put the MEL book PDFs in the `mel_books`
  folder next to `streamlit_app.py`. The folder is kept out of git. For a new revision,
  replace the file; the app picks it up on the next page load.
- **Online:** the app reads every PDF in the GitHub repository
  [briefing-sheet-mel-books](https://github.com/aidanflightplanning-web/briefing-sheet-mel-books)
  (`BOOKS_REPO` in `streamlit_app.py`). That repository is public, so anyone can download
  the books from it. No token or secrets are needed. The `mel_books` folder on this PC is
  a copy of it: for a new revision, replace the PDF there, then commit and push it in
  that folder; the app picks it up within ten minutes.

  The app's secrets can point somewhere else instead, for example a private repository
  with a read-only token:

  ```toml
  [mel_books]
  github_repo = "OWNER/REPO"
  token = "fine-grained token: only that repository, Contents read-only"
  ```

**Deploy on Streamlit Community Cloud:** sign in at [share.streamlit.io](https://share.streamlit.io)
with GitHub, choose **Create app**, pick this repository, branch `main` and main file
`streamlit_app.py`, then **Deploy**. `packages.txt` installs Liberation Sans and Carlito,
which have the same character widths as Arial and Calibri, so the layout matches the form.

## Desktop app (Windows)

Double-click `Briefing Sheet Generator.pyw` (or drop a flight plan PDF on it). The MEL
sheets and MEL books you attach (**Attach MEL sheets / MEL books…**, Excel or PDF) are
remembered, and so is the **Attach the MEL book pages of open items** switch. The wind
charts are downloaded when the window opens and shown along the bottom; click one to
view it full size, tick the ones to attach, **Refresh** for the latest.

Two files are saved next to the flight plan: `<flight plan>_BRIEFSHEET.pdf` and
`<flight plan>_WITH_BRIEFSHEET.pdf`. Both have the attachments after the sheet. A
briefing sheet and attachments added to the flight plan earlier are replaced.

`build_exe.bat` builds `dist\Briefing Sheet Generator.exe` (about 30 MB, single file) that
runs on PCs without Python. It needs PyInstaller.

**Command line** (asks only for the gate and pax loads):

```
briefsheet.bat FLIGHTPLAN.pdf --mel "B737 MEL SHEET.xlsx" --mel "ATR MEL SHEET.xlsx" --save-mel
briefsheet.bat FLIGHTPLAN.pdf --mel-book "B737-8 MEL.pdf" --mel-book "ATR MEL.pdf" --save-mel
briefsheet.bat FLIGHTPLAN.pdf --gate 13 --pax 2/11 --pax 15/144 --wind auto
```

Other options: `--cargo`, `--route`, `--mel-sheet "26TH SEPTEMBER 2026"`, `--out FOLDER`, `--no-append`,
`--no-mel-pages`, `--wind 6 --wind 12` (forecast hours of the charts to attach).
Desktop settings are stored in `%APPDATA%\BriefingSheetGenerator\settings.json`.

## Where each field comes from

| Field | Source |
|---|---|
| Aircraft reg 9Y- | Flight line (`B737 /GUY`) |
| Flight # BW | Flight numbers of the legs: `476-477`, `418`. Flight numbers below 100 are written with four digits (`0005`). |
| Gate position / Pax load | Entered by hand. Pax loads are separated by ` / ` per leg. |
| M.E.L items | Open items for the aircraft on the MEL sheet for the briefing date (`MEL#  DESCRIPTION`), or `NIL REPORTED`. |
| Cargo | `TBA` (can be edited). |
| Route | The ATC route of each sector (`ATC - ...` line of the navlog, including the line it wraps onto) followed by its flight time, the TIME column of the navlog in hours:minutes: `TTPP DCT POS DCT VOKAV DCT GATUX DCT AKSIN DCT OGRUM DCT SYCJ - 00:56`. One line per sector; a route flown more than once in the package (the POS-TAB shuttle) is listed once, with its longest time. `STANDARD COMPANY ROUTINGS` if the flight plan has no route. |
| WX @ departure | TAF of the first departure airport. |
| WX @ destination | TAF of each leg's destination. A return to the departure station is not repeated. |
| WX @ alternate | TAF of each filed alternate. An alternate already shown above becomes `SEE TTPP ABV`. |
| SIGMET info | SIGMETs in the flight plan brief, otherwise `NIL EN RTE`. |
| Enroute airport | ETP airports (Equal Time Point section), otherwise `N/A`. |
| Flight plan fuel | TOTAL FUEL REQUIRED of each leg, rounded up to 100 kg. A leg whose remarks say LOADSHEET TO CONFIRM gets `-LOADSHEET TO CONFIRM`. |
| Alt filed | Alternates from the ATC flight plan: `MKJP / TBPB & TGPY`. |
| Additional information | Dispatcher remarks (RMKS) of each leg, except RAIM CHECK VALIDATED (multi-leg remarks end with `EX <station>`), followed by the closure and outage NOTAMs for the flight (see below). Several items are shown as bullets, none as `-`. |
| Dispatcher | `DISPATCHER - ...` line of the flight plan. |
| Date | Local date (UTC-4) of the brief's "Briefing generated" time. |

TAFs are laid out as on the form: `BECMG`, `FM` and `PROB` groups start a new line
indented 2 spaces, `TEMPO` groups are indented 4 spaces.

### MEL sheets

- The worksheet for the briefing date is used (for example `23RD SEPTEMBER 2026`). If the
  workbook has no sheet for that day, the newest earlier sheet is used and a warning is
  shown. Another sheet can be chosen.
- An item is left off when it has a closure number or date, or when its row is green
  ("ENTIRE ROW OF CLEARED ITEMS").
- If the aircraft is not on any MEL sheet, the M.E.L box is left empty with a warning.
  `NIL REPORTED` is only printed after the aircraft was actually checked.

### MEL book pages

When an aircraft has open MEL items, the pages of those items are copied from the MEL
book and attached after the briefing sheet, in the order of the MEL sheet.

- **Which book:** the one whose cross-reference table lists the aircraft (9Y-GUY in the
  B737-8 MEL, 9Y-TTI in the ATR MEL), otherwise the one for the aircraft type in the flight
  plan (B38M → B737-8, AT76 → ATR 72-600).
- **Which pages:** every page of the item, including its "(Cont'd)" procedure pages.
  `23-11-01` gives all pages of 23-11-01 and its sub-items; `73-15-01C` gives only the
  page that shows 73-15-01C. A number that is not in the book falls back to its parent
  item (`74-00-01-01B` → `74-00-01-01`) and the note says so. Tables of contents and
  blank pages are never attached.
- **Effectivity:** sub-items marked for other aircraft only, such as `(CUB ONLY)`, are
  left out.
- The status panel lists the pages found for each item (`38-30-01: pages 38-30.1,
  38-30.2, 38-30.3`). A number that cannot be found, usually a typing error on the MEL
  sheet, is shown as a warning and nothing is attached for it.

### Wind charts

The WAFC wind/temperature charts for **Area A – 65N-50S 120W-25W (Americas), FL100** are
downloaded from [aviationweather.gov/fax](https://aviationweather.gov/fax/): the six
forecasts from +06 h to +36 h of the latest model run. Each chart is labelled with its
valid time (taken from the chart file) and is in force for three hours either side of it.

For a B737 flight the charts whose valid time is from **3 hours before departure to 3
hours after arrival** of a leg (both limits included) are ticked, and the screen shows
that window. The wind charts are shown and attached for B737 flights only. Tick or
untick as needed. Each ticked chart is
attached as a US Letter page, scaled to fit, with a source line. While the AWC is
publishing a new run the charts can come from two runs; a note says so and **Refresh**
gets the full set later.

### NOTAM screening

The NOTAM pages of the brief are checked for the **departure, destination, alternate and
en-route alternate (ETP) airports** of every leg. A NOTAM is added to Additional
information, in point form, when it reports one of these and is in force between **one
hour before departure and one hour after arrival** (for an alternate, plus the flying
time to it):

- the aerodrome closed, or its control tower closed
- a runway closed
- a navigation aid out of service: VOR, DME, TACAN, NDB, locator, ILS, localizer or glide
  path reported as U/S, unusable, withdrawn, unreliable or not to be used
- an instrument approach procedure not available, suspended or not authorised

Each item gives the airport, the period and the NOTAM text, with the NOTAM number for
reference:

```
• KIAD 21SEP26 1000Z-01NOV26 0359Z: RWY 01C/19C CLSD [A5101/26]
• KPHL 22SEP26 0200Z-26SEP26 1100Z DLY 0200-1100: RWY 17/35 CLSD [A5052/26]
• TJSJ 23SEP26 1858Z-UFN: SJU NAV VORTAC U/S [09/266]
```

A NOTAM with a plain daily schedule (`0300 - 1000`, `DLY 2200-1000`) only counts when the
flight falls inside the daily period. Schedules given by weekday or date are not
interpreted: such a NOTAM is listed for its whole validity, with the schedule in its text.

Not listed: taxiway, apron and stand closures, lighting and visual aids (PAPI, approach
and runway lights), signs and markings, obstacles, marker beacons, ATC frequencies, and
procedure amendments that only mention a navaid. Runway works without a closure (`WIP`)
are not listed either. Texts longer than 240 characters are cut; the number points to the
full NOTAM. Delete or edit any line in the review before generating.

This screening is an aid for the dispatcher and does not replace reading the NOTAMs. If a
leg's times or the NOTAM pages cannot be read, a warning is shown instead of an empty list.

## Limits

- TAFs and SIGMETs are taken from the flight plan brief, which is what the crew receives.
  They can differ from weather pulled from other sources after the brief was generated.
- NOTAMs are those in the brief; anything issued after the brief was generated is not seen.
- MEL book pages are found by their item numbers. Check the attached pages against the
  MEL items, in particular when a note says a parent item was used.
- Wind charts need an internet connection to aviationweather.gov at the time of use.

## Development

Python 3.10+ with the packages in `requirements.txt` (`pip install -r requirements.txt`).

```
python -m unittest -v
```

`tests/test_briefsheet.py` builds a small flight plan brief and MEL workbook in memory, so
it runs anywhere (with a small MEL book and wind chart). Checks against real flight plans
and MEL books (`tests/test_local_examples.py`) need operational data and are kept out of
the repository by `.gitignore`, together with all PDF and Excel files.

| Path | Purpose |
|---|---|
| `streamlit_app.py` | Web app |
| `Briefing Sheet Generator.pyw`, `briefsheet/gui.py` | Desktop window |
| `briefsheet/cli.py` | Command line |
| `briefsheet/flightplan.py` | Reads the flight plan brief |
| `briefsheet/mel.py` | Reads the MEL workbooks |
| `briefsheet/melbook.py` | Finds the pages of an MEL item in the MEL book |
| `briefsheet/windcharts.py` | Downloads the wind charts, makes the Letter pages |
| `briefsheet/notams.py` | Reads the NOTAM pages and picks the closures and outages |
| `briefsheet/builder.py` | Fills in the fields |
| `briefsheet/render.py` | Draws the SOC001 form |
| `briefsheet/output.py` | Output files, attachments, flight plan + sheet package |
