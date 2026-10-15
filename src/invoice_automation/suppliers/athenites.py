"""Athenites (Chr. Hadjichristofi) profile (D-020).

The invoice is a printout from the Athenites checkout till:
- columns A/A, Description, Barcode, Quantity, Unit Selling Price, Discount Amount, Amount Incl. VAT, VAT
- prices and amounts include VAT; VAT is a letter code
- the barcode is whatever their cashier scanned (a piece or a whole case)
- descriptions are cut at 30 characters
"""

import re
from datetime import date

from ..layout import find_table, parse_number, normalise_barcode, ean_is_valid
from ..model import RED, YELLOW, Flag, Invoice, InvoiceLine

SUPPLIER = "Chr. Hadjichristofi (Athienitis) Ltd"
SHORT_NAME = "Athienitis"
MARKERS = ("HADJICHRISTOF", "ATHIENITIS")  # matched against the page text, upper case

VAT_LETTERS = {"B": 5, "D": 19}  # checked against the catalogue on the first sample (D-020)
HEADERS = {
    "a/a": "line_no",
    "description": "description",
    "barcode": "barcode",
    "quantity": "quantity",
    "unit selling price": "unit_price",
    "discount amount": "discount",
    "amount incl. vat": "amount",
    "vat": "vat",
}
MIN_CONFIDENCE = 0.9  # below this, a number or barcode is flagged yellow (D-021)


def matches(page_text: str) -> bool:
    text = page_text.upper()
    return any(m in text for m in MARKERS)


def parse(result: dict, source, page_index: int) -> Invoice:
    text = result.get("content", "")
    number = _search(r"Invoice No\s*\.?\s*:?\s*(\d{6,})", text)  # read as 'Invoice No .:\n1000748334'
    when = _search(r"Date/Time:?\s*(\d{2}/\d{2}/\d{2,4})", text)

    lines = []
    for row in find_table(result, HEADERS, required="barcode"):
        qty = parse_number(row["quantity"].text)
        amount = parse_number(row["amount"].text)
        if qty is None and amount is None:
            continue  # not an item row (e.g. handwriting caught in the table)
        line = _line(row, qty, amount)
        # Lines are printed 1, 2, 3... in order; numbering by position avoids pen-damaged A/A cells.
        line.line_no = str(len(lines) + 1)
        lines.append(line)

    computed = round(sum(_incl_vat(l) for l in lines), 2)
    invoice = Invoice(
        supplier=SUPPLIER,
        short_name=SHORT_NAME,
        number=number,
        date=_date(when),
        lines=lines,
        printed_total=_printed_total(text),
        computed_total=computed,
        source=source,
        pages=[page_index],
    )
    if invoice.number is None:
        invoice.flags.append(Flag(RED, "row", "Invoice number not found on the page."))
    return invoice


def _line(row, qty, amount) -> InvoiceLine:
    flags = []
    vat_letter = row["vat"].text.strip().upper()
    vat = VAT_LETTERS.get(vat_letter)
    if vat is None:
        flags.append(Flag(RED, "row", f"Unknown VAT code '{vat_letter}' on the invoice."))
        vat = 0

    barcode = normalise_barcode(row["barcode"].text)
    if barcode and not ean_is_valid(barcode):
        flags.append(Flag(YELLOW, "item", f"Barcode {barcode} looks misread (check digit wrong)."))

    for name in ("quantity", "amount", "barcode", "unit_price"):
        cell = row[name]
        if cell.text and cell.confidence is not None and cell.confidence < MIN_CONFIDENCE:
            column = "quantity" if name == "quantity" else "cost" if name in ("amount", "unit_price") else "item"
            flags.append(Flag(YELLOW, column, f"The {name.replace('_', ' ')} '{cell.text}' was hard to read."))

    # Quantity x unit price + discount should equal the line amount. The printed unit price is
    # rounded (8 x 4.80 = 38.40 but the line says 38.39), so allow 2 cents.
    unit_price = parse_number(row["unit_price"].text)
    discount = parse_number(row["discount"].text) or 0.0
    if qty is None or amount is None:
        flags.append(Flag(RED, "quantity", "Quantity or amount could not be read."))
    elif unit_price is not None and abs(qty * unit_price + discount - amount) > 0.02:
        flags.append(Flag(YELLOW, "quantity",
                          f"Quantity x price ({qty:g} x {unit_price:.2f}) does not match the line amount {amount:.2f}."))

    qty = qty or 0.0
    amount = amount or 0.0
    return InvoiceLine(
        line_no=row["line_no"].text,
        description=row["description"].text,
        barcode=barcode,
        quantity=qty,
        amount_excl_vat=amount / (1 + vat / 100),
        vat_rate=vat,
        list_price_excl_vat=unit_price / (1 + vat / 100) if unit_price is not None else None,
        flags=flags,
    )


def _incl_vat(line: InvoiceLine) -> float:
    return line.amount_excl_vat * (1 + line.vat_rate / 100)


def _printed_total(text: str) -> float | None:
    # The totals are on the last page. Its exact layout is not known yet (the first sample's
    # page 2 was not scanned), so for now only an explicit "Total" followed by an amount counts.
    m = re.search(r"\bTOTAL\b[^\d\n]{0,30}(\d+[.,]\d{2})", text, flags=re.IGNORECASE)
    return parse_number(m.group(1)) if m else None


def _search(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _date(s: str | None) -> date | None:
    if not s:
        return None
    day, month, year = (int(x) for x in s.split("/"))
    return date(year + 2000 if year < 100 else year, month, day)
