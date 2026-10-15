"""The review engine (D-022): invoices in, questions out, Excel files once every question is answered.

Each scanned page sits in a queue (data/state/queue.json) with the answers given so far. To decide
what to ask next, a page is *evaluated*: read (cached DI result) -> parse with the supplier profile,
applying staff corrections -> match every line, applying staff answers -> check the total. Every
open flag becomes a question. When none is left, the invoice is *finalized*: new items get codes,
the Excel goes to output/Ready to upload/, and what was learned is saved (D-018).

Evaluation is repeated after every answer. That is cheap (nothing is sent to Azure again) and it
means one answer can settle other questions: e.g. confirming a barcode on one invoice stops the
same question on the next.
"""

import csv
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pymupdf

from . import suppliers
from .catalogue import Catalogue, Item
from .extract import analyze_page
from .matching import Match, match_line, similar_names, suggest_pack, usable_barcode
from .model import (MATCH, NEW, ORANGE, PACK, RED, UNREADABLE, YELLOW, ZEIN, Flag, Invoice, InvoiceLine)
from .output import OutputRow, write_invoice_excel
from .supplier_items import PROVISIONAL, TRUSTED, SupplierItem, SupplierItems

STATE_DIR = Path("data/state")
QUEUE = STATE_DIR / "queue.json"
NEW_ITEMS = STATE_DIR / "new_items.csv"  # codes issued by the tool = local additions (D-012, D-018)
PROCESSED = STATE_DIR / "processed_invoices.csv"  # duplicate-scan guard (D-018)
PRICE_CHANGES = STATE_DIR / "price_changes.csv"  # D-009
FLAG_ITEMS = Path("data/flag_items.csv")  # items that always need a look, e.g. single/pack pairs (D-005)
READY_DIR = Path("output/Ready to upload")
SCANS_DIR = Path("processed")  # scans are moved here from input/ (D-002)

TOTAL_TOLERANCE = 0.05  # euros
PRICE_CHANGE_MIN = 0.01  # euros per piece; smaller differences are rounding (PowerSoft keeps 2 decimals)
PROMOTE_WITHIN = 0.15  # a provisional match becomes trusted if its cost is within 15% of the known cost (D-018)

# Queue statuses. NEW = a whole PDF not yet split into invoices.
NEW, PENDING, ZEIN_LIST, DONE, SKIPPED, MANUAL, RESCAN = ("new", "pending", "needs_zein", "done", "skipped",
                                                          "manual", "rescan")


# --- Queue ------------------------------------------------------------------------------------

@dataclass
class Entry:
    """One invoice (one or more pages of a scan) waiting for review, with the answers given so far."""
    file: str
    pages: list[int]
    added: str
    status: str = PENDING
    answers: dict = field(default_factory=dict)
    note: str = ""  # why it is on Zein's list / to enter by hand / to rescan
    output: str = ""  # the Excel written for it
    label: str = ""  # "Athienitis 1000748334", once known

    @property
    def key(self) -> str:
        return f"{self.file}#{self.pages[0]}"


def load_queue() -> list[Entry]:
    if not QUEUE.exists():
        return []
    return [Entry(**e) for e in json.loads(QUEUE.read_text(encoding="utf-8"))]


def save_queue(entries: list[Entry]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(QUEUE)  # never leave a half-written queue behind


def enqueue(pdfs: list[Path], move: bool) -> list[Entry]:
    """Add these PDFs to the queue (split into invoices later, once read). With `move`, scans leave
    input/ first (D-002)."""
    entries = load_queue()
    known = {e.key for e in entries}
    now = datetime.now().isoformat(timespec="seconds")
    for pdf in pdfs:
        if move:
            target = SCANS_DIR / str(date.today()) / pdf.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():  # same file name scanned again today
                target = target.with_name(f"{target.stem} {datetime.now():%H%M%S}{target.suffix}")
            shutil.move(pdf, target)
            pdf = target
        with pymupdf.open(pdf) as doc:
            pages = doc.page_count
        entry = Entry(str(pdf).replace("\\", "/"), list(range(pages)), now, status=NEW)
        if entry.key not in known:
            entries.append(entry)
            known.add(entry.key)
    save_queue(entries)
    return entries


def split(entries: list[Entry]) -> list[Entry]:
    """Turn each NEW PDF into one entry per invoice (D-004).

    A page joins the invoice before it if the same supplier profile recognises it and the invoice
    numbers don't differ (a continuation page may not print the number). A page no profile
    recognises always stands alone (it becomes "enter by hand").
    """
    out = []
    for entry in entries:
        if entry.status != NEW:
            out.append(entry)
            continue
        groups: list[tuple[object, str | None, list[int]]] = []
        for page in entry.pages:
            layout = analyze_page(Path(entry.file), page, "prebuilt-layout")
            profile = suppliers.identify(layout.get("content", ""))
            number = profile.parse(layout, Path(entry.file), page).number if profile else None
            last = groups[-1] if groups else None
            if (profile and last and last[0] is profile
                    and (number is None or last[1] is None or number == last[1])):
                last[2].append(page)
                groups[-1] = (profile, last[1] or number, last[2])
            else:
                groups.append((profile, number, [page]))
        for _, _, pages in groups:
            out.append(Entry(entry.file, pages, entry.added))
    return out


# --- Questions --------------------------------------------------------------------------------

@dataclass
class Question:
    id: str  # where the answer is stored in Entry.answers
    kind: str  # pack, item, identify, not_storable, new_item, fix_line, number, total, duplicate, zein
    title: str  # the big line on screen
    detail: str = ""  # a smaller line of explanation
    line: InvoiceLine | None = None
    data: dict = field(default_factory=dict)


@dataclass
class Evaluation:
    entry: Entry
    invoice: Invoice | None = None
    outcome: str = "questions"  # questions, ready, skip, manual, zein, rescan
    questions: list[Question] = field(default_factory=list)
    lines: list[tuple[InvoiceLine, Match]] = field(default_factory=list)
    note: str = ""
    labels: dict[str, str] = field(default_factory=dict)  # the supplier's printed column names (fix_line)


@dataclass
class Context:
    catalogue: Catalogue
    table: SupplierItems
    flag_items: dict[str, str]

    @classmethod
    def load(cls) -> "Context":
        catalogue = Catalogue.load()
        for item in _load_new_items():
            catalogue.add_local(item)
        return cls(catalogue, SupplierItems.load(), _load_flag_items())


def evaluate(entry: Entry, ctx: Context) -> Evaluation:
    ev = Evaluation(entry)
    layouts = [analyze_page(Path(entry.file), page, "prebuilt-layout") for page in entry.pages]
    text = layouts[0].get("content", "")
    profile = suppliers.identify(text)
    if profile is None:
        ev.outcome = MANUAL
        ev.note = suppliers.skipped_reason(text) or "Supplier not supported yet: please enter this one by hand."
        return ev

    a = entry.answers
    pages = []
    for page, layout in zip(entry.pages, layouts):
        corrections = {k.split(":")[2]: v for k, v in a.items() if k.startswith(f"fix:{page}:")}
        pages.append(profile.parse(layout, Path(entry.file), page, corrections))
    inv = suppliers.base.combine(pages)
    ev.invoice = inv
    ev.labels = profile.EDITABLE
    if a.get("number"):
        inv.number = a["number"]
    entry.label = f"{inv.short_name} {inv.number or ''}".strip()

    for flag in inv.flags:
        if flag.kind == ZEIN:
            return _zein(ev, flag.message)

    # Invoice number first: the duplicate check needs it.
    if not inv.number:
        ev.questions.append(Question("number", "number", "Type the invoice number",
                                     "It is printed at the top of the invoice."))
        return ev
    previous = _previous_processing(inv)
    if previous and a.get("duplicate") != "again":
        if a.get("duplicate") == "skip":
            ev.outcome = SKIPPED
            ev.note = f"Already done on {previous['processed'][:10]}; skipped."
            return ev
        ev.questions.append(Question(
            "duplicate", "duplicate", "This invoice was already done",
            f"Done on {previous['processed'][:10]} ({previous['file']}). Do NOT upload it twice. "
            "Only make the Excel again if it was lost and never uploaded."))
        return ev

    for line in inv.lines:
        q = _line(line, inv, ev, ctx)
        if ev.outcome == "zein":
            return ev  # one line staff can't answer: the whole invoice goes to Zein
        if q:
            ev.questions.append(q)

    if not ev.questions:
        _check_total(ev)
    if ev.outcome == "questions" and not ev.questions:
        ev.outcome = "ready"
    return ev


def _zein(ev: Evaluation, note: str) -> Evaluation:
    ev.outcome = "zein"
    ev.note = note
    ev.questions = [Question("zein", "zein", "This invoice needs Zein", note)]
    return ev


def _line(line: InvoiceLine, inv: Invoice, ev: Evaluation, ctx: Context) -> Question | None:
    """Work out one line, applying answers. Returns the next question about it, if any."""
    a = ev.entry.answers
    row = line.key
    for flag in line.flags:
        if flag.kind == ZEIN:
            _zein(ev, f"Line {line.line_no}: {flag.message}")
            return None
    if any(f.kind == UNREADABLE for f in line.flags):
        return Question(f"fix:{row}", "fix_line", "Type the numbers as printed on the paper",
                        next(f.message for f in line.flags if f.kind == UNREADABLE), line, {"labels": ev.labels})

    item_answer = a.get(f"item:{row}")
    if isinstance(item_answer, dict) and "code" in item_answer:
        m = Match(item_answer["code"], None, "staff")
        suggest_pack(m, line, inv.supplier, inv.number, ctx.catalogue, ctx.table)
    elif isinstance(item_answer, dict) and "new" in item_answer:
        m = Match(None, float(item_answer["new"].get("pieces") or 1), "new_item")
    else:
        m = match_line(line, inv.supplier, inv.number, ctx.catalogue, ctx.table)
        if item_answer == "yes":
            m.flags = [f for f in m.flags if f.kind != MATCH]
            m.method += "+staff"
    ev.lines.append((line, m))

    if m.method == "new_item":
        return None
    if m.item_code is None:
        return Question(f"item:{row}", "identify", "This item was not found",
                        "Scan or type the barcode of ONE piece, or search for it by name.", line,
                        {"candidates": m.candidates})
    item = ctx.catalogue.items[m.item_code]
    if not item.storable and not isinstance(item_answer, dict):
        return Question(f"item:{row}", "not_storable", "Which single item is this?",
                        f"'{item.description}' is a pack that holds no stock. Scan or type the barcode of "
                        "ONE piece, or search for it.", line, {"candidates": m.candidates})
    if any(f.kind == MATCH for f in m.flags) or (item.code in ctx.flag_items and item_answer is None):
        reason = ctx.flag_items.get(item.code) or next((f.message for f in m.flags if f.kind == MATCH), "")
        return Question(f"item:{row}", "item", "Is it this item?", reason, line,
                        {"code": item.code, "description": item.description, "candidates": m.candidates})

    pack_answer = a.get(f"pack:{row}")
    if pack_answer is not None:
        m.pack_factor = float(pack_answer)
        m.flags = [f for f in m.flags if f.kind != PACK]
        m.method += "+pack"
    else:
        pack = next((f for f in m.flags if f.kind == PACK), None)
        if pack:
            return Question(f"pack:{row}", "pack", "How many pieces in 1 unit?", pack.message, line,
                            {"suggested": pack.data.get("suggested"), "description": item.description})
    return None


def _check_total(ev: Evaluation) -> None:
    """D-010 and its amendments: the lines must add up to the total on the paper."""
    inv = ev.invoice
    typed = ev.entry.answers.get("total")
    total = typed if typed is not None else inv.printed_total
    if total is not None and abs(total - inv.computed_total) <= TOTAL_TOLERANCE:
        return
    if typed is None:
        ev.questions.append(Question(
            "total", "total", "Type the total to pay, from the paper",
            "The total with VAT, at the bottom of the LAST page." if inv.printed_total is None else
            f"The tool read {inv.printed_total:.2f}, but the lines add up to {inv.computed_total:.2f}.",
            data={"computed": inv.computed_total}))
        return
    ev.outcome = RESCAN
    ev.note = (f"The lines add up to {inv.computed_total:.2f} but the paper says {typed:.2f}. A page may be "
               "missing: scan ALL pages of this invoice into one PDF and run again.")


# --- Finalize ---------------------------------------------------------------------------------

@dataclass
class Result:
    invoice: Invoice
    rows: list[OutputRow]
    output_file: Path
    price_changes: list[tuple[str, str, float, float]] = field(default_factory=list)
    confirmed: list[str] = field(default_factory=list)  # what staff answered, for Zein's report


def finalize(ev: Evaluation, ctx: Context) -> Result:
    inv = ev.invoice
    a = ev.entry.answers
    result_rows: dict[str, OutputRow] = {}
    amounts: dict[str, float] = {}
    confirmed = []
    for line, m in ev.lines:
        row_key = line.key
        if m.method == "new_item":
            form = a[f"item:{row_key}"]["new"]
            m.item_code = _issue_new_item(line, inv, form, m.pack_factor, ctx.catalogue).code
            confirmed.append(f"New item {m.item_code} '{form['description']}' (from '{line.description}'), "
                             f"retail {float(form['price']):.2f}, barcode {form['barcode']}")
        elif "staff" in m.method or "+pack" in m.method:
            confirmed.append(f"Line {line.line_no} '{line.description}' -> {m.item_code} "
                             f"'{ctx.catalogue.items[m.item_code].description}', {m.pack_factor:g} per unit")
        item = ctx.catalogue.items[m.item_code]
        pieces = line.quantity * (m.pack_factor or 1)
        row = result_rows.setdefault(item.code, OutputRow(item, 0.0, 0.0))
        row.quantity += pieces
        row.invoice_lines.append(line.line_no)
        amounts[item.code] = amounts.get(item.code, 0.0) + line.amount_excl_vat

    rows = list(result_rows.values())
    changes = []
    for row in rows:
        row.cost = amounts[row.item.code] / row.quantity if row.quantity else 0.0
        _check_cost(row, inv, ctx.table, changes)

    _learn(ev, ctx)
    name = f"{inv.short_name} {inv.number}" + (f" {inv.date:%Y-%m-%d}" if inv.date else "")
    output_file = READY_DIR / f"{name}.xlsx"
    write_invoice_excel(output_file, rows, ctx.catalogue, inv.supplier)
    ctx.table.save()
    _record_processed(inv, output_file)
    _record_price_changes(inv, changes)
    ev.entry.status = DONE
    ev.entry.output = output_file.name
    return Result(inv, rows, output_file, changes, confirmed)


def _check_cost(row: OutputRow, inv: Invoice, table: SupplierItems, changes: list) -> None:
    """D-009: flag a cost change against this supplier's last cost (or PowerSoft's, if none yet)."""
    if row.item.local:
        return
    reference = table.last_cost(inv.supplier, row.item.code, inv.number or "") or row.item.cost
    if not reference or abs(row.cost - reference) <= PRICE_CHANGE_MIN:
        return
    change = (row.cost - reference) / reference * 100
    row.flags.append(Flag(ORANGE, "cost", f"Cost changed: was {reference:.2f}, now {row.cost:.3f} ({change:+.0f}%)."))
    changes.append((row.item.code, row.item.description, reference, row.cost))


def _learn(ev: Evaluation, ctx: Context) -> None:
    """D-018: remember barcode -> item and pack size, and this supplier's latest cost.

    Staff answers count as confirmations (D-022). Other guesses are promoted to trusted only if the
    invoice total checks out and the cost per piece is within 15% of the known cost.
    """
    inv = ev.invoice
    total_ok = True  # finalize is only reached once the total has been checked
    today = str(date.today())
    for line, m in ev.lines:
        barcode = usable_barcode(line)
        keys = [("barcode", barcode)] if barcode else []
        keys += [("code", line.supplier_code)] if line.supplier_code else []
        if not keys or m.item_code is None:
            continue
        pieces = line.quantity * (m.pack_factor or 1)
        cost = line.amount_excl_vat / pieces if pieces else None
        trusted = m.method in ("barcode", "name", "learned", "staff", "new_item") or "staff" in m.method \
            or "+pack" in m.method
        if not trusted and total_ok and cost:
            reference = ctx.table.last_cost(inv.supplier, m.item_code, inv.number) or ctx.catalogue.items[m.item_code].cost
            trusted = bool(reference) and abs(cost - reference) / reference <= PROMOTE_WITHIN
        for key_type, key in keys:
            row = ctx.table.upsert(SupplierItem(
                supplier=inv.supplier, key_type=key_type, key=key,
                supplier_description=line.description, item_code=m.item_code, pack_factor=m.pack_factor,
                status=TRUSTED if trusted else PROVISIONAL, source=m.method, last_cost=cost,
                last_invoice=inv.number, previous_cost=None, last_seen=today,
            ))
            if "staff" in m.method or "+pack" in m.method or m.method == "new_item":
                # An explicit answer overrides whatever was stored before.
                row.item_code, row.pack_factor, row.status, row.source = m.item_code, m.pack_factor, TRUSTED, m.method


# --- New item codes (D-012) ---------------------------------------------------------------------

NEW_ITEM_FIELDS = ["code", "supplier", "invoice", "barcode", "description", "vat", "cost", "price", "category", "issued"]


def _load_new_items() -> list[Item]:
    if not NEW_ITEMS.exists():
        return []
    with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
        return [Item(code=r["code"], description=r["description"], barcode=r["barcode"], vat=int(r["vat"]),
                     cost=float(r["cost"]), price=float(r["price"]) if r.get("price") else None,
                     supplier=r["supplier"], brand="", category=r.get("category", ""), storable=True, local=True)
                for r in csv.DictReader(f)]


def _issue_new_item(line: InvoiceLine, inv: Invoice, form: dict, pieces_per_unit: float, catalogue: Catalogue) -> Item:
    """Give a staff-approved new item the next code (D-012) and add it to the local additions (D-018)."""
    existing = []
    if NEW_ITEMS.exists():
        with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
            existing = list(csv.DictReader(f))
    code = str(max([catalogue.highest_numeric_code()] + [int(r["code"]) for r in existing]) + 1)
    pieces = line.quantity * pieces_per_unit
    item = Item(code=code, description=form["description"], barcode=form["barcode"], vat=line.vat_rate,
                cost=line.amount_excl_vat / pieces if pieces else 0.0, price=float(form["price"]),
                supplier=inv.supplier, brand="", category=form.get("category", ""), storable=True)
    catalogue.add_local(item)
    write_header = not NEW_ITEMS.exists()
    NEW_ITEMS.parent.mkdir(parents=True, exist_ok=True)
    with NEW_ITEMS.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, NEW_ITEM_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow({"code": code, "supplier": inv.supplier, "invoice": inv.number, "barcode": item.barcode,
                    "description": item.description, "vat": item.vat, "cost": round(item.cost, 4),
                    "price": item.price, "category": item.category, "issued": str(date.today())})
    return item


def suggested_category(candidates, catalogue: Catalogue) -> str:
    """The category of the most similar existing item (D-012; an LLM suggestion may come later)."""
    for code, _, _ in candidates or []:
        if catalogue.items[code].category:
            return catalogue.items[code].category
    return ""


def search_items(text: str, ctx: Context, supplier: str | None) -> list[tuple[str, str, float]]:
    return similar_names(text, supplier, ctx.catalogue, ctx.table, limit=8)


# --- Small state files -------------------------------------------------------------------------

def _previous_processing(inv: Invoice) -> dict | None:
    if not PROCESSED.exists():
        return None
    with PROCESSED.open(encoding="utf-8", newline="") as f:
        return next((r for r in csv.DictReader(f) if r["supplier"] == inv.supplier and r["invoice"] == inv.number), None)


def _record_processed(inv: Invoice, output_file: Path) -> None:
    rows = []
    if PROCESSED.exists():
        with PROCESSED.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    rows.append({"supplier": inv.supplier, "invoice": inv.number, "scan": _file_hash(inv.source),
                 "file": output_file.name, "processed": datetime.now().isoformat(timespec="seconds")})
    _write_csv(PROCESSED, ["supplier", "invoice", "scan", "file", "processed"], rows)


def _record_price_changes(inv: Invoice, changes) -> None:
    fields = ["date", "supplier", "invoice", "item_code", "description", "old_cost", "new_cost", "change_pct"]
    rows = []
    if PRICE_CHANGES.exists():
        with PRICE_CHANGES.open(encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f) if not (r["supplier"] == inv.supplier and r["invoice"] == inv.number)]
    for code, description, old, new in changes:
        rows.append({"date": str(inv.date or date.today()), "supplier": inv.supplier, "invoice": inv.number,
                     "item_code": code, "description": description, "old_cost": f"{old:.3f}",
                     "new_cost": f"{new:.3f}", "change_pct": f"{(new - old) / old * 100:+.1f}"})
    _write_csv(PRICE_CHANGES, fields, rows)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


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
