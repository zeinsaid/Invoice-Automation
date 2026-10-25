"""Renos Agrotis, shop-counter invoice ('SALES POS 02'): what staff get when buying at their shop
rather than by order. Same supplier as agrotis.py, different printout, in Greek:

Columns: Κωδ.Είδους | Περιγραφή | Ποσ. | M/M | Αξία | Σύνολο | Έκπτωση | ΦΠΑ | Σύνολο
- No barcode column: the Agrotis code (TTPA4100) is the learning key, like Pambos' codes.
- M/M is the pack size ('x1'), Αξία the price of one unit and the first Σύνολο the line before VAT,
  Έκπτωση a discount amount, the last Σύνολο the line with VAT. Decimal commas.
- Invoice number 'S02 - 1234567' (the till, then the number), total 'ΟΛΙΚΟ ΤΙΜΟΛΟΓΙΟΥ 123,45'.
Headers are matched after Greek look-alikes become Latin letters (layout.latinise): 'Ποσ.' is 'ΠOΣ.'.
"""

import re
import sys

from ..layout import latinise, parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Renos Agrotis & Son Ltd"
SHORT_NAME = "Agrotis"
NUMBER_PATTERN = r"\b(S\d{2}\s*-\s*\d{5,})"  # also what tells this printout from the warehouse invoice

COLUMNS = {  # the two 'Σύνολο' columns: the first one found is the net, the second the total with VAT
    "code": r"^KΩΔ",
    "description": r"^ΠEPIΓ",
    "qty": r"^ΠOΣ",
    "uom": r"^M/M",
    "price": r"^A\S{1,2}A$",  # 'Αξία', which the scanner also reads as 'AĘia'
    "net": r"^Σ\S?NOΛO",
    "discount": r"KΠTΩΣ",
    "vat": r"^ΦΠA",
    "total": r"^Σ\S?NOΛO",
}
REQUIRED = "uom"
EDITABLE = {"qty": "Ποσ. (quantity)", "uom": "M/M (pack size)", "price": "Αξία (price)", "net": "Σύνολο (before VAT)",
            "discount": "Έκπτωση (discount)", "total": "Σύνολο (with VAT)"}
NUMBER = [NUMBER_PATTERN]
DATE = [r"[ΜM][ΗH][ΝN][ΙI][ΑA]\s*(\d{2}/\d{2}/\d{4})", r"\b(\d{2}/\d{2}/\d{4})\b"]
TOTAL = [r"[ΟO]Λ[ΙI][ΚK][ΟO]\s+\S+\s+(\d[\d.]*,\d{2})"]


def matches(page_text: str) -> bool:
    return "AGROTIS" in page_text.upper() and re.search(NUMBER_PATTERN, page_text) is not None


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def adjust(invoice, text: str) -> None:
    """'S02 - 1234567' and 'S02-1234567' are the same invoice: the duplicate check needs one spelling."""
    if invoice.number:
        invoice.number = re.sub(r"\s+", "", invoice.number)


def row_to_line(row) -> InvoiceLine | None:
    qty, price, net, total = (parse_number(row[k].text) for k in ("qty", "price", "net", "total"))
    if qty is None and total is None:
        return None
    flags = []
    vat, vat_flag = base.vat_from_percent(row["vat"])
    flags += [vat_flag] if vat_flag else []
    discount = parse_number(row["discount"].text) or 0.0
    uom = parse_number(row["uom"].text.lower().replace("x", "").replace("×", ""))

    if None in (qty, price, net, total) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or total"))
        qty, net = qty or 0, net or 0
    else:
        # The printed price is rounded to 2 decimals (10 x 1.50 may be printed as 15.01), so the line
        # amounts are the ones to trust; the checks catch a misread digit.
        for check in (base.arithmetic_flag(f"{qty:g} x {price:.2f} less {discount:.2f}", qty * price - discount, net),
                      base.arithmetic_flag(f"{net:.2f} plus VAT", net * (1 + vat / 100), total)):
            flags += [check] if check else []
    if uom is None:
        flags.append(base.unreadable_flag("The pack size (M/M)"))

    return InvoiceLine(
        line_no="", description=row["description"].text, barcode="",
        quantity=qty, amount_excl_vat=net, vat_rate=vat,
        list_price_excl_vat=net / qty if qty else None,
        printed_factor=uom if uom and uom > 1 else None,
        supplier_code=latinise(row["code"].text), flags=flags,  # 'ΤΤΡΑ4100' -> 'TTPA4100'
    )
