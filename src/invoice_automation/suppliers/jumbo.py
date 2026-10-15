"""Jumbo Trading profile (electronics accessories, batteries). Greek, faint print, decimal commas.

Columns: ΚΩΔΙΚΟΣ | ΠΕΡΙΓΡΑΦΗ | ΠΟΣΟΤΗΣ | ΤΙΜΗ ΜΟΝΑΔΟΣ | ΕΚΠΤΩΣΗ | ΚΑΘΑΡΗ ΑΞΙΑ | Φ.Π.Α. % | Φ.Π.Α | ΚΑΘΑΡΗ ΑΞΙΑ + Φ.Π.Α.
- ΚΩΔΙΚΟΣ is Jumbo's own code, the learning key: descriptions are Greek abbreviations ('ΚΑΛ TYPE-C')
  that won't match our English names, so staff identify each item once (D-022) and the code is
  remembered. Staff sometimes write our item code next to it ('1171628 1604'); only the first
  number is Jumbo's.
- Some descriptions end with a real barcode; others with a Jumbo number that isn't one.
- Prices have 5 decimals; ΚΑΘΑΡΗ ΑΞΙΑ is excl. VAT, the last column incl. VAT.
"""

import re
import sys

from ..layout import parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Jumbo Trading LTD"
SHORT_NAME = "Jumbo"
MARKERS = ("JUMBO TRADING",)

COLUMNS = {
    "total": r"\+",
    "code": r"KΩΔIKOΣ",
    "description": r"ΠEPIΓPAΦH",
    "qty": r"ΠOΣOTHΣ",
    "price": r"TIMH",
    "disc": r"EKΠTΩΣH",
    "net": r"KAΘAPH",
    "vat_pct": r"%",
    "vat_amount": r"Φ\.?Π\.?A",
}
REQUIRED = "net"
EDITABLE = {"qty": "ΠΟΣΟΤΗΣ", "price": "ΤΙΜΗ ΜΟΝΑΔΟΣ", "disc": "ΕΚΠΤΩΣΗ", "net": "ΚΑΘΑΡΗ ΑΞΙΑ",
            "total": "ΚΑΘΑΡΗ ΑΞΙΑ + Φ.Π.Α."}
NUMBER = [r"ΠΑΡΑΣΤΑΤΙΚΟΥ\s+\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s+(\d+)"]
DATE = [r"ΠΑΡΑΣΤΑΤΙΚΟΥ\s+(\d{2}/\d{2}/\d{4})"]
TOTAL = [r"([\d.]+,\d{2})\s+ΣΕΛΙΔΑ"]  # the payable amount is the last number before 'ΣΕΛΙΔΑ: 1 ΑΠΟ 1'


def matches(page_text: str) -> bool:
    return "JUMBO TRADING" in page_text.upper()


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)


def row_to_line(row) -> InvoiceLine | None:
    qty, price, net, total = (parse_number(row[k].text) for k in ("qty", "price", "net", "total"))
    if qty is None and net is None:
        return None
    flags = []
    _, barcode, _ = base.split_code_and_barcode(row["description"].text)
    name = re.sub(r"\s*\d{8,}.*$", "", row["description"].text).strip(" .·")  # drop the trailing number
    vat, vat_flag = base.vat_from_percent(row["vat_pct"])
    flags += [vat_flag] if vat_flag else []
    discount = parse_number(row["disc"].text) or 0.0

    if None in (qty, price, net, total) or not qty:
        flags.append(base.unreadable_flag("Quantity, price or amount"))
        qty, net = qty or 0, net or 0
    else:
        for check in (base.arithmetic_flag(f"{qty:g} x {price:.5f}", qty * price - discount, net),
                      base.arithmetic_flag(f"{net:.2f} plus VAT", net * (1 + vat / 100), total)):
            flags += [check] if check else []

    code = (re.findall(r"\d+", row["code"].text) or [""])[0]
    return InvoiceLine(
        line_no="", description=name, barcode=barcode,
        quantity=qty, amount_excl_vat=net, vat_rate=vat,
        list_price_excl_vat=net / qty if qty else None,
        supplier_code=code, flags=flags,
    )
