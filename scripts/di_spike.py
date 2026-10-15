"""Spike (D-003): which Document Intelligence model reads Athenites invoices best?

Runs prebuilt-layout and prebuilt-invoice on the Athenites sample page and scores both against
the hand transcription in data/eval/. Responses are cached (see extract.py), so re-running this
script after the first time uses no Azure pages.

Usage:  uv run python scripts/di_spike.py
"""

import csv
import difflib
import re
import sys
from pathlib import Path

from invoice_automation.extract import analyze_page

PDF = Path("data/samples/YPER. HADJICHRISTOFIS (ATHIENITIS) LTD.pdf")
TRUTH = Path("data/eval/athenites_1000748334.csv")

# Map the printed column headers to our field names (layout model).
HEADERS = {
    "a/a": "line",
    "description": "description",
    "barcode": "barcode",
    "quantity": "quantity",
    "unit selling price": "unit_price",
    "discount amount": "discount",
    "amount incl. vat": "amount",
    "vat": "vat_code",
}
CHECKED = ["description", "barcode", "quantity", "amount"]


def norm_text(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().upper()


def norm_num(s):
    try:
        return round(float(str(s).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return None


def same(field: str, read, truth) -> bool:
    if field in ("quantity", "amount"):
        return norm_num(read) is not None and norm_num(read) == norm_num(truth)
    if field == "barcode":
        return re.sub(r"\D", "", str(read or "")) == truth
    return norm_text(read) == norm_text(truth)


def word_confidences(result: dict) -> list[tuple[int, int, float]]:
    """(start offset, end offset, confidence) for every word DI read on the page."""
    out = []
    for page in result["pages"]:
        for w in page.get("words", []):
            out.append((w["span"]["offset"], w["span"]["offset"] + w["span"]["length"], w["confidence"]))
    return out


def cell_confidence(cell: dict, words) -> float | None:
    """Layout table cells carry no confidence of their own; use the weakest word inside the cell."""
    confs = []
    for span in cell.get("spans", []):
        a, b = span["offset"], span["offset"] + span["length"]
        confs += [c for (s, e, c) in words if s >= a and e <= b]
    return min(confs) if confs else None


def layout_rows(result: dict) -> list[dict]:
    words = word_confidences(result)
    rows = []
    for table in result.get("tables", []):
        grid: dict[int, dict[int, dict]] = {}
        for cell in table["cells"]:
            grid.setdefault(cell["rowIndex"], {})[cell["columnIndex"]] = cell
        # Find the header row and which column holds which field.
        colmap = {}
        for r in sorted(grid):
            names = {c: HEADERS.get(norm_text(cell["content"]).lower()) for c, cell in grid[r].items()}
            if "barcode" in names.values():
                colmap = {c: n for c, n in names.items() if n}
                header_row = r
                break
        if not colmap:
            continue
        for r in sorted(grid):
            if r <= header_row:
                continue
            row = {}
            for c, name in colmap.items():
                cell = grid[r].get(c)
                row[name] = cell["content"] if cell else ""
                row[name + "_conf"] = cell_confidence(cell, words) if cell else None
            rows.append(row)
    return rows


def invoice_rows(result: dict) -> list[dict]:
    rows = []
    for doc in result.get("documents", []):
        items = doc.get("fields", {}).get("Items", {}).get("valueArray", [])
        for item in items:
            f = item.get("valueObject", {})

            def get(key, value_key=None):
                field = f.get(key) or {}
                if value_key == "number":
                    value = field.get("valueNumber")
                elif value_key == "currency":
                    value = (field.get("valueCurrency") or {}).get("amount")
                else:
                    value = field.get("content")
                return value, field.get("confidence")

            row = {}
            for name, key, kind in [
                ("description", "Description", None),
                ("barcode", "ProductCode", None),
                ("quantity", "Quantity", "number"),
                ("amount", "Amount", "currency"),
            ]:
                row[name], row[name + "_conf"] = get(key, kind)
            rows.append(row)
    return rows


def align(rows: list[dict], truth: list[dict]) -> list[dict]:
    """Pair each truth line with the row DI read for it, so one missed or merged row doesn't
    shift every row after it. Rows are paired by description; leftovers in a mismatched block
    are paired by position."""
    a = [norm_text(t["description"]) for t in truth]
    b = [norm_text(r.get("description")) for r in rows]
    paired: list[dict] = [{} for _ in truth]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                paired[i1 + k] = rows[j1 + k]
    return paired


def score(model: str, rows: list[dict], truth: list[dict]) -> None:
    print(f"\n=== {model}: {len(rows)} rows read (truth has {len(truth)}) ===")
    errors = []
    correct_confs = []
    paired = align(rows, truth)
    for i, t in enumerate(truth):
        r = paired[i]
        for field in CHECKED:
            read, conf = r.get(field), r.get(field + "_conf")
            if same(field, read, t[field]):
                if conf is not None:
                    correct_confs.append(conf)
            else:
                errors.append((t["line"], field, t[field], read, conf))
    total = len(truth) * len(CHECKED)
    print(f"fields correct: {total - len(errors)}/{total}")
    if correct_confs:
        correct_confs.sort()
        print(f"confidence on correct fields: min {correct_confs[0]:.3f}, "
              f"5th pct {correct_confs[len(correct_confs) // 20]:.3f}")
    for line, field, want, got, conf in errors:
        conf_s = f"{conf:.3f}" if conf is not None else "n/a"
        print(f"  line {line:>2} {field:<11} want {want!r:<34} got {got!r:<34} conf {conf_s}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    with TRUTH.open(encoding="utf-8") as f:
        truth = list(csv.DictReader(f))

    layout = analyze_page(PDF, 0, "prebuilt-layout")
    score("prebuilt-layout", layout_rows(layout), truth)

    invoice = analyze_page(PDF, 0, "prebuilt-invoice")
    score("prebuilt-invoice", invoice_rows(invoice), truth)
    doc = (invoice.get("documents") or [{}])[0].get("fields", {})
    for key in ("VendorName", "InvoiceId", "InvoiceDate", "InvoiceTotal"):
        field = doc.get(key) or {}
        print(f"  {key}: {field.get('content')!r} (conf {field.get('confidence')})")


if __name__ == "__main__":
    main()
