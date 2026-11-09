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


# --- An item we stopped selling, back again (D-031 amendment) -----------------------------------------

def _switched_off(tmp_path, answers):
    from invoice_automation.supplier_items import SupplierItems
    old = Item("5", "CHOC BAR 90GR", "5290000000017", 5, 1.00, 2.00, "S", "", "", True)
    ctx = pipeline.Context(Catalogue({}, {}, {}, {"5": old}), SupplierItems([], tmp_path / "t.xlsx"), {})
    line = InvoiceLine("1", "CHOC BAR 90G", "5290000000017", 12, 12.0, 5, pieces_known=True)
    line.page, line.row_index = 0, 3
    inv = Invoice("S", "Test", "INV1", None, [line], 12.6, 12.6, "x.pdf", [0])
    ev = Evaluation(Entry("x.pdf", [0], "", answers=answers), invoice=inv, answer_keys={line.key: line.key})
    return pipeline._line(line, inv, ev, ctx), ev, ctx


def test_an_inactive_item_with_the_lines_barcode_is_offered(tmp_path):
    q, _, ctx = _switched_off(tmp_path, {})
    assert (q.kind, q.id, q.data["code"], q.data["switched_off"]) == ("item", "item:0:3", "5", True)
    assert "switched off" in q.detail and "5" not in ctx.catalogue.items  # nothing changes until staff say YES


def test_yes_switches_the_inactive_item_back_on(tmp_path):
    q, ev, ctx = _switched_off(tmp_path, {"item:0:3": {"code": "5", "switch_on": True}})
    assert q is None and ev.lines[0][1].item_code == "5"
    assert ctx.catalogue.switched_on == {"5"}


# --- A cost far from what we pay is asked about (D-033) ---------------------------------------------

def _monster(tmp_path, answers, pieces_known=False):
    from invoice_automation.supplier_items import SupplierItems
    can = Item("1625", "MONSTER ZERO CAN 500ML", "5000000000001", 19, 0.99, 1.9, "S", "", "", True)
    ctx = pipeline.Context(Catalogue({"1625": can}, {}, {}), SupplierItems([], tmp_path / "t.xlsx"), {})
    line = InvoiceLine("49", "MONSTER LANDO NORRIS 500ML", "5000000000001", 24, 19.97, 19, 0.83,
                       pieces_known=pieces_known)
    line.page, line.row_index = 0, 48
    inv = Invoice("S", "Test", "INV1", None, [line], 23.76, 23.76, "x.pdf", [0])
    answers = {"item:0:48": {"code": "1625"}, **answers}  # staff picked the item, as on the real invoice
    ev = Evaluation(Entry("x.pdf", [0], "", answers=answers), invoice=inv, answer_keys={line.key: line.key})
    return pipeline._line(line, inv, ev, ctx), ev


def test_cost_far_from_what_we_pay_is_asked(tmp_path):
    # 24 single cans typed as 24 per unit: 576 cans at 0.03 instead of 0.99.
    q, _ = _monster(tmp_path, {"pack:0:48": 24})
    assert q.kind == "cost" and q.id == "cost:0:48" and round(q.data["cost"], 3) == 0.035
    q, _ = _monster(tmp_path, {"pack:0:48": 1})
    assert q is None


def test_cost_confirmed_by_staff_goes_through_and_is_reported(tmp_path):
    q, ev = _monster(tmp_path, {"pack:0:48": 24, "cost:0:48": "ok"})
    assert q is None and "confirmed (usually 0.99)" in ev.cost_confirmed[0]


def test_wrong_pieces_from_the_cost_question_replaces_the_pack_answer(monkeypatch):
    from invoice_automation import session as sm
    monkeypatch.setattr(sm, "save_queue", lambda entries: None)
    s = sm.Session(ctx=None, entries=[])
    entry = Entry("x.pdf", [0], "", answers={"pack:0:48": 24})
    q = pipeline.Question("cost:0:48", "cost", "Is this cost right?", data={"row": "0:48"})
    s.answer(entry, q, 1)
    assert entry.answers == {"pack:0:48": 1}
    s.answer(entry, q, {"code": "86"})  # wrong item: the item answer is replaced, the pieces asked again
    assert entry.answers == {"item:0:48": {"code": "86"}}


# --- What the new-item form starts with (D-034 amendment) -------------------------------------------

def test_new_item_form_starts_at_the_printed_case_size():
    def start(description, printed=None, pieces_known=False):
        line = InvoiceLine("1", description, "", 1, 10.0, 19, printed_factor=printed, pieces_known=pieces_known)
        return pipeline.new_item_defaults(line)

    assert start("HELL ZERO 250ML X 24", 24) == ("HELL ZERO 250ML", 24)
    assert start("HELL COTTON CANDY 250ML X24 SUMMER EDITION", 24) == ("HELL COTTON CANDY 250ML SUMMER EDITION", 24)
    assert start("XIXO TEA LEMON 250ML \u00d7 24", 24) == ("XIXO TEA LEMON 250ML", 24)
    assert start("330 CAN 4X6 COCA COLA ZERO", 24) == ("330 CAN COCA COLA ZERO", 24)
    assert start("BIC LIGHTER MINI", 50) == ("BIC LIGHTER MINI", 50)  # a pack-size column (Andrikian): name kept
    assert start("CHUPA CHUPS X12", 50) == ("CHUPA CHUPS X12", 50)  # the name's number isn't the case: kept
    assert start("SNICKERS 50G") == ("SNICKERS 50G", 1)  # nothing printed
    assert start("MARLBORO RED", 10, pieces_known=True) == ("MARLBORO RED", 1)  # already counts packs (D-005)


def test_do_we_already_sell_one_piece_leaves_out_what_cant_be_the_same_product():
    def item(code, name, brand):
        return Item(code, name, "", 19, 0.5, 1.0, "", brand, "", True)

    items = [item("1", "HELL BLACK CHERRY 250ML", "HELL"), item("2", "HELL BLACK CHERRY 500ML", "HELL"),
             item("3", "SHARK BLACK CHERRY 250ML", "SHARK"), item("4", "HELL CLASSIC 250ML", "HELL")]
    ctx = pipeline.Context(Catalogue({i.code: i for i in items}, {}, {}), None, {})
    ctx.table = type("NoLearned", (), {"rows": []})()
    found = pipeline.single_piece_candidates("HELL BLACK CHERRY 250ML", ctx, None)
    assert [c for c, _, _ in found] == ["1"]  # not the 500 ml can, not Shark, not another flavour
    assert pipeline._sizes("COCA COLA 1.5 LTR") == pipeline._sizes("COCA COLA 1.5L") == {(1.5, "L")}
    assert pipeline._sizes("KINDER BUENO WHITE T3") == set()  # a pack count is not a size: no limit
