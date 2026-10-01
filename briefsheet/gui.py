"""Window for generating the Flight Crew Briefing Sheet.

1. Attach the MEL sheets (remembered between sessions).
2. Open the flight plan PDF - every field is filled in from it and the MEL sheet.
3. Enter the gate position and the passenger load of each leg.
4. Review/edit the filled-in fields if needed, then Generate.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import mel as melmod
from .builder import CHECKLIST_ITEMS, BriefingData, briefing_date, build_briefing, mel_text
from .flightplan import FlightPlan, parse_flight_plan
from .notams import flight_remarks
from .output import OutputError, write_outputs
from .render import asset
from .settings import Settings

REVIEW_FIELDS = [  # BriefingData attribute, label, minimum lines
    ("aircraft_reg", "AIRCRAFT REG 9Y-", 1),
    ("flight_no", "FLIGHT # BW", 1),
    ("mel_items", "M.E.L ITEMS", 2),
    ("cargo", "CARGO", 1),
    ("route", "ROUTE", 1),
    ("wx_departure", "WX @ DEPARTURE", 3),
    ("wx_destination", "WX @ DESTINATION", 3),
    ("wx_alternate", "WX @ ALTERNATE", 3),
    ("sigmet_info", "SIGMET INFO", 1),
    ("enroute_airport", "ENROUTE AIRPORT", 1),
    ("flight_plan_fuel", "FLIGHT PLAN FUEL", 1),
    ("alt_filed", "ALT FILED", 1),
    ("additional_info", "ADDITIONAL INFO", 1),
    ("dispatcher", "DISPATCHER", 1),
    ("date", "DATE", 1),
]
SINGLE_LINE = {"aircraft_reg", "flight_no", "cargo", "enroute_airport", "flight_plan_fuel", "alt_filed",
               "dispatcher", "date"}
OK, WARN, ERROR, MUTED = "#1b6e20", "#a15c00", "#b00020", "#555555"


class App(tk.Tk):
    def __init__(self, flight_plan: str | None = None):
        super().__init__()
        self.title("Flight Crew Briefing Sheet Generator")
        self.geometry("1220x820")
        self.minsize(1000, 640)
        try:
            self.iconbitmap(default=str(asset("icon.ico")))
        except tk.TclError:  # .ico icons are Windows-only
            pass
        self.settings = Settings.load()
        self.fp: FlightPlan | None = None
        self.fp_path: Path | None = None
        self.workbooks: list[melmod.MelWorkbook] = []
        self.lookups: list[melmod.MelLookup] = []
        self.pax_vars: list[tk.StringVar] = []
        self.pax_entries: list[ttk.Entry] = []
        self.fields: dict[str, tk.Text] = {}
        self.checks = {name: tk.BooleanVar(value=False) for name in CHECKLIST_ITEMS}
        self.last_written: list[Path] = []

        self._style()
        self._build()
        self._reload_mel()
        self.bind_all("<Control-o>", lambda e: self.open_flight_plan())
        self.bind_all("<Control-g>", lambda e: self.generate())
        self.bind_all("<MouseWheel>", self._on_wheel)
        if flight_plan:
            self.after(150, lambda: self.load_flight_plan(flight_plan))

    # layout -------------------------------------------------------------------
    def _style(self):
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Step.TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=(10, 8))
        style.configure("Field.TLabel", font=("Segoe UI", 9, "bold"))

    def _build(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        left = ttk.Frame(root, width=390)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        left.columnconfigure(0, weight=1)

        # 1. MEL sheets
        box = ttk.LabelFrame(left, text=" 1  MEL sheets ", style="Step.TLabelframe", padding=8)
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.mel_list = tk.Listbox(box, height=4, activestyle="none", font=("Segoe UI", 9))
        self.mel_list.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Button(box, text="Attach MEL sheet(s)…", command=self.attach_mel).grid(
            row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(box, text="Remove", command=self.remove_mel).grid(row=1, column=1, sticky="e", pady=(6, 0))

        # 2. Flight plan
        box = ttk.LabelFrame(left, text=" 2  Flight plan ", style="Step.TLabelframe", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        box.columnconfigure(1, weight=1)
        ttk.Button(box, text="Open flight plan (PDF)…", command=self.open_flight_plan).grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.fp_label = ttk.Label(box, text="No flight plan loaded", foreground=MUTED, wraplength=360,
                                  justify="left")
        self.fp_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.mel_status = ttk.Label(box, text="", wraplength=360, justify="left")
        self.mel_status.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(box, text="MEL sheet used:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.sheet_var = tk.StringVar()
        self.sheet_combo = ttk.Combobox(box, textvariable=self.sheet_var, state="disabled", width=30)
        self.sheet_combo.grid(row=3, column=1, sticky="ew", pady=(6, 0), padx=(6, 0))
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda e: self._update_mel(self.sheet_var.get()))
        self.sheet_combo.bind("<MouseWheel>", lambda e: "break")  # don't change the sheet while scrolling

        # 3. Prompted values
        box = ttk.LabelFrame(left, text=" 3  Not on the flight plan ", style="Step.TLabelframe", padding=8)
        box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Gate position").grid(row=0, column=0, sticky="w")
        self.gate_var = tk.StringVar()
        self.gate_entry = ttk.Entry(box, textvariable=self.gate_var, width=18, font=("Segoe UI", 10))
        self.gate_entry.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(box, text="PAX load (C/Y)").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.pax_frame = ttk.Frame(box)
        self.pax_frame.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(self.pax_frame, text="Open a flight plan first", foreground=MUTED).grid(row=0, column=0)

        # Output
        box = ttk.Frame(left, padding=(0, 10, 0, 0))
        box.grid(row=3, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)
        self.append_var = tk.BooleanVar(value=self.settings.append_to_flight_plan)
        self.open_var = tk.BooleanVar(value=self.settings.open_when_done)
        ttk.Checkbutton(box, text="Also save the flight plan with the sheet appended",
                        variable=self.append_var).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(box, text="Open the briefing sheet when done", variable=self.open_var).grid(
            row=1, column=0, sticky="w")
        ttk.Button(box, text="Generate briefing sheet", style="Big.TButton", command=self.generate).grid(
            row=2, column=0, sticky="ew", pady=(10, 0))
        self.status = ttk.Label(box, text="", wraplength=370, justify="left")
        self.status.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.folder_button = ttk.Button(box, text="Show in folder", command=self.show_in_folder)

        # 4. Review
        review = ttk.LabelFrame(root, text=" 4  Review – filled in from the flight plan and MEL sheet (editable) ",
                                style="Step.TLabelframe", padding=(8, 4))
        review.grid(row=0, column=1, sticky="nsew")
        review.rowconfigure(0, weight=1)
        review.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(review, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(review, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        inner = ttk.Frame(self.canvas, padding=(2, 4, 12, 4))
        inner.columnconfigure(1, weight=1)
        window = self.canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))

        ttk.Label(inner, text="DOCUMENT CHECKLIST", style="Field.TLabel").grid(row=0, column=0, sticky="nw",
                                                                             pady=4)
        checks = ttk.Frame(inner)
        checks.grid(row=0, column=1, sticky="w", pady=4)
        for i, name in enumerate(CHECKLIST_ITEMS):
            ttk.Checkbutton(checks, text=name, variable=self.checks[name]).grid(row=0, column=i, padx=(0, 8))
        for i, (key, label, lines) in enumerate(REVIEW_FIELDS, start=1):
            ttk.Label(inner, text=label, style="Field.TLabel").grid(row=i, column=0, sticky="nw", pady=4,
                                                                  padx=(0, 10))
            text = tk.Text(inner, height=lines, wrap="none", font=("Consolas", 10), undo=True,
                           borderwidth=1, relief="solid", padx=4, pady=2)
            text.grid(row=i, column=1, sticky="ew", pady=4)
            text.bind("<MouseWheel>", self._on_wheel)
            if key in SINGLE_LINE:
                text.bind("<Return>", lambda e: "break")
            text.bind("<<Modified>>", self._autosize)
            self.fields[key] = text
            text._min_lines = lines  # noqa: SLF001 - used by _autosize

    # helpers ------------------------------------------------------------------
    def _on_wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self.canvas:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
            widget = widget.master
        return None

    def _autosize(self, event):
        text = event.widget
        text.edit_modified(False)
        lines = int(text.index("end-1c").split(".")[0])
        text.configure(height=max(text._min_lines, min(lines, 18)))

    def _get(self, key: str) -> str:
        return self.fields[key].get("1.0", "end-1c").strip("\n")

    def _set(self, key: str, value: str):
        text = self.fields[key]
        text.delete("1.0", "end")
        text.insert("1.0", value)
        text.edit_modified(True)

    def _set_status(self, text: str, color: str = MUTED):
        self.status.configure(text=text, foreground=color)

    # MEL sheets ---------------------------------------------------------------
    def attach_mel(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="Attach MEL sheet(s)",
            filetypes=[("Excel workbooks", "*.xlsx *.xlsm"), ("All files", "*.*")],
            initialdir=self.settings.last_folder or None)
        added = False
        for p in paths:
            p = str(Path(p))
            if p not in self.settings.mel_paths:
                self.settings.mel_paths.append(p)
                added = True
        if added:
            self.settings.save()
            self._reload_mel()

    def remove_mel(self):
        for index in reversed(self.mel_list.curselection()):
            if index < len(self.settings.mel_paths):
                del self.settings.mel_paths[index]
        self.settings.save()
        self._reload_mel()

    def _reload_mel(self):
        self.config(cursor="watch")
        self.update_idletasks()
        self.workbooks = []
        self.mel_list.delete(0, "end")
        for path in self.settings.mel_paths:
            try:
                wb = melmod.load_workbook(path)
            except Exception as exc:
                self.mel_list.insert("end", f"✗ {Path(path).name}  – cannot read ({exc.__class__.__name__})")
                self.mel_list.itemconfigure("end", foreground=ERROR)
                continue
            self.workbooks.append(wb)
            dated = [s.date for s in wb.sheets if s.date]
            span = f"{min(dated):%d}–{max(dated):%d %b %Y}" if dated else f"{len(wb.sheets)} sheets"
            self.mel_list.insert("end", f"✓ {wb.fleet or 'MEL'}  {span}  –  {wb.path.name}")
        if not self.settings.mel_paths:
            self.mel_list.insert("end", "No MEL sheets attached")
            self.mel_list.itemconfigure(0, foreground=MUTED)
        self.config(cursor="")
        if self.fp:
            self._update_mel()

    def _update_mel(self, sheet_name: str | None = None):
        fp = self.fp
        day = briefing_date(fp, self.settings.utc_offset_hours)
        self.lookups = [melmod.lookup(self.workbooks, reg, day, sheet_name) for reg in fp.registrations]
        self._set("mel_items", mel_text(self.lookups))
        if not self.workbooks:
            self.mel_status.configure(text="Attach the MEL sheets (step 1) to fill in the M.E.L items.",
                                      foreground=ERROR)
        else:
            lines, color = [], OK
            for lk in self.lookups:
                if not lk.found:
                    lines.append(f"9Y-{lk.registration} is not in the attached MEL sheets – "
                                 "enter the M.E.L items in the review panel.")
                    color = ERROR
                    continue
                count = len(lk.items)
                result = f"{count} open item{'s' if count != 1 else ''}" if count else "NIL REPORTED"
                lines.append(f"MEL 9Y-{lk.registration}: {result}\nfrom {lk.source}")
                if not lk.exact_date and not sheet_name:
                    lines.append(f"No sheet for {day:%d/%m/%y} – the latest earlier sheet was used.")
                    color = WARN if color == OK else color
            self.mel_status.configure(text="\n".join(lines), foreground=color)
        first = next((lk for lk in self.lookups if lk.found), None)
        if first:
            self.sheet_combo.configure(values=[s.name for s in first.workbook.sheets], state="readonly")
            self.sheet_var.set(first.sheet.name)
        else:
            self.sheet_combo.configure(values=[], state="disabled")
            self.sheet_var.set("")

    # flight plan --------------------------------------------------------------
    def open_flight_plan(self):
        path = filedialog.askopenfilename(parent=self, title="Open flight plan",
                                          filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
                                          initialdir=self.settings.last_folder or None)
        if path:
            self.load_flight_plan(path)

    def load_flight_plan(self, path: str):
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            fp = parse_flight_plan(path)
        except Exception as exc:
            self.config(cursor="")
            messagebox.showerror("Flight plan", f"Could not read {Path(path).name}:\n\n{exc}", parent=self)
            return
        self.config(cursor="")
        self.fp, self.fp_path = fp, Path(path)
        self.settings.last_folder = str(self.fp_path.parent)
        self.settings.save()

        day = briefing_date(fp, self.settings.utc_offset_hours)
        legs = "\n".join(f"{leg.flight}  {leg.dep_icao}–{leg.dest_icao}  {leg.date_text}  9Y-{leg.registration}"
                         for leg in fp.legs)
        warnings = "".join(f"\n⚠ {w}" for w in fp.warnings)
        notams = len(flight_remarks(fp))
        self.fp_label.configure(
            text=f"{self.fp_path.name}\n{legs}\nBriefing date {day:%d/%m/%y}\n"
                 f"NOTAMs: {notams} closure/outage item{'' if notams == 1 else 's'} added to the remarks{warnings}",
            foreground=WARN if fp.warnings else "black")

        for child in self.pax_frame.winfo_children():
            child.destroy()
        self.pax_vars, self.pax_entries = [], []
        for i, leg in enumerate(fp.legs):
            ttk.Label(self.pax_frame, text=f"{leg.flight} {leg.sector}").grid(row=i, column=0, sticky="w", pady=2)
            var = tk.StringVar()
            entry = ttk.Entry(self.pax_frame, textvariable=var, width=12, font=("Segoe UI", 10))
            entry.grid(row=i, column=1, sticky="w", padx=(8, 0), pady=2)
            self.pax_vars.append(var)
            self.pax_entries.append(entry)
        chain = [self.gate_entry] + self.pax_entries
        for widget, nxt in zip(chain, chain[1:]):
            widget.bind("<Return>", lambda e, n=nxt: n.focus_set())
        chain[-1].bind("<Return>", lambda e: self.generate())

        data = build_briefing(fp, utc_offset_hours=self.settings.utc_offset_hours,
                              dispatcher=self.settings.dispatcher)
        for key, _, _ in REVIEW_FIELDS:
            self._set(key, getattr(data, key))
        for name, var in self.checks.items():
            var.set(data.checklist.get(name, False))
        self._update_mel()
        self.gate_var.set("")
        self.folder_button.grid_remove()
        self._set_status("Enter the gate position and passenger loads, then Generate.")
        self.canvas.yview_moveto(0)
        self.gate_entry.focus_set()

    # generate -----------------------------------------------------------------
    def _collect(self) -> BriefingData:
        data = BriefingData()
        for key, _, _ in REVIEW_FIELDS:
            value = self._get(key)
            setattr(data, key, value.upper() if key not in ("wx_departure", "wx_destination", "wx_alternate",
                                                             "sigmet_info") else value)
        data.checklist = {name: var.get() for name, var in self.checks.items()}
        return data

    def generate(self):
        if not self.fp:
            messagebox.showinfo("Briefing sheet", "Open a flight plan first (step 2).", parent=self)
            return
        if not self.workbooks:
            messagebox.showwarning("MEL sheets", "Attach the MEL sheets first (step 1).", parent=self)
            return
        gate = self.gate_var.get().strip().upper()
        pax = [var.get().strip().upper() for var in self.pax_vars]
        missing = (["gate position"] if not gate else []) + (["passenger load"] if not all(pax) else [])
        if missing and not messagebox.askyesno(
                "Missing information", f"The {' and '.join(missing)} is blank.\n\nPrint TBA instead?", parent=self):
            (self.gate_entry if not gate else self.pax_entries[pax.index("")]).focus_set()
            return
        unchecked = [lk.registration for lk in self.lookups if not lk.found]
        if unchecked and not self._get("mel_items").strip() and not messagebox.askyesno(
                "M.E.L items", f"9Y-{', 9Y-'.join(unchecked)} was not found in the attached MEL sheets and the "
                               "M.E.L ITEMS box is empty.\n\nGenerate anyway?", parent=self):
            return

        data = self._collect()
        data.gate = gate or "TBA"
        data.pax_load = " / ".join(p or "TBA" for p in pax)
        self.settings.append_to_flight_plan = self.append_var.get()
        self.settings.open_when_done = self.open_var.get()
        self.settings.save()
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            written = write_outputs(self.fp_path, data, self.settings.output_dir or None,
                                    append=self.append_var.get())
        except OutputError as exc:
            messagebox.showerror("Briefing sheet", str(exc), parent=self)
            return
        except Exception:
            messagebox.showerror("Briefing sheet", f"Could not create the briefing sheet:\n\n{traceback.format_exc()}",
                                 parent=self)
            return
        finally:
            self.config(cursor="")
        self.last_written = written
        self._set_status("Saved:\n" + "\n".join(p.name for p in written) + f"\nin {written[0].parent}", OK)
        self.folder_button.grid(row=4, column=0, sticky="w", pady=(4, 0))
        if self.open_var.get():
            self._open(written[0])

    def _open(self, path: Path):
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # noqa: S606 - opens the PDF in the default viewer
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except OSError as exc:
            messagebox.showwarning("Open", f"Saved, but could not open the PDF:\n{exc}", parent=self)

    def show_in_folder(self):
        if not self.last_written:
            return
        path = self.last_written[0]
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            self._open(path.parent)


def _dpi_aware():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main(flight_plan: str | None = None) -> int:
    _dpi_aware()
    App(flight_plan).mainloop()
    return 0
