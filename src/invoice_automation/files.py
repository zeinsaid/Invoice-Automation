"""Saving files so a crash or power cut can never leave a half-written one behind (D-023).

Each file is written to a temporary copy next to it, then swapped in with one rename. Windows
does that rename in a single step, so the file is always either the old version or the new one.
"""

import os
from pathlib import Path
from typing import Callable

import openpyxl


def save_atomic(path: Path, write: Callable[[Path], None]) -> None:
    """Call `write(tmp)` to write the new content, then put it in place of `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        write(tmp)
        os.replace(tmp, path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise PermissionError(f"{path.name} is open in Excel. Close it and run again.") from None
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_rows(path: Path, first_sheet: bool = False) -> list[tuple]:
    """The values of every row below the header. A read-only workbook keeps its file open until it is
    closed, and Windows can't replace an open file: the learned table, loaded and saved again at once
    (an invoice with no questions), failed with "open in Excel". So it is closed here straight away."""
    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        ws = wb.worksheets[0] if first_sheet else wb.active
        return list(ws.iter_rows(min_row=2, values_only=True))
    finally:
        wb.close()
