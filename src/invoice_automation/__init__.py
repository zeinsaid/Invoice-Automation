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
    args = parser.parse_args()

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
