"""Supplier profiles and page cleaning, on made-up pages shaped like the real scans (2026-10-25 fixes)."""

import re

import pytest

from invoice_automation.layout import without_handwriting
from invoice_automation.suppliers import agrotis_pos, athenites, cocacola, identify, pambos


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
    ("330 NRG 4X6 CORONA EXTRA BOX 11.3 CY", 24), ("COCA COLA 500 X24", 24)])
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
