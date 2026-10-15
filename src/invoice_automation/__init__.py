"""Turn scanned supplier invoices into PowerSoft-ready Excel files for The Plug."""

import argparse
import shutil
from datetime import date
from pathlib import Path

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
PROCESSED_DIR = Path("processed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Process scanned invoices into PowerSoft import files.")
    parser.add_argument("pdfs", nargs="*", type=Path,
                        help="Specific PDFs to process (left where they are). Default: everything in input/.")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    from .pipeline import run
    from .report import write_report

    pdfs = args.pdfs or sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDFs in input/.")
        return
    result = run(pdfs, args.output)
    report = write_report(result, args.output)
    print(f"Done. {len(result.invoices)} invoice(s) written to {args.output}/. Report: {report.name}")

    if not args.pdfs:  # D-002: move processed scans out of input/ so nothing is processed twice
        done = PROCESSED_DIR / str(date.today())
        done.mkdir(parents=True, exist_ok=True)
        for pdf in pdfs:
            shutil.move(pdf, done / pdf.name)
