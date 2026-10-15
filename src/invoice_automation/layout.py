"""Helpers for reading prebuilt-layout results (D-021): tables, cell confidence, numbers, barcodes."""

import re
from dataclasses import dataclass

# DI reports checkboxes as these markers; staff pen ticks are often read as checkboxes (D-021).
SELECTION_MARKS = re.compile(r":(un)?selected:")


@dataclass
class Cell:
    text: str
    confidence: float | None  # lowest word confidence inside the cell; None if the cell is empty


def clean_text(text: str) -> str:
    """Remove checkbox markers and collapse whitespace/line breaks."""
    return re.sub(r"\s+", " ", SELECTION_MARKS.sub("", text or "")).strip()


def parse_number(text: str) -> float | None:
    """Read a printed number: '1,234.50', '2,51249' (comma decimal), '-11.80', '5 774' (space for dot)."""
    s = clean_text(text).replace("€", "").replace("%", "").strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+ \d{3}", s):  # '5 774': a dot read as a space
        s = s.replace(" ", ".")
    s = s.replace(" ", "")
    if "," in s and "." in s:  # thousands separator plus decimal point
        s = s.replace(",", "")
    elif "," in s:  # comma used as the decimal point (Jumbo, Vassos)
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def ean_is_valid(code: str) -> bool:
    """Check the last digit of an EAN-8/UPC-A/EAN-13 barcode against the other digits.

    The check digit catches almost every single misread digit, so a barcode that passes was
    almost certainly read correctly.
    """
    if not code.isdigit() or len(code) not in (8, 12, 13):
        return False
    digits = [int(d) for d in code]
    body, check = digits[:-1], digits[-1]
    # Weights 3,1,3,1,... counted from the digit next to the check digit.
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalise_barcode(text: str) -> str:
    """Pull the barcode out of a printed cell (D-006).

    Handles a trailing '-n' (Cosmos '40331423-n'), a 13-digit barcode wrapped onto two lines
    ('52130036125 44'), and a handwritten item code next to it ('52018251n 1623'). The check
    digit decides which digit groups belong together. Returns '' if the cell has no digits.
    """
    s = re.sub(r"(?<=\d)-?n\b", "", clean_text(text), flags=re.IGNORECASE)
    groups = re.findall(r"\d+", s)
    if not groups:
        return ""
    if ean_is_valid(groups[0]):
        return groups[0]
    for end in range(2, len(groups) + 1):
        joined = "".join(groups[:end])
        if ean_is_valid(joined):
            return joined
    return groups[0]


def _word_spans(result: dict) -> list[tuple[int, int, float]]:
    return [
        (w["span"]["offset"], w["span"]["offset"] + w["span"]["length"], w["confidence"])
        for page in result["pages"]
        for w in page.get("words", [])
    ]


def _cell_confidence(cell: dict, words) -> float | None:
    """Layout table cells have no confidence of their own; use the weakest word inside the cell."""
    confs = []
    for span in cell.get("spans", []):
        a, b = span["offset"], span["offset"] + span["length"]
        confs += [c for (s, e, c) in words if s >= a and e <= b]
    return min(confs) if confs else None


def find_table(result: dict, headers: dict[str, str], required: str) -> list[dict[str, Cell]]:
    """Find the table whose header row contains `required`, and return its data rows.

    `headers` maps printed header text (lower case) to our field names. Each returned row maps
    field name -> Cell. Rows above and including the header row are skipped.
    """
    words = _word_spans(result)
    for table in result.get("tables", []):
        grid: dict[int, dict[int, dict]] = {}
        for cell in table["cells"]:
            grid.setdefault(cell["rowIndex"], {})[cell["columnIndex"]] = cell
        for header_row in sorted(grid):
            names = {c: headers.get(clean_text(cell["content"]).lower()) for c, cell in grid[header_row].items()}
            if required in names.values():
                break
        else:
            continue
        columns = {c: name for c, name in names.items() if name}
        rows = []
        for r in sorted(grid):
            if r <= header_row:
                continue
            row = {}
            for c, name in columns.items():
                cell = grid[r].get(c)
                row[name] = Cell(clean_text(cell["content"]), _cell_confidence(cell, words)) if cell else Cell("", None)
            rows.append(row)
        return rows
    return []
