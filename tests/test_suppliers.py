"""Supplier profiles and page cleaning, on made-up pages shaped like the real scans (2026-10-25 fixes)."""

import re

import pytest

from invoice_automation.layout import without_handwriting
from invoice_automation.model import ZEIN
from invoice_automation.suppliers import (agrotis_pos, asian, athenites, base, cassandra, cocacola, fereos, hell,
                                         identify, jawda, pambos, skipped_reason)


def _page(rows, content="", styles=()):
    """A layout result with one table; `rows` is a list of rows of cell texts, the first being the header."""
    cells = [{"rowIndex": r, "columnIndex": c, "content": t, "spans": []}
             for r, row in enumerate(rows) for c, t in enumerate(row)]
    return {"content": content, "styles": list(styles), "pages": [{"words": [], "angle": 0.0}],
            "tables": [{"rowCount": len(rows), "columnCount": len(rows[0]), "cells": cells}]}


# --- Handwriting (D-027) ---------------------------------------------------------------------------

def test_handwritten_note_is_not_part_of_the_item_name():
    content = "Cutting Mat A2 new"
    page = _page([["Description"], ["Cutting Mat A2 new"]], content,
                 [{"isHandwritten": True, "confidence": 1, "spans": [{"offset": 15, "length": 3}]}])
    page["tables"][0]["cells"][1]["spans"] = [{"offset": 0, "length": len(content)}]
    clean = without_handwriting(page)
    assert clean["tables"][0]["cells"][1]["content"].strip() == "Cutting Mat A2"
    assert clean["content"] == "Cutting Mat A2    "  # same length: offsets into it stay valid
    assert page["tables"][0]["cells"][1]["content"] == "Cutting Mat A2 new"  # the original is untouched


def test_unsure_handwriting_is_kept():
    # DI called a printed quantity '2' handwritten with 0.5 confidence (Coca-Cola): it must stay.
    page = _page([["Quantity"], ["2"]], "2", [{"isHandwritten": True, "confidence": 0.5,
                                              "spans": [{"offset": 0, "length": 1}]}])
    page["tables"][0]["cells"][1]["spans"] = [{"offset": 0, "length": 1}]
    assert without_handwriting(page)["tables"][0]["cells"][1]["content"] == "2"


# --- Athenites total -------------------------------------------------------------------------------

def test_athenites_total_after_a_zero_discount_line():
    text = "Total (VAT) Included:\n0.00\n412.50\nVAT\n20.10"
    assert re.search(athenites.TOTAL[0], text).group(1) == "412.50"


# --- Pambos ----------------------------------------------------------------------------------------

PAMBOS_HEADER = ["Item", "Description", "Quantity", "Price", "Disc %", "Discount", "VAT%", "Total"]


def test_pambos_vat_read_into_the_discount_column():
    page = _page([PAMBOS_HEADER, ["CRYSTALVAPE10", "6970925917131 BERRY ICE 10", "10", "3.00", "", "19", "", "30.00"]])
    line = pambos.parse(page, "x.pdf", 0).lines[0]
    assert (line.vat_rate, line.amount_excl_vat, line.flags) == (19, 30.0, [])


def test_pambos_real_discount_is_still_a_discount():
    page = _page([PAMBOS_HEADER, ["CRYSTALVAPE10", "6970925917131 BERRY ICE 10", "10", "3.00", "", "3.00", "19",
                                  "27.00"]])
    line = pambos.parse(page, "x.pdf", 0).lines[0]
    assert (line.vat_rate, line.amount_excl_vat, line.flags) == (19, 27.0, [])


def test_pambos_description_read_into_the_row_above():
    page = _page([PAMBOS_HEADER,
                  ["GKSPOD9", "6979193576897 GB POD BANANA ICE 9 *10pcs 6979193577153 GB POD STRAWBERRY WATERMELON 11",
                   "30", "1.50", "", "19", "", "45.00"],
                  ["GKSPOD11", "*10pcs", "30", "1.50", "", "", "19", "45.00"]])
    banana, watermelon = pambos.parse(page, "x.pdf", 0).lines
    assert (banana.barcode, banana.description) == ("6979193576897", "GB POD BANANA ICE 9 *10pcs")
    assert (watermelon.barcode, watermelon.description) == ("6979193577153", "GB POD STRAWBERRY WATERMELON 11 *10pcs")
    assert watermelon.pieces_known  # '*10pcs' is the box: the quantity already counts pods


def test_pambos_merged_discount_header_and_summary_box():
    # IN2600007050: both discount columns empty, read as one 'Disc % Discount' column (it crashed on the missing
    # 'Discount'). The line table then had 7 columns, like the summary box below it, which was read as more rows.
    lines = _page([["Item", "Description", "Quantity", "Price", "Disc % Discount", "VAT%", "Total"],
                   ["GKBDEVICE4", "6979193571229 SPARK DEVICE LUNAR SILVER *10pcs", "10", "3.00", "", "19", "30.00"]])
    summary = _page([["Customer Balances", "", "VAT Analysis", "", "", "Invoice Summary", ""],
                     ["Previous Balance 0", "New Balance 0", "Value of Goods", "VAT %", "VAT Amount", "Subtotal", "30.00"],
                     ["", "", "30.00", "19% (19)", "5.70", "Discount Value", ""],
                     ["", "", "", "", "", "Total:", "35.70"]])
    lines["tables"] += summary["tables"]
    inv = pambos.parse(lines, "x.pdf", 0)
    assert [(l.supplier_code, l.quantity, l.amount_excl_vat, l.vat_rate, l.flags) for l in inv.lines] == [
        ("GKBDEVICE4", 10, 30.0, 19, [])]
    assert inv.computed_total == 35.70


# --- Fereos ----------------------------------------------------------------------------------------

FEREOS_HEADER = ["A/A", "ΠΡΟΙΟΝ", "M.M A", "ΠΟΣ. A", "M.M B", "ΠΟΣ. B", "TIMH A (€)", "TIMH B (€)", "EKNIT. (€)",
                 "ΣΥΝΟΛΟ (€)", "Φ.Π.Α. (%)"]


def test_fereos_packets_count_pieces():
    page = _page([FEREOS_HEADER, ["1", "1005017 - Davidoff Gold (5.00 E2C) CY / 4030600298763", "Packet 20", "10", "", "",
                                  "3.927", "", "0.00", "39.27", "19"]])
    line = fereos.parse(page, "x.pdf", 0).lines[0]
    assert (line.description, line.quantity, line.amount_excl_vat, line.pieces_known, line.flags) == (
        "Davidoff Gold", 10, 39.27, True, [])


def test_fereos_outer_in_unit_b_is_a_case():
    # S15310019903: 1 'Outer 5000' of Rizla booklets at 24.00 in the B columns. Staff are asked how many pieces.
    page = _page([FEREOS_HEADER, ["6", "1005020 - Rizla Single Silver 50s (GPSR) / 54031289", "", "", "Outer 5000", "1",
                                  "", "24.000", "0.00", "24.00", "19"]])
    line = fereos.parse(page, "x.pdf", 0).lines[0]
    assert (line.barcode, line.quantity, line.list_price_excl_vat, line.amount_excl_vat) == ("54031289", 1, 24.0, 24.0)
    assert (line.pieces_known, line.flags) == (False, [])


def test_fereos_both_units_filled_goes_to_zein():
    page = _page([FEREOS_HEADER, ["6", "1005020 - Rizla Single Silver 50s (GPSR) / 54031289", "Box 50", "10",
                                  "Outer 5000", "1", "0.46", "24.000", "0.00", "28.60", "19"]])
    assert ZEIN in [f.kind for f in fereos.parse(page, "x.pdf", 0).lines[0].flags]


# --- Agrotis shop counter --------------------------------------------------------------------------

AGROTIS_POS_TEXT = "agrotis Renos Agrotis & Son Ltd\nSALES\nΑΡ. ΤΙΜΟΛΟΓΙΟΥ\nS02 - 1234567\nΗΜΕΡΟΜΗΝΙΑ\n19/10/2026\n" \
                   "ΟΛΙΚΟ ΤΙΜΟΛΟΓΙΟΥ\n17,85"


def test_agrotis_counter_invoice():
    page = _page([["Κωδ.Είδους", "Περιγραφή", "Ποσ.", "M/M", "AĘia", "Σύνολο", "Έκπτωση", "ΦΠΑ", "Σύνολο"],
                  ["ΤΤΡΑ4100", "Lucky Boss Tracing Paper Pad A4 100g 20 sh", "10,00", "x1", "1,50", "15,01", "0,00",
                   "19%", "17,86"]], AGROTIS_POS_TEXT)
    assert identify(AGROTIS_POS_TEXT) is agrotis_pos
    inv = agrotis_pos.parse(page, "x.pdf", 0)
    line = inv.lines[0]
    assert (inv.number, str(inv.date), inv.printed_total) == ("S02-1234567", "2026-10-19", 17.85)
    assert (line.quantity, line.amount_excl_vat, line.vat_rate, line.flags) == (10, 15.01, 19, [])
    assert line.supplier_code == "TTPA4100"  # Greek look-alike letters made Latin: one learning key


def test_agrotis_warehouse_invoice_is_not_the_counter_one():
    from invoice_automation.suppliers import agrotis
    assert identify("Renos Agrotis & Son Ltd\nInvoice No./Page 238742 07.10.2026 1 Of 2") is agrotis


# --- Coca-Cola -------------------------------------------------------------------------------------

COLA_HEADER = ["EAN NUMBER", "MATERIAL", "MATERIAL DESCRIPTION", "UOM", "QUANTITY", "PRICE PER UNIT", "VALUE",
               "REGULAR DISCOUNT", "PROMO DISCOUNT", "NET AMOUNT", "VAT %"]
COLA_TEXT = "Coca-Cola HBC Cyprus\nDocument No: 4000000001 Shipment No: 1000000001\nInvoice Date: 23.10.2026\n" \
            "TOTAL VALUE OF INVOICE 28,56"


@pytest.mark.parametrize("description, size", [
    ("1.5 PET X6 COCA COLA CY", 6), ("330 CAN 4X6 COCA COLA SLK KC GR", 24), ("330 CAN 3X8 COCA COLA ZERO", 24),
    ("500 CAN X24 MONSTER ULTRA FIESTA NP CY", 24), ("500 PET X12 FUZE TEA LEM", 12),
    ("330 NRG 4X6 CORONA EXTRA BOX 11.3 CY", 24), ("COCA COLA 500 X24", 24),
    ("XIXO TEA LEMON 250ML × 24", 24)])
def test_coca_cola_case_size(description, size):
    assert cocacola.case_size(description) == size


def test_coca_cola_line_and_totals_row():
    page = _page([COLA_HEADER,
                  ["5449000000439", "592049", "1.5 PET X6 COCA COLA CY", "CS", "3", "10,00", "30,00", "6,00", "0,00",
                   "24,00", "19"],
                  ["", "", "Totals", "", "3", "", "30,00", "6,00", "0,00", "24,00", ""]], COLA_TEXT)
    assert identify(COLA_TEXT) is cocacola
    inv = cocacola.parse(page, "x.pdf", 0)
    assert (inv.number, str(inv.date), inv.printed_total, inv.computed_total) == ("4000000001", "2026-10-23", 28.56,
                                                                                 28.56)
    [line] = inv.lines  # the Totals row is not an item
    assert (line.quantity, line.printed_factor, line.amount_excl_vat, line.flags) == (3, 6, 24.0, [])
    assert line.list_price_excl_vat == pytest.approx(24.0 / 3)  # what we pay per case


def test_coca_cola_free_case():
    page = _page([COLA_HEADER, ["5060896621647", "2205308", "500 CAN X24 MONSTER ULTRA FIESTA NP CY", "CS", "1",
                                "30,00", "30,00", "0,00", "30,00", "0,00", "19"]], COLA_TEXT)
    line = cocacola.parse(page, "x.pdf", 0).lines[0]
    assert (line.amount_excl_vat, line.list_price_excl_vat, line.flags) == (0.0, 30.0, [])  # price still checks the size


def test_coca_cola_total_after_jumbled_labels():
    text = "TOTAL VALUE OF INVOICE\nISSUED BY :\nRECEIVED BY :\n123,45\nCOLLECTED"
    assert re.search(cocacola.TOTAL[0], text).group(1) == "123,45"


def test_coca_cola_deposit_is_not_stock():
    page = _page([COLA_HEADER, ["5449000000439", "592049", "1.5 PET X6 COCA COLA CY", "CS", "3", "10,00", "30,00",
                                "6,00", "0,00", "24,00", "19"]],
                 COLA_TEXT.replace("28,56", "31,56") + "\nTOTAL VALUE OF RETURNABLES\n3,00")
    assert cocacola.parse(page, "x.pdf", 0).printed_total == 28.56


# --- Asian Food Market order invoice (D-030) -------------------------------------------------------

ASIAN_TEXT = ("CLIENT ZHENG DONISCHAL LTD ORDER NO .: SXS-2026-10-26-00007 DATE: 2026-10-26 11:55:56 "
              "TOTAL QUANTITY: 30 TOTAL AMOUNT: 1,040")
ASIAN_HEADER = ["NO.", "BAR CODE", "NAME", "UNIT", "QUANTITY", "PRICE", "AMOUNT", "NOTES"]


def test_asian_order_invoice():
    page = _page([ASIAN_HEADER,
                  ["1", "1111111111116", "LOTTE SOJU APPLE 苹果烧酒", "BTL 瓶", "20", "50", "1000", ""],
                  ["2", "2222222222222", "KOREAN NOODLES", "袋", "10", "4", "40", ""],
                  ["SUM", "", "", "", "30", "", "1040", ""]], ASIAN_TEXT)
    assert identify(ASIAN_TEXT) is asian
    inv = asian.parse(page, "x.pdf", 0)
    assert (inv.number, str(inv.date), inv.printed_total, inv.discount) == ("SXS-2026-10-26-00007", "2026-10-26",
                                                                           1040.0, 0.15)
    first, second = inv.lines  # the SUM row is not an item
    assert (first.description, first.quantity, first.flags) == ("LOTTE SOJU APPLE", 20, [])
    assert (first.amount_incl_vat, second.amount_incl_vat) == (pytest.approx(850.0), pytest.approx(34.0))  # 15% off


def test_asian_till_receipt_is_still_entered_by_hand():
    receipt = "Cash Invoice ASIAN FOOD MARKET ZHENG DONISCHAL LTD InvNo: 00155409"
    assert identify(receipt) is None
    assert "till receipt" in skipped_reason(receipt)


# --- Hell Beverages ---------------------------------------------------------------------------------

HELL_TEXT = ("HELL BEVERAGES LTD\nCREDIT INVOICE\nDocument No. : INIC1000001\nDocument Date\n: 01/11/2026\n"
             "Gross Value:\n30.00\nDiscount:\n0.00\nNet Value:\n30.00\nVAT:\n4.83\nTotal:\n34.83")
HELL_HEADER = ["Item Code", "Description", "Qty", "Price", "Disc %", "Vat %", "Amount"]


def test_hell_invoice():
    page = _page([HELL_HEADER,
                  ["5449000000439", "HELL CLASSIC 250ML X 24", "1", "10.00", "", "19", "10.00"],
                  ["5000112637922", "XIXO TEA LEMON 250ML \u00d7 24", "1.", "5.00", "", "5", "5.00"],
                  ["5000112637939", "HELL ZERO 500ML X 12", "2", "7.50", "", "19", "15.00"]], HELL_TEXT)
    assert identify(HELL_TEXT) is hell
    assert identify("ATHIENITIS ... HELL CLASSIC 250ML") is athenites  # Hell cans on another supplier's invoice
    inv = hell.parse(page, "x.pdf", 0)
    assert (inv.number, str(inv.date), inv.printed_total) == ("INIC1000001", "2026-11-01", 34.83)
    assert [(l.quantity, l.printed_factor, l.list_price_excl_vat, l.flags) for l in inv.lines] == [
        (1, 24, 10.0, []), (1, 24, 5.0, []), (2, 12, 7.5, [])]  # 'x' read as the '×' sign; '1.' is 1


def test_hell_rounds_vat_per_line():
    # 10.60 at 19% is 2.014: Hell prints 2.01 on every such line. Rounded once per rate, ten of them
    # would be 4 cents more than the paper; rounded per line, the same as the paper.
    page = _page([HELL_HEADER] + [["5449000000439", "HELL CLASSIC 250ML X 24", "1", "10.60", "", "19", "10.60"]] * 10,
                 HELL_TEXT)
    inv = hell.parse(page, "x.pdf", 0)
    assert inv.computed_total == 126.10  # 10 x (10.60 + 2.01)
    assert hell.base.computed_total(inv.lines) == 126.14  # the usual way
    assert hell.base.combine([inv]).computed_total == 126.10


# --- Jawda (D-035) ----------------------------------------------------------------------------------

def test_jawda_invoice():
    # Made-up lines shaped like # 105: no barcodes, pieces in the description, a wrong 'Σύνολο' (the supplier's
    # own sum) under the lines, and the right total in 'Τελική τιμή'.
    text = "JAWDA LTD\nΑριθμός τιμολογίου # 7 ΗΜΕΡΟΜΗΝΙΑ: 3/12/2026\nΦΠΑ (19%)\n9.12\nΤελική τιμή\n€ 57.12"
    page = _page([["Περιγραφή", "Ποσότητα", "Τιμή (EURO)"],
                  ["Test Tissues Rose 500ply 18packs/bag", "2", "14.40"],
                  ["Test pocket 10packs/multipack 12mltp/box", "2", "9.60"],
                  ["Σύνολο", "", "50.00"], ["ΦΠΑ (19%)", "9.12", ""], ["Τελική τιμή", "€ 57.12", ""]], text)
    assert identify(text) is jawda
    inv = jawda.parse(page, "x.pdf", 0)
    assert [(l.quantity, l.amount_excl_vat, l.vat_rate, l.printed_factor, l.pieces_known) for l in inv.lines] == [
        (2, 28.80, 19, 18, False), (2, 19.20, 19, 12, False)]
    assert (inv.number, str(inv.date), inv.printed_total, inv.computed_total) == ("7", "2026-12-03", 57.12, 57.12)


# --- Cassandra: a long till roll scanned in two pieces (D-004 amendment 2026-11-09) ----------------------------

CASSANDRA_HEADER = ["PRODUCT", "FACT", "QTY", "SUB", "PRC", "GROSS", "DISC %", "VAT %", "TOTAL"]
RED = ["AB01 - TEST RED KS/ 5290000000017", "10", "2", "0", "30.00", "60.00", "0%", "19%", "71.40"]
GOLD = ["AB02 - TEST GOLD KS/ 5290000000024", "10", "1", "0", "30.00", "30.00", "0%", "19%", "35.70"]


def _cassandra_pages(second_piece):
    first = _page([CASSANDRA_HEADER, RED, GOLD], "CASSANDRA TRADING LTD\n2220210000001 (Αρ. Εκτύπωσης: 1)")
    second = _page(second_piece, "ΟΛΙΚΟ ΕΥΡΩ / TOTAL EURO\n130.90")
    return [cassandra.parse(first, "x.pdf", 0), cassandra.parse(second, "x.pdf", 1)]


def test_cassandra_second_piece_without_header_and_with_overlap():
    # The second piece starts with the end of a product cut off at the top, then repeats the last line of the
    # first piece. The scanner added an empty column among the numbers, in a different place on each row.
    pages = _cassandra_pages([
        ["5290000000048", "", "", "", "", "", "", "", "", ""],
        ["AB02 - TEST GOLD KS/ 5290000000024", "10", "1", "0", "", "30.00", "30.00", "0%", "19%", "35.70"],
        ["AB03 - TEST BLUE/ 5290000000031", "6", "2", "", "0", "10.00", "20.00", "0%", "19%", "23.80"]])
    inv = base.combine(pages)
    assert [(l.description, l.quantity, l.amount_excl_vat, l.flags) for l in inv.lines] == [
        ("TEST RED", 20, 60.0, []), ("TEST GOLD", 10, 30.0, []), ("TEST BLUE", 12, 20.0, [])]
    assert (inv.computed_total, inv.printed_total) == (130.90, 130.90)


def test_overlap_is_only_dropped_for_till_rolls():
    pages = _cassandra_pages([GOLD])
    for page in pages:
        page.overlapping_pages = False  # an A4 invoice: the same line on two pages is two lines
    assert len(base.combine(pages).lines) == 3
    pages = _cassandra_pages([GOLD[:4] + ["30.00", "60.00"] + GOLD[6:8] + ["71.40"]])  # same item, other numbers
    assert len(base.combine(pages).lines) == 3
