"""Review-engine rules on made-up lines (D-022)."""

from invoice_automation.catalogue import Catalogue, Item
from invoice_automation.model import UNREADABLE, ZEIN, Invoice, InvoiceLine
from invoice_automation import pipeline
from invoice_automation.pipeline import Entry, Evaluation, _answer_keys, skip_id
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


def test_not_for_the_shop_leaves_out_every_line_of_that_product():
    # D-025: no question, no Excel row, nothing learned; the other line of the same product goes too.
    lines = [_line(0, 0, "5410126006377"), _line(0, 1, "8710522961032"), _line(1, 3, "5410126006377")]
    ev = Evaluation(Entry("x.pdf", [0, 1], ""), answer_keys=_answer_keys(lines))
    ev.entry.answers[skip_id(ev, lines[2])] = True
    assert [_check(line, ev) for line in (lines[0], lines[2])] == [None, None]
    assert ev.skipped == [lines[0], lines[2]] and ev.lines == []


def _check(line, ev):
    return pipeline._line(line, None, ev, None)  # a skipped line needs neither the invoice nor the catalogue


def test_fixed_invoices_go_back_to_staff_but_not_sure_ones_stay(monkeypatch):
    # After an update fixes an automatic check's cause, the invoice leaves Zein's list by itself;
    # one staff sent with "I'm not sure" stays. Zein's mode then shows his list first.
    from invoice_automation import session as sm
    fixed = Entry("a.pdf", [0], "", status="needs_zein", note="Line 3: VAT rate '' could not be read.")
    unsure = Entry("b.pdf", [0], "", status="needs_zein", note=sm.NOT_SURE + "How many pieces in 1 unit?")
    monkeypatch.setattr(sm, "evaluate", lambda entry, ctx: Evaluation(entry, outcome="questions"))
    monkeypatch.setattr(sm, "save_queue", lambda entries: None)
    s = sm.Session(zein=True, ctx=None, entries=[fixed, unsure])
    assert (fixed.status, unsure.status) == ("pending", "needs_zein")
    monkeypatch.setattr(sm, "evaluate", lambda entry, ctx: Evaluation(entry, questions=[pipeline.Question("x", "x", "x")]))
    assert s.next_question()[0] is unsure


# --- An invoice that prints no VAT, with a discount the paper doesn't show (D-030) -------------------

def _asian_invoice(lines, printed_total):
    inv = Invoice("Asian Food Market LTD", "Asian", "SXS-1", None, lines, printed_total, 0.0, "x.pdf", [0],
                  discount=0.15)
    inv.computed_total = athenites.base.computed_total(lines)
    return Evaluation(Entry("x.pdf", [0], ""), invoice=inv)


def test_line_takes_its_items_vat():
    soju = InvoiceLine("1", "SOJU", "", 10, 119.0, 0, amount_incl_vat=119.0)
    ctx = pipeline.Context(Catalogue({"7": Item("7", "SOJU", "", 19, 1.0, 2.0, "", "", "", True)}, {}, {}), None, {})
    pipeline._item_vat(soju, "7", ctx)
    assert (soju.vat_rate, soju.amount_excl_vat, soju.list_price_excl_vat) == (19, 100.0, 10.0)


def test_total_check_takes_the_unprinted_discount_into_account():
    soju = InvoiceLine("1", "SOJU", "", 10, 85.0, 0, amount_incl_vat=85.0)  # 100 on the paper, 15% off
    ev = _asian_invoice([soju], printed_total=100.0)
    pipeline._check_total(ev)
    assert ev.questions == [] and ev.outcome == "questions"
    for typed in (100.0, 85.0):  # the paper's total, or what was paid: both are right
        ev = _asian_invoice([soju], printed_total=None)
        ev.entry.answers["total"] = typed
        pipeline._check_total(ev)
        assert ev.questions == [] and ev.outcome == "questions"
