"""Phoenicia Fereos profile (Davidoff, Rothmans, Pall Mall, Lucky Strike, Rizla).

Columns: A/A | ΠΡΟΙΟΝ | Μ.Μ A | ΠΟΣ. A | Μ.Μ B | ΠΟΣ. B | ΤΙΜΗ A | ΤΙΜΗ B | ΕΚΠΤ. (€) | ΣΥΝΟΛΟ | Φ.Π.Α. (%)
- ΠΡΟΙΟΝ holds 'code - Name (retail price) CY / barcode'; barcodes are piece barcodes.
- Unit A is the selling piece ('Packet 20', 'Box 120'), so quantity A is already in pieces.
  Unit B has been empty on every sample; if it is ever filled, the line is flagged red.
- ΤΙΜΗ A is per piece excl. VAT; ΣΥΝΟΛΟ is excl. VAT, after the discount in euros.
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import RED, Flag, InvoiceLine
from . import base

SUPPLIER = "Phoenicia Fereos Cyprus Ltd"
SHORT_NAME = "Fereos"
MARKERS = ("PHOENICIA", "FEREOS")

COLUMNS = {
    "qty_a": r"^ΠOΣ\.? ?A$",
    "qty_b": r"^ΠOΣ\.? ?B$",
    "price_a": r"^TIMH ?A",
    "product": r"[ΠN]POION|PRODUCT",
    "disc": r"^EK",
    "total": r"ΣYNOΛO|TOTAL",
    "vat": r"Φ|D\.N\.A|\(%\)",
}
REQUIRED = "qty_a"
NUMBER = [r"Document No:?\s*(S\d{8,})", r"(S\d{8,})\s*\(\s*[ΑA][ΡP]"]  # the layout differs between print runs
DATE = [r"Date:?\s*(\d{2}/\d{2}/\d{4})", r"S\d{8,}\s*\([^)]*\)\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"TOTAL EURO\s*(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index):
    return base.parse(sys.modules[__name__], result, source, page_index)


def row_to_line(row) -> InvoiceLine | None:
    qty, price, total = (parse_number(row[k].text) for k in ("qty_a", "price_a", "total"))
    if qty is None and total is None:
        return None
    flags = []
    name, barcode = _split_product(row["product"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    discount = parse_number(row["disc"].text) or 0.0  # euros for the whole line

    if parse_number(row["qty_b"].text):
        flags.append(Flag(RED, "quantity", "Quantity in unit B is filled in. That has never happened before; "
                                           "check how many pieces this is."))
    if None in (qty, price, total):
        flags.append(Flag(RED, "quantity", "Quantity, price or total could not be read."))
        qty, total = qty or 0, total or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:.3f} - {discount:.2f}", qty * price - discount, total)
        flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=name, barcode=barcode,
        quantity=qty, amount_excl_vat=total, vat_rate=vat,
        list_price_excl_vat=price, pieces_known=True, flags=flags,
    )


def _split_product(text: str) -> tuple[str, str]:
    """'1005154 - Davidoff Classic (5.00 E2C) CY / 4030600298794' -> ('Davidoff Classic', '4030600298794')."""
    name, _, code = text.rpartition("/")
    if not name:
        name, code = text, ""
    name = re.sub(r"^\d+\s*-\s*", "", name.strip())  # Fereos' own code
    name = re.sub(r"\s*\(.*?\)", "", name)  # retail price / packaging notes
    name = re.sub(r"\s+CY\b.*$", "", name)  # 'CY', 'CY New'
    return name.strip(), normalise_barcode(code)
