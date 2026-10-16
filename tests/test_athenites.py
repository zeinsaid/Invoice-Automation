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


def test_vat_letter_a_is_zero():
    assert athenites.VAT_LETTERS["A"] == 0
