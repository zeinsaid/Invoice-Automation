"""Cosmos Tobacco Trading profile (Winston, Camel, Karelia, Old Holborn).

Columns: BARCODE | ΠΡΟΙΟΝ | M.M | ΠΟΣ. | ΤΙΜΗ ΜΟΝ | ΕΚΠΤ | Φ.Π.Α | ΣΥΝΟΛΟ
- Barcodes are piece barcodes; 8-digit ones are printed with '-n' (D-006).
- Quantity is in pieces (packs, booklets). Price is per piece excl. VAT; ΣΥΝΟΛΟ includes VAT.
- Two pages are printed on one long sheet, so the table continues after a gap (layout.find_table).
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Cosmos Tobacco Trading LTD"
SHORT_NAME = "Cosmos"
MARKERS = ("COSMOS TOBACCO",)

COLUMNS = {
    "barcode": r"BARCODE",
    "product": r"[ΠN]POION|PRODUCT",
    "uom": r"^M\.?M",
    "qty": r"^ΠOΣ",
    "price": r"TIMH",
    "disc": r"^EK",
    "vat": r"Φ\.?Π\.?A|VAT",
    "total": r"ΣYNOΛO|TOTAL",
}
REQUIRED = "barcode"
EDITABLE = {"qty": "ΠΟΣ. (quantity)", "price": "ΤΙΜΗ (price)", "disc": "ΕΚΠΤ (discount %)", "total": "ΣΥΝΟΛΟ (total)"}
NUMBER = [r"(\d{8,})\s*\(\s*[ΑA][ΡP]\.?\s*[ΕE][ΚK]"]  # '72100058162 (Αρ. Εκτύπωσης: 1)'
DATE = [r"ΠΑΡΑΣΤΑΤΙΚΟΥ:?\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"TOTAL EURO\s*(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    return "COSMOS TOBACCO" in page_text.upper()


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def row_to_line(row) -> InvoiceLine | None:
    qty, price, total = (parse_number(row[k].text) for k in ("qty", "price", "total"))
    if qty is None and total is None:
        return None
    flags = []
    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc"].text) or 0.0) / 100

    if None in (qty, price, total):
        flags.append(base.unreadable_flag("Quantity, price or total"))
        qty, price = qty or 0, price or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:.3f} plus VAT", qty * price * (1 - disc) * (1 + vat / 100), total)
        flags += [check] if check else []

    # Drop the printed retail price ('CAMEL BLUE €4.80') from the name.
    name = re.sub(r"\s*€\s*\d+[.,]\d+", "", row["product"].text).strip()
    return InvoiceLine(
        line_no="", description=name, barcode=barcode,
        quantity=qty, amount_excl_vat=qty * price * (1 - disc), vat_rate=vat,
        list_price_excl_vat=price, pieces_known=True, flags=flags,
    )
