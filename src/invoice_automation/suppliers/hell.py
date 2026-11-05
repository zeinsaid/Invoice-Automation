"""Hell Beverages profile (Hell energy drinks, Xixo iced tea, iced coffee). Two pages; the second only has the totals.

Columns: Item Code | Description | Qty | Price | Disc % | Vat % | Amount
- Item Code is the barcode of ONE can (the same barcodes Athienitis' Hell cans have in PowerSoft).
- Qty is in cases; the case size is in the description: 'HELL CLASSIC 250ML X 24' is 24,
  '500ML X 12' is 12. The price per case confirms it (matching.suggest_pack), as for Coca-Cola.
- Price is per case before VAT; Amount = Qty x Price less Disc %, before VAT. VAT % per line (19 or 5).
- Hell rounds the VAT of each line, not of each rate: 10.60 at 19% is 2.01, never 2.014. On a long
  order that adds up to more than the total check allows, so the lines are added up the same way.
- 'Document No. : INIC2105219' and the date on every page, so the pages join by number (D-004); the
  total with VAT ('Total: 346.53') is on the last page. Dot decimals.
- The paper says 'CREDIT INVOICE': an invoice paid on credit terms, not a credit note.
"""

import sys

from ..layout import normalise_barcode, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Hell Beverages LTD"  # as spelled in PowerSoft
SHORT_NAME = "Hell"
MARKERS = ("HELL BEVERAGES",)  # not 'HELL': Athienitis invoices print Hell cans too
VAT_PER_LINE = True

COLUMNS = {
    "barcode": r"^ITEM CODE",
    "description": r"^DESCRIPTION",
    "qty": r"^QTY",
    "price": r"^PRICE",
    "disc": r"^DISC",
    "vat": r"^VAT",
    "amount": r"^AMOUNT",
}
REQUIRED = "barcode"
EDITABLE = {"qty": "Qty (cases)", "price": "Price", "disc": "Disc %", "amount": "Amount"}
NUMBER = [r"Document No\.?\s*:?\s*([A-Z]{2,}\d{5,})"]
DATE = [r"Document Date\s*:?\s*(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"\bTotal:\s*(\d[\d,]*\.\d{2})"]


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def row_to_line(row) -> InvoiceLine | None:
    if not row["barcode"].text.strip() and not row["description"].text.strip():
        return None  # an empty row
    qty, price, amount = (parse_number(row[k].text) for k in ("qty", "price", "amount"))
    if qty is None and amount is None:
        return None
    flags = []
    barcode = normalise_barcode(row["barcode"].text)
    flags += [f for f in [base.barcode_flag(barcode)] if f]
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    disc = (parse_number(row["disc"].text) or 0.0) / 100
    size = base.case_size(row["description"].text)

    if None in (qty, price, amount) or not qty:
        flags.append(base.unreadable_flag("Qty, price or amount"))
        qty, amount = qty or 0, amount or 0
    else:
        check = base.arithmetic_flag(f"{qty:g} x {price:.2f}" + (f" less {disc:.0%}" if disc else ""),
                                     qty * price * (1 - disc), amount)
        flags += [check] if check else []

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode=barcode,
        quantity=qty, amount_excl_vat=amount, vat_rate=vat,
        list_price_excl_vat=amount / qty if qty else None,  # what we pay per case, after the discount
        printed_factor=size if size and size > 1 else None, flags=flags,
    )
