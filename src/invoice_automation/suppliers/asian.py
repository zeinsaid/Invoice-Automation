"""Asian Food Market (Zheng Donischal Ltd) order invoice (D-030). Their till receipt is still entered by hand.

Columns: NO. | BAR CODE | NAME | UNIT | QUANTITY | PRICE | AMOUNT | NOTES
- Names are English plus Chinese; the Chinese part is dropped (it never matches our names).
- Units are bottles and bags; the barcode is the piece's own.
- No VAT is printed. Prices include it, so each line takes its item's VAT rate from PowerSoft (pipeline).
- We get 15% off every order, which the paper doesn't show: TOTAL AMOUNT 586 is 498.10 paid.
- Order number 'SXS-2026-10-26-00007', date '2026-10-26', numbers with a dot decimal.
"""

import re
import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Asian Food Market LTD"
SHORT_NAME = "Asian"
DISCOUNT = 0.15  # standing discount on every order, not printed (Zein, 2026-10-27)

COLUMNS = {
    "no": r"^NO\.?$",
    "barcode": r"BAR ?CODE",
    "description": r"^NAME",
    "qty": r"QUANTITY",
    "price": r"^PRICE",
    "amount": r"^AMOUNT",
}
REQUIRED = "barcode"
EDITABLE = {"qty": "Quantity", "price": "Price", "amount": "Amount"}
NUMBER = [r"ORDER NO\s*\.?\s*:?\s*([A-Z]{2,4}-[\d-]{8,})"]
DATE = [r"DATE\s*:?\s*(\d{4}-\d{2}-\d{2})"]
TOTAL = [r"TOTAL AMOUNT\s*:?\s*(\d[\d,]*(?:\.\d+)?)"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return "ZHENG DONISCHAL" in text and "ORDER NO" in text  # the till receipt has neither 'ORDER NO' nor a table


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def adjust(invoice, text: str) -> None:
    """The 15% comes off every line, so each item's cost includes it. The total on the paper stays as
    printed; the total check takes the discount off it (pipeline)."""
    m = re.search(TOTAL[0], text, flags=re.IGNORECASE)
    invoice.printed_total = _number(m.group(1)) if m else None  # '1,586' is 1586 here, not 1.586
    invoice.discount = DISCOUNT
    for line in invoice.lines:
        line.amount_incl_vat *= 1 - DISCOUNT
        line.amount_excl_vat = line.amount_incl_vat  # until the pipeline knows the VAT rate


def row_to_line(row) -> InvoiceLine | None:
    if not row["no"].text.strip().isdigit():
        return None  # the SUM row
    qty, price, amount = (_number(row[k].text) for k in ("qty", "price", "amount"))
    flags = []
    if None in (qty, price, amount) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or amount"))
        qty, amount = qty or 0, amount or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:g}", qty * price, amount)
        flags += [check] if check else []
    barcode = normalise_barcode(row["barcode"].text)
    flag = base.barcode_flag(barcode)
    flags += [flag] if flag else []
    name = " ".join(re.sub(r"[^\x00-\x7F]+", " ", row["description"].text).split())
    # VAT 0 until the item is known: the pipeline then applies the item's rate to amount_incl_vat.
    return InvoiceLine(
        line_no="", description=name, barcode=barcode, quantity=qty, amount_excl_vat=amount, vat_rate=0,
        list_price_excl_vat=price, amount_incl_vat=amount, flags=flags,
    )


def _number(text: str) -> float | None:
    return parse_number(text.replace(",", ""))  # dot decimal only: a comma separates thousands
