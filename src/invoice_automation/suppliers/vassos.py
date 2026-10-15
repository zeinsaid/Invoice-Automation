"""Vassos Eliades profile (Nestlé: Fitness bars, Lion, Kit Kat, Nestea; Durex).

Columns: NEW CODE | OLD CODE | DESCRIPTION | BARCODE | QTY UNIT / FRACTION | PRICE | NET PRICE | NET AMOUNT | VAT %
- QTY is cases and a loose fraction ('0 3' = 0 cases + 3 pieces). The case size isn't printed.
- NET PRICE is already per piece, after discount, excl. VAT (D-005). So pieces = NET AMOUNT / NET
  PRICE, which must come out a whole number; with no cases, it must equal the fraction.
- Numbers use a decimal comma.
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Vassos Eliades Ltd"
SHORT_NAME = "Vassos"
MARKERS = ("VASSOS ELIADES",)

COLUMNS = {
    "new_code": r"NEW CODE",
    "old_code": r"OLD CODE",
    "description": r"DESCRIPTION",
    "barcode": r"BARCODE",
    "qty": r"QTY",
    "net_price": r"NET PRICE",
    "price": r"^PRICE",
    "amount": r"NET AMOUNT",
    "vat": r"VAT",
}
REQUIRED = "net_price"
EDITABLE = {"qty": "QTY UNIT / FRACTION", "net_price": "NET PRICE", "amount": "NET AMOUNT"}
NUMBER = [r"Doc\.?\s*Number\s*/\s*\S+\s*\S+\s*(\w*SIN\d+)", r"\b(\d{3}SIN\d{6,})"]
DATE = [r"Date\s*/\s*Ημερομηνία\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"Gross Value \(Euro\)\s*([\d.,]+)"]


def matches(page_text: str) -> bool:
    return "VASSOS ELIADES" in page_text.upper()


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def row_to_line(row) -> InvoiceLine | None:
    net_price, amount = parse_number(row["net_price"].text), parse_number(row["amount"].text)
    if net_price is None and amount is None:
        return None
    flags = []
    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []

    pieces = 0.0
    if not net_price or amount is None:
        flags.append(base.unreadable_flag("Net price or amount"))
        amount = amount or 0
    else:
        pieces = amount / net_price
        whole = round(pieces)
        if whole < 1 or abs(pieces - whole) > 0.05:
            flags.append(base.arithmetic_flag(f"{amount:.2f} / {net_price:.3f} (pieces)", pieces, whole)
                         or base.unreadable_flag("The number of pieces"))
        else:
            parts = [parse_number(x) for x in re.findall(r"\d+(?:[.,]\d+)?", row["qty"].text)]
            if len(parts) == 2 and parts[0] == 0:  # no full cases: the fraction is the piece count
                check = base.arithmetic_flag(f"{parts[1]:g} pieces x {net_price:.3f}", parts[1] * net_price, amount)
                flags += [check] if check else []
            pieces = whole

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=pieces, amount_excl_vat=amount, vat_rate=vat,
        list_price_excl_vat=net_price, pieces_known=True,
        supplier_code=row["new_code"].text.strip(), flags=flags,
    )
