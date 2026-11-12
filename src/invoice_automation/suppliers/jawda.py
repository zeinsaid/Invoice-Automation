"""Jawda LTD profile (Zeina tissues). A new supplier from November 2026 (D-035); first invoice # 105.

Columns: Περιγραφή (description) | Ποσότητα (quantity) | Τιμή (EURO) (price)
- A short, typed invoice: no barcodes, no item codes, no line totals. Lines are matched by name, and the
  first time each product is new: staff scan the barcode on ONE piece.
- Quantity is in the supplier's unit (a bag, a box); the pieces are in the description ('18packs/bag',
  '12mltp/box') and the new-item form starts at that number. The price checks it once a cost is known.
- Τιμή is taken as the price of one unit before VAT, so a line is quantity x price. Every line so far has
  quantity 1, so it could also be the line amount; the total check would catch it on a line with more.
- VAT is printed once for the invoice ('ΦΠΑ (19%)') and applies to every line.
- Under the lines, 'Σύνολο' (the sum before VAT) can be wrong: # 105 prints 67.60 for lines adding up to
  67.20. Its VAT (12.77) and 'Τελική τιμή' (79.97) are right, so the total checked is 'Τελική τιμή'.
- '# 105' and a date like 7/11/2026 (no leading zero).
"""

import re
import sys
import unicodedata

from ..layout import parse_number
from ..model import InvoiceLine
from . import base

SUPPLIER = "Jawda LTD"  # as spelled in PowerSoft (supplier 10000027)
SHORT_NAME = "Jawda"
MARKERS = ("JAWDA",)
VAT_RATE = 19  # if the invoice doesn't print one

COLUMNS = {
    "description": r"^ΠEPIΓPAΦ|DESCRIPTION",
    "qty": r"^ΠOΣ|QUANTITY|^QTY",
    "price": r"^TIM|PRICE",
}
REQUIRED = "qty"
EDITABLE = {"qty": "Ποσότητα (quantity)", "price": "Τιμή (price)"}
NUMBER = [r"#\s*(\d+)"]
DATE = [r"ΗΜΕΡΟΜΗΝΙΑ\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", r"\b(\d{1,2}/\d{1,2}/\d{4})\b"]
TOTAL = [r"Τελική τιμή\s*€?\s*(\d[\d,]*\.\d{2})"]

# Rows under the lines: Σύνολο, ΦΠΑ, Τελική τιμή (compared in capitals without accents)
SUMMARY = re.compile(r"^(ΣΥΝΟΛΟ|ΦΠΑ|ΤΕΛΙΚΗ|SUBTOTAL|TOTAL|VAT)\b")
PIECES = re.compile(r"(\d+)\s*(?:PACKS?|MLTP|PCS|PIECES)\s*/\s*(?:BAG|BOX|CASE)", flags=re.IGNORECASE)


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    vat = _first_int(r"ΦΠΑ\s*\((\d+)\s*%\)", result.get("content", "")) or VAT_RATE
    invoice = base.parse(sys.modules[__name__], result, source, page_index, corrections)
    for line in invoice.lines:
        line.vat_rate = vat
    invoice.computed_total = base.computed_total(invoice.lines)
    return invoice


def row_to_line(row) -> InvoiceLine | None:
    description = row["description"].text.strip()
    if not description or SUMMARY.match(_plain(description)):
        return None
    qty, price = parse_number(row["qty"].text), parse_number(row["price"].text)
    if qty is None and price is None:
        return None
    flags = []
    if None in (qty, price) or not qty:
        flags.append(base.unreadable_flag("Quantity or price"))
        qty, price = qty or 0, price or 0
    else:
        flags += base.confidence_flags({"quantity": row["qty"], "cost": row["price"]})  # no line total to check them
    pieces = pieces_per_unit(description)
    return InvoiceLine(
        line_no="", description=description, barcode="",
        quantity=qty, amount_excl_vat=round(qty * price, 2), vat_rate=VAT_RATE,
        list_price_excl_vat=price, printed_factor=pieces, flags=flags,
    )


def pieces_per_unit(description: str) -> int | None:
    """'Zeina Peach 500ply 18packs/bag' -> 18; 'Zeina pocket 10packs/multipack 12mltp/box' -> 12 (per box;
    '10packs/multipack' is what's inside each multipack)."""
    found = PIECES.findall(description)
    return int(found[-1]) if found else None


def _plain(text: str) -> str:
    """'Σύνολο' -> 'ΣΥΝΟΛΟ': capitals, accents dropped."""
    return "".join(c for c in unicodedata.normalize("NFD", text.upper()) if not unicodedata.combining(c))


def _first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None
