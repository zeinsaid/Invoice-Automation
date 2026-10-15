"""Shared parsing for suppliers whose invoices are one printed table of lines (D-005, D-021).

A supplier module describes its invoice and turns one table row into an InvoiceLine:

    SUPPLIER, SHORT_NAME   PowerSoft supplier name, short name for file names
    MARKERS                text that identifies the supplier's pages (upper case)
    COLUMNS, REQUIRED      header patterns for the line table (see layout.find_table)
    EDITABLE               {field: label} for the printed numbers staff may correct (D-022)
    NUMBER, DATE, TOTAL    regex patterns (first group) for invoice number, date, printed total
    row_to_line(row)       one table row -> InvoiceLine, or None if it isn't an item row
    adjust(invoice, text)  optional: invoice-wide changes, e.g. a discount on the whole invoice

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
        line.page = page_index
        line.row_index = row_index
        line.box = row["_row"].box
        line.header_box = row["_header"].box
        line.angle = result["pages"][0].get("angle", 0.0) or 0.0
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
        page_angle=page.get("angle", 0.0) or 0.0,
    )
    adjust = getattr(profile, "adjust", None)
    if adjust:
        adjust(invoice, text)
        invoice.computed_total = computed_total(invoice.lines)
    return invoice


def combine(pages: list[Invoice]) -> Invoice:
    """Several pages of one invoice (D-004): lines in order, header from the first page that has
    it, the total from the last page that prints one."""
    first = pages[0]
    lines = [line for p in pages for line in p.lines]
    for i, line in enumerate(lines, 1):
        line.line_no = str(i)
    invoice = Invoice(
        supplier=first.supplier, short_name=first.short_name,
        number=next((p.number for p in pages if p.number), None),
        date=next((p.date for p in pages if p.date), None),
        lines=lines,
        printed_total=next((p.printed_total for p in reversed(pages) if p.printed_total is not None), None),
        computed_total=computed_total(lines),
        source=first.source, pages=[i for p in pages for i in p.pages],
        flags=[f for p in pages for f in p.flags], page_angle=first.page_angle,
    )
    if not lines:
        invoice.flags.append(Flag(RED, "row", "No item lines could be read.", ZEIN))
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


def spread_discount(invoice: Invoice, discount_excl_vat: float) -> None:
    """An invoice-wide discount (D-009) is shared over every line in proportion to its value,
    so each item's cost per piece includes its share."""
    net = sum(line.amount_excl_vat for line in invoice.lines)
    if discount_excl_vat and net:
        factor = 1 - discount_excl_vat / net
        for line in invoice.lines:
            line.amount_excl_vat *= factor
            if line.list_price_excl_vat is not None:
                line.list_price_excl_vat *= factor


def split_code_and_barcode(text: str) -> tuple[str, str, str]:
    """'1003/ 5290750000152' or '6970925916646 LEMON & LIME 1' -> (code, barcode, rest of the text).

    The barcode is the first group of 8, 12 or 13 digits with a valid check digit."""
    for m in re.finditer(r"\d{8,14}", text):
        if ean_is_valid(m.group()):
            before, after = text[:m.start()].strip(" /-"), text[m.end():].strip(" /-")
            return before, m.group(), after
    return "", "", text.strip()


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
