"""Cut a picture of one invoice line (or part of the page) out of the scan, for the review window (D-022).

DI gives every table cell's position on the page in inches. A PDF page is measured in points
(72 per inch), so the same box can be cut out of the PDF directly. Pages scanned sideways
(Cassandra on A3) are turned upright after cutting.
"""

from pathlib import Path

import pymupdf
from PIL import Image

PADDING = 0.06  # inches around the line
DPI = 160


def crop(pdf: Path, page_index: int, box: tuple[float, float, float, float] | None,
         angle: float = 0.0, region: str | None = None) -> Image.Image | None:
    """`box` is (x0, y0, x1, y1) in inches. Without a box, `region` 'top' or 'bottom' gives that part of the page."""
    with pymupdf.open(pdf) as doc:
        page = doc[page_index]
        rect = page.rect
        if box:
            x0, y0, x1, y1 = box
            clip = pymupdf.Rect((x0 - PADDING) * 72, (y0 - PADDING) * 72, (x1 + PADDING) * 72, (y1 + PADDING) * 72)
        elif region == "top":
            clip = pymupdf.Rect(0, 0, rect.width, rect.height * 0.35)
        elif region == "bottom":
            clip = pymupdf.Rect(0, rect.height * 0.55, rect.width, rect.height)
        else:
            return None
        clip &= rect  # stay on the page
        pix = page.get_pixmap(dpi=DPI, clip=clip)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    quarter_turns = round(angle / 90) % 4  # DI's angle: how far the text is turned clockwise
    if quarter_turns:
        image = image.rotate(90 * quarter_turns, expand=True)  # PIL turns anticlockwise
    return image
