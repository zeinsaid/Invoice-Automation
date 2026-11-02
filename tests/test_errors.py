"""One invoice the tool fails on waits for Zein; the others carry on (D-032). Made-up data only."""

import csv

import pytest

from invoice_automation import pipeline
from invoice_automation import session as sm
from invoice_automation.catalogue import Catalogue, Item
from invoice_automation.matching import Match
from invoice_automation.model import Invoice, InvoiceLine
from invoice_automation.pipeline import Entry, Evaluation, Question
from invoice_automation.supplier_items import SupplierItems

SUPPLIER = "Test Supplier"


@pytest.fixture
def shop(tmp_path, monkeypatch):
    """An empty shop folder: the tool's files go to tmp_path, nothing real is touched."""
    monkeypatch.chdir(tmp_path)
    ready = tmp_path / "ready"
    for name, value in (("READY_DIR", ready), ("TO_UPLOAD", tmp_path / "to_upload.json"),
                        ("PROCESSED", tmp_path / "processed.csv"), ("PRICE_CHANGES", tmp_path / "prices.csv"),
                        ("NEW_ITEMS", tmp_path / "new_items.csv")):
        monkeypatch.setattr(pipeline, name, value)
    monkeypatch.setattr(sm, "save_queue", lambda entries: None)
    monkeypatch.setattr(sm.Context, "load", classmethod(lambda cls: "reloaded"))
    return tmp_path


def _session(entries, evaluate, monkeypatch):
    monkeypatch.setattr(sm, "evaluate", evaluate)
    return sm.Session(ctx=None, entries=entries)


def test_an_invoice_that_crashes_waits_for_zein_and_the_next_one_is_asked(shop, monkeypatch):
    broken, fine = Entry("a.pdf", [0], ""), Entry("b.pdf", [0], "")

    def evaluate(entry, ctx):
        if entry is broken:
            raise KeyError("something the code didn't expect")
        return Evaluation(entry, questions=[Question("x", "x", "x")])

    s = _session([broken, fine], evaluate, monkeypatch)
    assert s.next_question()[0] is fine
    assert (broken.status, broken.note) == ("needs_zein", sm.CRASHED)
    assert "KeyError" in (shop / "logs" / "error.log").read_text(encoding="utf-8")
    assert s.ctx == "reloaded"  # nothing half-done reaches the next invoice
    assert s.next_question()[0] is fine  # not tried again in this run, so it is logged once
    assert (shop / "logs" / "error.log").read_text(encoding="utf-8").count("\n--- ") == 1


def test_a_file_open_in_excel_still_stops_with_the_close_excel_message(shop, monkeypatch):
    def evaluate(entry, ctx):
        raise PermissionError("supplier_items.xlsx is open in Excel. Close it and run again.")

    s = _session([Entry("a.pdf", [0], "")], evaluate, monkeypatch)
    with pytest.raises(PermissionError):
        s.next_question()
    assert s.entries[0].status == "pending"


def test_a_scan_that_cant_be_read_is_tried_again_next_time(shop, monkeypatch):
    unreadable, good = Entry("a.pdf", [0, 1], "", status="new"), Entry("b.pdf", [0], "", status="new")

    def split(entries):
        if entries[0] is unreadable:
            raise ConnectionError("no internet")
        return [Entry(e.file, e.pages, e.added) for e in entries]

    monkeypatch.setattr(sm, "split", split)
    s = _session([unreadable, good], lambda entry, ctx: Evaluation(entry, questions=[Question("x", "x", "x")]),
                 monkeypatch)
    entry, _, _ = s.next_question()
    assert entry.file == "b.pdf"
    assert unreadable.status == "new"  # split into invoices once it can be read
    assert s.summary()["needs_zein"][0].note == sm.UNREADABLE_SCAN


def _ready_invoice(tmp_path):
    item = Item("7", "FIZZ CAN 330ML", "1111111111116", 19, 0.50, 1.20, SUPPLIER, "", "", True)
    catalogue = Catalogue({"7": item}, {}, {})
    line = InvoiceLine("1", "FIZZ CAN 330ML", "1111111111116", 24, 12.0, 19)
    inv = Invoice(SUPPLIER, "Test", "INV1", None, [line], 14.28, 14.28, tmp_path / "x.pdf", [0])
    (tmp_path / "x.pdf").write_bytes(b"scan")
    ev = Evaluation(Entry("x.pdf", [0], ""), invoice=inv, outcome="ready", lines=[(line, Match("7", 1, "barcode"))])
    return ev, pipeline.Context(catalogue, SupplierItems([], tmp_path / "t.xlsx"), {})


def test_finalize_that_stops_half_way_leaves_nothing_to_upload(shop, monkeypatch):
    ev, ctx = _ready_invoice(shop)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(pipeline, "_record_processed", fail)  # the very last save
    with pytest.raises(OSError):
        pipeline.finalize(ev, ctx)
    assert list((shop / "ready").glob("*.xlsx")) == []  # staff can't upload an invoice on Zein's list
    assert pipeline.waiting_uploads() == []
    assert ev.entry.status == "pending"

    monkeypatch.undo()  # fixed by an update: the second try goes through, and isn't "already done"
    monkeypatch.chdir(shop)
    for name, value in (("READY_DIR", shop / "ready"), ("TO_UPLOAD", shop / "to_upload.json"),
                        ("PROCESSED", shop / "processed.csv"), ("PRICE_CHANGES", shop / "prices.csv"),
                        ("NEW_ITEMS", shop / "new_items.csv")):
        monkeypatch.setattr(pipeline, name, value)
    assert pipeline._previous_processing(ev.invoice) is None
    pipeline.finalize(ev, ctx)
    assert [w["file"] for w in pipeline.waiting_uploads()] == ["Test INV1.xlsx"] and ev.entry.status == "done"


def test_a_new_item_keeps_its_code_when_the_invoice_is_finished_again(shop):
    _, ctx = _ready_invoice(shop)
    line = InvoiceLine("1", "NEW CHOC 50G", "4000000000006", 10, 5.0, 5)
    inv = Invoice(SUPPLIER, "Test", "INV1", None, [line], 5.25, 5.25, shop / "x.pdf", [0])
    form = {"description": "NEW CHOC 50G", "barcode": "4000000000006", "price": 1.0, "category": "Chocolate"}
    first = pipeline._issue_new_item([line], inv, form, 1, ctx.catalogue)
    again = pipeline._issue_new_item([line], inv, form, 1, ctx.catalogue)
    assert first.code == again.code == "8"
    with (shop / "new_items.csv").open(encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 1
