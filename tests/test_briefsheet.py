"""Tests with synthetic data: a small flight plan brief and MEL workbook are built in memory.

Run from the project folder:  py -m unittest -v
Checks against real example flight plans live in test_local_examples.py (kept out of the repository).
"""

import io
import unittest
from datetime import date, datetime

from briefsheet import flightplan, mel, render
from briefsheet.builder import BriefingData, build_briefing, briefing_date
from briefsheet.output import output_names, package_pdf
from briefsheet.pdftext import extract_pages
from briefsheet.taf import format_taf


def make_pdf(pages: list[list[str]], header: bool = True) -> bytes:
    """A PDF with one text line per list item, laid out like the brief."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    for number, lines in enumerate(pages, start=1):
        if header:
            lines = [f"CARIBBEAN AIRLINES LIMITED BRIEF PAGE {number} OF {len(pages)}", *lines,
                     f"PAGE {number} OF {len(pages)}"]
        c.setFont("Courier", 9)
        for i, line in enumerate(lines):
            c.drawString(40, 750 - 11 * i, line)
        c.showPage()
    c.save()
    return buffer.getvalue()


BRIEF = [
    ["RMKS", "RAIM CHECK VALIDATED", "XFUE DUE EN RTE WX",
     "FLTNO /DATE ORIG/DEST ALTN EQUIP/REG PYLD FUEL RAMP B/O LDWT",
     "BWA123 /01OCT POS /BGI GND B737 /ABC 0100 0070 0600 0020 0580",
     "TOTAL FUEL REQUIRED I 02.10 006123",
     "EQUAL TIME POINT / ENGINEOUT DEPRESSURIZATION TIME . . . FOB . . .",
     "TTPP TO TGPY POSN N11 00.0 W061 00.0 GWT 060000KGS DDALT 10000FT",
     "TGPY TO TBPB POSN N12 00.0 W060 00.0 GWT 059000KGS DDALT 10000FT",
     "(FPL-BWA123-IS", "-B38M/M-SDE3FGHIRWYZ/LB1", "-TTPP1200", "-N0450F280 DCT POS UR515 BGI DCT",
     "-TBPB0040 TGPY TTCP", "-PBN/A1B1C1D1S2 DOF/261001 REG/9YABC)", "DISPATCHER - JANE DOE"],
    ["DEPARTURE", "METAR TTPP 011100Z 09010KT 9999 FEW016 28/24 Q1012",
     "TAF TTPP 011000Z 0112/0212 09010KT 9999 SCT018 PROB30 TEMPO", "0114/0118 4000 SHRA BKN014",
     "ARRIVAL", "TAF TBPB 011000Z 0112/0212 10012KT 9999 SCT020",
     "OTHER", "TAF TGPY 011000Z 0112/0212 10008KT 9999 FEW018 BECMG 0200/0202 VRB03KT",
     "OTHER", "TAF TTCP 011000Z 0112/0212 09010KT 9999 FEW018"],
    ["TTPP (PIARCO INTL) - TBPB (GRANTLEY ADAMS INTL)",
     "Briefing generated: 01OCT26 0230 (All times in UTC unless otherwise stated) FLT BWA0123",
     "NTM No: Eff from:Eff to: Description:", "PIARCO INTL (TTPP/POS), TRINIDAD TOBAGO PIARCO FIR (TTZP)"],
    ["TTZP SIGMET 1 VALID 010100/010500 TTPP-", "TTZP PIARCO FIR EMBD TS OBS AT 0050Z WI N1100 W06230",
     "TOP FL400 MOV W 10KT NC"],
]


class TafLayout(unittest.TestCase):
    def test_change_groups(self):
        raw = ("TAF TTPP 232200Z 2400/2424 09003KT 9999 FEW010CB SCT015 TEMPO 2402/2409 5000 SHRA BKN015 "
               "BECMG 2411/2413 11010KT PROB30 TEMPO 2415/2418 3000 TSRA SCT010CB")
        self.assertEqual(format_taf(raw), [
            "TAF TTPP 232200Z 2400/2424 09003KT 9999 FEW010CB SCT015",
            "    TEMPO 2402/2409 5000 SHRA BKN015",
            "  BECMG 2411/2413 11010KT",
            "  PROB30",
            "    TEMPO 2415/2418 3000 TSRA SCT010CB",
        ])

    def test_us_style_from_and_prob_with_time(self):
        raw = ("TAF KIAD 260541Z 2606/2712 32009G16KT P6SM SCT250 FM261400 35016G26KT P6SM SCT130 BKN250 "
               "PROB30 2709/2712 5SM -RA BKN035")
        self.assertEqual(format_taf(raw), [
            "TAF KIAD 260541Z 2606/2712 32009G16KT P6SM SCT250",
            "  FM261400 35016G26KT P6SM SCT130 BKN250",
            "  PROB30 2709/2712 5SM -RA BKN035",
        ])

    def test_remarks_stay_inline(self):
        raw = "TAF CYYZ 232340Z 2400/2506 09012KT P6SM FEW260 BECMG 2422/2424 VRB03KT RMK NXT FCST BY 240300Z"
        self.assertEqual(format_taf(raw)[-1], "  BECMG 2422/2424 VRB03KT RMK NXT FCST BY 240300Z")


class ParserEdgeCases(unittest.TestCase):
    def test_sigmet_directly_after_the_weather(self):
        lines = ["DEPARTURE", "METAR TTPP 240200Z 10004KT 9999 FEW016 28/25 Q1012 NOSIG",
                 "TAF TTPP 232200Z 2400/2424 09003KT 9999 FEW010CB", "SCT015",
                 "TJZS SIGMET GOLF 2 VALID 240205/240605 KKCI-", "SAN JUAN OCEANIC FIR FRQ TS"]
        tafs, _ = flightplan._parse_weather(lines)
        self.assertEqual(tafs["TTPP"], "TAF TTPP 232200Z 2400/2424 09003KT 9999 FEW010CB SCT015")
        self.assertEqual(flightplan._parse_sigmets(lines),
                         [["TJZS SIGMET GOLF 2 VALID 240205/240605 KKCI-", "SAN JUAN OCEANIC FIR FRQ TS"]])

    def test_theme_font_colour_is_not_treated_as_green(self):
        class Color:
            rgb = "Values must be of type <class 'str'>"

        class Font:
            color = Color()

        class Cell:
            font = Font()

        self.assertFalse(mel._is_green(Cell()))


class SyntheticBrief(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pdf = make_pdf(BRIEF)
        cls.fp = flightplan.parse_flight_plan(cls.pdf, name="BWA012301TTPP.pdf")
        cls.data = build_briefing(cls.fp, gate="5", pax=["3/120"])

    def test_leg(self):
        (leg,) = self.fp.legs
        self.assertEqual((leg.flight, leg.orig, leg.dest, leg.registration), ("BWA123", "POS", "BGI", "ABC"))
        self.assertEqual((leg.dep_icao, leg.dest_icao, leg.alternates), ("TTPP", "TBPB", ["TGPY", "TTCP"]))
        self.assertEqual(leg.total_fuel, 6123)
        self.assertEqual(self.fp.path.name, "BWA012301TTPP.pdf")
        self.assertEqual(self.fp.briefing_generated, datetime(2026, 10, 1, 2, 30))

    def test_briefing_fields(self):
        d = self.data
        self.assertEqual((d.aircraft_reg, d.flight_no, d.gate, d.pax_load), ("ABC", "123", "5", "3/120"))
        self.assertEqual(d.flight_plan_fuel, "6200KG")
        self.assertEqual(d.alt_filed, "TGPY & TTCP")
        self.assertEqual(d.wx_departure.splitlines(), [
            "TAF TTPP 011000Z 0112/0212 09010KT 9999 SCT018", "  PROB30", "    TEMPO 0114/0118 4000 SHRA BKN014"])
        self.assertEqual(d.wx_destination, "TAF TBPB 011000Z 0112/0212 10012KT 9999 SCT020")
        self.assertEqual(d.wx_alternate.splitlines()[0], "TAF TGPY 011000Z 0112/0212 10008KT 9999 FEW018")
        self.assertIn("TAF TTCP", d.wx_alternate)
        self.assertEqual(d.sigmet_info.splitlines()[0], "TTZP SIGMET 1 VALID 010100/010500 TTPP-")
        self.assertEqual(d.sigmet_info.splitlines()[-1], " TOP FL400 MOV W 10KT NC")
        self.assertEqual(d.enroute_airport, "TGPY")
        self.assertEqual(d.additional_info, "XFUE DUE EN RTE WX")
        self.assertEqual(d.dispatcher, "JANE DOE")
        self.assertEqual(d.date, "30/09/26")   # 0230Z on 1 Oct is still 30 Sep in Trinidad

    def test_package_replaces_an_attached_sheet(self):
        old_sheet = make_pdf([["Flight Crew Briefing Sheet", "FORM NBR SOC001"]], header=False)
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        for source in (self.pdf, old_sheet):
            for page in PdfReader(io.BytesIO(source)).pages:
                writer.add_page(page)
        with_old = io.BytesIO()
        writer.write(with_old)
        new_sheet = io.BytesIO()
        render.render_briefing(self.data, new_sheet)
        texts = extract_pages(package_pdf(with_old.getvalue(), new_sheet.getvalue()))
        self.assertEqual(len(texts), len(BRIEF) + 1)
        self.assertIn("GATE POSITION", texts[-1])
        self.assertEqual(output_names("BWA012301TTPP_WITH_BRIEFSHEET.pdf"),
                         ("BWA012301TTPP_BRIEFSHEET.pdf", "BWA012301TTPP_WITH_BRIEFSHEET.pdf"))


class SyntheticMel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import openpyxl
        from openpyxl.styles import Font

        book = openpyxl.Workbook()
        headers = ["", "MEL", "CAT", "ST", "EXP", "LP/SNG#/DWC", "AUTH", "DESCRIPTION", "REP. MAINT ACTION",
                   "PARTS", "REMARKS", "TROUBLESHOOTING", "DEFECT RECTIFICATION", "OPS", "CLOSURE #", "DATE"]
        for ws, day, open_item in ((book.active, "1ST OCTOBER 2026", ("21-00-01", "PACK TEMP LIGHT INOP")),
                                   (book.create_sheet(), "30TH SEPTEMBER 2026", ("30-11-01", "WING ANTI-ICE INOP"))):
            ws.title = day
            ws["A1"] = f"B737 MEL STAT/CDL STATUS  {day} UPDATE AT 1500 HRS"
            for col, text in enumerate(headers, start=1):
                ws.cell(4, col, text)
            ws["A5"], ws["B5"], ws["C5"], ws["H5"] = "ABC", open_item[0], "C", open_item[1]
            ws["B6"], ws["H6"], ws["O6"], ws["P6"] = "25-00-01", "TRAY TABLE 3A", "C01/XX/261001", datetime(2026, 10, 1)
            ws["B7"], ws["H7"] = "33-11-01", "LOGO LIGHT INOP"
            ws["B7"].font = Font(color="FF00B050")          # cleared: green row, closure # missing
            ws.merge_cells("A5:A7")
            ws["A8"], ws["G9"], ws["H9"] = "DEF", "NO", "ROBBERIES"
            ws["G11"] = "LEGEND"
            ws["A12"], ws["B12"], ws["H12"] = "ABC", "99-99-99", "NOT AN ITEM"
        buffer = io.BytesIO()
        book.save(buffer)
        cls.books = [mel.load_workbook(buffer.getvalue(), name="OCTOBER 2026 B737 MEL SHEET.xlsx")]

    def items(self, reg, day):
        return [i.briefing_text for i in mel.lookup(self.books, reg, day).items]

    def test_only_open_items_of_the_day(self):
        self.assertEqual(self.books[0].fleet, "B737")
        self.assertEqual(self.items("ABC", date(2026, 10, 1)), ["21-00-01  PACK TEMP LIGHT INOP"])
        self.assertEqual(self.items("ABC", date(2026, 9, 30)), ["30-11-01  WING ANTI-ICE INOP"])
        self.assertEqual(self.items("DEF", date(2026, 10, 1)), [])

    def test_missing_day_and_unknown_aircraft(self):
        later = mel.lookup(self.books, "ABC", date(2026, 10, 5))
        self.assertEqual((later.sheet.name, later.exact_date), ("1ST OCTOBER 2026", False))
        self.assertFalse(mel.lookup(self.books, "XYZ", date(2026, 10, 1)).found)
        chosen = mel.lookup(self.books, "ABC", date(2026, 10, 1), "30TH SEPTEMBER 2026")
        self.assertEqual(chosen.sheet.name, "30TH SEPTEMBER 2026")


def template_data() -> BriefingData:
    """The values on the Word template (Briefsheet.pdf)."""
    return BriefingData(
        aircraft_reg="GUY", flight_no="476-477", gate="13", pax_load="2/11 / 15/144", mel_items="NIL REPORTED",
        wx_departure="TAF TTPP 260400Z 2606/2706 00000KT 9999 FEW016\n  BECMG 2612/2614 11008KT 9999 SCT018\n"
                     "  PROB40\n    TEMPO 2614/2620 11010G20KT 3000 TSRA FEW010CB BKN015\n"
                     "  BECMG 2700/2702 00000KT 9999 FEW016 SCT038",
        wx_destination="TAF AMD MUHA 260854Z 2608/2706 VRB05KT 9000 FEW030\n    TEMPO 2609/2611 3000 BR\n"
                       "  BECMG 2614/2616 36008KT",
        wx_alternate="TAF MKJP 260515Z 2606/2706 VRB02KT 9999 FEW022\n  BECMG 2614/2616 16009KT\n"
                     "  BECMG 2623/2701 34004KT AMD NOT SKED\n\nTAF TBPB 260500Z 2606/2706 09014KT 9999 SCT018\n"
                     "  PROB30\n    TEMPO 2606/2612 SHRA BKN014\n\nTAF TGPY 260400Z 2606/2706 09008KT 9999 SCT018",
        flight_plan_fuel="19600KG / 11500KG", alt_filed="MKJP / TBPB & TGPY", dispatcher="A DISPATCHER",
        date="26/09/26")


class Rendering(unittest.TestCase):
    def words(self, data):
        import pdfplumber

        buffer = io.BytesIO()
        pages = render.render_briefing(data, buffer)
        with pdfplumber.open(io.BytesIO(buffer.getvalue())) as pdf:
            return pages, {w["text"]: w for w in pdf.pages[0].extract_words()}

    def test_layout_matches_template_positions(self):
        pages, words = self.words(template_data())
        self.assertEqual(pages, 1)
        # (text, x0, top) measured on the Word template
        for text, x0, top in [("GUY", 169.13, 184.03), ("476-477", 169.13, 204.79), ("13", 169.13, 223.87),
                              ("DOCUMENT", 77.66, 140.06), ("GATE", 77.66, 219.79), ("TBA", 169.13, 284.26),
                              ("STANDARD", 169.13, 306.70), ("DEPARTURE", 77.66, 337.18),
                              ("SIGMET", 77.66, 522.72), ("INFORMATION", 77.66, 606.15)]:
            self.assertAlmostEqual(words[text]["x0"], x0, delta=0.3, msg=text)
            self.assertAlmostEqual(words[text]["top"], top, delta=0.3, msg=text)

    def test_long_content_flows_onto_a_second_page(self):
        data = template_data()
        data.sigmet_info = "\n".join(["TJZS SIGMET GOLF 2 VALID 240205/240605 KKCI-"] + [" LINE"] * 20)
        self.assertEqual(render.render_briefing(data, io.BytesIO()), 2)

    def test_renders_without_arial_or_calibri_installed(self):
        saved = render._fonts, render._font_dirs, render._font_trees
        try:
            render._fonts = None
            render._font_dirs = render._font_trees = lambda: []
            self.assertEqual(render.render_briefing(template_data(), io.BytesIO()), 1)
            self.assertEqual(render.get_fonts(), render.Fonts("Helvetica", "Helvetica-Bold", "Helvetica-Bold"))
        finally:
            render._fonts, render._font_dirs, render._font_trees = saved


if __name__ == "__main__":
    unittest.main()
