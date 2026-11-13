"""WAFC wind/temperature charts from the Aviation Weather Center (https://aviationweather.gov/fax/).

Only the Area A chart (65N-50S 120W-25W, Americas) at FL100 is used, at the six forecast
times the AWC publishes (+06 h to +36 h from the model run). Each GIF carries its model
run in a comment ("ProdTime=20261111-1800"), so the valid time is run + forecast hours.
A chart is valid for three hours either side of its valid time.

For a B737 flight the charts valid from 3 h before departure to 3 h after arrival are
ticked. Selected charts are added to the briefing package as US Letter pages.
"""

from __future__ import annotations

import io
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

PAGE_URL = "https://aviationweather.gov/fax/"
CHART_URL = "https://aviationweather.gov/data/products/fax/F{hour:02d}_wind_100_a.gif"
HOURS = (6, 12, 18, 24, 30, 36)
AREA = "Area A – 65N-50S 120W-25W (Americas)"
LEVEL = "FL100"
USER_AGENT = "BriefingSheetGenerator/1.0 (+https://github.com/aidanflightplanning-web/briefing-sheet-generator)"
SELECTION_MARGIN = timedelta(hours=3)   # charts valid from 3 h before departure to 3 h after arrival
PROD_TIME_RE = re.compile(rb"ProdTime=(\d{8})-(\d{4})")

CHART_THRESHOLD = 200    # black and white: keeps the light grey coastlines
LETTER = (612.0, 792.0)
MARGIN = 18.0
CAPTION_SPACE = 14.0


class WindChartError(OSError):
    pass


@dataclass
class WindChart:
    hour: int                      # forecast hour: 6, 12 ... 36
    url: str
    image: bytes                   # the GIF as published
    run: datetime | None           # model run (UTC, naive)
    retrieved: datetime            # when it was downloaded (UTC, naive)

    @property
    def valid(self) -> datetime | None:
        return self.run + timedelta(hours=self.hour) if self.run else None

    @property
    def label(self) -> str:
        """'+06 h · valid 0000Z THU 12 NOV'."""
        valid = self.valid
        when = f"VALID {valid:%H%MZ %a %d %b}".upper() if valid else "VALID TIME UNKNOWN"
        return f"+{self.hour:02d} h · {when}"

    def thumbnail(self, width: int = 360) -> bytes:
        """A small PNG of the chart, for the selection screen."""
        from PIL import Image

        with Image.open(io.BytesIO(self.image)) as im:
            im = im.convert("L")
            im.thumbnail((width, width * 2))
            buffer = io.BytesIO()
            im.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()


def _run_time(image: bytes, last_modified: str | None) -> datetime | None:
    m = PROD_TIME_RE.search(image[:4096]) or PROD_TIME_RE.search(image)
    if m:
        try:
            return datetime.strptime((m.group(1) + m.group(2)).decode(), "%Y%m%d%H%M")
        except ValueError:
            pass
    if last_modified:  # products appear about 3.5 h after the model run
        try:
            stamp = parsedate_to_datetime(last_modified).astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None
        stamp -= timedelta(hours=3)
        return stamp.replace(hour=stamp.hour - stamp.hour % 6, minute=0, second=0, microsecond=0)
    return None


def fetch_chart(hour: int, timeout: float = 30) -> WindChart:
    url = CHART_URL.format(hour=hour)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
            image = response.read()
            modified = response.headers.get("Last-Modified")
    except OSError as exc:
        raise WindChartError(f"Could not download the +{hour:02d} h wind chart: {exc}") from exc
    if not image.startswith(b"GIF8"):
        raise WindChartError(f"The +{hour:02d} h wind chart is not an image ({url})")
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    return WindChart(hour, url, image, _run_time(image, modified), now)


def fetch_charts(hours=HOURS, timeout: float = 30) -> tuple[list[WindChart], list[str]]:
    """Download the charts in parallel. Returns (charts in hour order, error messages)."""
    charts, errors = [], []
    with ThreadPoolExecutor(max_workers=len(hours) or 1) as pool:
        futures = [pool.submit(fetch_chart, h, timeout) for h in hours]
        for future in futures:
            try:
                charts.append(future.result())
            except WindChartError as exc:
                errors.append(str(exc))
    return charts, errors


def run_summary(charts: list[WindChart]) -> str:
    """'Model run 12 NOV 0000Z', or a note when the AWC is part way through publishing a new run."""
    runs = sorted({c.run for c in charts if c.run})
    if not runs:
        return ""
    if len(runs) == 1:
        return f"Model run {runs[0]:%d %b %H%MZ}".upper()
    newest = runs[-1]
    hours = ", ".join(f"+{c.hour:02d}" for c in charts if c.run == newest)
    return (f"Update in progress: {hours} h from the {newest:%H%MZ} run, the rest from {runs[0]:%H%MZ}. "
            "Each chart shows its own valid time; Refresh later for the full set.")


def selection_windows(fp) -> list[tuple[datetime, datetime]]:
    """For each leg: 3 h before the scheduled departure to 3 h after the scheduled arrival (UTC).
    Overlapping windows of a rotation are joined."""
    windows = []
    for leg in fp.legs:
        dep, arr = leg.departure, leg.arrival or leg.departure
        if dep:
            windows.append((dep - SELECTION_MARGIN, arr + SELECTION_MARGIN))
    joined: list[tuple[datetime, datetime]] = []
    for start, end in sorted(windows):
        if joined and start <= joined[-1][1]:
            joined[-1] = (joined[-1][0], max(joined[-1][1], end))
        else:
            joined.append((start, end))
    return joined


def suggested_hours(charts: list[WindChart], fp) -> list[int]:
    """Charts whose valid time is from 3 h before departure to 3 h after arrival of a leg
    (both limits included)."""
    windows = selection_windows(fp)
    return [c.hour for c in charts if c.valid and any(start <= c.valid <= end for start, end in windows)]


def selection_text(fp) -> str:
    """'0915Z 12 NOV – 1940Z 12 NOV' : the valid times that are ticked."""
    return ", ".join(f"{start:%H%MZ %d %b} – {end:%H%MZ %d %b}".upper() for start, end in selection_windows(fp))


def charts_pdf(charts: list[WindChart]) -> bytes:
    """One US Letter portrait page per chart, scaled to fit, with a source line.

    The chart is stored in black and white with fax compression (about 100 KB a page
    instead of 530 KB in grey); these are fax charts, made to print that way."""
    from PIL import Image
    from pypdf import PageObject, PdfReader, PdfWriter, Transformation
    from reportlab.pdfgen import canvas

    from .compact import bilevel, images_pdf

    writer = PdfWriter()
    width, height = LETTER
    box_w, box_h = width - 2 * MARGIN, height - 2 * MARGIN - CAPTION_SPACE
    for chart in charts:
        with Image.open(io.BytesIO(chart.image)) as im:
            bw = bilevel(im, CHART_THRESHOLD)
        scale = min(box_w / bw.width, box_h / bw.height)
        w, h = bw.width * scale, bw.height * scale
        x, y = (width - w) / 2, MARGIN + CAPTION_SPACE + (box_h - h) / 2

        frame = io.BytesIO()   # border and source line, drawn over the chart
        pdf = canvas.Canvas(frame, pagesize=LETTER, pageCompression=1)
        pdf.setLineWidth(0.5)
        pdf.rect(x, y, w, h)
        pdf.setFont("Helvetica", 7)
        pdf.setFillGray(0.35)
        pdf.drawString(MARGIN, MARGIN + 3, f"WAFC {LEVEL} wind/temp · Area A (Americas) · {chart.label}")
        pdf.drawRightString(width - MARGIN, MARGIN + 3,
                            f"aviationweather.gov · retrieved {chart.retrieved:%d%b%y %H%MZ}".upper())
        pdf.showPage()
        pdf.save()

        page = PageObject.create_blank_page(width=width, height=height)
        image_page = PdfReader(io.BytesIO(images_pdf([bw], 72))).pages[0]   # 1 px = 1 pt
        page.merge_transformed_page(image_page, Transformation().scale(scale, scale).translate(x, y))
        page.merge_page(PdfReader(frame).pages[0])
        writer.add_page(page)
    writer.add_metadata({"/Title": f"Wind/temperature charts {LEVEL} {AREA}"})
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
