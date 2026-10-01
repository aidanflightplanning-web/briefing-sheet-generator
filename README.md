# Flight Crew Briefing Sheet Generator

Builds the Caribbean Airlines **Flight Crew Briefing Sheet (form SOC001)** from the
flight plan brief PDF and the monthly MEL status workbooks. The PDF reproduces the
Word form exactly: same layout, fonts, logo, "Wheels UP!" watermark and footer. Long
content continues on a second page, as in the Word form.

Only the **gate position** and the **passenger load of each leg** are entered by hand.
Everything else comes from the flight plan and the MEL sheet. B737 and ATR flight plans
are supported, including packages that cover a whole rotation (several legs).

It runs as a **web app** (Streamlit) or as a **Windows desktop app**. No flight plans or
MEL workbooks are stored in this repository or by the web app.

## Web app

1. Upload the **MEL sheets** (B737 and/or ATR workbooks).
2. Upload the **flight plan brief** (PDF). All fields are filled in.
3. Enter the **gate** and the **PAX load (C/Y)** for each leg.
4. Check the review section (every field can be edited), then **Generate briefing sheet**.
5. Download the briefing sheet, or the flight plan with the sheet appended at the end.

Uploaded files are processed in memory for the browser session and are not saved.

**Run locally:** `streamlit run streamlit_app.py`

**Deploy on Streamlit Community Cloud:** sign in at [share.streamlit.io](https://share.streamlit.io)
with GitHub, choose **Create app**, pick this repository, branch `main` and main file
`streamlit_app.py`, then **Deploy**. `packages.txt` installs Liberation Sans and Carlito,
which have the same character widths as Arial and Calibri, so the layout matches the form.

## Desktop app (Windows)

Double-click `Briefing Sheet Generator.pyw` (or drop a flight plan PDF on it). The MEL
sheets you attach are remembered. Two files are saved next to the flight plan:
`<flight plan>_BRIEFSHEET.pdf` and `<flight plan>_WITH_BRIEFSHEET.pdf` (a briefing sheet
already attached to the flight plan is replaced).

`build_exe.bat` builds `dist\Briefing Sheet Generator.exe` (about 30 MB, single file) that
runs on PCs without Python. It needs PyInstaller.

**Command line** (asks only for the gate and pax loads):

```
briefsheet.bat FLIGHTPLAN.pdf --mel "B737 MEL SHEET.xlsx" --mel "ATR MEL SHEET.xlsx" --save-mel
briefsheet.bat FLIGHTPLAN.pdf --gate 13 --pax 2/11 --pax 15/144
```

Other options: `--cargo`, `--route`, `--mel-sheet "26TH SEPTEMBER 2026"`, `--out FOLDER`, `--no-append`.
Desktop settings are stored in `%APPDATA%\BriefingSheetGenerator\settings.json`.

## Where each field comes from

| Field | Source |
|---|---|
| Aircraft reg 9Y- | Flight line (`B737 /GUY`) |
| Flight # BW | Flight numbers of the legs: `476-477`, `418`. Flight numbers below 100 are written with four digits (`0005`). |
| Gate position / Pax load | Entered by hand. Pax loads are separated by ` / ` per leg. |
| M.E.L items | Open items for the aircraft on the MEL sheet for the briefing date (`MEL#  DESCRIPTION`), or `NIL REPORTED`. |
| Cargo / Route | `TBA` / `STANDARD COMPANY ROUTINGS` (can be edited). |
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
- MEL manual pages are not added to the sheet.

## Development

Python 3.10+ with the packages in `requirements.txt` (`pip install -r requirements.txt`).

```
python -m unittest -v
```

`tests/test_briefsheet.py` builds a small flight plan brief and MEL workbook in memory, so
it runs anywhere. Checks against real flight plans (`tests/test_local_examples.py`) need
operational data and are kept out of the repository by `.gitignore`, together with all
PDF and Excel files.

| Path | Purpose |
|---|---|
| `streamlit_app.py` | Web app |
| `Briefing Sheet Generator.pyw`, `briefsheet/gui.py` | Desktop window |
| `briefsheet/cli.py` | Command line |
| `briefsheet/flightplan.py` | Reads the flight plan brief |
| `briefsheet/mel.py` | Reads the MEL workbooks |
| `briefsheet/notams.py` | Reads the NOTAM pages and picks the closures and outages |
| `briefsheet/builder.py` | Fills in the fields |
| `briefsheet/render.py` | Draws the SOC001 form |
| `briefsheet/output.py` | Output files, flight plan + sheet package |
