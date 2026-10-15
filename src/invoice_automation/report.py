"""The run report (D-011): every flag in plain language, one section per invoice."""

from datetime import datetime
from pathlib import Path

from .model import ORANGE, RED, SEVERITY, YELLOW
from .pipeline import RunResult

VERDICT = {
    None: "OK. Check it against the paper, then upload.",
    YELLOW: "CHECK the yellow cells against the paper, then upload.",
    ORANGE: "CHECK the yellow/orange cells against the paper, then upload.",
    RED: "DO NOT UPLOAD. Red cells need Zein.",
}


def write_report(run: RunResult, output_dir: Path) -> Path:
    lines = [f"Invoice run {datetime.now():%Y-%m-%d %H:%M}", ""]
    for res in run.invoices:
        inv = res.invoice
        lines.append("=" * 72)
        lines.append(f"{res.output_file.name if res.output_file else '(no file)'}")
        lines.append(f"  From scan: {inv.source.name}, page {', '.join(str(p + 1) for p in inv.pages)}")
        lines.append(f"  {VERDICT[res.worst]}")
        total = f"{inv.printed_total:.2f}" if inv.printed_total is not None else "not found"
        lines.append(f"  {len(inv.lines)} invoice lines -> {len(res.rows)} items. "
                     f"Total: lines {inv.computed_total:.2f}, printed {total}.")
        for flag in inv.flags:
            lines.append(f"  [{flag.level.upper()}] {flag.message}")
        for row in sorted(res.rows, key=lambda r: -max((SEVERITY[f.level] for f in r.flags), default=0)):
            if not row.flags:
                continue
            lines.append(f"  - {row.item.code} {row.item.description} "
                         f"(invoice line {', '.join(row.invoice_lines)}): qty {row.quantity:g}")
            for flag in sorted(row.flags, key=lambda f: -SEVERITY[f.level]):
                lines.append(f"      [{flag.level.upper()}] {flag.message}")
        if res.price_changes:
            lines.append(f"  Price changes: {len(res.price_changes)} (also saved in data/state/price_changes.csv)")
        lines.append("")
    if run.skipped:
        lines.append("=" * 72)
        lines.append("Pages not processed:")
        lines += [f"  - {s}" for s in run.skipped]
    path = output_dir / f"Report {datetime.now():%Y-%m-%d %H%M}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
