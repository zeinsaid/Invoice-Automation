"""Shared parsing for suppliers whose invoices are one printed table of lines (D-005, D-021).

A supplier module describes its invoice and turns one table row into an InvoiceLine:

    SUPPLIER, SHORT_NAME   PowerSoft supplier name, short name for file names
    MARKERS                text that identifies the supplier's pages (upper case)
    COLUMNS, REQUIRED      header patterns for the line table (see layout.find_table)
    EDITABLE               {field: label} for the printed numbers staff may correct (D-022)
    NUMBER, DATE, TOTAL    regex patterns (first group) for invoice number, date, printed total
    row_to_line(row)       one table row -> InvoiceLine, or None if it isn't an item row

This module does the rest the same way for everyone: find the table, apply staff corrections,
number the lines, find the header fields and the total.
"""

import re
from dataclasses import replace
from datetime import date

from ..layout import Cell, ean_is_valid, find_table, parse_number
from ..model import RED, UNREADABLE, YELLOW, ZEIN, Flag, Invoice, InvoiceLine

MIN_CONFIDENCE = 0.9  # below this, a number no check covers is flagged yellow (D-021)


def parse(profile, result: dict, source, page_index: int, corrections: dict | None = None) -> Invoice:
    """`corrections` maps a table row index to {field: text} typed by staff from the paper (D-022)."""
    corrections = corrections or {}
    text = result.get("content", "")
    lines = []
    rows = find_table(result, profile.COLUMNS, profile.REQUIRED)
    for row_index, row in enumerate(rows):
        fixed = corrections.get(str(row_index))
        if fixed:
            row = dict(row)
            for name, value in fixed.items():
                row[name] = replace(row[name], text=value, confidence=1.0)
        line = profile.row_to_line(row)
        if line is None:
            continue  # not an item row (e.g. handwriting caught in the table)
        if fixed:
            # Staff typed these numbers from the paper. If they still don't add up, the supplier
            # printed it that way; don't ask again.
            line.flags = [f for f in line.flags if f.kind != UNREADABLE]
        line.line_no = str(len(lines) + 1)  # by position: printed line numbers get pen-damaged
        line.row_index = row_index
        line.box = row["_row"].box
        line.fields = {name: row[name].text for name in profile.EDITABLE}
        lines.append(line)

    page = result["pages"][0]
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
        page_size=(page.get("width", 0.0), page.get("height", 0.0)),
        page_angle=page.get("angle", 0.0) or 0.0,
        header_box=rows[0]["_header"].box if rows else None,
    )
    if not lines:
        invoice.flags.append(Flag(RED, "row", "No item lines could be read from this page.", ZEIN))
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
    those three were read correctly whatever their confidence (D-021 amendment). Barcodes are
    vouched for by their check digit, and names go through matching.
    """
    flags = []
    for column, cell in cells.items():
        if cell.text and cell.confidence is not None and cell.confidence < MIN_CONFIDENCE:
            flags.append(Flag(YELLOW, column, f"'{cell.text}' was hard to read.", UNREADABLE))
    return flags


def arithmetic_flag(description: str, computed: float, printed: float) -> Flag | None:
    """D-010 amendment: quantity x price (+ discounts, VAT) should give the printed line amount.
    Allows 2 cents plus 0.1% for printed rounding."""
    if abs(computed - printed) <= 0.02 + 0.001 * abs(printed):
        return None
    return Flag(YELLOW, "quantity", f"{description} gives {computed:.2f}, but the line says {printed:.2f}. "
                                    "Something was misread.", UNREADABLE)


def unreadable_flag(what: str) -> Flag:
    return Flag(RED, "quantity", f"{what} could not be read.", UNREADABLE)


def barcode_flag(barcode: str) -> Flag | None:
    """A barcode with a wrong check digit is just not used for matching (matching falls back to the name)."""
    if barcode and not ean_is_valid(barcode):
        return Flag(YELLOW, "item", f"Barcode {barcode} looks misread (check digit wrong).")
    return None


def vat_from_percent(cell: Cell) -> tuple[int, Flag | None]:
    rate = parse_number(cell.text)
    if rate is None or round(rate) not in (0, 3, 5, 9, 19):
        return 0, Flag(RED, "row", f"VAT rate '{cell.text}' could not be read.", ZEIN)
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
