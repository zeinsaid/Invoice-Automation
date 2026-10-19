"""Turn scanned supplier invoices into PowerSoft-ready Excel files for The Plug."""

import argparse
import sys
from pathlib import Path

INPUT_DIR = Path("input")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process scanned invoices into PowerSoft import files.")
    parser.add_argument("pdfs", nargs="*", type=Path,
                        help="Specific PDFs to process, left where they are. Default: everything in input/, "
                             "which is moved to processed/.")
    parser.add_argument("--zein", action="store_true", help="Zein's mode: also work through Zein's list.")
    parser.add_argument("--no-window", action="store_true",
                        help="No window: finish what needs no questions and list the rest (for testing).")
    parser.add_argument("--packs", action="store_true",
                        help="List which single item each pack sub-item counts as (check after a new export).")
    args = parser.parse_args()

    if args.packs:
        show_packs()
        return

    from .session import Session

    session = Session(zein=args.zein)
    pdfs = args.pdfs or sorted(INPUT_DIR.glob("*.pdf"))
    move = not args.pdfs  # D-002: scans taken from input/ are moved out so nothing is processed twice

    if args.no_window:
        sys.stdout.reconfigure(encoding="utf-8")
        if pdfs:
            session.add(pdfs, move)
        nxt = session.next_question()
        for status, events in session.summary().items():
            for e in events:
                print(f"{status:10} {e.entry.label or e.entry.file}  {e.note}")
        if nxt:
            entry, ev, q = nxt
            print(f"Waiting for answers: {entry.label}: {q.title} (and {len(ev.questions) - 1} more on it)")
        session.write_report()
        return

    from .ui import run_window

    run_window(session, pdfs, move)


def show_packs() -> None:
    """Zein's check after a new export: every pack named "... xN" and the single item it counts as."""
    from .catalogue import Catalogue

    sys.stdout.reconfigure(encoding="utf-8")
    cat = Catalogue.load()
    for code, link in sorted(cat.pack_links.items(), key=lambda kv: cat.items[kv[0]].description):
        how = "same name" if link.exact else "NEAR NAME, check it"
        print(f"{cat.items[code].description} ({code})  ->  {link.pieces} x {cat.items[link.single].description} "
              f"({link.single})   [{how}]")
    for code in cat.unlinked_packs:
        print(f"{cat.items[code].description} ({code})  ->  NOT LINKED: no clear single item. Staff will be asked "
              "once. Rename it to the single item's exact name plus ' xN' to link it.")
