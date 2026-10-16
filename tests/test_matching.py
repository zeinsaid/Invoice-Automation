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
