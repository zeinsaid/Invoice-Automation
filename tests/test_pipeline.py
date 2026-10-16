"""Review-engine rules on made-up lines (D-022)."""

from invoice_automation.model import UNREADABLE, ZEIN, InvoiceLine
from invoice_automation.pipeline import _answer_keys
from invoice_automation.suppliers import athenites


def _line(page, row, barcode, code=""):
    line = InvoiceLine("1", "X", barcode, 1, 1.0, 5, supplier_code=code)
    line.page, line.row_index = page, row
    return line


def test_repeated_product_shares_one_answer():
    # Athenites prints a second line when an item is scanned again: one question, one new code.
    lines = [_line(0, 0, "5410126006377"), _line(0, 1, "8710522961032"), _line(1, 3, "5410126006377")]
    keys = _answer_keys(lines)
    assert keys["1:3"] == "0:0" and keys["0:1"] == "0:1"


def test_supplier_code_links_lines_without_barcode():
    lines = [_line(0, 0, "", "CRYSTALVAPE14"), _line(0, 4, "", "CRYSTALVAPE14"), _line(0, 5, "")]
    keys = _answer_keys(lines)
    assert keys["0:4"] == "0:0" and keys["0:5"] == "0:5"


def _row_cells(qty):
    cells = ["9", "LOTUS BISCOFF 150G 5410126006377", "", qty, "1.45", "0.00", "13.05", "B"]
    return {"content": "", "pages": [{"words": [], "angle": 0.0}],
            "tables": [{"rowCount": 1, "columnCount": 8, "cells": [
                {"rowIndex": 0, "columnIndex": c, "content": t, "spans": []} for c, t in enumerate(cells)]}]}


def test_negative_quantity_is_a_misread():
    line = athenites.parse(_row_cells("-9.00"), "x.pdf", 1).lines[0]
    assert any(f.kind == UNREADABLE for f in line.flags)


def test_negative_quantity_typed_from_the_paper_goes_to_zein():
    line = athenites.parse(_row_cells("-9.00"), "x.pdf", 1, {"0": {"quantity": "-9.00"}}).lines[0]
    assert any(f.kind == ZEIN for f in line.flags)
