"""Find which of our items an invoice line is, and how many selling pieces it holds (D-006, D-020).

Order, cheapest and most certain first:
1. learned:  this supplier's barcode (or own item code) is already in the supplier-items table
2. barcode:  the printed barcode is an item's barcode in PowerSoft (a single piece, factor 1)
3. name:     the supplier's wording matches exactly (their old wording from the legacy lists, or
             our item name; Athenites cuts names at 30 characters, so a cut-off name also counts)
4. fuzzy:    the most similar name, above a strict threshold; always asked in the review window
Anything else is a new item (D-012). A match to a pack sub-item that holds no stock becomes its single
piece, N per pack, when the catalogue links them by name (D-005 amendment).

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
EXACT_TOLERANCE = 0.01  # within 1% of a whole number (costs are kept to 2 decimals, about 0.6% rounding), that number is almost certainly the pack size
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
    m = _match(line, supplier, invoice_no, catalogue, table, exclude)
    if m.item_code in catalogue.pack_links:
        _unpack(m, line, supplier, invoice_no, catalogue, table)
    return m


def _unpack(m: Match, line: InvoiceLine, supplier, invoice_no, catalogue, table) -> None:
    """The line matched a pack that holds no stock: count it as its single piece (D-005 amendment).
    PowerSoft's "xN" is the pack size, checked by price like any other; if the price disagrees, staff
    are asked with N suggested. With no known cost to compare, N is used (Zein set it up)."""
    link = catalogue.pack_links[m.item_code]
    pack = catalogue.items[m.item_code].description
    m.item_code, m.method = link.single, m.method + "+pack_link"
    m.candidates = [(link.single, catalogue.items[link.single].description, 100)] + m.candidates[1:]
    m.flags = [f for f in m.flags if f.kind != PACK]
    if line.pieces_known:  # the invoice already counts pieces
        m.pack_factor = 1
        return
    ratios = _ratios(link.single, line, supplier, invoice_no, catalogue, table)
    if not ratios or any(_near(r, link.pieces) for r in ratios):
        m.pack_factor = link.pieces
        return
    m.pack_factor = None
    m.flags.append(Flag(YELLOW, "quantity", f"PowerSoft says '{pack}' is {link.pieces} pieces, but the price looks "
                                            f"like {ratios[0]:.1f}. Count on the box.", PACK,
                        {"suggested": link.pieces}))


def _match(line: InvoiceLine, supplier: str, invoice_no: str, catalogue: Catalogue,
           table: SupplierItems, exclude: set[str]) -> Match:
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
        else:
            _recheck_learned(m, line, supplier, invoice_no, catalogue, table)
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
        ratios = _ratios(m.item_code, line, supplier, invoice_no, catalogue, table)
        if line.printed_factor or (ratios and min(ratios) >= MULTIPACK_RATIO):
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


def _references(code, supplier, invoice_no, catalogue, table) -> list[float]:
    """Known costs of one piece: this supplier's last cost, then PowerSoft's. With two, a promotion on
    the last invoice or an out-of-date PowerSoft cost only spoils one of them."""
    refs = []
    for ref in (table.last_cost(supplier, code, invoice_no), catalogue.items[code].cost):
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _unit_price(line: InvoiceLine) -> float | None:
    """Invoice price of one unit, before VAT."""
    if line.list_price_excl_vat is not None:
        return line.list_price_excl_vat
    return line.amount_excl_vat / line.quantity if line.quantity else None


def _ratios(code, line, supplier, invoice_no, catalogue, table) -> list[float]:
    """How many known pieces the invoice unit costs, once per reference cost."""
    unit_price = _unit_price(line)
    refs = _references(code, supplier, invoice_no, catalogue, table)
    return [unit_price / ref for ref in refs] if unit_price else []


def _near(ratio: float, size: float) -> bool:
    return abs(ratio - size) <= PACK_TOLERANCE * size


def _recheck_learned(m: Match, line: InvoiceLine, supplier, invoice_no, catalogue, table) -> None:
    """A learned pack size is checked by price like everything else (D-020 amendment). If the price
    no longer fits it against either known cost (the supplier changed the box from 24 to 12, or the
    first answer was wrong), the question is asked again; the new answer replaces the old one."""
    if line.pieces_known or not m.pack_factor:
        return
    ratios = _ratios(m.item_code, line, supplier, invoice_no, catalogue, table)
    if not ratios or any(1 / MULTIPACK_RATIO < r / m.pack_factor < MULTIPACK_RATIO for r in ratios):
        return
    learned = m.pack_factor
    m.pack_factor = None
    suggest_pack(m, line, supplier, invoice_no, catalogue, table)
    note = f"Last time 1 unit was {learned:g} pieces, but the price has changed a lot. Count again."
    pack = next((f for f in m.flags if f.kind == PACK), None)
    if pack:
        pack.message = f"{note} {pack.message}"
    else:
        m.flags.append(Flag(YELLOW, "quantity", note, PACK, {"suggested": m.pack_factor}))


def suggest_pack(m: Match, line: InvoiceLine, supplier, invoice_no, catalogue, table) -> None:
    """Pack factor = invoice unit price / known cost of one piece (D-020).

    Checked against both known costs (_references). A normal size (COMMON_PACK_SIZES) within the
    tolerance is preferred over the nearest whole number: 25.5x one piece suggests 24, not 26.
    Anything else is still asked, never assumed.
    """
    if line.pieces_known:  # the invoice printed the pack size; quantity is already in pieces
        m.pack_factor = 1
        return
    unit_price = _unit_price(line)
    if not unit_price and line.quantity:  # free goods: no price to compare, so staff confirm the size
        m.flags.append(Flag(YELLOW, "quantity", "Free goods (no price), so the pack size can't be checked.", PACK,
                            {"suggested": line.printed_factor or 1}))
        return
    ratios = _ratios(m.item_code, line, supplier, invoice_no, catalogue, table)
    if not ratios:
        m.flags.append(Flag(RED, "quantity", "Pack size unknown (no known cost to compare with).", PACK,
                            {"suggested": line.printed_factor}))
        return
    printed = line.printed_factor
    if printed:
        if any(_near(r, printed) for r in ratios):
            m.pack_factor = printed  # the invoice prints the pack size and the price confirms it
        elif printed > 1 and any(_near(r, 1) for r in ratios):
            m.pack_factor = 1  # printed as a pack, but our item is the whole pack (priced like one piece)
        else:
            # The price doesn't confirm the printed size (e.g. our cost is out of date): suggest what the
            # paper says, and let staff confirm.
            m.pack_factor = printed
            m.flags.append(Flag(YELLOW, "quantity", f"The invoice says {printed:g} per unit, but the price looks like "
                                                    f"{ratios[0]:.1f}. Check on the box.", PACK, {"suggested": printed}))
        return
    if any(_near(r, 1) for r in ratios):
        m.pack_factor = 1
        return
    # An almost exact whole number wins (13.0x is 13, not the normal 12; 25.6x is not 26); among several, a normal size.
    exact = [(r, round(r)) for r in ratios if abs(r - round(r)) <= EXACT_TOLERANCE * round(r)]
    exact.sort(key=lambda c: c[1] not in COMMON_PACK_SIZES)
    common = next(((r, size) for r in ratios for size in COMMON_PACK_SIZES if _near(r, size)), None)
    best = exact[0] if exact else common
    if best and best[1] in COMMON_PACK_SIZES:
        ratio, size = best
        m.pack_factor = size
        m.flags.append(Flag(YELLOW, "quantity", f"Looks like a pack of {size} (price is {ratio:.1f}x one piece).",
                            PACK, {"suggested": size}))
        return
    ratio = best[0] if best else ratios[0]
    nearest = max(1, round(ratio))
    if _near(ratio, nearest):
        m.pack_factor = nearest
        m.flags.append(Flag(RED, "quantity", f"Possibly a pack of {nearest} (price is {ratio:.1f}x one piece), "
                                             "an unusual size.", PACK, {"suggested": nearest}))
    else:
        m.flags.append(Flag(RED, "quantity", f"Pack size unknown: price is {ratio:.2f}x one piece.", PACK,
                            {"suggested": None}))
