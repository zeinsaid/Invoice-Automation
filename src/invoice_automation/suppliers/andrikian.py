"""Andrikian Trading profile (Smoking papers, Orbit gum).

Columns: ITEM CODE | DESCRIPTION | VAT CODE | U.O.M. | QTY | PRICE | DISC. % | NET AMOUNT | GROSS VALUE
- ITEM CODE is the barcode.
- U.O.M. is the pack size (24, 16, 6...), so 1 x 6 = 6 pieces (D-005). Some of our items are the
  pack itself, so the price decides (matching.suggest_pack with a printed factor).
- PRICE is per unit before discount, excl. VAT. GROSS = QTY x PRICE; NET AMOUNT = GROSS less DISC %.
- VAT is a code: 3 = 19%, 4 = 5% (from the invoice's own VAT analysis).
- Free goods come as lines with no price; their pieces are averaged into the item's cost (D-009).
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import RED, ZEIN, Flag, InvoiceLine
from . import base

SUPPLIER = "Andrikian Trading Co. LTD"
SHORT_NAME = "Andrikian"
MARKERS = ("ANDRIKIAN",)

VAT_CODES = {"3": 19, "4": 5}
COLUMNS = {
    "vat": r"VAT CODE",
    "uom": r"U\.?O\.?M",
    "qty": r"QTY",
    "price": r"PRICE",
    "disc": r"DISC",
    "net": r"NET AMOUNT",
    "gross": r"GROSS",
    "barcode": r"ITEM CODE",
    "description": r"DESCRIPTION",
}
REQUIRED = "uom"
EDITABLE = {"uom": "U.O.M. (pack size)", "qty": "QTY", "price": "PRICE", "disc": "DISC. %", "net": "NET AMOUNT",
            "gross": "GROSS VALUE"}
NUMBER = [r"REFERENCE\s*:?\s*([A-Z]{2,}\d{4,})"]
DATE = [r"DOC\.?\s*DATE\s*:?\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"PAYABLE AMOUNT\s*(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    return "ANDRIKIAN" in page_text.upper()


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def adjust(invoice, text):
    m = re.search(r"EXTRA DISC\.?\s*([\d.,]+)", text)
    base.spread_discount(invoice, parse_number(m.group(1)) or 0.0 if m else 0.0)


def row_to_line(row) -> InvoiceLine | None:
    qty, uom, price, net, gross = (parse_number(row[k].text) for k in ("qty", "uom", "price", "net", "gross"))
    if qty is None and net is None:
        return None
    flags = []
    vat = VAT_CODES.get(row["vat"].text.strip())
    if vat is None:
        flags.append(Flag(RED, "row", f"Unknown VAT code '{row['vat'].text}' on the invoice.", ZEIN))
        vat = 0
    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    disc = (parse_number(row["disc"].text) or 0.0) / 100

    if qty and price is None and net is None and gross is None:
        net = 0.0  # free goods ('buy 2 get 1'): no price printed; averaged into the item's cost (D-009)
    elif None in (qty, price, net, gross) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or amount"))
        qty, net = qty or 0, net or 0
    else:
        for check in (base.arithmetic_flag(f"{qty:g} x {price:.2f}", qty * price, gross),
                      base.arithmetic_flag(f"{gross:.2f} less {disc:.0%}", gross * (1 - disc), net)):
            flags += [check] if check else []
    if uom is None:
        flags += base.confidence_flags({"quantity": row["uom"]}) or [base.unreadable_flag("The pack size (U.O.M.)")]

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=qty, amount_excl_vat=net, vat_rate=vat,
        list_price_excl_vat=net / qty if qty else None,
        printed_factor=uom if uom and uom > 1 else None, flags=flags,
    )
