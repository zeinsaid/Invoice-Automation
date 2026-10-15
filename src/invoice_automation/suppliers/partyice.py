"""Party Ice profile (ice bags). Same billing software as Cassandra, Cosmos and Fereos.

Columns: ΚΩΔΙΚΟΣ / BARCODE | ΠΡΟΙΟΝ | Μ.Μ UOM | ΠΟΣ. QTY | ΤΙΜΗ PRC | ΕΚΠΤ. DISC | ΦΠΑ VAT | ΣΥΝ. TOTAL
- The first cell is 'code/ barcode' ('1003/ 5290750000152').
- UOM is 'PIECE/ 1': a pack size, normally 1.
- PRC is per unit excl. VAT; DISC is a percentage; TOTAL includes VAT.
"""

import re
import sys

from ..layout import parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Party Ice & Party Time Ice LTD"
SHORT_NAME = "Party Ice"
MARKERS = ("PARTY ICE", "PARTY TIME ICE")

COLUMNS = {
    "code": r"BARCODE|KΩΔIKOΣ",
    "product": r"PRODUCT|[ΠN]POION",
    "uom": r"UOM|^M\.?M",
    "qty": r"QTY|^ΠOΣ",
    "price": r"PRC|TIMH",
    "disc": r"DISC|^EK",
    "vat": r"VAT|ΦΠA",
    "total": r"TOTAL|ΣYN",
}
REQUIRED = "uom"
EDITABLE = {"qty": "ΠΟΣ. QTY", "price": "ΤΙΜΗ PRC", "disc": "ΕΚΠΤ. DISC %", "total": "ΣΥΝ. TOTAL"}
NUMBER = [r"Document No:?\s*(\d{8,})"]
DATE = [r"\bDate:\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"TOTAL €\s*(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def row_to_line(row) -> InvoiceLine | None:
    qty, price, total = (parse_number(row[k].text) for k in ("qty", "price", "total"))
    if qty is None and total is None:
        return None
    flags = []
    code, barcode, _ = base.split_code_and_barcode(row["code"].text)
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc"].text) or 0.0) / 100
    factor = next((parse_number(x) for x in reversed(re.findall(r"\d+", row["uom"].text))), None)

    if None in (qty, price, total) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or total"))
        qty, price = qty or 0, price or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:.2f} less {disc:.0%} plus VAT",
                                     qty * price * (1 - disc) * (1 + vat / 100), total)
        flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=row["product"].text, barcode=barcode,
        quantity=qty, amount_excl_vat=qty * price * (1 - disc), vat_rate=vat,
        list_price_excl_vat=price * (1 - disc),
        printed_factor=factor if factor and factor > 1 else None,
        supplier_code=code, flags=flags,
    )
