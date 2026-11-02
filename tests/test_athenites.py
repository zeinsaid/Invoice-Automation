import re

from invoice_automation.suppliers import athenites


def _cell(row, col, text):
    return {"rowIndex": row, "columnIndex": col, "content": text, "spans": []}


def test_total_skips_the_discount_sum():
    text = "Total (VAT) Included:\n-5.98\n1,026.26\nVAT\n73.14"
    assert re.search(athenites.TOTAL[0], text).group(1) == "1,026.26"


def test_total_without_discounts():
    text = "Total (VAT) Included:\n412.50\nVAT\n20.10"
    assert re.search(athenites.TOTAL[0], text).group(1) == "412.50"


def test_continuation_page_without_header():
    """Page 2: no header row, and the scanner merges number, description and barcode."""
    cells = [
        *[_cell(0, c, t) for c, t in enumerate(["Tel:", "", "", "Staff No.", "2309", "RASAILI M.", "", ""])],
        *[_cell(1, c, t) for c, t in enumerate(["50 LOTUS BISCOFF 150G 5410126006377", "", "",
                                               "9.00", "1.45", "0.00", "13.05", "B"])],
        *[_cell(2, c, t) for c, t in enumerate(["51", "LUX SOAP CREAMY 125GR 8710522961032", "",
                                               "5.00", "2.70", "-4.00", "9.50", "D"])],
    ]
    result = {"content": "", "pages": [{"words": [], "angle": 0.0}],
              "tables": [{"rowCount": 3, "columnCount": 8, "cells": cells}]}
    lines = athenites.parse(result, "x.pdf", 1).lines
    assert [(l.description, l.barcode, l.quantity) for l in lines] == [
        ("LOTUS BISCOFF 150G", "5410126006377", 9.0),
        ("LUX SOAP CREAMY 125GR", "8710522961032", 5.0),
    ]
    assert round(lines[1].amount_excl_vat, 2) == 7.98  # 9.50 incl. 19% VAT
    assert not lines[0].flags and not lines[1].flags


def test_continuation_page_with_seven_columns_and_totals():
    """Another page 2 (invoice 1000752311): number and description share a cell, so the table has 7
    columns, and the header and totals are rows of the same table. Before, none of its lines were read."""
    cells = [
        *[_cell(0, c, t) for c, t in enumerate(["Customer: Cash Customer", "", "Date/Time:", "20/10/26 / 14:50:59",
                                               "", "", ""])],
        *[_cell(1, c, t) for c, t in enumerate(["", "", "", "811647 2320", "", "", ""])],
        *[_cell(2, c, t) for c, t in enumerate(["50 SOUR PATCH COLA 120GR", "7622202812118", "8.00", "1.85",
                                               "0.00", "14.80", "B"])],
        *[_cell(3, c, t) for c, t in enumerate(["", "Total (VAT) Included:", "", "", "-8.90", "1,241.45", ""])],
        *[_cell(4, c, t) for c, t in enumerate(["", "VAT", "", "", "", "107.23", ""])],
    ]
    result = {"content": "", "pages": [{"words": [], "angle": 0.0}],
              "tables": [{"rowCount": 5, "columnCount": 7, "cells": cells}]}
    lines = athenites.parse(result, "x.pdf", 1).lines
    assert [(l.description, l.barcode, l.quantity) for l in lines] == [
        ("SOUR PATCH COLA 120GR", "7622202812118", 8.0)]
    assert not lines[0].flags


def test_one_page_invoice_with_totals_in_the_item_table():
    """A short invoice prints its totals inside the item table (invoices 1000754750/1). Before, the
    'Total (VAT) Included' row was read as a line with no VAT letter and the invoice went to Zein."""
    header = ["A/A", "Description", "Barcode", "Quantity", "Unit Selling Price", "Discount Amount",
              "Amount Incl. VAT", "VAT"]
    rows = [header,
            ["1", "FIZZ PEACH 500ML", "4000000000006", "24.00", "0.95", "0.00", "22.80", "B"],
            ["", "", "Total (VAT) Included:", "", "", "0.00", "22.80", ""],
            ["", "", "VAT", "", "", "", "1.09", ""],
            ["", "VAT Analysis", "NET-TOT VAT 5% (B)", "", "21.71 VAT 5%", "", "1.09", ""]]
    cells = [_cell(r, c, t) for r, row in enumerate(rows) for c, t in enumerate(row)]
    result = {"content": "Total (VAT) Included:\n0.00\n22.80", "pages": [{"words": [], "angle": 0.0}],
              "tables": [{"rowCount": len(rows), "columnCount": 8, "cells": cells}]}
    inv = athenites.parse(result, "x.pdf", 0)
    assert [(l.description, l.quantity, l.flags) for l in inv.lines] == [("FIZZ PEACH 500ML", 24.0, [])]
    assert inv.printed_total == inv.computed_total == 22.80


def test_vat_letter_a_is_zero():
    assert athenites.VAT_LETTERS["A"] == 0
