"""Renos Agrotis profile (stationery): the warehouse invoice. Often two or three pages; the total is on
the last one. Their shop-counter invoice is a different layout: agrotis_pos.py.

Columns: # | Code | BarCode | Description | Qty | UOM | Price | Dis. | Value | Tax | Total
- UOM is the pack size ('x12'); some of our items are the pack itself, so the price decides
  (matching.suggest_pack with a printed factor).
- Price is per unit before discount, Value after discount, both excl. VAT. Total = Qty x Value, excl. VAT.
"""

import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Renos Agrotis & Son Ltd"
SHORT_NAME = "Agrotis"
MARKERS = ("AGROTIS",)

COLUMNS = {
    "code": r"^CODE",
    "barcode": r"BARCODE",
    "description": r"DESCRIPTION",
    "qty": r"^QTY",
    "uom": r"^UOM",
    "price": r"^PRICE",
    "disc": r"^DIS",
    "value": r"^VALUE",
    "vat": r"^TAX",
    "total": r"^TOTAL",
}
REQUIRED = "uom"
EDITABLE = {"qty": "Qty", "uom": "UOM (pack size)", "price": "Price", "disc": "Dis. %", "value": "Value",
            "total": "Total"}
NUMBER = [r"/Page\s+(\d{5,})\s"]
DATE = [r"/Page\s+\d{5,}\s+(\d{2}\.\d{2}\.\d{4})"]
TOTAL = [r"Total\s*:\s*EUR\s*(\d[\d,]*\.\d{2})"]  # last page: 'Σύνολο / Total :\nEUR 1,234.50'


def matches(page_text: str) -> bool:
    return "AGROTIS" in page_text.upper()  # agrotis_pos is tried first and takes its own pages


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def row_to_line(row) -> InvoiceLine | None:
    qty, price, value, total = (parse_number(row[k].text) for k in ("qty", "price", "value", "total"))
    if qty is None and total is None:
        return None
    flags = []
    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc"].text) or 0.0) / 100
    uom = parse_number(row["uom"].text.lower().replace("x", "").replace("×", ""))

    if None in (qty, price, value, total) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or total"))
        qty, total = qty or 0, total or 0
    else:
        for check in (base.arithmetic_flag(f"{price:.3f} less {disc:.0%}", price * (1 - disc), value),
                      base.arithmetic_flag(f"{qty:g} x {value:.2f}", qty * value, total)):
            flags += [check] if check else []
    if uom is None:
        flags.append(base.unreadable_flag("The pack size (UOM)"))

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=qty, amount_excl_vat=total, vat_rate=vat,
        list_price_excl_vat=total / qty if qty else None,
        printed_factor=uom if uom and uom > 1 else None,
        supplier_code=row["code"].text.strip(), flags=flags,
    )
