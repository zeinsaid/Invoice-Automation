"""Run prebuilt-layout on every sample page and summarise what it found (D-021 check).

For each page: rotation angle, the tables found (size and header row), and the cells with the
lowest confidence. Results are cached, so only new pages use Azure.

Usage:  uv run python scripts/layout_survey.py [name filter]
"""

import sys
from pathlib import Path

import pymupdf

from invoice_automation.extract import analyze_page

SAMPLES = Path("data/samples")


def word_confs(result):
    return [
        (w["span"]["offset"], w["span"]["offset"] + w["span"]["length"], w["confidence"])
        for p in result["pages"] for w in p.get("words", [])
    ]


def cell_conf(cell, words):
    confs = []
    for span in cell.get("spans", []):
        a, b = span["offset"], span["offset"] + span["length"]
        confs += [c for (s, e, c) in words if s >= a and e <= b]
    return min(confs) if confs else None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    name_filter = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        if name_filter not in pdf.name.lower():
            continue
        with pymupdf.open(pdf) as doc:
            n_pages = doc.page_count
        for i in range(n_pages):
            result = analyze_page(pdf, i, "prebuilt-layout")
            words = word_confs(result)
            page = result["pages"][0]
            print(f"\n##### {pdf.name}  page {i + 1}/{n_pages}  angle={page.get('angle', 0):.1f}  "
                  f"words={len(words)}  tables={len(result.get('tables', []))}")
            for t_i, table in enumerate(result.get("tables", [])):
                rows = {}
                for cell in table["cells"]:
                    rows.setdefault(cell["rowIndex"], {})[cell["columnIndex"]] = cell
                first = rows.get(0, {})
                header = " | ".join(first[c]["content"].replace("\n", " ") for c in sorted(first))
                print(f"  table {t_i}: {table['rowCount']}x{table['columnCount']}  row0: {header[:150]}")
            low = sorted(
                (cell_conf(c, words), c["content"].replace("\n", " "), t_i, c["rowIndex"], c["columnIndex"])
                for t_i, table in enumerate(result.get("tables", []))
                for c in table["cells"]
                if c["content"].strip() and (cell_conf(c, words) or 1) < 0.9
            )
            for conf, text, t_i, r, c in low[:8]:
                print(f"    low conf {conf:.3f}  t{t_i} r{r} c{c}: {text[:60]!r}")
            if len(low) > 8:
                print(f"    ... and {len(low) - 8} more cells below 0.9")


if __name__ == "__main__":
    main()
