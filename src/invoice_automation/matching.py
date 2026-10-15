"""Find which of our items an invoice line is, and how many selling pieces it holds (D-006, D-020).

Order, cheapest and most certain first:
1. learned:  this supplier's barcode is already in the supplier-items table
2. barcode:  the printed barcode is an item's barcode in PowerSoft (a single piece, factor 1)
3. name:     the supplier's wording matches exactly (their old wording from the legacy lists, or
             our item name; Athenites cuts names at 30 characters, so a cut-off name also counts)
4. fuzzy:    the most similar name, above a strict threshold; always flagged yellow
Anything else is a new item (D-012), always red.

The LLM suggestion step (D-006 step 4) is not built yet.
"""

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .catalogue import Catalogue, name_key
from .model import RED, YELLOW, Flag, InvoiceLine
from .supplier_items import TRUSTED, SupplierItems

FUZZY_THRESHOLD = 90  # strict, for Athenites (D-015); 0-100 similarity
COMMON_PACK_SIZES = (4, 6, 9, 12, 24)  # D-020; grows as Zein confirms others
PACK_TOLERANCE = 0.10  # the price ratio must be within 10% of a whole pack size


@dataclass
class Match:
    item_code: str | None
    pack_factor: float | None
    method: str  # learned, barcode, name, fuzzy, new
    flags: list[Flag] = field(default_factory=list)
    candidates: list[tuple[str, str, float]] = field(default_factory=list)  # (code, description, score)


def match_line(line: InvoiceLine, supplier: str, invoice_no: str, catalogue: Catalogue,
               table: SupplierItems, exclude: set[str] = frozenset()) -> Match:
    """Match one line. `exclude` holds item codes this same invoice created as new items on an
    earlier run; they are ignored so that re-running an invoice gives the same result."""
    # 1. Learned from an earlier invoice. An unconfirmed guess made by this same invoice on an
    #    earlier run doesn't count: it would turn this invoice's own red flags into yellow ones.
    learned = table.get(supplier, "barcode", line.barcode) if line.barcode else None
    if learned and learned.status != TRUSTED and learned.last_invoice == invoice_no:
        learned = None
    if learned and learned.item_code in catalogue.items and learned.item_code not in exclude:
        m = Match(learned.item_code, learned.pack_factor, "learned")
        if learned.status != TRUSTED:
            m.flags.append(Flag(YELLOW, "item",
                                f"Matched to '{catalogue.items[learned.item_code].description}' on an earlier "
                                "invoice, not yet confirmed. Check it is the right item."))
        if m.pack_factor is None:
            _suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    # 2. Barcode is the piece barcode in PowerSoft.
    codes = [c for c in catalogue.by_barcode.get(line.barcode, []) if c not in exclude] if line.barcode else []
    if codes:
        storable = [c for c in codes if catalogue.items[c].storable] or codes
        m = Match(storable[0], 1, "barcode")
        if len(storable) > 1:
            m.flags.append(Flag(YELLOW, "item", f"Barcode {line.barcode} is on several items ({', '.join(storable)})."))
        return m

    # 3. Exact name.
    key = name_key(line.description)
    code = _exact_name(key, line.description, supplier, catalogue, table, exclude)
    if code:
        m = Match(code, None, "name")
        _suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    # 4. Similar name.
    candidates = _similar_names(key, supplier, catalogue, table, exclude)
    if candidates and candidates[0][2] >= FUZZY_THRESHOLD:
        code, description, score = candidates[0]
        m = Match(code, None, "fuzzy", candidates=candidates)
        m.flags.append(Flag(YELLOW, "item",
                            f"Not an exact match. Closest item is '{description}' ({score:.0f}% similar). Check it."))
        _suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    return Match(None, None, "new", candidates=candidates)


def _exact_name(key, raw, supplier, catalogue, table, exclude) -> str | None:
    row = next((r for r in table.names_for(supplier)
                if r.key == key and r.item_code in catalogue.items and r.item_code not in exclude), None)
    if row:
        return row.item_code
    truncated = len(raw.strip()) >= 30  # Athenites prints at most 30 characters
    for item in catalogue.items.values():
        if item.code in exclude:
            continue
        item_key = name_key(item.description)
        if item_key == key or (truncated and item_key.startswith(key)):
            return item.code
    return None


def _similar_names(key, supplier, catalogue, table, exclude) -> list[tuple[str, str, float]]:
    """Top 3 candidates from the supplier's own wording and from all item names."""
    choices = {}
    for r in table.names_for(supplier):
        if r.item_code in catalogue.items and r.item_code not in exclude:
            choices[("legacy", r.item_code, r.key)] = r.key
    for item in catalogue.items.values():
        if item.code in exclude:
            continue
        choices[("item", item.code, item.description)] = name_key(item.description)
    best: dict[str, float] = {}
    for _, score, (_, code, _) in process.extract(key, choices, scorer=fuzz.token_sort_ratio, limit=10):
        best[code] = max(best.get(code, 0), score)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:3]
    return [(code, catalogue.items[code].description, score) for code, score in ranked]


def _suggest_pack(m: Match, line: InvoiceLine, supplier, invoice_no, catalogue, table) -> None:
    """Pack factor = invoice unit price / known cost of one piece (D-020)."""
    reference = table.last_cost(supplier, m.item_code, invoice_no) or catalogue.items[m.item_code].cost
    unit_price = line.list_price_excl_vat
    if unit_price is None and line.quantity:
        unit_price = line.amount_excl_vat / line.quantity
    if not reference or not unit_price:
        m.flags.append(Flag(RED, "quantity", "Pack size unknown (no known cost to compare with)."))
        return
    ratio = unit_price / reference
    nearest = max(1, round(ratio))
    close = abs(ratio - nearest) <= PACK_TOLERANCE * nearest
    if close and nearest == 1:
        m.pack_factor = 1
    elif close and nearest in COMMON_PACK_SIZES:
        m.pack_factor = nearest
        m.flags.append(Flag(YELLOW, "quantity",
                            f"Looks like a pack of {nearest} (price is {ratio:.1f}x one piece). Quantity converted; check it."))
    elif close:
        m.pack_factor = nearest
        m.flags.append(Flag(RED, "quantity",
                            f"Possibly a pack of {nearest} (price is {ratio:.1f}x one piece), an unusual size. Confirm it."))
    else:
        m.flags.append(Flag(RED, "quantity",
                            f"Pack size unknown: price is {ratio:.2f}x one piece. Quantity left as on the invoice."))
