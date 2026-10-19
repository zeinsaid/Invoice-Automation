"""A daily backup of everything the tool has learned (D-023).

The first run each day zips the learned table and the state files into data/backups/, and keeps
the newest KEEP zips. To restore, unzip the newest one into data/ (Zein does this over AnyDesk).
The DI cache is not included: it is large, and losing it only costs Azure pages, never answers.
"""

import zipfile
from datetime import date
from pathlib import Path

from .files import save_atomic

DATA = Path("data")
BACKUPS = DATA / "backups"
KEEP = 30
LEARNED = [DATA / "supplier_items.xlsx", DATA / "flag_items.csv", DATA / "state"]


def backup_daily() -> Path | None:
    """Make today's backup if there isn't one yet. Returns the zip, or None if nothing was done."""
    target = BACKUPS / f"backup {date.today()}.zip"
    files = [f for p in LEARNED if p.exists() for f in ([p] if p.is_file() else sorted(p.rglob("*"))) if f.is_file()]
    if target.exists() or not files:
        return None

    def write(tmp: Path) -> None:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, f.relative_to(DATA))

    save_atomic(target, write)
    for old in sorted(BACKUPS.glob("backup *.zip"))[:-KEEP]:
        old.unlink()
    return target
