"""Cassandra Trading profile (Marlboro, Terea, VEEV, Delia).

Columns: PRODUCT | FACT | QTY | SUB | PRC | GROSS | DISC % | VAT % | TOTAL
- PRODUCT holds 'code - NAME KS/ barcode'. The barcode is the *carton* barcode, which never
  matches PowerSoft's piece barcode (D-006), so the learned mapping takes over after the first
  confirmation; until then the name (without 'KS', king size) is matched.
- FACT = packs per carton, QTY = cartons, SUB = loose packs. Pieces = QTY x FACT + SUB (D-005).
- PRC is the price of one carton before discount, excl. VAT. GROSS = QTY x PRC.
- TOTAL is incl. VAT, after the discount (e.g. VEEV devices at 70% off).
Long invoices are scanned sideways on A3; DI detects the rotation. A longer till roll is scanned in two or
more pieces (2220210014739, Nov 2026): the later pieces have no header row (continuation_rows), and a piece
may start with the last lines of the one before, which are dropped (OVERLAPPING_PAGES, D-004 amendment 2026-11-09).
"""

import re
import sys

from ..layout import headless_rows, normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Cassandra Trading LTD"
SHORT_NAME = "Cassandra"
# Their VAT number too: a scan that cuts off the logo still has it (2026-10-23).
MARKERS = ("CASSANDRA", "99000044T")

COLUMNS = {
    "product": r"PRODUCT|[ΠN]POION",
    "fact": r"FACT",
    "sub": r"SUB",
    "qty": r"QTY|OTY",
    "price": r"PRC",
    "gross": r"GROSS",
    "disc": r"DISC",
    "vat": r"VAT",
    "total": r"TOTAL",
}
REQUIRED = "fact"
EDITABLE = {"fact": "FACT (packs per carton)", "qty": "QTY (cartons)", "sub": "SUB (loose packs)",
            "price": "PRC", "gross": "GROSS", "disc": "DISC %", "total": "TOTAL"}
NUMBER = [r"(\d{10,})\s*\(\s*[ΑA][ΡP]\.?\s*[ΕE][ΚK]"]  # '2220210014484 (Αρ. Εκτύπωσης: 2)'
DATE = [r"ΠΑΡΑΣΤΑΤΙΚΟΥ:?\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"TOTAL EURO\s*(\d+[.,]\d{2})"]
OVERLAPPING_PAGES = True
# A piece without a header row: the eight number columns, right to left, are always the same. Everything to
# their left is the product (the scanner may split it into two cells, or add an empty column among the numbers).
CONTINUATION_COLUMNS = (9, 10, 11)
CONTINUATION_TAIL = ["fact", "qty", "sub", "price", "gross", "disc", "vat", "total"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def continuation_rows(result) -> list[dict]:
    """Rows of a piece of the till roll that has no header row. Rows that aren't items (the end of a
    product cut off at the top, a totals table with the same width) have no quantity and no total, and
    row_to_line drops them."""
    rows = headless_rows(result, CONTINUATION_COLUMNS, CONTINUATION_TAIL, skip_empty=True)
    for row in rows:
        row["product"] = row.pop("_lead")
    return rows


def row_to_line(row) -> InvoiceLine | None:
    fact, qty, sub = (parse_number(row[k].text) for k in ("fact", "qty", "sub"))
    price, gross, total = (parse_number(row[k].text) for k in ("price", "gross", "total"))
    if qty is None and total is None:
        return None
    flags = base.confidence_flags({"quantity": row["fact"]})  # FACT is not covered by the arithmetic

    name, barcode = _split_product(row["product"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc"].text) or 0.0) / 100

    if None in (fact, qty, price, gross, total) or not fact:
        flags.append(base.unreadable_flag("Pack size, quantity or price"))
        fact, qty, price, gross = fact or 1, qty or 0, price or 0, gross or 0
    else:
        cartons = qty + (sub or 0) / fact  # loose packs are priced as part of a carton
        for check in (base.arithmetic_flag(f"{cartons:g} x {price:.2f}", cartons * price, gross),
                      base.arithmetic_flag(f"{gross:.2f} less {disc:.0%} plus VAT", gross * (1 - disc) * (1 + vat / 100), total)):
            flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=name, barcode=barcode,
        quantity=qty * fact + (sub or 0), amount_excl_vat=gross * (1 - disc), vat_rate=vat,
        list_price_excl_vat=price / fact, pieces_known=True, flags=flags,
    )


def _split_product(text: str) -> tuple[str, str]:
    """'ML01 - MARLBORO RED KS/ 5290415022215' -> ('MARLBORO RED', '5290415022215')."""
    name, _, code = text.rpartition("/")
    if not name:
        name, code = text, ""
    name = re.sub(r"^\S+\s*[-.]\s*", "", name.strip())  # drop Cassandra's own code ('ML01 -')
    name = re.sub(r"\s+KS$", "", name)  # king size: our items don't carry it
    return name.strip(), normalise_barcode(code)
