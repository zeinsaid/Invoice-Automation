"""Athenites (Chr. Hadjichristofi) profile (D-020).

The invoice is a printout from the Athenites checkout till:
- columns A/A, Description, Barcode, Quantity, Unit Selling Price, Discount Amount, Amount Incl. VAT, VAT
- prices and amounts include VAT; VAT is a letter code
- the barcode is whatever their cashier scanned (a piece or a whole case); the pack size is
  worked out in matching (D-020)
- descriptions are cut at 30 characters
"""

import sys

from ..layout import normalise_barcode, parse_number
from ..model import RED, Flag, InvoiceLine
from . import base

SUPPLIER = "Chr. Hadjichristofi (Athienitis) Ltd"
SHORT_NAME = "Athienitis"
MARKERS = ("HADJICHRISTOF", "ATHIENITIS")

VAT_LETTERS = {"B": 5, "D": 19}  # checked against the catalogue on the first sample (D-020)
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
NUMBER = [r"Invoice No\s*\.?\s*:?\s*(\d{6,})"]  # read as 'Invoice No .:\n1000748334'
DATE = [r"Date/Time:?\s*(\d{2}/\d{2}/\d{2,4})"]
# The totals are on the last page, whose layout isn't known yet (the first sample's page 2 was
# not scanned). Until then only an explicit "Total" followed by an amount counts.
TOTAL = [r"\bTOTAL\b[^\d\n]{0,30}(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index):
    return base.parse(sys.modules[__name__], result, source, page_index)


def row_to_line(row) -> InvoiceLine | None:
    qty = parse_number(row["quantity"].text)
    amount = parse_number(row["amount"].text)  # incl. VAT, after the line discount
    if qty is None and amount is None:
        return None
    flags = []

    letter = row["vat"].text.strip().upper()
    vat = VAT_LETTERS.get(letter)
    if vat is None:
        flags.append(Flag(RED, "row", f"Unknown VAT code '{letter}' on the invoice."))
        vat = 0

    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]

    unit_price = parse_number(row["unit_price"].text)  # incl. VAT, before discount
    discount = parse_number(row["discount"].text) or 0.0
    if qty is None or amount is None:
        flags.append(Flag(RED, "quantity", "Quantity or amount could not be read."))
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
