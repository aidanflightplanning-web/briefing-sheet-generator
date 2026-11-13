"""Compact PDF pages: black-and-white images with CCITT Group 4 (fax) compression.

Used for the attachments, so the briefing sheet with its MEL book pages and wind
charts stays small: a wind chart page is about 100 KB this way instead of 530 KB
in grey, and an MEL book page 15-45 KB instead of about 100 KB with its fonts.
"""

from __future__ import annotations

import io

from PIL import Image


def bilevel(image: Image.Image, threshold: int) -> Image.Image:
    """Black where the grey value is at or below `threshold`, white elsewhere (no dithering,
    which keeps text and lines sharp and compresses well)."""
    return image.convert("L").point(lambda v: 255 if v > threshold else 0, mode="1")


def images_pdf(images: list[Image.Image], dpi: float) -> bytes:
    """One page per black-and-white image; the page size is the image size at `dpi`."""
    first, *rest = images
    out = io.BytesIO()
    first.save(out, format="PDF", resolution=dpi, save_all=bool(rest), append_images=rest)
    return out.getvalue()
