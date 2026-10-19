"""Pack-size suggestion (D-020) on a tiny made-up catalogue."""

from invoice_automation.catalogue import Catalogue, Item, name_key
from invoice_automation.matching import match_line
from invoice_automation.model import RED, YELLOW, InvoiceLine
from invoice_automation.supplier_items import SupplierItems

SUPPLIER = "Test Supplier"


def catalogue(*extra: Item):
    items = [
        Item("1", "FIZZ CAN 330ML", "1111111111116", 19, 0.50, 1.20, SUPPLIER, "", "", True),
        Item("2", "CRISPS SALTED 40G", "2222222222222", 5, 0.40, 0.90, SUPPLIER, "", "", True),
        *extra,
    ]
    return Catalogue({i.code: i for i in items}, {}, {})


def line(description, barcode, qty, list_price, amount=None):
    amount = qty * list_price if amount is None else amount
    return InvoiceLine("1", description, barcode, qty, amount, 19, list_price_excl_vat=list_price)


def match(l, tmp_path):
    return match_line(l, SUPPLIER, "INV1", catalogue(), SupplierItems([], tmp_path / "t.xlsx"))


def test_piece_barcode_is_factor_one(tmp_path):
    m = match(line("FIZZ CAN 330ML", "1111111111116", 24, 0.50), tmp_path)
    assert (m.item_code, m.pack_factor, m.method, m.flags) == ("1", 1, "barcode", [])


def test_case_barcode_suggests_common_pack(tmp_path):
    # A different (case) barcode, same name, priced at 24 cans.
    m = match(line("FIZZ CAN 330ML", "9999999999994", 2, 12.00), tmp_path)
    assert (m.item_code, m.pack_factor) == ("1", 24)
    assert [f.level for f in m.flags] == [YELLOW]


def test_discount_does_not_change_pack_size(tmp_path):
    # 25% off the case: the ratio uses the price before discount, so it's still 24.
    m = match(line("FIZZ CAN 330ML", "9999999999994", 1, 12.00, amount=9.00), tmp_path)
    assert m.pack_factor == 24


def test_unusual_pack_size_is_red(tmp_path):
    m = match(line("FIZZ CAN 330ML", "9999999999994", 1, 6.50), tmp_path)  # 13x one can
    assert m.pack_factor == 13 and [f.level for f in m.flags] == [RED]


def test_price_between_pack_sizes_is_red_with_no_factor(tmp_path):
    m = match(line("FIZZ CAN 330ML", "9999999999994", 1, 1.25), tmp_path)  # 2.5x
    assert m.pack_factor is None and [f.level for f in m.flags] == [RED]


def test_cut_off_name_matches(tmp_path):
    # The supplier prints at most 30 characters.
    items = catalogue(Item("3", "SUPER LONG PRODUCT NAME HERE 500ML", "", 19, 1.0, 2.0, SUPPLIER, "", "", True))
    m = match_line(line("SUPER LONG PRODUCT NAME HERE 5", "8888888888888", 1, 1.0), SUPPLIER, "INV1",
                   items, SupplierItems([], tmp_path / "t.xlsx"))
    assert (m.item_code, m.method) == ("3", "name")


def test_unknown_product_is_new(tmp_path):
    m = match(line("SOMETHING ELSE ENTIRELY", "7777777777777", 1, 3.0), tmp_path)
    assert m.item_code is None and m.method == "new"


def test_name_key_ignores_characters_powersoft_strips():
    assert name_key("M&M'S (PEANUT) 45G") == name_key("MMS PEANUT 45 G")


def test_misread_letter_still_matches(tmp_path):
    items = catalogue(Item("4", "L&M BLUE LABEL", "76239366", 19, 3.3, 4.3, SUPPLIER, "", "", True))
    m = match_line(line("L&M BLUE ABEL", "7623900203895", 10, 3.3), SUPPLIER, "INV1", items,
                   SupplierItems([], tmp_path / "t.xlsx"))
    assert (m.item_code, m.method) == ("4", "fuzzy")


def test_printed_pack_size_confirmed_by_price(tmp_path):
    # Piece barcode, but the invoice sells boxes of 24 (Andrikian); the price agrees, so no question.
    l = line("FIZZ CAN 330ML", "1111111111116", 2, 12.00)
    l.printed_factor = 24
    m = match(l, tmp_path)
    assert (m.item_code, m.pack_factor, m.flags) == ("1", 24, [])


def test_printed_pack_size_but_our_item_is_the_pack(tmp_path):
    # The invoice prints x12, but our item is priced like the whole pack: 1 unit = 1 item.
    l = line("CRISPS SALTED 40G", "2222222222222", 3, 0.40)
    l.printed_factor = 12
    m = match(l, tmp_path)
    assert (m.pack_factor, m.flags) == (1, [])


def test_printed_pack_size_disagreeing_with_price_is_asked(tmp_path):
    l = line("FIZZ CAN 330ML", "1111111111116", 1, 10.00)  # 20x one can, but printed x24
    l.printed_factor = 24
    m = match(l, tmp_path)
    assert m.pack_factor == 24 and [(f.level, f.data["suggested"]) for f in m.flags] == [("yellow", 24)]


def test_piece_item_holding_the_pack_barcode_is_asked(tmp_path):
    # PowerSoft's single item carries the bag's barcode (Chupa Chups 310): priced at 10 pieces.
    m = match(line("FIZZ CAN 330ML X10", "1111111111116", 6, 5.00), tmp_path)
    assert (m.item_code, m.pack_factor, m.method) == ("1", 10, "barcode")
    assert [f.level for f in m.flags] == [RED]  # 10 isn't a common size yet


def test_barcode_match_with_old_cost_stays_one_piece(tmp_path):
    # Cost stored with VAT (0.60 instead of 0.50) is a price change, not a pack.
    m = match(line("FIZZ CAN 330ML", "1111111111116", 24, 0.42), tmp_path)
    assert (m.pack_factor, m.flags) == (1, [])


def _learned(barcode, factor, last_cost, tmp_path):
    from invoice_automation.supplier_items import TRUSTED, SupplierItem
    row = SupplierItem(SUPPLIER, "barcode", barcode, "FIZZ CASE", "1", factor, TRUSTED, "staff",
                       last_cost, "INV0", None, "2026-10-01")
    return SupplierItems([row], tmp_path / "t.xlsx")


def test_normal_size_preferred_within_tolerance(tmp_path):
    # 12.75 / 0.50 = 25.5x: suggest the normal 24, not an unusual 26.
    m = match(line("FIZZ CAN 330ML", "9999999999994", 1, 12.75), tmp_path)
    assert m.pack_factor == 24 and [f.level for f in m.flags] == [YELLOW]


def test_promotion_on_last_invoice_does_not_spoil_the_suggestion(tmp_path):
    # The last invoice was a promotion (0.40 a can); PowerSoft still says 0.50. A case at 12.00 is 24.
    table = SupplierItems([], tmp_path / "t.xlsx")
    from invoice_automation.supplier_items import TRUSTED, SupplierItem
    table.upsert(SupplierItem(SUPPLIER, "name", "X", "X", "1", None, TRUSTED, "legacy", 0.40, "INV0", None, "2026-10-01"))
    m = match_line(line("FIZZ CAN 330ML", "9999999999994", 1, 12.00), SUPPLIER, "INV1", catalogue(), table)
    assert m.pack_factor == 24


def test_learned_pack_size_is_kept_while_the_price_fits(tmp_path):
    table = _learned("9999999999994", 24, 0.50, tmp_path)
    m = match_line(line("FIZZ CASE", "9999999999994", 1, 12.50), SUPPLIER, "INV1", catalogue(), table)
    assert (m.method, m.pack_factor, m.flags) == ("learned", 24, [])


def test_learned_pack_size_is_asked_again_when_the_price_halves(tmp_path):
    # The supplier now sells the case of 12: same barcode, half the price.
    table = _learned("9999999999994", 24, 0.50, tmp_path)
    m = match_line(line("FIZZ CASE", "9999999999994", 1, 6.00), SUPPLIER, "INV1", catalogue(), table)
    assert m.pack_factor == 12
    assert "Last time 1 unit was 24 pieces" in m.flags[0].message


# --- Pack sub-items linked to their single piece by name (D-005 amendment) -------------------------

def pack(code, name, barcode="", cost=0.0):
    return Item(code, name, barcode, 19, cost, None, SUPPLIER, "", "", False)  # holds no stock


def test_pack_links_by_same_name_typo_and_size():
    cat = catalogue(
        Item("3", "FIZZ ZERO CAN 330ML", "3333333333333", 19, 0.50, 1.20, SUPPLIER, "", "", True),
        Item("4", "WATER 500ML", "4444444444444", 5, 0.20, 0.50, SUPPLIER, "", "", True),
        pack("10", "FIZZ CAN 330ML x6"),  # same name as 1, although 3 is just as similar
        pack("11", "FIZZ CAN x6"),  # 1 and 3 equally similar: not linked
        pack("12", "CRIPSS SALTED 40G X12"),  # typo
        pack("13", "WATER 1.5L x6"),  # no 1.5 L single: not linked to the 500 ML one
        pack("14", "WATER 500ML x1"),  # one piece is not a pack
    )
    links = {code: (link.single, link.pieces, link.exact) for code, link in cat.pack_links.items()}
    assert links == {"10": ("1", 6, True), "12": ("2", 12, False)}
    assert sorted(cat.unlinked_packs) == ["11", "13"]


def match_in(cat, l, tmp_path):
    return match_line(l, SUPPLIER, "INV1", cat, SupplierItems([], tmp_path / "t.xlsx"))


def test_pack_barcode_counts_as_single_pieces(tmp_path):
    cat = catalogue(pack("10", "FIZZ CAN 330ML x6", "5555555555550"))
    m = match_in(cat, line("FIZZ 6PACK", "5555555555550", 10, 3.00), tmp_path)  # 6 x 0.50
    assert (m.item_code, m.pack_factor, m.method, m.flags) == ("1", 6, "barcode+pack_link", [])


def test_pack_price_that_disagrees_is_asked_with_n_suggested(tmp_path):
    cat = catalogue(pack("10", "FIZZ CAN 330ML x6", "5555555555550"))
    m = match_in(cat, line("FIZZ 6PACK", "5555555555550", 10, 6.00), tmp_path)  # priced like 12
    assert (m.item_code, m.pack_factor) == ("1", None)
    assert [(f.level, f.data["suggested"]) for f in m.flags] == [(YELLOW, 6)]
