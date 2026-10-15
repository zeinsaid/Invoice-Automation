"""One run of the tool: add scans to the queue, hand out questions one at a time, record answers.

The review window (ui.py) is a thin layer over this, so the same logic can be driven from tests.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .pipeline import (DONE, MANUAL, PENDING, RESCAN, SKIPPED, ZEIN_LIST, Context, Entry, Evaluation, Question,
                       Result, enqueue, evaluate, finalize, load_queue, save_queue)

REPORTS_DIR = Path("data/reports")


@dataclass
class Event:
    entry: Entry
    status: str
    note: str = ""
    result: Result | None = None


@dataclass
class Session:
    zein: bool = False  # Zein's mode: also works through Zein's list, and has extra options
    ctx: Context = field(default_factory=Context.load)
    entries: list[Entry] = field(default_factory=load_queue)
    events: list[Event] = field(default_factory=list)

    def add(self, pdfs: list[Path], move: bool = True) -> None:
        self.entries = enqueue(pdfs, move)

    def next_question(self) -> tuple[Entry, Evaluation, Question] | None:
        """Finish everything that needs no question; return the next question, or None when done."""
        for entry in self.entries:
            if entry.status != PENDING and not (self.zein and entry.status == ZEIN_LIST):
                continue
            ev = evaluate(entry, self.ctx)
            if ev.outcome == "ready":
                result = finalize(ev, self.ctx)
                self._event(entry, DONE, result=result)
            elif ev.outcome in (MANUAL, SKIPPED, RESCAN):
                self._event(entry, ev.outcome, ev.note)
            elif ev.outcome == "zein" and not self.zein:
                self._event(entry, ZEIN_LIST, ev.note)
            else:
                return entry, ev, ev.questions[0]
        return None

    def answer(self, entry: Entry, question: Question, value) -> None:
        entry.answers[question.id] = value
        if entry.status == ZEIN_LIST:
            entry.status = PENDING  # Zein answered: back to the normal flow
        save_queue(self.entries)

    def not_sure(self, entry: Entry, question: Question) -> None:
        note = f"Staff were not sure: {question.title}" + (f" ({question.detail})" if question.detail else "")
        self._event(entry, ZEIN_LIST, note)

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
        if not self.events:
            return None
        g = self.summary()
        out = [f"Invoice run {datetime.now():%Y-%m-%d %H:%M}" + (" (Zein)" if self.zein else ""), ""]
        for e in g[DONE]:
            r = e.result
            out.append(f"READY  {r.output_file.name}  ({len(r.invoice.lines)} lines -> {len(r.rows)} items, "
                       f"total {r.invoice.computed_total:.2f})")
            out += [f"   staff: {c}" for c in r.confirmed]
            out += [f"   price: {code} {name}: {old:.2f} -> {new:.3f} ({(new - old) / old * 100:+.0f}%)"
                    for code, name, old, new in r.price_changes]
        for status, label in ((ZEIN_LIST, "ZEIN"), (RESCAN, "RESCAN"), (MANUAL, "BY HAND"), (SKIPPED, "SKIPPED")):
            for e in g[status]:
                out.append(f"{label:7}{_where(e.entry)}: {e.note}")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"Report {datetime.now():%Y-%m-%d %H%M%S}.txt"
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return path


def _where(entry: Entry) -> str:
    name = Path(entry.file).name
    return f"{entry.label} ({name}, page {entry.page + 1})" if entry.label else f"{name}, page {entry.page + 1}"
