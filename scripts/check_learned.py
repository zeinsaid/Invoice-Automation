"""Monthly check of what the tool has learned (D-026).

Staff answers are remembered for good (D-018): a wrong "Is it this item? YES" would put every later
invoice line of that product on the wrong item, without a question. Once a month Zein brings a copy
of the shop PC's 'Admin only\\data' folder, and this lists the learned rows worth a second look:

  - the item no longer exists in the PowerSoft export
  - another item's name fits the supplier's wording clearly better than the chosen item's
  - the supplier's wording and the item's name have little in common
  - both print a size and the sizes differ (Red Bull 4x250ML learned as the 355ML can, November 2026)
  - the cost per piece is far from PowerSoft's cost (wrong item, or wrong pieces per unit)

It also lists invoices marked as uploaded whose new costs never reached PowerSoft: their Purchase order was
most likely not uploaded, so their stock is missing too (Athenites 1000756371, November 2026: only the Items
import was done).

A row on this list isn't necessarily wrong (supplier names are abbreviated: 'N/VALLEY MUES/BAR'); Zein
decides. A wrong row is deleted in Excel (Admin.bat, option 5), so that line is asked again next time.
Rows from the old supplier lists (names, and unconfirmed barcodes, D-028) are skipped unless --all is given.

Usage:  uv run python scripts/check_learned.py "<copy of Admin only\\data>" [--all]
"""

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from rapidfuzz import fuzz

from invoice_automation import pipeline
from invoice_automation.catalogue import Catalogue, name_key
from invoice_automation.supplier_items import LEGACY_BARCODE, SupplierItems

LOW_SIMILARITY = 55  # 0-100: below this, the wording and the item's name barely overlap
BETTER_BY = 15  # another item's name scores this much higher than the chosen one
COST_RATIO = 1.5  # cost per piece more than 1.5x PowerSoft's, or less than 1/1.5
SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ML|CL|LTR|LT|L|KG|GR|G)\b")
TO_ML_OR_G = {"ML": 1, "CL": 10, "L": 1000, "LT": 1000, "LTR": 1000, "G": 1, "GR": 1, "KG": 1000}
SAME_COST = 0.011  # PowerSoft keeps 2 decimals: 0.575 is stored as 0.57 or 0.58


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data", type=Path, help="the copy of the shop PC's 'Admin only\\data' folder")
    parser.add_argument("--all", action="store_true", help="also check rows seeded from the old supplier lists")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    catalogue = Catalogue.load(args.data / "powersoft")
    pipeline.NEW_ITEMS = args.data / "state" / "new_items.csv"  # codes the tool issued at the shop
    for item in pipeline._load_new_items():
        catalogue.add_local(item)
    table = SupplierItems.load(args.data / "supplier_items.xlsx")

    found = []
    for r in table.rows:
        if r.source in ("legacy", LEGACY_BARCODE) and not args.all:  # from the old lists, not staff
            continue
        where = f"{r.supplier} | {r.key_type} {r.key} | '{r.supplier_description}'"
        item = catalogue.items.get(r.item_code)
        if item is None:
            found.append((0, where, f"item {r.item_code} is inactive or not in the PowerSoft export any more"))
            continue
        reasons = []
        wording = name_key(r.supplier_description)
        score = _similarity(wording, catalogue.name_keys[item.code])
        best = max(((code, _similarity(wording, key)) for code, key in catalogue.name_keys.items()
                    if code != item.code and catalogue.items[code].storable), key=lambda h: h[1], default=None)
        if best and best[1] >= score + BETTER_BY:
            reasons.append(f"'{catalogue.items[best[0]].description}' ({best[0]}) fits the name better "
                           f"({best[1]:.0f} vs {score:.0f})")
        elif score < LOW_SIMILARITY:
            reasons.append(f"names barely match ({score:.0f}/100)")
        ours, theirs = _words(catalogue.name_keys[item.code]), _words(wording)
        # A match on PowerSoft's own barcode settles which item it is: different spelling ('PAPRICA') isn't
        # worth a look then (2026-11-09: 52 of 125 rows were only that). A better-fitting name still is.
        by_barcode = r.source.startswith("barcode")
        if theirs - ours and ours - theirs and not by_barcode:  # BER vs HON: a word on each side the other lacks
            reasons.append(f"words differ: {' '.join(sorted(theirs - ours))} vs {' '.join(sorted(ours - theirs))}")
        theirs_size, ours_size = _sizes(r.supplier_description), _sizes(item.description)
        if r.pack_factor and r.pack_factor > 1:  # 'TRONKY T5 90GR' is 5 x the 18gr single
            theirs_size |= {round(s / r.pack_factor, 1) for s in theirs_size}
        if theirs_size and ours_size and not theirs_size & ours_size:
            reasons.append(f"size differs: {_show(theirs_size)} vs {_show(ours_size)}")
        if r.last_cost and item.cost and not item.local:
            ratio = r.last_cost / item.cost
            if ratio > COST_RATIO or ratio < 1 / COST_RATIO:
                reasons.append(f"cost per piece {r.last_cost:.3f} vs PowerSoft {item.cost:.2f} "
                               f"(pieces per unit: {r.pack_factor or '?'})")
        if reasons:
            found.append((score, where, f"-> {item.code} '{item.description}' [{r.source}]: " + "; ".join(reasons)))

    for _, where, why in sorted(found, key=lambda f: f[0]):
        print(f"{where}\n    {why}")
    print(f"\n{len(found)} of {len(table.rows)} rows to look at.")

    missing = not_uploaded(args.data / "state", catalogue)
    print("\nInvoices marked as uploaded whose new costs are not in PowerSoft (Purchase order not uploaded?):")
    for line in missing or ["   none"]:
        print(line)


def not_uploaded(state: Path, catalogue: Catalogue) -> list[str]:
    """Invoices whose Purchase order seems never to have been uploaded: the export has none of the costs it
    should have set. Only costs no later invoice changed again count, and only invoices finished before the
    export was made and already marked as uploaded (to_upload.json lists the rest)."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", catalogue.export_name)
    exported = date.fromisoformat(m.group()) if m else date.today()
    finished = {}
    if (state / "processed_invoices.csv").exists():
        with (state / "processed_invoices.csv").open(encoding="utf-8", newline="") as f:
            finished = {(r["supplier"], r["invoice"]): r for r in csv.DictReader(f)}
    waiting = set(json.loads((state / "to_upload.json").read_text(encoding="utf-8"))) \
        if (state / "to_upload.json").exists() else set()
    latest = {}  # item code -> the last cost change the tool made to it
    if (state / "price_changes.csv").exists():
        with (state / "price_changes.csv").open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                latest[r["item_code"]] = r
    by_invoice: dict[tuple[str, str], list[dict]] = {}
    for code, r in latest.items():
        if code in catalogue.items and not catalogue.items[code].local:
            by_invoice.setdefault((r["supplier"], r["invoice"]), []).append(r)
    out = []
    for key, changes in by_invoice.items():
        done = finished.get(key)
        if not done or done["file"] in waiting or date.fromisoformat(done["processed"][:10]) >= exported:
            continue
        if all(abs(catalogue.items[r["item_code"]].cost - float(r["new_cost"])) > SAME_COST for r in changes):
            r = changes[0]
            out.append(f"   {done['file']}: none of its {len(changes)} new costs are in PowerSoft (e.g. "
                       f"{r['item_code']} {r['description']}: {catalogue.items[r['item_code']].cost:.2f}, "
                       f"should be {float(r['new_cost']):.2f}). Upload it as a Purchase order if it isn't there.")
    return out


def _similarity(a: str, b: str) -> float:
    return max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b))


def _sizes(description: str) -> set[float]:
    """The sizes a name prints, in ml or g: '4×250ML' is {250}, 'MALIBU 70CL' is {700}, '1.5LT' is {1500}.
    The word check leaves numbers out (pack and size details), so without this a 250ML can learned as the
    355ML one never shows: both are 'RED BULL ENERGY'."""
    return {float(n.replace(",", ".")) * TO_ML_OR_G[unit] for n, unit in SIZE.findall(description.upper())}


def _show(sizes: set[float]) -> str:
    return "/".join(f"{s:g}" for s in sorted(sizes))


def _words(key: str) -> set[str]:
    """The words of a name key that can tell two products apart: flavour, colour, size word. Numbers
    and single letters (5 X 42 G) are pack and size details, which differ between packs and singles."""
    return {w for w in key.split() if len(w) > 1 and not any(c.isdigit() for c in w)}


if __name__ == "__main__":
    main()
