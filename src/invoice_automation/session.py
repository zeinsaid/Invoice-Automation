"""One run of the tool: add scans to the queue, hand out questions one at a time, record answers.

The review window (ui.py) is a thin layer over this, so the same logic can be driven from tests.
"""

import csv
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .files import save_atomic
from .model import InvoiceLine
from .suppliers import PROFILES, example
from .pipeline import (DONE, MANUAL, NEW, PENDING, RESCAN, SKIPPED, STATE_DIR, ZEIN_LIST, Context, Entry, Evaluation,
                       Question, Result, enqueue, evaluate, finalize, load_queue, save_queue, skip_id, split)

REPORTS_DIR = Path("data/reports")
LAST_EXPORT = STATE_DIR / "last_export.txt"  # the export the last report described (D-023)
TIMINGS = STATE_DIR / "timings.csv"  # time staff spent per invoice, for real before/after numbers
EXPORT_MAX_AGE = 45  # days; after that the report asks Zein for a fresh PowerSoft export
NOT_SURE = "Staff were not sure: "  # how an invoice staff sent to Zein is noted


@dataclass
class Event:
    entry: Entry
    status: str
    note: str = ""
    result: Result | None = None
    seconds: int | None = None  # from its first question to done, in this run


@dataclass
class Session:
    zein: bool = False  # Zein's mode: also works through Zein's list, and has extra options
    ctx: Context = field(default_factory=Context.load)
    entries: list[Entry] = field(default_factory=load_queue)
    events: list[Event] = field(default_factory=list)
    started: dict[str, float] = field(default_factory=dict)  # invoice -> when its first question was shown

    def __post_init__(self) -> None:
        self._return_fixed()

    def _return_fixed(self) -> None:
        """An invoice an automatic check sent to Zein goes back to staff once an update has fixed the
        cause (Pambos' unreadable VAT, October 2026). One staff sent with "I'm not sure" stays with Zein."""
        changed = False
        for entry in self.entries:
            if entry.status != ZEIN_LIST or entry.note.startswith(NOT_SURE):
                continue
            try:
                outcome = evaluate(entry, self.ctx).outcome
            except Exception:  # noqa: BLE001 - e.g. the scan was moved away: it simply stays on Zein's list
                continue
            if outcome != "zein":
                entry.status, entry.note, changed = PENDING, "", True
        if changed:
            save_queue(self.entries)

    def add(self, pdfs: list[Path], move: bool = True) -> None:
        self.entries = enqueue(pdfs, move)

    def next_question(self) -> tuple[Entry, Evaluation, Question] | None:
        """Finish everything that needs no question; return the next question, or None when done."""
        if any(e.status == NEW for e in self.entries):
            self.entries = split(self.entries)
            save_queue(self.entries)
        # Zein's mode is for Zein's list: those come first, so a long staff invoice doesn't stand in front.
        order = sorted(self.entries, key=lambda e: e.status != ZEIN_LIST) if self.zein else self.entries
        for entry in order:
            if entry.status != PENDING and not (self.zein and entry.status == ZEIN_LIST):
                continue
            ev = evaluate(entry, self.ctx)
            if ev.outcome == "ready":
                result = finalize(ev, self.ctx)
                self._event(entry, DONE, result=result)
                self._time(entry, result)
            elif ev.outcome in (MANUAL, SKIPPED, RESCAN):
                self._event(entry, ev.outcome, ev.note)
            elif ev.outcome == "zein" and not self.zein:
                self._event(entry, ZEIN_LIST, ev.note)
            else:
                self.started.setdefault(entry.key, time.monotonic())
                return entry, ev, ev.questions[0]
        return None

    def answer(self, entry: Entry, question: Question, value) -> None:
        entry.answers[question.id] = value
        if entry.status == ZEIN_LIST:
            entry.status = PENDING  # Zein answered: back to the normal flow
        save_queue(self.entries)

    def undo(self, entry: Entry) -> None:
        """Take back the last answer on this invoice (a mis-click). Its question comes back."""
        if entry.answers:
            entry.answers.pop(next(reversed(entry.answers)))
            save_queue(self.entries)

    def not_sure(self, entry: Entry, question: Question) -> None:
        note = f"{NOT_SURE}{question.title}" + (f" ({question.detail})" if question.detail else "")
        self._event(entry, ZEIN_LIST, note)

    def not_for_shop(self, entry: Entry, ev: Evaluation, line: InvoiceLine) -> None:
        """D-025: bought on the shop's invoice for home or the restaurant: left out of the Excel."""
        self.answer(entry, Question(skip_id(ev, line), "skip", "Not for the shop"), True)

    def drop(self, entry: Entry) -> None:
        """Zein only: take an invoice out of the tool; it is entered by hand."""
        self._event(entry, MANUAL, "Taken out by Zein: enter this one by hand.")

    def restart(self, entry: Entry) -> None:
        """Zein only: forget all answers for an invoice and ask again."""
        entry.answers, entry.status, entry.note = {}, PENDING, ""
        save_queue(self.entries)

    def _event(self, entry: Entry, status: str, note: str = "", result: Result | None = None) -> None:
        entry.status, entry.note = status, note
        save_queue(self.entries)
        self.events = [e for e in self.events if e.entry is not entry] + [Event(entry, status, note, result)]

    def _time(self, entry: Entry, result: Result) -> None:
        """Log how long staff spent on the invoice, so the time saved can be measured, not guessed.
        An invoice finished over two runs only counts the last one."""
        start = self.started.pop(entry.key, None)
        seconds = round(time.monotonic() - start) if start else 0
        self.events[-1].seconds = seconds
        row = {"date": str(date.today()), "invoice": entry.label, "lines": len(result.invoice.lines),
               "questions": len(entry.answers), "seconds": seconds}
        new = not TIMINGS.exists()
        TIMINGS.parent.mkdir(parents=True, exist_ok=True)
        with TIMINGS.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, list(row))
            if new:
                w.writeheader()
            w.writerow(row)

    # --- What happened -------------------------------------------------------------------------

    def summary(self) -> dict[str, list[Event]]:
        groups: dict[str, list[Event]] = {DONE: [], RESCAN: [], MANUAL: [], ZEIN_LIST: [], SKIPPED: []}
        for e in self.events:
            groups.setdefault(e.status, []).append(e)
        # Invoices that were already on Zein's list before this run still count.
        listed = {e.entry.key for e in groups[ZEIN_LIST]}
        groups[ZEIN_LIST] += [Event(x, ZEIN_LIST, x.note) for x in self.entries
                              if x.status == ZEIN_LIST and x.key not in listed]
        return groups

    def write_report(self) -> Path | None:
        """Zein's report: everything that happened, price changes and what staff confirmed (D-011, D-022)."""
        notes = self._export_notes()
        if not self.events and not notes:
            return None
        g = self.summary()
        out = [f"Invoice run {datetime.now():%Y-%m-%d %H:%M}" + (" (Zein)" if self.zein else ""), ""]
        out += notes
        for e in g[DONE]:
            r = e.result
            timing = f", {len(e.entry.answers)} questions in {e.seconds / 60:.1f} min" if e.seconds else ""
            out.append(f"READY  {r.output_file.name}  ({len(r.invoice.lines)} lines -> {len(r.rows)} items, "
                       f"total {r.invoice.computed_total:.2f}{timing})")
            out.append(f"   upload: Items import first ({r.items_import}), then Purchase order" if r.items_import
                       else "   upload: Purchase order only")
            out += [f"   {c}" if c.startswith("pack: ") else f"   staff: {c}" for c in r.confirmed]
            out += [f"   not for the shop: {s}" for s in r.skipped]
            out += [f"   price: {code} {name}: {old:.2f} -> {new:.3f} ({(new - old) / old * 100:+.0f}%)"
                    for code, name, old, new in r.price_changes]
        for status, label in ((ZEIN_LIST, "ZEIN"), (RESCAN, "RESCAN"), (MANUAL, "BY HAND"), (SKIPPED, "SKIPPED")):
            for e in g[status]:
                out.append(f"{label:8}{_where(e.entry)}: {e.note}")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"Report {datetime.now():%Y-%m-%d %H%M%S}.txt"
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        name = self.ctx.catalogue.export_name
        save_atomic(LAST_EXPORT, lambda tmp: tmp.write_text(name, encoding="utf-8"))  # its packs are now reported
        return path

    def _export_notes(self) -> list[str]:
        """Automatic checks on the PowerSoft export, so Zein doesn't have to remember them (D-023):
        an export that was skipped and why, the pack links whenever a new export comes into use, and
        a reminder when the export is getting old."""
        cat = self.ctx.catalogue
        notes = [f"EXPORT  {w}" for w in cat.warnings]
        last = LAST_EXPORT.read_text(encoding="utf-8").strip() if LAST_EXPORT.exists() else ""
        if cat.export_name != last:
            notes.append(f"EXPORT  New PowerSoft export in use: {cat.export_name} ({len(cat.items)} items). Packs:")
            for code, link in sorted(cat.pack_links.items(), key=lambda kv: cat.items[kv[0]].description):
                check = "   <- NEAR NAME, check it" if not link.exact else ""
                notes.append(f"   {cat.items[code].description} = {link.pieces} x "
                             f"{cat.items[link.single].description} ({link.single}){check}")
            for code in cat.unlinked_packs:
                notes.append(f"   {cat.items[code].description} ({code}): NOT LINKED, staff will be asked. "
                             "Rename it to the single item's exact name + ' xN'.")
        for profile in PROFILES:  # a new item needs its supplier's PowerSoft code
            if profile is not example and profile.SUPPLIER not in cat.supplier_codes:
                notes.append(f"EXPORT  '{profile.SUPPLIER}' has no code in data/powersoft/suppliers.xlsx: new items "
                             "from it would have no supplier code.")
        m = re.search(r"\d{4}-\d{2}-\d{2}", cat.export_name)
        if m and (date.today() - date.fromisoformat(m.group())).days > EXPORT_MAX_AGE:
            notes.append(f"EXPORT  The PowerSoft export is from {m.group()}. Time for a new one.")
        return notes + [""] if notes else []


def _where(entry: Entry) -> str:
    name = Path(entry.file).name
    pages = ", ".join(str(p + 1) for p in entry.pages)
    where = f"{name}, page{'s' if len(entry.pages) > 1 else ''} {pages}"
    return f"{entry.label} ({where})" if entry.label else where
