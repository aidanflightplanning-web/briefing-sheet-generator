# Flight Crew Briefing Sheet Generator

Builds the Caribbean Airlines **Flight Crew Briefing Sheet (form SOC001)** from the
flight plan brief PDF and the monthly MEL status workbooks. The PDF reproduces the
Word form exactly: same layout, fonts, logo, "Wheels UP!" watermark and footer. Long
content continues on a second page, as in the Word form.

Only the **gate position** and the **passenger load of each leg** are entered by hand.
Everything else comes from the flight plan and the MEL sheet.

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
| Additional information | Dispatcher remarks (RMKS) of each leg, except RAIM CHECK VALIDATED. Multi-leg remarks end with `EX <station>`. Several remarks are shown as bullets, none as `-`. |
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

## Limits

- TAFs and SIGMETs are taken from the flight plan brief, which is what the crew receives.
  They can differ from weather pulled from other sources after the brief was generated.
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
| `briefsheet/builder.py` | Fills in the fields |
| `briefsheet/render.py` | Draws the SOC001 form |
| `briefsheet/output.py` | Output files, flight plan + sheet package |
