"""Monthly check of what the tool has learned (D-026).

Staff answers are remembered for good (D-018): a wrong "Is it this item? YES" would put every later
invoice line of that product on the wrong item, without a question. Once a month Zein brings a copy
of the shop PC's 'Admin only\\data' folder, and this lists the learned rows worth a second look:

  - the item no longer exists in the PowerSoft export
  - another item's name fits the supplier's wording clearly better than the chosen item's
  - the supplier's wording and the item's name have little in common
  - the cost per piece is far from PowerSoft's cost (wrong item, or wrong pieces per unit)

A row on this list isn't necessarily wrong (supplier names are abbreviated: 'N/VALLEY MUES/BAR'); Zein
decides. A wrong row is deleted in Excel (Admin.bat, option 5), so that line is asked again next time.
Rows from the old supplier lists (names, and unconfirmed barcodes, D-028) are skipped unless --all is given.

Usage:  uv run python scripts/check_learned.py "<copy of Admin only\\data>" [--all]
"""

import argparse
import sys
from pathlib import Path

from rapidfuzz import fuzz

from invoice_automation import pipeline
from invoice_automation.catalogue import Catalogue, name_key
from invoice_automation.supplier_items import LEGACY_BARCODE, SupplierItems

LOW_SIMILARITY = 55  # 0-100: below this, the wording and the item's name barely overlap
BETTER_BY = 15  # another item's name scores this much higher than the chosen one
COST_RATIO = 1.5  # cost per piece more than 1.5x PowerSoft's, or less than 1/1.5


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
            found.append((0, where, f"item {r.item_code} is not in the PowerSoft export any more"))
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
        if theirs - ours and ours - theirs:  # BER vs HON: a word on each side the other lacks
            reasons.append(f"words differ: {' '.join(sorted(theirs - ours))} vs {' '.join(sorted(ours - theirs))}")
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


def _similarity(a: str, b: str) -> float:
    return max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b))


def _words(key: str) -> set[str]:
    """The words of a name key that can tell two products apart: flavour, colour, size word. Numbers
    and single letters (5 X 42 G) are pack and size details, which differ between packs and singles."""
    return {w for w in key.split() if len(w) > 1 and not any(c.isdigit() for c in w)}


if __name__ == "__main__":
    main()
