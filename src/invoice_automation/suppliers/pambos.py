"""Pambos & Andreas Trading profile (vapes). 'Credit Invoice' here means sold on credit (D-013).

Columns: Item | Description | Quantity | Price | Disc % | Discount | VAT% | Total
- Item is Pambos' own code (CRYSTALVAPE14), the steadiest key: long descriptions sometimes spill
  into the next row, mixing up barcodes and names, but the code stays on its row.
- The barcode is the first number in the description.
- Price is per piece excl. VAT; Total is excl. VAT. Quantities count single pieces, even when the
  name says '*10pcs' (that's the box they come in), so nothing is ever multiplied (D-005 amendment).
"""

import sys

from ..layout import parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Pambos & Andreas Trading Ltd"
SHORT_NAME = "Pambos"
MARKERS = ("PAMBOS & ANDREAS", "PAMBOSANDREAS")

COLUMNS = {
    "code": r"^ITEM$",
    "description": r"DESCRIPTION",
    "qty": r"QUANTITY",
    "price": r"^PRICE",
    "disc_pct": r"DISC ?%",
    "discount": r"^DISCOUNT",
    "vat": r"^VAT",
    "total": r"^TOTAL",
}
REQUIRED = "code"
EDITABLE = {"qty": "Quantity", "price": "Price", "disc_pct": "Disc %", "discount": "Discount", "total": "Total"}
NUMBER = [r"Invoice Number:?\s*(IN\d+)"]
DATE = [r"\bDate:\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"\bTotal:\s*(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def adjust(invoice, text: str) -> None:
    """A description can be read into the row above (invoice IN2600006599): 'GB POD BANANA ICE 9 *10pcs
    6979193577153 GB POD STRAWBERRY WATERMELON 11' on GKSPOD9's row, and only '*10pcs' on GKSPOD11's.
    A second barcode in a description, with the next line having none, goes back to that line."""
    for line, below in zip(invoice.lines, invoice.lines[1:]):
        before, barcode, after = base.split_code_and_barcode(line.description)
        if barcode and not below.barcode:
            line.description = before
            below.barcode, below.description = barcode, f"{after} {below.description}".strip()


def row_to_line(row) -> InvoiceLine | None:
    qty, price, total = (parse_number(row[k].text) for k in ("qty", "price", "total"))
    if qty is None and total is None:
        return None
    flags = []
    _, barcode, name = base.split_code_and_barcode(row["description"].text)
    vat_cell, discount_text = row["vat"], row["discount"].text
    if not vat_cell.text.strip() and None not in (qty, price, total) and abs(qty * price - total) <= 0.02:
        # The scanner sometimes reads the VAT rate one column to the left, into Discount
        # (October 2026). With no discount the line adds up as it is, so that number is the VAT.
        vat_cell, discount_text = row["discount"], ""
    vat, vat_flag = base.vat_from_percent(vat_cell)
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc_pct"].text) or 0.0) / 100
    discount = parse_number(discount_text) or 0.0

    if None in (qty, price, total) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or total"))
        qty, total = qty or 0, total or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:.2f}", qty * price * (1 - disc) - discount, total)
        flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=name, barcode=barcode,
        quantity=qty, amount_excl_vat=total, vat_rate=vat,
        list_price_excl_vat=total / qty if qty else None, pieces_known=True,
        supplier_code=row["code"].text.strip(), flags=flags,
    )
