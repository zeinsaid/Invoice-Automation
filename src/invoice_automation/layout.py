"""Helpers for reading prebuilt-layout results (D-021): tables, cell confidence, numbers, barcodes."""

import re
from dataclasses import dataclass

# DI reports checkboxes as these markers; staff pen ticks are often read as checkboxes (D-021).
SELECTION_MARKS = re.compile(r":(un)?selected:")


@dataclass
class Cell:
    text: str
    confidence: float | None  # lowest word confidence inside the cell; None if the cell is empty
    box: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 on the page (inches)


def clean_text(text: str) -> str:
    """Remove checkbox markers and collapse whitespace/line breaks."""
    return re.sub(r"\s+", " ", SELECTION_MARKS.sub("", text or "")).strip()


def parse_number(text: str) -> float | None:
    """Read a printed number: '1,234.50', '1.234,50' and '2,51249' (comma decimal: Jumbo, Vassos),
    '-11.80', '5 774' (space for dot)."""
    s = clean_text(text).replace("€", "").replace("%", "").strip()
    if not s:
        return None
    if re.fullmatch(r"-?\d+ \d{3}", s):  # '5 774': a dot read as a space
        s = s.replace(" ", ".")
    s = s.replace(" ", "")
    if "," in s and "." in s:  # thousands separator plus decimal point: the last one is the decimal
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
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


HANDWRITING_MIN = 0.9  # below this, DI's "handwritten" is usually printed text it was unsure of ('2', '%')


def without_handwriting(result: dict) -> dict:
    """The page with handwriting taken out (D-027): notes like 'new' or a supplier's name written next
    to a line were read into the item's description. DI marks handwritten text in `styles`; only marks
    it is sure of count, so a faint printed digit is never lost. The page text keeps its length
    (handwriting becomes spaces), so every offset into it stays valid. Returns a copy."""
    ranges = [(s["offset"], s["offset"] + s["length"])
              for style in result.get("styles", [])
              if style.get("isHandwritten") and (style.get("confidence") or 0) >= HANDWRITING_MIN
              for s in style.get("spans", [])]
    if not ranges:
        return result
    content = result.get("content", "")

    def handwritten(a: int, b: int) -> bool:
        return any(s <= a and b <= e for s, e in ranges)

    out = dict(result)
    chars = list(content)
    for s, e in ranges:
        chars[s:e] = " " * (e - s)
    out["content"] = "".join(chars)
    out["pages"] = [{**page, "words": [w for w in page.get("words", [])
                                        if not handwritten(w["span"]["offset"], w["span"]["offset"] + w["span"]["length"])]}
                    for page in result.get("pages", [])]
    tables = []
    for table in result.get("tables", []):
        cells = []
        for cell in table["cells"]:
            text = cell.get("content", "")
            for s, e in ranges:
                if any(sp["offset"] <= s and e <= sp["offset"] + sp["length"] for sp in cell.get("spans", [])):
                    text = re.sub(rf"(?<!\S){re.escape(content[s:e])}(?!\S)", " ", text, count=1)
            cells.append({**cell, "content": text})
        tables.append({**table, "cells": cells})
    out["tables"] = tables
    return out


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


# Greek capitals that look like Latin ones. OCR mixes them freely in headers ('TIMH' vs 'ΤΙΜΗ'),
# so headers are compared after turning every look-alike into its Latin letter.
_LOOKALIKES = str.maketrans("ΑΒΕΗΙΚΜΝΟΡΤΥΧΖ", "ABEHIKMNOPTYXZ")


def latinise(text: str) -> str:
    return clean_text(text).upper().translate(_LOOKALIKES)


def _grid(table: dict) -> dict[int, dict[int, dict]]:
    grid: dict[int, dict[int, dict]] = {}
    for cell in table["cells"]:
        grid.setdefault(cell["rowIndex"], {})[cell["columnIndex"]] = cell
    return grid


def _header_columns(row: dict[int, dict], columns: dict[str, str]) -> dict[int, str]:
    """Map column index -> field name for a header row. Each field is used at most once, and
    fields are tried in the order given, so put more specific patterns first."""
    found: dict[int, str] = {}
    for c in sorted(row):
        text = latinise(row[c]["content"])
        for name, pattern in columns.items():
            if name not in found.values() and re.search(pattern, text):
                found[c] = name
                break
    return found


def find_table(result: dict, columns: dict[str, str], required: str) -> list[dict[str, Cell]]:
    """Find the line-item table and return its data rows as {field name: Cell}.

    `columns` maps our field names to regex patterns, matched against the latinised header text.
    The table is the first one whose header row has the `required` field. A table split by a page
    break (e.g. Cosmos prints two pages on one sheet) continues in later tables with the same
    number of columns and no header row of their own; their rows are added too.
    """
    words = _word_spans(result)
    tables = result.get("tables", [])
    for t_index, table in enumerate(tables):
        grid = _grid(table)
        header_row, mapping = None, {}
        for r in sorted(grid):
            mapping = _header_columns(grid[r], columns)
            if required in mapping.values():
                header_row = r
                break
        if header_row is None:
            continue
        rows = _rows(grid, mapping, words, after=header_row)
        header = _rows(grid, mapping, words, after=header_row - 1)[:1]
        for row in rows:  # every row carries the header's position, to show column names above a crop
            row["_header"] = header[0]["_row"] if header else Cell("", None)
        for later in tables[t_index + 1:]:
            if later["columnCount"] != table["columnCount"]:
                continue
            later_grid = _grid(later)
            first = later_grid.get(min(later_grid), {}) if later_grid else {}
            if len(_header_columns(first, columns)) >= 3:
                break  # another headed table, not a continuation
            for row in _rows(later_grid, mapping, words, after=-1):
                row["_header"] = rows[0]["_header"] if rows else Cell("", None)
                rows.append(row)
        return rows
    return []


def headless_rows(result: dict, column_counts: tuple[int, ...], tail: list[str]) -> list[dict[str, Cell]]:
    """Rows of a line table that has no header row, read by position (D-004 amendment 2).

    Continuation pages (Athenites page 2) repeat the table without its column names, and the
    scanner may merge neighbouring cells (description + barcode). The numbers on the right keep
    their columns, so the last len(`tail`) cells are named by `tail`; every cell to their left is
    joined into "_lead" for the profile to take apart. Only tables with one of `column_counts` columns
    are read (the scanner splits the left part differently from page to page). Rows that aren't item
    rows are left for the profile to reject.
    """
    words = _word_spans(result)
    rows = []
    for table in result.get("tables", []):
        column_count = table["columnCount"]
        if column_count not in column_counts:
            continue
        grid = _grid(table)
        lead_columns = range(column_count - len(tail))
        mapping = {column_count - len(tail) + i: name for i, name in enumerate(tail)}
        for r, row in zip(sorted(grid), _rows(grid, mapping, words, after=-1)):
            lead = [grid[r][c] for c in lead_columns if c in grid[r]]
            confs = [c for c in (_cell_confidence(cell, words) for cell in lead) if c is not None]
            row["_lead"] = Cell(clean_text(" ".join(cell["content"] for cell in lead)), min(confs) if confs else None)
            row["_header"] = Cell("", None)
            rows.append(row)
    return rows


def _rows(grid, mapping, words, after: int) -> list[dict[str, Cell]]:
    """Data rows as {field: Cell}. The key "_row" holds a Cell spanning the whole row (for cropping)."""
    rows = []
    for r in sorted(grid):
        if r <= after:
            continue
        row = {}
        for c, name in mapping.items():
            cell = grid[r].get(c)
            row[name] = Cell(clean_text(cell["content"]), _cell_confidence(cell, words), _box(cell))                 if cell else Cell("", None)
        boxes = [b for b in (_box(cell) for cell in grid[r].values()) if b]
        row["_row"] = Cell("", None, (min(b[0] for b in boxes), min(b[1] for b in boxes),
                                      max(b[2] for b in boxes), max(b[3] for b in boxes)) if boxes else None)
        rows.append(row)
    return rows


def _box(cell: dict) -> tuple[float, float, float, float] | None:
    regions = cell.get("boundingRegions") or []
    if not regions:
        return None
    xs, ys = regions[0]["polygon"][0::2], regions[0]["polygon"][1::2]
    return min(xs), min(ys), max(xs), max(ys)
