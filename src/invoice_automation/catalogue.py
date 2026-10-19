"""The item catalogue: the latest PowerSoft export plus the tool's local additions (D-018).

PowerSoft owns what an item *is*. The tool never edits item data; it only reads the export. New
items the tool has issued codes for (the ledger, D-012) are merged on top until a fresh export
contains them.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl
from rapidfuzz import fuzz

POWERSOFT_DIR = Path("data/powersoft")
EXPORT_COLUMNS = ["Item Code", "Item Description", "Barcode", "VAT", "Cost", "Price 1", "Supplier", "Brand",
                  "Category", "Storable"]
# A pack sub-item is named like its single piece plus " xN": "KYKKOS WATER 500ML X12" (D-005 amendment).
PACK_NAME = re.compile(r"^(.*\S)\s*[xX]\s*(\d+)$")
PACK_LINK_SCORE = 85  # 0-100 name similarity needed to link a pack to a single piece by a near name
PACK_LINK_MARGIN = 5  # ... and it must beat the next item by this much, or nothing is linked


@dataclass
class Item:
    code: str
    description: str
    barcode: str
    vat: int  # 0, 5 or 19
    cost: float  # per selling piece, excl. VAT
    price: float | None  # retail incl. VAT
    supplier: str
    brand: str
    category: str
    storable: bool
    local: bool = False  # issued by the tool, not yet in a PowerSoft export


def _number(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (AttributeError, ValueError):
        return None


class Catalogue:
    def __init__(self, items: dict[str, Item], category_codes: dict[str, str], supplier_codes: dict[str, str]):
        self.items = items
        self.category_codes = category_codes  # category name -> code
        self.supplier_codes = supplier_codes  # supplier name -> code
        self.by_barcode: dict[str, list[str]] = {}
        self.name_keys: dict[str, str] = {}  # code -> name_key(description), computed once
        for item in items.values():
            self._index(item)
        self.pack_links: dict[str, PackLink] = {}  # pack item code -> its single piece
        self.unlinked_packs: list[str] = []  # packs named "... xN" with no clear single piece
        self._link_packs()

    def _index(self, item: Item) -> None:
        if item.barcode:
            self.by_barcode.setdefault(item.barcode, []).append(item.code)
        self.name_keys[item.code] = name_key(item.description)

    @classmethod
    def load(cls, powersoft_dir: Path = POWERSOFT_DIR) -> "Catalogue":
        exports = sorted(powersoft_dir.glob("items_export_*.csv"))
        if not exports:
            raise FileNotFoundError(f"No items_export_*.csv in {powersoft_dir}")
        items = {}
        # PowerSoft exports in cp1253 (Greek Windows). Row 2 is a sub-header ('Incl') and is skipped.
        with exports[-1].open(encoding="cp1253", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            col = {name: i for i, name in enumerate(header)}
            missing = [c for c in EXPORT_COLUMNS if c not in col]
            if missing:  # e.g. an export made without the Storable column (D-005: needed to never touch packs)
                raise ValueError(f"{exports[-1].name} has no {', '.join(missing)} column. Export the items again "
                                 f"with these columns: {', '.join(EXPORT_COLUMNS)}.")
            for row in reader:
                code = row[col["Item Code"]].strip()
                if not code or row[col["Item Description"]] == "":
                    continue
                items[code] = Item(
                    code=code,
                    description=row[col["Item Description"]].strip(),
                    barcode=row[col["Barcode"]].strip(),
                    vat=int(row[col["VAT"]].rstrip("%") or 0),
                    cost=_number(row[col["Cost"]]) or 0.0,
                    price=_number(row[col["Price 1"]]),
                    supplier=row[col["Supplier"]].strip(),
                    brand=row[col["Brand"]].strip(),
                    category=row[col["Category"]].strip(),
                    storable=row[col["Storable"]].strip().lower() == "yes",
                )
        return cls(items, _category_codes(powersoft_dir), _supplier_codes(powersoft_dir))

    def _link_packs(self) -> None:
        """Link each pack sub-item to its single piece by name (D-005 amendment).

        The same name wins. Otherwise the most similar name, if it is close (a typo like 'Kidder') and
        clearly ahead of the next one; the sizes in the pack's name (500 ML) must be in the single's
        name too. Anything unclear stays unlinked, and staff are asked once, as before.
        """
        singles = [i for i in self.items.values() if i.storable]
        for pack in self.items.values():
            m = PACK_NAME.match(pack.description)
            if pack.storable or not m or int(m.group(2)) < 2:
                continue
            base = name_key(m.group(1))
            exact = [i.code for i in singles if self.name_keys[i.code] == base]
            if len(exact) == 1:
                self.pack_links[pack.code] = PackLink(exact[0], int(m.group(2)), True)
                continue
            sizes = _sizes(base)
            scored = sorted(((_name_similarity(base, self.name_keys[i.code]), i.code) for i in singles
                             if sizes <= _sizes(self.name_keys[i.code])), reverse=True)
            if scored and scored[0][0] >= PACK_LINK_SCORE and (
                    len(scored) == 1 or scored[0][0] - scored[1][0] >= PACK_LINK_MARGIN):
                self.pack_links[pack.code] = PackLink(scored[0][1], int(m.group(2)), False)
            else:
                self.unlinked_packs.append(pack.code)

    def add_local(self, item: Item) -> None:
        """Merge an item the tool created (D-018 point 4), unless the export already has it."""
        if item.code in self.items:
            return
        item.local = True
        self.items[item.code] = item
        self._index(item)

    def highest_numeric_code(self) -> int:
        return max((int(c) for c in self.items if c.isdigit()), default=0)


@dataclass
class PackLink:
    single: str  # item code of one piece
    pieces: int  # pieces in one pack
    exact: bool  # linked by the same name (True) or by a near name (False: shown to Zein to check)


def _sizes(key: str) -> set[str]:
    """The number words of a name key: '500', '1.5', '2'."""
    return {t for t in key.split() if any(c.isdigit() for c in t)}


def _name_similarity(a: str, b: str) -> float:
    """0-100. Plain similarity catches typos; token-set similarity catches a missing word ('AQUA 500 ML'
    vs 'AQUA WATER 500 ML')."""
    return max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b))


def _category_codes(powersoft_dir: Path) -> dict[str, str]:
    ws = openpyxl.load_workbook(powersoft_dir / "categories.xlsx", read_only=True).active
    codes = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = next((v for v in row[1:4] if v), None)
        if name and row[5] is not None:
            codes[str(name).strip()] = str(row[5]).strip()
    return codes


def _supplier_codes(powersoft_dir: Path) -> dict[str, str]:
    ws = openpyxl.load_workbook(powersoft_dir / "suppliers.xlsx", read_only=True).active
    return {
        str(row[3]).strip(): str(row[0]).strip()
        for row in ws.iter_rows(min_row=2, values_only=True)
        if row[0] and row[3]
    }


def name_key(text: str) -> str:
    """Normalise an item name for comparison.

    PowerSoft strips & ' % ( ) from names on save (D-019), so they are ignored on both sides.
    Other punctuation becomes a space, and digits are split from letters ('FREE240ML' -> 'FREE 240 ML').
    """
    s = text.upper()
    s = re.sub(r"[&'%()]", "", s)
    s = re.sub(r"[^A-Z0-9Α-Ω.]+", " ", s)
    s = re.sub(r"(?<=\d)(?=[A-ZΑ-Ω])|(?<=[A-ZΑ-Ω])(?=\d)", " ", s)
    return re.sub(r"\s+", " ", s).strip()
