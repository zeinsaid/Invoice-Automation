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
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

import pymupdf

from . import suppliers
from .catalogue import Catalogue, Item, name_key
from .extract import analyze_page
from .matching import Match, match_line, similar_names, suggest_pack, usable_barcode
from .model import MATCH, ORANGE, PACK, RED, UNREADABLE, ZEIN, Flag, Invoice, InvoiceLine
from .files import save_atomic
from .output import OutputRow, write_invoice_excel
from .supplier_items import PROVISIONAL, TABLE_PATH, TRUSTED, SupplierItem, SupplierItems

STATE_DIR = Path("data/state")
QUEUE = STATE_DIR / "queue.json"
NEW_ITEMS = STATE_DIR / "new_items.csv"  # codes issued by the tool = local additions (D-012, D-018)
PROCESSED = STATE_DIR / "processed_invoices.csv"  # duplicate-scan guard (D-018)
PRICE_CHANGES = STATE_DIR / "price_changes.csv"  # D-009
FLAG_ITEMS = Path("data/flag_items.csv")  # items that always need a look, e.g. single/pack pairs (D-005)
# Only files not yet uploaded to PowerSoft. On the shop PC, env.bat points this at "2. Excel files ready
# to upload", the folder staff see; everything else stays in 'Admin only' (D-024).
READY_DIR = Path(os.environ.get("INVOICE_READY", "output/Ready to upload"))
UPLOADED_DIR = Path("output/Uploaded")  # files staff marked as uploaded, by date
TO_UPLOAD = STATE_DIR / "to_upload.json"  # file -> its upload steps, until it is marked as uploaded
SCANS_DIR = Path("processed")  # scans are moved here from input/ (D-002)

TOTAL_TOLERANCE = 0.05  # euros
PRICE_CHANGE_MIN = 0.01  # euros per piece; smaller differences are rounding (PowerSoft keeps 2 decimals)
# D-008: it isn't known yet whether PowerSoft's Purchase order upload updates an item's stored cost. Until
# Zein has checked, a file with cost changes also goes through Items import (with Modify ticked).
COSTS_NEED_ITEMS_IMPORT = True
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
    text = json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=1)
    save_atomic(QUEUE, lambda tmp: tmp.write_text(text, encoding="utf-8"))  # never a half-written queue


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
    answer_keys: dict[str, str] = field(default_factory=dict)  # line key -> key its item/pack answers live under
    skipped: list[InvoiceLine] = field(default_factory=list)  # not for the shop (D-025)


@dataclass
class Context:
    catalogue: Catalogue
    table: SupplierItems
    flag_items: dict[str, str]

    @classmethod
    def load(cls) -> "Context":
        # Without the learned table the tool would quietly start again from the old supplier lists.
        # Once invoices have been processed, a missing table is an accident: stop, and restore it (D-023).
        if not TABLE_PATH.exists() and PROCESSED.exists():
            raise FileNotFoundError(f"{TABLE_PATH} is missing, but invoices were processed before. Restore it "
                                    "from the newest zip in data/backups. It is never re-created on its own.")
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

    ev.answer_keys = _answer_keys(inv.lines)
    for line in inv.lines:
        q = _line(line, inv, ev, ctx)
        if ev.outcome == "zein":
            return ev  # one line staff can't answer: the whole invoice goes to Zein
        if q and q.id not in {x.id for x in ev.questions}:
            ev.questions.append(q)

    if not ev.questions:
        _check_total(ev)
    if ev.outcome == "questions" and not ev.questions:
        ev.outcome = "ready"
    return ev


def _answer_keys(lines: list[InvoiceLine]) -> dict[str, str]:
    """Lines with the same barcode (or, without one, the same supplier code) are the same product in
    the same unit: Athenites prints a second line when an item is scanned again. They share one answer,
    so staff are asked once and a new product gets one code, not two."""
    first: dict[str, str] = {}
    keys = {}
    for line in lines:
        product = usable_barcode(line) or (f"code:{line.supplier_code}" if line.supplier_code else "")
        keys[line.key] = first.setdefault(product, line.key) if product else line.key
    return keys


def skip_id(ev: Evaluation, line: InvoiceLine) -> str:
    """Where "Not for the shop" is stored (D-025). By product, like item answers: a second line of the
    same product is left out with it."""
    return f"skip:{ev.answer_keys.get(line.key, line.key)}"


def _zein(ev: Evaluation, note: str) -> Evaluation:
    ev.outcome = "zein"
    ev.note = note
    ev.questions = [Question("zein", "zein", "This invoice needs Zein", note)]
    return ev


def _line(line: InvoiceLine, inv: Invoice, ev: Evaluation, ctx: Context) -> Question | None:
    """Work out one line, applying answers. Returns the next question about it, if any."""
    a = ev.entry.answers
    row = ev.answer_keys.get(line.key, line.key)  # item and pack answers; fix answers stay per line
    if a.get(skip_id(ev, line)):
        ev.skipped.append(line)  # D-025: not in the Excel and not learned, but still in the total
        return None
    for flag in line.flags:
        if flag.kind == ZEIN:
            _zein(ev, f"Line {line.line_no}: {flag.message}")
            return None
    if any(f.kind == UNREADABLE for f in line.flags):
        return Question(f"fix:{line.key}", "fix_line", "Type the numbers as printed on the paper",
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
    if not item.storable:  # never output: PowerSoft keeps no stock for it (D-005)
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
    skipped: list[str] = field(default_factory=list)  # lines left out as not for the shop (D-025)

    @property
    def new_items(self) -> int:
        return sum(1 for row in self.rows if any(f.column == "new" for f in row.flags))

    @property
    def items_import(self) -> str:
        """Why this file must also go through PowerSoft's Items import (before the Purchase order), or ""."""
        reasons = []
        if self.new_items:
            reasons.append(f"{self.new_items} new item{'s' if self.new_items > 1 else ''}")
        if COSTS_NEED_ITEMS_IMPORT and self.price_changes:
            n = len(self.price_changes)
            reasons.append(f"{n} cost change{'s' if n > 1 else ''}")
        return ", ".join(reasons)


def finalize(ev: Evaluation, ctx: Context) -> Result:
    inv = ev.invoice
    a = ev.entry.answers
    name = f"{inv.short_name} {inv.number}" + (f" {inv.date:%Y-%m-%d}" if inv.date else "")
    output_file = READY_DIR / f"{name}.xlsx"
    # All or nothing: if a file is open in Excel, stop before any code is issued or anything is written.
    _check_writable([output_file, ctx.table.path, NEW_ITEMS, PROCESSED, PRICE_CHANGES])
    result_rows: dict[str, OutputRow] = {}
    amounts: dict[str, float] = {}
    confirmed = []
    issued: dict[str, str] = {}  # answer key -> code, so lines sharing a new-item answer share the code
    new_lines: dict[str, list[InvoiceLine]] = {}
    for line, m in ev.lines:
        if m.method == "new_item":
            new_lines.setdefault(ev.answer_keys.get(line.key, line.key), []).append(line)
    for line, m in ev.lines:
        row_key = ev.answer_keys.get(line.key, line.key)
        if m.method == "new_item":
            if row_key not in issued:
                form = a[f"item:{row_key}"]["new"]
                issued[row_key] = _issue_new_item(new_lines[row_key], inv, form, m.pack_factor, ctx.catalogue).code
                confirmed.append(f"New item {issued[row_key]} '{form['description']}' (from '{line.description}'), "
                                 f"retail {float(form['price']):.2f}, barcode {form['barcode']}")
            m.item_code = issued[row_key]
        elif "staff" in m.method or "+pack" in m.method:
            # A linked pack (D-005 amendment) went in without a question, unless staff answered its size.
            asked = "staff" in m.method or "+pack" in m.method.replace("+pack_link", "")
            confirmed.append(("" if asked else "pack: ") + f"Line {line.line_no} '{line.description}' -> {m.item_code} "
                             f"'{ctx.catalogue.items[m.item_code].description}', {m.pack_factor:g} per unit"
                             + ("" if asked else " (linked pack in PowerSoft, not asked)"))
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
        if row.item.code in issued.values():  # D-011: a new item is always red, so it gets a look before upload
            row.flags.append(Flag(RED, "new", "NEW item: check the name, barcode, price, category and brand "
                                              "before uploading."))
            if not ctx.catalogue.supplier_codes.get(inv.supplier):
                row.flags.append(Flag(RED, "supplier", f"'{inv.supplier}' has no supplier code in "
                                                       "data/powersoft/suppliers.xlsx. Add it, then fix this cell."))

    _learn(ev, ctx)
    write_invoice_excel(output_file, rows, ctx.catalogue, inv.supplier)
    ctx.table.save()
    _record_processed(inv, output_file)
    _record_price_changes(inv, changes)
    ev.entry.status = DONE
    ev.entry.output = output_file.name
    skipped = [f"Line {line.line_no} '{line.description}', {line.amount_excl_vat * (1 + line.vat_rate / 100):.2f} "
               "incl. VAT" for line in ev.skipped]
    result = Result(inv, rows, output_file, changes, confirmed, skipped)
    waiting = _load_to_upload()
    waiting[output_file.name] = {"items_import": result.items_import, "made": str(date.today())}
    _save_to_upload(waiting)
    return result


# --- Uploads: what is waiting in 'Ready to upload', and marking it as uploaded -------------------------

def _load_to_upload() -> dict[str, dict]:
    return json.loads(TO_UPLOAD.read_text(encoding="utf-8")) if TO_UPLOAD.exists() else {}


def _save_to_upload(waiting: dict[str, dict]) -> None:
    text = json.dumps(waiting, ensure_ascii=False, indent=1)
    save_atomic(TO_UPLOAD, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def waiting_uploads() -> list[dict]:
    """Every file in 'Ready to upload', oldest first, with its upload steps: {file, items_import, made}.
    A file the tool has no record of (put there by hand) gets made = "" and no Items import step."""
    waiting = _load_to_upload()
    files = sorted((f for f in READY_DIR.glob("*.xlsx") if not f.name.startswith("~$")),
                   key=lambda f: (waiting.get(f.name, {}).get("made", ""), f.name)) if READY_DIR.exists() else []
    return [{"file": f.name, "items_import": waiting.get(f.name, {}).get("items_import", ""),
             "made": waiting.get(f.name, {}).get("made", "")} for f in files]


def mark_uploaded(names: list[str]) -> None:
    """Staff uploaded these to PowerSoft: move them out of 'Ready to upload', so they can't go in twice."""
    target = UPLOADED_DIR / str(date.today())
    target.mkdir(parents=True, exist_ok=True)
    waiting = _load_to_upload()
    for name in names:
        source = READY_DIR / name
        if source.exists():
            dest = target / name
            if dest.exists():
                dest = target / f"{source.stem} {datetime.now():%H%M%S}{source.suffix}"
            try:
                shutil.move(source, dest)
            except PermissionError:
                raise PermissionError(f"{name} is open in Excel. Close it and press the button again.") from None
        waiting.pop(name, None)
    _save_to_upload(waiting)


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

NEW_ITEM_FIELDS = ["code", "supplier", "invoice", "barcode", "description", "vat", "cost", "price", "category", "brand",
                   "issued"]


def _load_new_items() -> list[Item]:
    if not NEW_ITEMS.exists():
        return []
    with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
        return [Item(code=r["code"], description=r["description"], barcode=r["barcode"], vat=int(r["vat"]),
                     cost=float(r["cost"]), price=float(r["price"]) if r.get("price") else None,
                     supplier=r["supplier"], brand=r.get("brand", ""), category=r.get("category", ""), storable=True,
                     local=True)
                for r in csv.DictReader(f)]


def _issue_new_item(lines: list[InvoiceLine], inv: Invoice, form: dict, pieces_per_unit: float,
                    catalogue: Catalogue) -> Item:
    """Give a staff-approved new item the next code (D-012) and add it to the local additions (D-018).
    `lines` are all the invoice lines of this product; the cost is averaged over them."""
    existing = []
    if NEW_ITEMS.exists():
        with NEW_ITEMS.open(encoding="utf-8", newline="") as f:
            existing = list(csv.DictReader(f))
    code = str(max([catalogue.highest_numeric_code()] + [int(r["code"]) for r in existing]) + 1)
    pieces = sum(line.quantity for line in lines) * pieces_per_unit
    amount = sum(line.amount_excl_vat for line in lines)
    item = Item(code=code, description=form["description"], barcode=form["barcode"], vat=lines[0].vat_rate,
                cost=amount / pieces if pieces else 0.0, price=float(form["price"]),
                supplier=inv.supplier, brand=form.get("brand") or suggested_brand(form["description"], catalogue),
                category=form.get("category", ""), storable=True)
    catalogue.add_local(item)
    # The whole file is rewritten (crash-safe), so a file from before a column was added stays readable.
    _write_csv(NEW_ITEMS, NEW_ITEM_FIELDS, existing + [{
        "code": code, "supplier": inv.supplier, "invoice": inv.number, "barcode": item.barcode,
        "description": item.description, "vat": item.vat, "cost": round(item.cost, 4), "price": item.price,
        "category": item.category, "brand": item.brand, "issued": str(date.today())}])
    return item


def suggested_category(candidates, catalogue: Catalogue) -> str:
    """The category of the most similar existing item (D-012; no LLM, D-006 amendment)."""
    for code, _, _ in candidates or []:
        if catalogue.items[code].category:
            return catalogue.items[code].category
    return ""


def suggested_brand(name: str, catalogue: Catalogue) -> str:
    """A new item's brand, filled in by the tool (staff aren't asked: nothing in the shop uses it).
    A brand we already use that the name starts with ('KINDER BUENO WHITE T3' -> KINDER; the longest
    wins, so 7UP ZERO before 7UP), otherwise the name's first word ('TOBLERONE MILK 100G' -> TOBLERONE)."""
    key = name_key(name)
    hits = [b for b in catalogue.brands if key == name_key(b) or key.startswith(name_key(b) + " ")]
    return max(hits, key=len, default="") or (name.split() or [""])[0].upper()


def search_items(text: str, ctx: Context, supplier: str | None) -> list[tuple[str, str, float]]:
    """The search box in the review window. Items that hold no stock can't be chosen (D-005)."""
    hits = similar_names(text, supplier, ctx.catalogue, ctx.table, limit=16)
    return [h for h in hits if ctx.catalogue.items[h[0]].storable][:8]


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


def _check_writable(paths: list[Path]) -> None:
    """Excel locks the files it has open. Opening each one for appending finds that out without
    changing anything."""
    for path in paths:
        if path.exists():
            try:
                with path.open("a"):
                    pass
            except PermissionError:
                raise PermissionError(f"{path.name} is open in Excel. Close it and run again.") from None


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    def write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fields, restval="")
            w.writeheader()
            w.writerows(rows)
    save_atomic(path, write)


def _load_flag_items() -> dict[str, str]:
    if not FLAG_ITEMS.exists():
        return {}
    with FLAG_ITEMS.open(encoding="utf-8", newline="") as f:
        return {r["item_code"]: r["reason"] for r in csv.DictReader(f)}
