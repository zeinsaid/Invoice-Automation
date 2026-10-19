"""Make the made-up invoice used for the public demo and the final test (docs/demo/example-invoice.pdf).

It copies the Athenites till-printout layout under a made-up supplier, Example Wholesale Ltd (see
suppliers/example.py). The products are real products the shop stocks, so the tool can match them,
but every price is made up. Each line is there to show one thing:

  plain barcode matches ........ go straight in, no question
  COCA COLA case barcode ........ "How many pieces in 1 unit?" (the price suggests 24)
  KYKKOS WATER 500ML X12 ........ a pack sub-item: goes in as 60 single bottles, no question (D-005)
  PERRIER WATR 33CL ............. a misspelling: "Is it this item?", differing words in red
  KINDER BUENO WHITE T3 ......... not found; the new-item form offers the single bar we already sell
  TOBLERONE MILK 100G ........... really new: the new-item form
  LAYS BARBEQUE 42G ............. 10 x 0.60 printed as 6.60: staff correct the quantity from the paper
  FANTA with a line discount .... discounts are taken off the cost

Barcodes starting with 200 are reserved for in-store use, so they can't be a real product's.

    uv run python scripts/make_demo_invoice.py
"""

import io
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter

OUT = Path("docs/demo/example-invoice.pdf")


def ean13(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return first12 + str((10 - total % 10) % 10)


# description, barcode, quantity, unit price incl. VAT, discount, VAT letter (B 5%, D 19%), printed amount (None = right)
LINES = [
    ("LAYS SALTED 42G", "5290052006227", 20, 0.60, 0.00, "B", None),
    ("PRINGLES ORIGINAL 40GR", "5053990107339", 12, 0.82, 0.00, "B", None),
    ("COCA COLA CANS 330ML", ean13("200000000001"), 2, 15.00, 0.00, "D", None),
    ("RED BULL DRINK 250ML", "90162602", 24, 0.86, 0.00, "D", None),
    ("KYKKOS WATER 500ML X12", "5291469000051", 5, 3.47, 0.00, "B", None),
    ("PERRIER WATR 33CL", ean13("200000000002"), 24, 0.67, 0.00, "B", None),
    ("SNICKERS 50GR", "5900951311505", 24, 0.70, 0.00, "B", None),
    ("KINDER BUENO WHITE T3", ean13("200000000003"), 6, 3.02, 0.00, "B", None),
    ("TOBLERONE MILK 100G", ean13("200000000004"), 10, 1.60, 0.00, "B", None),
    ("LAYS BARBEQUE 42G", "5290052006258", 10, 0.60, 0.00, "B", 6.60),
    ("FANTA ORANGE CAN 33CL", "5449000335906", 24, 0.76, -1.20, "D", None),
    ("COCA COLA ZERO 330ML", "5449000214799", 24, 0.62, 0.00, "D", None),
]

X = {"aa": 40, "desc": 62, "barcode": 248, "qty": 360, "price": 420, "disc": 478, "amount": 532, "vat": 552}


def draw() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4

    def text(x, y, s, size=8.5, bold=False, right=False):
        font = "hebo" if bold else "helv"
        if right:
            x -= pymupdf.get_text_length(s, fontname=font, fontsize=size)
        page.insert_text((x, y), s, fontname=font, fontsize=size)

    text(40, 50, "EXAMPLE WHOLESALE LTD", 14, True)
    text(40, 64, "12 Sample Street, 1000 Nicosia  -  Tel 22 000000  -  VAT No 10000000X")
    text(40, 92, "INVOICE", 12, True)
    text(330, 92, "Invoice No .:", 9)
    text(400, 92, "9000004217", 9, True)
    text(330, 106, "Date/Time:", 9)
    text(400, 106, "19/10/26 14:20", 9)
    text(40, 106, "Customer: THE PLUG BUSINESS CENTER", 9)

    top = 130
    page.draw_rect(pymupdf.Rect(36, top, 575, top + 26), width=1.2)
    for key, label, right in (("aa", "A/A", False), ("desc", "Description", False), ("barcode", "Barcode", False),
                              ("qty", "Quantity", True), ("price", "Unit Selling|Price", True),
                              ("disc", "Discount|Amount", True), ("amount", "Amount Incl.|VAT", True),
                              ("vat", "VAT", False)):
        parts = label.split("|")
        for i, part in enumerate(parts):
            text(X[key], top + (11 if len(parts) == 2 else 17) + 9 * i, part, 8, True, right)

    y, total, discounts = top + 42, 0.0, 0.0
    for n, (desc, barcode, qty, price, disc, vat, printed) in enumerate(LINES, 1):
        amount = round(qty * price + disc, 2) if printed is None else printed
        total += amount
        discounts += disc
        text(X["aa"], y, str(n))
        text(X["desc"], y, desc)
        text(X["barcode"], y, barcode)
        text(X["qty"], y, f"{qty:.2f}", right=True)
        text(X["price"], y, f"{price:.2f}", right=True)
        text(X["disc"], y, f"{disc:.2f}", right=True)
        text(X["amount"], y, f"{amount:.2f}", right=True)
        text(X["vat"], y, vat)
        y += 17
    page.draw_line((36, y - 6), (575, y - 6), width=0.8)

    text(330, y + 14, "Total (VAT) Included:", 9, True)
    text(330, y + 28, f"{discounts:.2f}", 9)
    text(330, y + 42, f"{total:,.2f}", 10, True)
    text(40, 800, "MADE-UP INVOICE FOR DEMONSTRATION. The supplier and every price on it are fictional.", 7.5)
    return doc.tobytes()


def as_scan(pdf: bytes) -> bytes:
    """Render to a grey, slightly tilted image, like a page from the shop's scanner."""
    rng = random.Random(7)
    pix = pymupdf.open("pdf", pdf)[0].get_pixmap(dpi=200, colorspace="gray")
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    img = img.rotate(-0.4, resample=Image.BICUBIC, expand=False, fillcolor=255).filter(ImageFilter.GaussianBlur(0.5))
    img = img.point(lambda v: min(255, int(v * 0.93) + rng.randint(0, 6)))
    out = io.BytesIO()
    img.save(out, "PDF", resolution=200)
    return out.getvalue()


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(as_scan(draw()))
    print(f"Wrote {OUT}")
