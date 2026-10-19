"""Data safety (D-023): nothing learned is lost to a crash, a bad export or a missing file."""

import csv
import zipfile

import openpyxl
import pytest

from invoice_automation.backup import backup_daily
from invoice_automation.catalogue import EXPORT_COLUMNS, Catalogue
from invoice_automation.files import save_atomic
from invoice_automation.pipeline import Context


def write_export(folder, day, n, columns=EXPORT_COLUMNS):
    with (folder / f"items_export_2026-10-{day:02d}.csv").open("w", encoding="cp1253", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for i in range(1, n + 1):
            row = {"Item Code": str(i), "Item Description": f"ITEM {i}", "Barcode": "", "VAT": "19%",
                   "Cost": "1.00", "Price 1": "2.00", "Supplier": "S", "Brand": "", "Category": "C", "Storable": "Yes"}
            w.writerow([row.get(c, "") for c in columns])


@pytest.fixture
def powersoft(tmp_path):
    for name in ("categories.xlsx", "suppliers.xlsx"):
        wb = openpyxl.Workbook()
        wb.active.append(["header"])
        wb.save(tmp_path / name)
    return tmp_path


def test_newest_good_export_is_used(powersoft):
    write_export(powersoft, 1, 100)
    write_export(powersoft, 2, 102)
    cat = Catalogue.load(powersoft)
    assert (cat.export_name, len(cat.items), cat.warnings) == ("items_export_2026-10-02.csv", 102, [])


def test_cut_off_export_falls_back_to_the_previous_one(powersoft):
    write_export(powersoft, 1, 100)
    write_export(powersoft, 2, 40)
    cat = Catalogue.load(powersoft)
    assert (cat.export_name, len(cat.items)) == ("items_export_2026-10-01.csv", 100)
    assert "cut off" in cat.warnings[0]


def test_export_missing_a_column_falls_back_to_the_previous_one(powersoft):
    write_export(powersoft, 1, 100)
    write_export(powersoft, 2, 100, [c for c in EXPORT_COLUMNS if c != "Storable"])
    cat = Catalogue.load(powersoft)
    assert cat.export_name == "items_export_2026-10-01.csv" and "Storable" in cat.warnings[0]


def test_failed_save_keeps_the_old_file(tmp_path):
    path = tmp_path / "learned.txt"
    path.write_text("months of answers")

    def crash(tmp):
        tmp.write_text("half")
        raise OSError("power cut")

    with pytest.raises(OSError):
        save_atomic(path, crash)
    assert path.read_text() == "months of answers" and list(tmp_path.iterdir()) == [path]


def test_daily_backup_once_a_day(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/state").mkdir(parents=True)
    (tmp_path / "data/supplier_items.xlsx").write_text("table")
    (tmp_path / "data/state/queue.json").write_text("[]")
    first = backup_daily()
    assert sorted(zipfile.ZipFile(first).namelist()) == ["state/queue.json", "supplier_items.xlsx"]
    assert backup_daily() is None  # already done today


def test_missing_learned_table_stops_instead_of_starting_over(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/state").mkdir(parents=True)
    (tmp_path / "data/state/processed_invoices.csv").write_text("supplier,invoice\n")
    with pytest.raises(FileNotFoundError, match="backups"):
        Context.load()


def test_itemslist_is_taken_in_once_as_a_dated_copy(powersoft):
    write_export(powersoft, 1, 100)
    write_export(powersoft, 2, 101)
    (powersoft / "items_export_2026-10-02.csv").rename(powersoft / "itemsList.csv")  # PowerSoft's own name
    first = Catalogue.load(powersoft)
    assert len(first.items) == 101 and first.export_name.startswith("items_export_") and first.export_name != \
        "items_export_2026-10-01.csv"
    copies = sorted(p.name for p in powersoft.glob("items_export_*.csv"))
    Catalogue.load(powersoft)  # the same itemsList again: no new copy
    assert sorted(p.name for p in powersoft.glob("items_export_*.csv")) == copies
