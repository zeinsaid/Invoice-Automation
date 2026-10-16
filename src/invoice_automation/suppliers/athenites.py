"""Athenites (Chr. Hadjichristofi) profile (D-020).

The invoice is a printout from the Athenites checkout till:
- columns A/A, Description, Barcode, Quantity, Unit Selling Price, Discount Amount, Amount Incl. VAT, VAT
- prices and amounts include VAT; VAT is a letter code
- the barcode is whatever their cashier scanned (a piece or a whole case); the pack size is
  worked out in matching (D-020)
- descriptions are cut at 30 characters
"""

import re
import sys

from ..layout import Cell, headless_rows, normalise_barcode, parse_number
from ..model import RED, ZEIN, Flag, InvoiceLine
from . import base

SUPPLIER = "Chr. Hadjichristofi (Athienitis) Ltd"
SHORT_NAME = "Athienitis"
MARKERS = ("HADJICHRISTOF", "ATHIENITIS")

# B and D checked against the catalogue on the first sample (D-020). A (milk, tortillas, sanitary
# pads) has no line in the printed VAT analysis: those lines make up exactly the difference
# between the total and the B + D amounts, so it is 0%.
VAT_LETTERS = {"A": 0, "B": 5, "D": 19}
COLUMNS = {
    "description": r"DESCRIPTION",
    "barcode": r"BARCODE",
    "quantity": r"QUANTITY",
    "unit_price": r"UNIT SELLING",
    "discount": r"DISCOUNT",
    "amount": r"AMOUNT",
    "vat": r"^VAT$",
}
REQUIRED = "barcode"
EDITABLE = {"quantity": "Quantity", "unit_price": "Unit Selling Price", "discount": "Discount Amount",
            "amount": "Amount Incl. VAT"}
NUMBER = [r"Invoice No\s*\.?\s*:?\s*(\d{6,})"]  # read as 'Invoice No .:\n1000748334'
DATE = [r"Date/Time:?\s*(\d{2}/\d{2}/\d{2,4})"]
# On the last page: 'Total (VAT) Included:\n-5.98\n1,026.26'. The first number is the sum of the
# line discounts, printed only when there are any; the second is the total to pay.
TOTAL = [r"Total \(VAT\) Included:?\s*(?:-\d[\d,]*\.\d{2}\s+)?(\d[\d,]*\.\d{2})"]
# Page 2 onwards repeats the 8-column table without its header (D-004).
CONTINUATION_COLUMNS = 8
CONTINUATION_TAIL = ["quantity", "unit_price", "discount", "amount", "vat"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def continuation_rows(result) -> list[dict]:
    """Page 2 onwards: the line number, description and barcode may be merged into one or two
    cells ('51 | LOTUS SAND/BISCOFF CREAM 150GR 5410126006360'), so they are taken apart here."""
    rows = []
    for row in headless_rows(result, CONTINUATION_COLUMNS, CONTINUATION_TAIL):
        lead = row.pop("_lead")
        m = re.fullmatch(r"(?:\d{1,3}\s+)?(.*?)\s*(\d{8,14})?", lead.text)
        row["description"] = Cell(m.group(1), lead.confidence, lead.box)
        row["barcode"] = Cell(m.group(2) or "", lead.confidence, lead.box)
        rows.append(row)
    return rows


def row_to_line(row) -> InvoiceLine | None:
    qty = parse_number(row["quantity"].text)
    amount = parse_number(row["amount"].text)  # incl. VAT, after the line discount
    if qty is None and amount is None:
        return None
    flags = []

    letter = row["vat"].text.strip().upper()
    vat = VAT_LETTERS.get(letter)
    if vat is None:
        flags.append(Flag(RED, "row", f"Unknown VAT code '{letter}' on the invoice.", ZEIN))
        vat = 0

    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]

    unit_price = parse_number(row["unit_price"].text)  # incl. VAT, before discount
    discount = parse_number(row["discount"].text) or 0.0
    if qty is None or amount is None:
        flags.append(base.unreadable_flag("Quantity or amount"))
    elif unit_price is None:
        flags += base.confidence_flags({"quantity": row["quantity"], "cost": row["amount"]})
    else:
        f = base.arithmetic_flag(f"{qty:g} x {unit_price:.2f} {discount:+.2f} discount", qty * unit_price + discount, amount)
        flags += [f] if f else []

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=qty or 0.0, amount_excl_vat=(amount or 0.0) / (1 + vat / 100), vat_rate=vat,
        list_price_excl_vat=unit_price / (1 + vat / 100) if unit_price is not None else None,
        flags=flags,
    )
