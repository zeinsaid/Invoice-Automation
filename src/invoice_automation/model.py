"""Data passed between the steps: what was read from an invoice, and why something is flagged."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Flag levels (D-011). Red outranks orange outranks yellow.
YELLOW, ORANGE, RED = "yellow", "orange", "red"
SEVERITY = {YELLOW: 1, ORANGE: 2, RED: 3}


@dataclass
class Flag:
    level: str  # YELLOW / ORANGE / RED
    column: str  # output column the flag belongs on: "quantity", "cost", "item", or "row"
    message: str  # plain language, shown to staff in the cell comment and the report


@dataclass
class InvoiceLine:
    line_no: str
    description: str
    barcode: str
    quantity: float  # in the invoice's own unit (a can, a case...)
    amount_excl_vat: float  # what this line cost, after discounts, before VAT
    vat_rate: int  # 0, 5 or 19
    list_price_excl_vat: float | None = None  # price of one invoice unit before discounts (for pack-size checks)
    flags: list[Flag] = field(default_factory=list)


@dataclass
class Invoice:
    supplier: str  # PowerSoft supplier name
    short_name: str  # used in output file names
    number: str | None
    date: date | None
    lines: list[InvoiceLine]
    printed_total: float | None  # incl. VAT, as printed; None if not found
    computed_total: float  # incl. VAT, summed from the lines
    source: Path
    pages: list[int]
    flags: list[Flag] = field(default_factory=list)  # invoice-wide flags
