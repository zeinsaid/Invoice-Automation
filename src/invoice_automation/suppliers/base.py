"""Shared parsing for suppliers whose invoices are one printed table of lines (D-005, D-021).

A supplier module describes its invoice and turns one table row into an InvoiceLine:

    SUPPLIER, SHORT_NAME   PowerSoft supplier name, short name for file names
    MARKERS                text that identifies the supplier's pages (upper case)
    COLUMNS, REQUIRED      header patterns for the line table (see layout.find_table)
    NUMBER, DATE, TOTAL    regex patterns (first group) for invoice number, date, printed total
    row_to_line(row)       one table row -> InvoiceLine, or None if it isn't an item row

This module does the rest the same way for everyone: find the table, number the lines, check
confidence and arithmetic, find the header fields and the total.
"""

import re
from datetime import date

from ..layout import Cell, ean_is_valid, find_table, parse_number
from ..model import RED, YELLOW, Flag, Invoice, InvoiceLine

MIN_CONFIDENCE = 0.9  # below this, a number or barcode is flagged yellow (D-021)


def parse(profile, result: dict, source, page_index: int) -> Invoice:
    text = result.get("content", "")
    lines = []
    for row in find_table(result, profile.COLUMNS, profile.REQUIRED):
        line = profile.row_to_line(row)
        if line is None:
            continue  # not an item row (e.g. handwriting caught in the table)
        line.line_no = str(len(lines) + 1)  # by position: printed line numbers get pen-damaged
        lines.append(line)

    invoice = Invoice(
        supplier=profile.SUPPLIER,
        short_name=profile.SHORT_NAME,
        number=_first(profile.NUMBER, text),
        date=_date(_first(profile.DATE, text)),
        lines=lines,
        printed_total=parse_number(_first(profile.TOTAL, text) or ""),
        computed_total=computed_total(lines),
        source=source,
        pages=[page_index],
    )
    if invoice.number is None:
        invoice.flags.append(Flag(RED, "row", "Invoice number not found on the page."))
    if not lines:
        invoice.flags.append(Flag(RED, "row", "No item lines could be read from this page."))
    return invoice


def computed_total(lines: list[InvoiceLine]) -> float:
    """Total incl. VAT the way invoices compute it: VAT on the sum per rate, rounded once."""
    by_rate: dict[int, float] = {}
    for line in lines:
        by_rate[line.vat_rate] = by_rate.get(line.vat_rate, 0.0) + line.amount_excl_vat
    return round(sum(round(net * (1 + rate / 100), 2) for rate, net in by_rate.items()), 2)


# --- Helpers for row_to_line ---------------------------------------------------------------------

def confidence_flags(cells: dict[str, Cell]) -> list[Flag]:
    """Yellow for every hard-to-read cell. `cells` maps output column ('quantity', 'cost', 'item') to a cell.

    Only used for numbers the arithmetic check can't vouch for: if quantity x price = line amount,
    those three were read correctly whatever their confidence. Barcodes are vouched for by their
    check digit, and names go through matching, so neither needs a confidence flag.
    """
    flags = []
    for column, cell in cells.items():
        if cell.text and cell.confidence is not None and cell.confidence < MIN_CONFIDENCE:
            flags.append(Flag(YELLOW, column, f"'{cell.text}' was hard to read."))
    return flags


def arithmetic_flag(description: str, computed: float, printed: float) -> Flag | None:
    """D-010 amendment: quantity x price (+ discounts, VAT) should give the printed line amount.
    Allows 2 cents plus 0.1% for printed rounding."""
    if abs(computed - printed) <= 0.02 + 0.001 * abs(printed):
        return None
    return Flag(YELLOW, "quantity", f"{description} gives {computed:.2f}, but the line says {printed:.2f}. "
                                    "Something was misread.")


def barcode_flag(barcode: str) -> Flag | None:
    if barcode and not ean_is_valid(barcode):
        return Flag(YELLOW, "item", f"Barcode {barcode} looks misread (check digit wrong).")
    return None


def vat_from_percent(cell: Cell) -> tuple[int, Flag | None]:
    rate = parse_number(cell.text)
    if rate is None or round(rate) not in (0, 3, 5, 9, 19):
        return 0, Flag(RED, "row", f"VAT rate '{cell.text}' could not be read.")
    return int(round(rate)), None


def _first(patterns, text: str) -> str | None:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        day, month, year = (int(x) for x in re.split(r"[/.\-]", s))
        return date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        return None
