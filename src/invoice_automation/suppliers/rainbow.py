"""Rainbow Agencies profile (art supplies). Printed by PowerSoft's own invoicing.

Columns: BARCODE | ITEM CODE | DESCRIPTION | QTY | RETAIL W/OUT VAT | DISC % | NET VALUE | VAT
- Big discounts on every line (35-38%); our cost is after discount (D-009).
- Sometimes an extra 'ADDITIONAL DISCOUNT' on the whole invoice, shared over the lines.
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Rainbow Agencies LTD"
SHORT_NAME = "Rainbow"
MARKERS = ("RAINBOW AGENCIES",)

COLUMNS = {
    "barcode": r"BARCODE",
    "code": r"ITEM CODE",
    "description": r"DESCRIPTION",
    "qty": r"QTY",
    "price": r"RETAIL",
    "disc": r"DISC",
    "net": r"NET VALUE",
    "vat": r"^VAT",
}
REQUIRED = "net"
EDITABLE = {"qty": "QTY", "price": "RETAIL W/OUT VAT", "disc": "DISC %", "net": "NET VALUE"}
NUMBER = [r"INVOICE NUMBER:?\s*(IN\d+)"]
DATE = [r"INVOICE DATE:?\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"TOTAL AMOUNT\s*€?\s*(\d+[.,]\d{2})"]


def matches(page_text: str) -> bool:
    return "RAINBOW AGENCIES" in page_text.upper()


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def adjust(invoice, text):
    # 'ADDITIONAL DISCOUNT ... 0.03% 0.04': the euro amount follows a percentage with decimals
    # (the VAT rate, '19%', has none). A share bigger than 30% can't be right: ignore it.
    m = re.search(r"ADDITIONAL DISCOUNT.*?\b(\d+\.\d+)%\s+(\d+\.\d{2})\b", text, flags=re.DOTALL)
    net = sum(line.amount_excl_vat for line in invoice.lines)
    if m and net and float(m.group(2)) < 0.3 * net:
        base.spread_discount(invoice, float(m.group(2)))


def row_to_line(row) -> InvoiceLine | None:
    qty, price, net = (parse_number(row[k].text) for k in ("qty", "price", "net"))
    if qty is None and net is None:
        return None
    flags = []
    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc"].text) or 0.0) / 100

    if None in (qty, price, net) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or net value"))
        qty, net = qty or 0, net or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:.2f} less {disc:.0%}", qty * price * (1 - disc), net)
        flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=qty, amount_excl_vat=net, vat_rate=vat,
        list_price_excl_vat=net / qty if qty else None,
        supplier_code=row["code"].text.strip(), flags=flags,
    )
