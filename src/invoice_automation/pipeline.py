"""Scans in, Excel files and a report out: ties the steps together.

For each PDF: split into pages (D-004) -> read each page with prebuilt-layout (D-021) -> find the
supplier -> parse its invoice (supplier profile) -> match every line (D-006) -> convert to selling
pieces and cost per piece (D-005, D-009) -> check the total (D-010) -> write the Excel with flags
(D-008, D-011) -> remember what was learned (D-018).
"""

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pymupdf

from . import suppliers
from .catalogue import Catalogue, Item
from .extract import analyze_page
from .matching import Match, match_line
from .model import ORANGE, RED, SEVERITY, YELLOW, Flag, Invoice, InvoiceLine
from .output import OutputRow, write_invoice_excel
from .supplier_items import PROVISIONAL, TRUSTED, SupplierItem, SupplierItems

STATE_DIR = Path("data/state")
NEW_ITEMS = STATE_DIR / "new_items.csv"  # codes issued by the tool = local additions (D-012, D-018)
PROCESSED = STATE_DIR / "processed_invoices.csv"  # duplicate-scan guard (D-018)
PRICE_CHANGES = STATE_DIR / "price_changes.csv"  # D-009
FLAG_ITEMS = Path("data/flag_items.csv")  # items to always flag, e.g. single/pack pairs (D-005 amendment)

TOTAL_TOLERANCE = 0.05  # euros
PRICE_CHANGE_MIN = 0.01  # euros per piece; smaller differences are rounding (PowerSoft keeps 2 decimals)
PROMOTE_WITHIN = 0.15  # a provisional match becomes trusted if its cost is within 15% of the known cost (D-018)


@dataclass
class InvoiceResult:
    invoice: Invoice
    rows: list[OutputRow]
    output_file: Path | None
    price_changes: list[tuple[str, str, float, float]] = field(default_factory=list)  # code, name, old, new

    @property
    def worst(self) -> str | None:
        levels = [f.level for f in self.invoice.flags] + [f.level for r in self.rows for f in r.flags]
        return max(levels, key=SEVERITY.get) if levels else None


@dataclass
class RunResult:
    invoices: list[InvoiceResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # plain-language notes about pages not processed


def run(pdfs: list[Path], output_dir: Path) -> RunResult:
    catalogue = Catalogue.load()
    for item in _load_new_items():
        catalogue.add_local(item)
    table = SupplierItems.load()
    flag_items = _load_flag_items()
    result = RunResult()

    for pdf in pdfs:
        with pymupdf.open(pdf) as doc:
            page_count = doc.page_count
        for page in range(page_count):
            layout = analyze_page(pdf, page, "prebuilt-layout")
            text = layout.get("content", "")
            profile = suppliers.identify(text)
            where = f"{pdf.name} page {page + 1}"
            if profile is None:
                reason = suppliers.skipped_reason(text) or "supplier not recognised or not supported yet"
                result.skipped.append(f"{where}: {reason}")
                continue
            invoice = profile.parse(layout, pdf, page)
            result.invoices.append(_process_invoice(invoice, catalogue, table, flag_items, output_dir))

    table.save()
    return result


def _process_invoice(invoice: Invoice, catalogue: Catalogue, table: SupplierItems,
                     flag_items: dict[str, str], output_dir: Path) -> InvoiceResult:
    number = invoice.number or "unknown"
    _check_total(invoice)
    _check_duplicate(invoice)

    own_new_items = _codes_issued_for(invoice)
    matches = [match_line(line, invoice.supplier, number, catalogue, table, own_new_items)
               for line in invoice.lines]

    rows: dict[str, OutputRow] = {}
    amounts: dict[str, float] = {}
    for line, m in zip(invoice.lines, matches):
        if m.item_code is None:
            m.item_code = _issue_new_item(line, invoice, catalogue).code
            close = ", ".join(f"'{d}' ({s:.0f}%)" for _, d, s in m.candidates) or "none"
            m.flags.append(Flag(RED, "row", f"New item, not in PowerSoft. Code {m.item_code} reserved. "
                                            f"Closest existing items: {close}. Contact Zein."))
            m.pack_factor = 1
        item = catalogue.items[m.item_code]
        flags = line.flags + m.flags
        if not item.storable:
            flags.append(Flag(RED, "item", "This is a non-storable pack item in PowerSoft. "
                                           "Stock should go to the single item instead. Contact Zein."))
        if item.code in flag_items:
            flags.append(Flag(YELLOW, "item", flag_items[item.code]))

        pieces = line.quantity * (m.pack_factor or 1)
        row = rows.setdefault(item.code, OutputRow(item, 0.0, 0.0))
        row.quantity += pieces
        row.flags += [f for f in flags if f not in row.flags]
        row.invoice_lines.append(line.line_no)
        amounts[item.code] = amounts.get(item.code, 0.0) + line.amount_excl_vat

    result = InvoiceResult(invoice, list(rows.values()), None)
    for row in result.rows:
        row.cost = amounts[row.item.code] / row.quantity if row.quantity else 0.0
        _check_cost(row, invoice, table, result)

    total_ok = (invoice.printed_total is not None
                and abs(invoice.printed_total - invoice.computed_total) <= TOTAL_TOLERANCE)
    _learn(invoice, matches, catalogue, table, total_ok)

    name = f"{invoice.short_name} {number}"
    if invoice.date:
        name += f" {invoice.date:%Y-%m-%d}"
    result.output_file = output_dir / f"{name}.xlsx"
    write_invoice_excel(result.output_file, result.rows, catalogue, invoice.supplier)
    _record_processed(invoice, result.output_file)
    _record_price_changes(invoice, result.price_changes)
    return result


def _check_total(invoice: Invoice) -> None:
    """D-010, with the 2026-10-15 amendment: no printed total = maybe a missing page."""
    if invoice.printed_total is None:
        invoice.flags.append(Flag(RED, "row", f"Total not found on the invoice. Were all pages scanned? "
                                              f"(Lines add up to {invoice.computed_total:.2f} incl. VAT.)"))
    elif abs(invoice.printed_total - invoice.computed_total) > TOTAL_TOLERANCE:
        invoice.flags.append(Flag(RED, "row", f"Lines add up to {invoice.computed_total:.2f} but the invoice "
                                              f"total is {invoice.printed_total:.2f}. A line may be misread or missing."))


def _check_cost(row: OutputRow, invoice: Invoice, table: SupplierItems, result: InvoiceResult) -> None:
    """D-009: flag a cost change against this supplier's last cost (or PowerSoft's, if none yet)."""
    if row.item.local:
        return
    reference = table.last_cost(invoice.supplier, row.item.code, invoice.number or "") or row.item.cost
    if not reference or abs(row.cost - reference) <= PRICE_CHANGE_MIN:
        return
    change = (row.cost - reference) / reference * 100
    row.flags.append(Flag(ORANGE, "cost", f"Cost changed: was {reference:.2f}, now {row.cost:.3f} ({change:+.0f}%)."))
    result.price_changes.append((row.item.code, row.item.description, reference, row.cost))
    if abs(change) > PROMOTE_WITHIN * 100 and any(f.column in ("item", "quantity") for f in row.flags):
        row.flags.append(Flag(YELLOW, "quantity", f"Cost per piece is {abs(change):.0f}% away from the known cost. "
                                                  "Check the item and pack size."))


def _learn(invoice: Invoice, matches: list[Match], catalogue: Catalogue, table: SupplierItems,
           total_ok: bool) -> None:
    """D-018: remember barcode -> item and pack size, and this supplier's latest cost.

    A provisional match is promoted to trusted only if the invoice total checks out and the
    implied cost per piece is within 15% of the known cost.
    """
    today = str(date.today())
    for line, m in zip(invoice.lines, matches):
        if not line.barcode or m.item_code is None:
            continue
        flagged = any(f.column in ("item", "quantity") for f in m.flags)
        # A red pack-size guess is not remembered: it must stay red until Zein confirms a factor.
        pack_red = any(f.level == RED and f.column == "quantity" for f in m.flags)
        trusted = m.method == "barcode" or (m.method in ("name", "learned") and not flagged)
        pieces = line.quantity * (m.pack_factor or 1)
        cost = line.amount_excl_vat / pieces if pieces else None
        if not trusted and total_ok and cost:
            reference = table.last_cost(invoice.supplier, m.item_code, invoice.number or "")
            reference = reference or catalogue.items[m.item_code].cost
            trusted = bool(reference) and abs(cost - reference) / reference <= PROMOTE_WITHIN
        table.upsert(SupplierItem(
            supplier=invoice.supplier, key_type="barcode", key=line.barcode,
            supplier_description=line.description, item_code=m.item_code,
            pack_factor=None if pack_red else m.pack_factor,
            status=TRUSTED if trusted else PROVISIONAL, source=m.method, last_cost=cost,
            last_invoice=invoice.number or "", previous_cost=None, last_seen=today,
        ))


# --- New item codes (D-012) ------------------------------------------------------------------

NEW_ITEM_FIELDS = ["code", "supplier", "invoice", "barcode", "description", "vat", "cost", "issued"]


def _load_new_items() -> list[Item]:
    if not NEW_ITEMS.exists():
        return []
    with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
        return [Item(code=r["code"], description=r["description"], barcode=r["barcode"], vat=int(r["vat"]),
                     cost=float(r["cost"]), price=None, supplier=r["supplier"], brand="", category="",
                     storable=True, local=True)
                for r in csv.DictReader(f)]


def _codes_issued_for(invoice: Invoice) -> set[str]:
    if not NEW_ITEMS.exists():
        return set()
    with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
        return {r["code"] for r in csv.DictReader(f)
                if r["supplier"] == invoice.supplier and r["invoice"] == (invoice.number or "")}


def _issue_new_item(line: InvoiceLine, invoice: Invoice, catalogue: Catalogue) -> Item:
    """Reserve the next item code. Re-running the same invoice reuses the code it got before."""
    existing = []
    if NEW_ITEMS.exists():
        with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
            existing = list(csv.DictReader(f))
    for r in existing:
        if r["supplier"] == invoice.supplier and r["invoice"] == (invoice.number or "") and \
                r["description"] == line.description and r["code"] in catalogue.items:
            return catalogue.items[r["code"]]
    code = str(max([catalogue.highest_numeric_code()] + [int(r["code"]) for r in existing]) + 1)
    item = Item(code=code, description=line.description, barcode=line.barcode, vat=line.vat_rate,
                cost=line.amount_excl_vat / line.quantity if line.quantity else 0.0, price=None,
                supplier=invoice.supplier, brand="", category="", storable=True)
    catalogue.add_local(item)
    NEW_ITEMS.parent.mkdir(parents=True, exist_ok=True)
    write_header = not NEW_ITEMS.exists()
    with NEW_ITEMS.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, NEW_ITEM_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow({"code": code, "supplier": invoice.supplier, "invoice": invoice.number or "",
                    "barcode": line.barcode, "description": line.description, "vat": line.vat_rate,
                    "cost": round(item.cost, 4), "issued": str(date.today())})
    return item


# --- Small state files -------------------------------------------------------------------------

def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _check_duplicate(invoice: Invoice) -> None:
    """The same invoice from a *different* scan file = scanned twice (D-018). Re-running the same file is fine."""
    if not PROCESSED.exists() or not invoice.number:
        return
    scan = _file_hash(invoice.source)
    with PROCESSED.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["supplier"] == invoice.supplier and r["invoice"] == invoice.number and r["scan"] != scan:
                invoice.flags.append(Flag(RED, "row", f"This invoice was already processed on {r['processed'][:10]} "
                                                      f"(file {r['file']}). Uploading it again would double the stock."))
                return


def _record_processed(invoice: Invoice, output_file: Path) -> None:
    if not invoice.number:
        return
    scan = _file_hash(invoice.source)
    rows = []
    if PROCESSED.exists():
        with PROCESSED.open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f)
                    if not (r["supplier"] == invoice.supplier and r["invoice"] == invoice.number and r["scan"] == scan)]
    rows.append({"supplier": invoice.supplier, "invoice": invoice.number, "scan": scan,
                 "file": output_file.name, "processed": datetime.now().isoformat(timespec="seconds")})
    _write_csv(PROCESSED, ["supplier", "invoice", "scan", "file", "processed"], rows)


def _record_price_changes(invoice: Invoice, changes) -> None:
    fields = ["date", "supplier", "invoice", "item_code", "description", "old_cost", "new_cost", "change_pct"]
    rows = []
    if PRICE_CHANGES.exists():
        with PRICE_CHANGES.open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f)
                    if not (r["supplier"] == invoice.supplier and r["invoice"] == (invoice.number or ""))]
    for code, description, old, new in changes:
        rows.append({"date": str(invoice.date or date.today()), "supplier": invoice.supplier,
                     "invoice": invoice.number or "", "item_code": code, "description": description,
                     "old_cost": f"{old:.3f}", "new_cost": f"{new:.3f}", "change_pct": f"{(new - old) / old * 100:+.1f}"})
    _write_csv(PRICE_CHANGES, fields, rows)


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)


def _load_flag_items() -> dict[str, str]:
    if not FLAG_ITEMS.exists():
        return {}
    with FLAG_ITEMS.open(encoding="utf-8", newline="") as f:
        return {r["item_code"]: r["reason"] for r in csv.DictReader(f)}
