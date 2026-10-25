"""Coca-Cola HBC Cyprus profile (soft drinks, Monster, beers). A delivery invoice, scanned sideways.

Columns: EAN NUMBER | MATERIAL | MATERIAL DESCRIPTION | UOM | QUANTITY | PRICE PER UNIT | VALUE |
         REGULAR DISCOUNT | PROMO DISCOUNT | NET AMOUNT | VAT %
- EAN is the barcode of ONE bottle or can (Coke Zero 1.5L is our item's barcode), MATERIAL their
  own code. Quantity is in cases (UOM 'CS'); the case size is in the description: '1.5 PET X6' is
  6, '330 CAN 4X6' and '330 CAN 3X8' are 24. The price per case confirms it (matching.suggest_pack).
- Price per unit is per case before discounts, all excl. VAT; Net amount = Value - both discounts.
  Our PowerSoft costs are what we really pay, so the case size is checked against the net price
  (Monster: net price / 24 is exactly our cost). A promo can make a case free (net 0.00): its size
  is then checked against the price before the promo, and its cost is averaged with the paid cases (D-009).
- Every page repeats the header and the Document No, so pages join by number (D-004); the
  total ('TOTAL VALUE OF INVOICE 123,45', with VAT) is on the last page. Decimal commas.
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Coca-Cola HBC Cyprus"
SHORT_NAME = "Coca-Cola"
MARKERS = ("COCA-COLA HBC", "COCA COLA HBC")

COLUMNS = {
    "ean": r"^EAN",
    "code": r"^MATERIAL$",
    "description": r"^MATERIAL DESC",
    "qty": r"^QUANTITY",
    "price": r"^PRICE PER",
    "value": r"^VALUE",
    "regular": r"^REGULAR",
    "promo": r"^PROMO",
    "net": r"^NET AMOUNT",
    "vat": r"^VAT",
}
REQUIRED = "ean"
EDITABLE = {"qty": "Quantity (cases)", "price": "Price per unit", "value": "Value", "regular": "Regular discount",
            "promo": "Promo discount", "net": "Net amount"}
NUMBER = [r"Document No:?\s*(\d{8,})"]
DATE = [r"Invoice Date:?\s*(\d{2}\.\d{2}\.\d{4})"]
# The scan's reading order can put a label or two between the words and the number
# ('TOTAL VALUE OF INVOICE\nISSUED BY :\nRECEIVED BY :\n123,45'): up to 3 lines without digits are skipped.
TOTAL = [r"TOTAL VALUE OF INVOICE\s*(?:[^\d\n]*\n){0,3}?\s*(\d[\d.]*,\d{2})"]
RETURNABLES = r"TOTAL VALUE OF RETURNABLES\s*(\d[\d.]*,\d{2})"


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def adjust(invoice, text: str) -> None:
    """A deposit on returnable crates or bottles is in the invoice total but is not stock: take it off,
    so the lines can add up to the rest. (No invoice with a deposit has been seen yet.)"""
    m = re.search(RETURNABLES, text)
    deposit = parse_number(m.group(1)) if m else None
    if deposit and invoice.printed_total is not None:
        invoice.printed_total = round(invoice.printed_total - deposit, 2)


def case_size(description: str) -> int | None:
    """'330 CAN 4X6 COCA COLA' -> 24, '500 CAN X24 MONSTER' -> 24, '1.5 PET X6 SPRITE' -> 6."""
    m = re.search(r"\b(\d+)X(\d+)\b", description, flags=re.IGNORECASE)  # no space: '500 X24' is not 500 x 24
    if m:
        return int(m.group(1)) * int(m.group(2))
    m = re.search(r"(?<![\w.])X\s*(\d+)\b", description, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def row_to_line(row) -> InvoiceLine | None:
    if not row["ean"].text.strip() and not row["code"].text.strip():
        return None  # the 'Totals' row, or an empty one
    qty, price, value, net = (parse_number(row[k].text) for k in ("qty", "price", "value", "net"))
    if qty is None and net is None:
        return None
    flags = []
    barcode = normalise_barcode(row["ean"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    regular = parse_number(row["regular"].text) or 0.0
    promo = parse_number(row["promo"].text) or 0.0
    size = case_size(row["description"].text)

    if None in (qty, price, value, net) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or net amount"))
        qty, value, net = qty or 0, value or 0, net or 0
    else:
        for check in (base.arithmetic_flag(f"{qty:g} x {price:.2f}", qty * price, value),
                      base.arithmetic_flag(f"{value:.2f} less discounts {regular + promo:.2f}", value - regular - promo,
                                           net)):
            flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=qty, amount_excl_vat=net, vat_rate=vat,
        list_price_excl_vat=(net if net else value - regular) / qty if qty else None,
        printed_factor=size if size and size > 1 else None,
        supplier_code=row["code"].text.strip(), flags=flags,
    )
