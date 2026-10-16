"""Find which of our items an invoice line is, and how many selling pieces it holds (D-006, D-020).

Order, cheapest and most certain first:
1. learned:  this supplier's barcode (or own item code) is already in the supplier-items table
2. barcode:  the printed barcode is an item's barcode in PowerSoft (a single piece, factor 1)
3. name:     the supplier's wording matches exactly (their old wording from the legacy lists, or
             our item name; Athenites cuts names at 30 characters, so a cut-off name also counts)
4. fuzzy:    the most similar name, above a strict threshold; always asked in the review window
Anything else is a new item (D-012).

There is no LLM step: lines nothing matches are asked of staff (D-006 amendment).
"""

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .catalogue import Catalogue, name_key
from .layout import ean_is_valid
from .model import MATCH, PACK, RED, YELLOW, Flag, InvoiceLine
from .supplier_items import TRUSTED, SupplierItems

FUZZY_THRESHOLD = 90  # strict, for Athenites (D-015); 0-100 similarity
COMMON_PACK_SIZES = (3, 4, 6, 9, 12, 24)  # D-020; grows as Zein confirms others
PACK_TOLERANCE = 0.10  # the price ratio must be within 10% of a whole pack size
# A barcode match priced at this many times the known cost or more is a pack, not one piece.
# Below it, the difference is a price change (or an old VAT-inclusive cost) and goes to the report.
MULTIPACK_RATIO = 1.5


@dataclass
class Match:
    item_code: str | None
    pack_factor: float | None
    method: str  # learned, barcode, name, fuzzy, new, staff
    flags: list[Flag] = field(default_factory=list)
    candidates: list[tuple[str, str, float]] = field(default_factory=list)  # (code, description, score)


def usable_barcode(line: InvoiceLine) -> str:
    """The line's barcode, if its check digit is right. A misread barcode is not used for lookups."""
    return line.barcode if ean_is_valid(line.barcode) else ""


def match_line(line: InvoiceLine, supplier: str, invoice_no: str, catalogue: Catalogue,
               table: SupplierItems, exclude: set[str] = frozenset()) -> Match:
    """Match one line. Item codes in `exclude` are ignored (codes created for this same invoice)."""
    barcode = usable_barcode(line)

    # 1. Learned from an earlier invoice, by barcode or by the supplier's own item code.
    learned = table.get(supplier, "barcode", barcode) if barcode else None
    if not (learned and learned.item_code in catalogue.items) and line.supplier_code:
        learned = table.get(supplier, "code", line.supplier_code)
    if learned and learned.item_code in catalogue.items and learned.item_code not in exclude:
        m = Match(learned.item_code, learned.pack_factor, "learned", candidates=_top(learned.item_code, catalogue))
        if learned.status != TRUSTED:
            m.flags.append(Flag(YELLOW, "item", "Matched on an earlier invoice, not yet confirmed.", MATCH))
        if m.pack_factor is None:
            suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    # 2. Barcode is in PowerSoft. The item is certain; the pack size is 1, unless the invoice prints one
    #    (Andrikian: the lighter's barcode, but a box of 25) or the price is a multiple of the known cost
    #    (PowerSoft item 310 holds the bag-of-10 barcode but is one lollipop). Either way the price checks it.
    codes = [c for c in catalogue.by_barcode.get(barcode, []) if c not in exclude] if barcode else []
    if codes:
        storable = [c for c in codes if catalogue.items[c].storable] or codes
        m = Match(storable[0], 1, "barcode", candidates=[(c, catalogue.items[c].description, 100) for c in storable])
        if len(storable) > 1:
            m.flags.append(Flag(YELLOW, "item", f"Barcode {barcode} is on several items ({', '.join(storable)}).", MATCH))
        ratio = _price_ratio(m.item_code, line, supplier, invoice_no, catalogue, table)
        if line.printed_factor or (ratio is not None and ratio >= MULTIPACK_RATIO):
            m.pack_factor = None
            suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    # 3. Exact name.
    key = name_key(line.description)
    code = _exact_name(key, line.description, supplier, catalogue, table, exclude)
    if code:
        m = Match(code, None, "name", candidates=_top(code, catalogue))
        suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    # 4. Similar name.
    candidates = similar_names(line.description, supplier, catalogue, table, exclude)
    if candidates and candidates[0][2] >= FUZZY_THRESHOLD:
        code, description, score = candidates[0]
        m = Match(code, None, "fuzzy", candidates=candidates)
        m.flags.append(Flag(YELLOW, "item", f"Not an exact match. Closest item is '{description}' ({score:.0f}% similar).", MATCH))
        suggest_pack(m, line, supplier, invoice_no, catalogue, table)
        return m

    return Match(None, None, "new", candidates=candidates)


def _top(code, catalogue) -> list[tuple[str, str, float]]:
    return [(code, catalogue.items[code].description, 100)]


def _exact_name(key, raw, supplier, catalogue, table, exclude) -> str | None:
    row = next((r for r in table.names_for(supplier)
                if r.key == key and r.item_code in catalogue.items and r.item_code not in exclude), None)
    if row:
        return row.item_code
    truncated = len(raw.strip()) >= 30  # Athenites prints at most 30 characters
    for item in catalogue.items.values():
        if item.code in exclude:
            continue
        item_key = catalogue.name_keys[item.code]
        if item_key == key or (truncated and item_key.startswith(key)):
            return item.code
    return None


def similar_names(text: str, supplier: str | None, catalogue: Catalogue, table: SupplierItems | None = None,
                  exclude: set[str] = frozenset(), limit: int = 3) -> list[tuple[str, str, float]]:
    """Top candidates from the supplier's own wording and from all item names. Also used by the
    search box in the review window."""
    key = name_key(text)
    choices = {}
    if table is not None and supplier:
        for r in table.names_for(supplier):
            if r.item_code in catalogue.items and r.item_code not in exclude:
                choices[("legacy", r.item_code, r.key)] = r.key
    for item in catalogue.items.values():
        if item.code not in exclude:
            choices[("item", item.code, item.description)] = catalogue.name_keys[item.code]
    best: dict[str, float] = {}
    for _, score, (_, code, _) in process.extract(key, choices, scorer=_similarity, limit=limit * 4):
        best[code] = max(best.get(code, 0), score)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
    return [(code, catalogue.items[code].description, score) for code, score in ranked]


def _similarity(a: str, b: str, **_) -> float:
    """0-100. Plain character similarity catches misread letters ('BLUE ABEL' vs 'BLUE LABEL');
    word-order-free similarity catches reordered words ('SALT VINEGAR LAYS'). The better one counts."""
    return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))


def _reference_and_price(code, line, supplier, invoice_no, catalogue, table) -> tuple[float | None, float | None]:
    """Known cost of one piece, and the invoice price of one unit (both before VAT)."""
    reference = table.last_cost(supplier, code, invoice_no) or catalogue.items[code].cost
    unit_price = line.list_price_excl_vat
    if unit_price is None and line.quantity:
        unit_price = line.amount_excl_vat / line.quantity
    return reference, unit_price


def _price_ratio(code, line, supplier, invoice_no, catalogue, table) -> float | None:
    reference, unit_price = _reference_and_price(code, line, supplier, invoice_no, catalogue, table)
    return unit_price / reference if reference and unit_price else None


def suggest_pack(m: Match, line: InvoiceLine, supplier, invoice_no, catalogue, table) -> None:
    """Pack factor = invoice unit price / known cost of one piece (D-020)."""
    if line.pieces_known:  # the invoice printed the pack size; quantity is already in pieces
        m.pack_factor = 1
        return
    reference, unit_price = _reference_and_price(m.item_code, line, supplier, invoice_no, catalogue, table)
    if not unit_price and line.quantity:  # free goods: no price to compare, so staff confirm the size
        m.flags.append(Flag(YELLOW, "quantity", "Free goods (no price), so the pack size can't be checked.", PACK,
                            {"suggested": line.printed_factor or 1}))
        return
    if not reference or not unit_price:
        m.flags.append(Flag(RED, "quantity", "Pack size unknown (no known cost to compare with).", PACK,
                            {"suggested": line.printed_factor}))
        return
    ratio = unit_price / reference
    nearest = max(1, round(ratio))
    close = abs(ratio - nearest) <= PACK_TOLERANCE * nearest
    printed = line.printed_factor
    if printed and abs(ratio - printed) <= PACK_TOLERANCE * printed:
        m.pack_factor = printed  # the invoice prints the pack size and the price confirms it
    elif printed and printed > 1 and close and nearest == 1:
        m.pack_factor = 1  # printed as a pack, but our item is the whole pack (priced like one piece)
    elif printed:
        # The price doesn't confirm the printed size (e.g. our cost is out of date): suggest what the
        # paper says, and let staff confirm.
        m.pack_factor = printed
        m.flags.append(Flag(YELLOW, "quantity", f"The invoice says {printed:g} per unit, but the price looks like "
                                                f"{ratio:.1f}. Check on the box.", PACK, {"suggested": printed}))
    elif close and nearest == 1:
        m.pack_factor = 1
    elif close and nearest in COMMON_PACK_SIZES:
        m.pack_factor = nearest
        m.flags.append(Flag(YELLOW, "quantity", f"Looks like a pack of {nearest} (price is {ratio:.1f}x one piece).",
                            PACK, {"suggested": nearest}))
    elif close:
        m.pack_factor = nearest
        m.flags.append(Flag(RED, "quantity", f"Possibly a pack of {nearest} (price is {ratio:.1f}x one piece), "
                                             "an unusual size.", PACK, {"suggested": nearest}))
    else:
        m.flags.append(Flag(RED, "quantity", f"Pack size unknown: price is {ratio:.2f}x one piece.", PACK,
                            {"suggested": None}))
