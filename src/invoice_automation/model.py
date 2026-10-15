"""Data passed between the steps: what was read from an invoice, and why something is flagged."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Flag levels (D-011). Red outranks orange outranks yellow.
YELLOW, ORANGE, RED = "yellow", "orange", "red"
SEVERITY = {YELLOW: 1, ORANGE: 2, RED: 3}

# Flag kinds. Each kind becomes one type of question in the review window (D-022).
UNREADABLE = "unreadable"  # a number doesn't add up or can't be read -> staff type it from the paper
MATCH = "match"  # not sure which item this is -> "is it this item?"
PACK = "pack"  # pack size suggested or unknown -> "how many pieces in 1 unit?"
NEW = "new"  # not in PowerSoft -> identify it, or fill in the new-item form
NOT_STORABLE = "not_storable"  # matched a pack item that holds no stock -> identify the single item
ZEIN = "zein"  # nothing staff can answer from the paper
INFO = ""  # report only (cost changes, notes); no question


@dataclass
class Flag:
    level: str  # YELLOW / ORANGE / RED
    column: str  # output column the flag belongs on: "quantity", "cost", "item", or "row"
    message: str  # plain language, shown in the report and the cell comment
    kind: str = INFO
    data: dict = field(default_factory=dict)  # extras for the question, e.g. {"suggested": 24}


@dataclass
class InvoiceLine:
    line_no: str
    description: str
    barcode: str
    quantity: float  # in the invoice's own unit (a can, a case...)
    amount_excl_vat: float  # what this line cost, after discounts, before VAT
    vat_rate: int  # 0, 5 or 19
    list_price_excl_vat: float | None = None  # price of one invoice unit before discounts (for pack-size checks)
    pieces_known: bool = False  # True if the invoice printed the pack factor and quantity is already in pieces
    printed_factor: float | None = None  # a pack size the invoice prints but that needs the price to confirm it
    supplier_code: str = ""  # the supplier's own item code, a learning key that survives OCR noise in names
    flags: list[Flag] = field(default_factory=list)
    page: int = 0  # which page of the PDF the line is on
    row_index: int = -1  # position in that page's table, including non-item rows
    box: tuple[float, float, float, float] | None = None  # where the line is on the page (inches)
    header_box: tuple[float, float, float, float] | None = None  # the table's header row on that page
    angle: float = 0.0  # the page's rotation (degrees clockwise), for turning crops upright
    fields: dict[str, str] = field(default_factory=dict)  # the printed numbers staff may correct, as read

    @property
    def key(self) -> str:
        """Identifies the line across re-evaluations: answers are stored under it."""
        return f"{self.page}:{self.row_index}"


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
    page_angle: float = 0.0  # first page's rotation, degrees clockwise; 90 for a page scanned sideways
