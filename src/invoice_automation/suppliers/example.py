"""Example Wholesale Ltd: a made-up supplier for the public demo and the final test.

Its invoice (docs/demo/example-invoice.pdf, made by scripts/make_demo_invoice.py) copies the
Athenites layout, so this profile is the Athenites one under another name. Nothing public then names
a real supplier or shows a real price.
"""

import sys

from . import base
from .athenites import (COLUMNS, CONTINUATION_COLUMNS, CONTINUATION_TAIL, DATE, EDITABLE, NUMBER, REQUIRED, TOTAL,
                        VAT_LETTERS, continuation_rows, row_to_line)

__all__ = ["COLUMNS", "CONTINUATION_COLUMNS", "CONTINUATION_TAIL", "DATE", "EDITABLE", "NUMBER", "REQUIRED", "TOTAL",
           "VAT_LETTERS", "continuation_rows", "row_to_line"]

SUPPLIER = "Example Wholesale Ltd"
SHORT_NAME = "Example Wholesale"
MARKERS = ("EXAMPLE WHOLESALE",)


def matches(page_text: str) -> bool:
    return any(m in page_text.upper() for m in MARKERS)


def parse(result, source, page_index, corrections=None):
    return base.parse(sys.modules[__name__], result, source, page_index, corrections)
