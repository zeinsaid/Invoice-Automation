"""The review window (D-022): one question at a time, big buttons, the invoice line shown from the scan.

All decisions live in session.py / pipeline.py; this file only draws screens and passes answers on.
"""

import os
import threading
import tkinter as tk
import traceback
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from .catalogue import name_key
from .crops import crop
from .extract import analyze_page
from .layout import ean_is_valid, parse_number
from .pipeline import (MANUAL, NEW, PENDING, READY_DIR, RESCAN, SKIPPED, ZEIN_LIST, mark_uploaded,
                       search_items, suggested_category, waiting_uploads)
from .session import Session, _where

LOG = Path("logs/error.log")
FONT = "Segoe UI"
GREEN, RED_BG, GREY = "#2e7d32", "#c62828", "#555555"
IMAGE_WIDTH = 940


def fmt(x: float) -> str:
    return f"{x:g}" if float(x).is_integer() else f"{x:.2f}"


class App:
    def __init__(self, session: Session, new_pdfs: list[Path], move: bool):
        self.session = session
        self.root = tk.Tk()
        self.root.title("Invoices" + (" (Zein)" if session.zein else ""))
        self.root.geometry("1000x780")
        self.root.minsize(820, 640)
        self.root.state("zoomed")  # the new-item form needs the height
        self.root.configure(bg="white")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.report_callback_exception = lambda *exc: self.fail(exc[1])
        style = ttk.Style(self.root)
        style.configure("TCombobox", padding=6)
        self.body = tk.Frame(self.root, bg="white", padx=24, pady=16)
        self.body.pack(fill="both", expand=True)
        self.photos = []  # keep image references alive
        self.current = None
        self.show_message("Reading invoices...", "Please wait. This can take a minute.")
        # Reading new scans calls Azure and can take a while, so it runs in the background. Only the
        # main thread may touch the window, so the reader just leaves its progress here to be polled.
        self._progress, self._read_done, self._read_error = "", False, None
        threading.Thread(target=self._read, args=(new_pdfs, move), daemon=True).start()
        self.root.after(200, self._poll)

    def run(self) -> None:
        self.root.mainloop()

    # --- Reading new scans (in the background, so the window stays responsive) ------------------

    def _read(self, pdfs, move):
        try:
            if pdfs:
                self.session.add(pdfs, move)
            todo = [(e.file, p) for e in self.session.entries if e.status in (NEW, PENDING) for p in e.pages]
            for i, (file, page) in enumerate(todo, 1):
                self._progress = f"Page {i} of {len(todo)}"
                analyze_page(Path(file), page, "prebuilt-layout")  # cached after the first time
        except Exception as e:  # noqa: BLE001 - every failure becomes "contact Zein"
            self._read_error = e
        self._read_done = True

    def _poll(self):
        if self._read_error:
            self.fail(self._read_error)
        elif self._read_done:
            self.next()
        else:
            if self._progress:
                self.show_message("Reading invoices...", self._progress)
            self.root.after(200, self._poll)

    # --- Flow ---------------------------------------------------------------------------------

    def next(self):
        nxt = self.session.next_question()
        if nxt is None:
            self.show_done()
        else:
            self.current = nxt
            self.show_question(*nxt)

    def answer(self, value):
        entry, _, question = self.current
        self.session.answer(entry, question, value)
        self.next()

    def go_back(self):
        self.session.undo(self.current[0])
        self.next()

    def not_sure(self):
        entry, _, question = self.current
        if messagebox.askyesno("Not sure", "Send this invoice to Zein?\n\nDo not upload it. Zein will finish it."):
            self.session.not_sure(entry, question)
            self.next()

    # --- Screens --------------------------------------------------------------------------------

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.photos.clear()

    def label(self, parent, text, size=13, bold=False, color="black", wrap=940, **pack):
        lbl = tk.Label(parent, text=text, font=(FONT, size, "bold" if bold else "normal"), fg=color, bg="white",
                       wraplength=wrap, justify="left", anchor="w")
        lbl.pack(anchor="w", **pack)
        return lbl

    def button(self, parent, text, command, color=GREY, side="left", size=14):
        btn = tk.Button(parent, text=text, command=command, font=(FONT, size, "bold"), fg="white", bg=color,
                        activebackground=color, activeforeground="white", relief="flat", padx=22, pady=10,
                        cursor="hand2")
        btn.pack(side=side, padx=(0, 12), pady=6)
        return btn

    def entry_box(self, parent, value="", width=30, on_enter=None):
        box = tk.Entry(parent, font=(FONT, 16), width=width, relief="solid", bd=1)
        box.insert(0, value)
        if on_enter:
            box.bind("<Return>", lambda _: on_enter())  # barcode scanners type the code and press Enter
        return box

    def scroll_area(self) -> tk.Frame:
        """The part of the screen above the bottom buttons, scrollable, so nothing (like 'Save new item')
        is ever out of reach on a small screen. Pack the bottom buttons before calling this."""
        holder = tk.Frame(self.body, bg="white")
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, bg="white", highlightthickness=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        inner = tk.Frame(canvas, bg="white")
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def fit(_=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            if inner.winfo_reqheight() > canvas.winfo_height():  # the bar only when there is more to see
                bar.pack(side="right", fill="y")
            else:
                bar.pack_forget()
                canvas.yview_moveto(0)

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(window, width=e.width), fit()))
        canvas.pack(side="left", fill="both", expand=True)

        def wheel(e):
            if bar.winfo_ismapped() and not isinstance(e.widget, tk.Listbox):  # a list scrolls itself
                canvas.yview_scroll(int(-e.delta / 120), "units")

        self.root.bind_all("<MouseWheel>", wheel)
        return inner

    def show_message(self, title, text):
        self.clear()
        self.label(self.body, title, 24, True, pady=(80, 10))
        self.label(self.body, text, 14, color=GREY)

    def show_question(self, entry, ev, q):
        self.clear()
        # Packed first so it keeps its place; everything else scrolls above it.
        bottom = tk.Frame(self.body, bg="white")
        bottom.pack(side="bottom", fill="x")
        content = self.content = self.scroll_area()
        top = tk.Frame(content, bg="white")
        top.pack(fill="x")
        tk.Label(top, text=f"{entry.label}   ·   {Path(entry.file).name}", font=(FONT, 12), fg=GREY,
                 bg="white").pack(side="left")
        left = len(ev.questions)
        tk.Label(top, text=f"{left} question{'s' if left > 1 else ''} on this invoice", font=(FONT, 12),
                 fg=GREY, bg="white").pack(side="right")

        self.show_picture(entry, ev, q)
        self.label(content, q.title, 22, True, pady=(14, 2))
        if q.detail:
            self.label(content, q.detail, 13, color=GREY, pady=(0, 8))
        area = tk.Frame(content, bg="white")
        area.pack(fill="x", pady=6)
        getattr(self, f"ask_{q.kind}")(area, entry, ev, q)

        if entry.answers:
            self.button(bottom, "< Previous question", self.go_back, size=11)
        if self.session.zein:
            self.button(bottom, "Take out (enter by hand)", lambda: self._zein(self.session.drop), size=11)
            self.button(bottom, "Start this invoice again", lambda: self._zein(self.session.restart), size=11)
        else:
            self.button(bottom, "I'm not sure", self.not_sure, size=11)

    def _zein(self, action):
        action(self.current[0])
        self.next()

    def show_picture(self, entry, ev, q):
        inv = ev.invoice
        if inv is None:
            return
        parts = []
        pdf = Path(entry.file)
        if q.line is not None:
            header_page = q.line.page if q.line.header_page is None else q.line.header_page
            for page, box in ((header_page, q.line.header_box), (q.line.page, q.line.box)):
                if box:
                    parts.append(crop(pdf, page, box, q.line.angle))
        elif q.kind in ("number", "duplicate"):
            parts.append(crop(pdf, entry.pages[0], None, inv.page_angle, "top"))
        elif q.kind == "total" and inv.printed_total is not None:
            parts.append(crop(pdf, entry.pages[-1], None, inv.page_angle, "bottom"))
        parts = [p for p in parts if p is not None]
        if not parts:
            return
        width = max(p.width for p in parts)
        canvas = Image.new("RGB", (width, sum(p.height for p in parts) + 6 * (len(parts) - 1)), "white")
        y = 0
        for p in parts:
            canvas.paste(p, (0, y))
            y += p.height + 6
        scale = min(1.0, IMAGE_WIDTH / canvas.width, 260 / canvas.height)
        canvas = canvas.resize((int(canvas.width * scale), int(canvas.height * scale)), Image.LANCZOS)
        photo = ImageTk.PhotoImage(canvas)
        self.photos.append(photo)
        tk.Label(self.content, image=photo, bg="white", bd=1, relief="solid").pack(anchor="w", pady=(10, 0))

    # --- One function per question kind ------------------------------------------------------------

    def ask_pack(self, area, entry, ev, q):
        line, n = q.line, q.data.get("suggested")
        self.label(area, f"Invoice:   {fmt(line.quantity)}  x  {line.description}", 15)
        self.label(area, f"Our item:  {q.data['description']}", 15, pady=(0, 8))
        if n:
            self.label(area, f"1 unit = {n} pieces?      ({fmt(line.quantity)} units = {fmt(line.quantity * n)} pieces)",
                       18, True)
            row = tk.Frame(area, bg="white")
            row.pack(anchor="w", pady=8)
            self.button(row, "YES", lambda: self.answer(n), GREEN)
            self.button(row, "NO", lambda: (row.destroy(), self._pieces(area)), RED_BG)
        else:
            self._pieces(area)

    def _pieces(self, area):
        self.label(area, "How many pieces are in 1 unit? (Count them on the box or the shelf.)", 15, pady=(8, 4))
        row = tk.Frame(area, bg="white")
        row.pack(anchor="w")
        error = None

        def ok():
            value = parse_number(box.get())
            if value is None or not value.is_integer() or not 1 <= value <= 500:
                error.config(text="Type a whole number, e.g. 6, 12 or 24.")
                return
            self.answer(int(value))

        box = self.entry_box(row, width=8, on_enter=ok)
        box.pack(side="left", padx=(0, 12))
        box.focus_set()
        self.button(row, "OK", ok, GREEN)
        error = self.label(area, "", 12, color=RED_BG)

    def ask_item(self, area, entry, ev, q):
        # Words that differ are red, so 'A2' vs 'A3' or 'Black' vs 'Blue' can't be missed.
        self._compare(area, "Invoice says:", q.line.description, q.data["description"])
        self._compare(area, "Our item:", q.data["description"], q.line.description, f"(code {q.data['code']})")
        tk.Frame(area, bg="white", height=8).pack()
        row = tk.Frame(area, bg="white")
        row.pack(anchor="w")
        self.button(row, "YES", lambda: self.answer("yes"), GREEN)
        self.button(row, "NO", lambda: (row.destroy(), self._identify(area, entry, ev, q, allow_new=True)), RED_BG)

    def _compare(self, area, title, text, other, suffix=""):
        row = tk.Frame(area, bg="white")
        row.pack(anchor="w")
        tk.Label(row, text=title, font=(FONT, 15), bg="white", width=13, anchor="w").pack(side="left")
        others = set(name_key(other).split())
        for word in text.split():
            differs = any(part not in others for part in name_key(word).split())
            tk.Label(row, text=word, font=(FONT, 15, "bold" if differs else "normal"), bg="white",
                     fg=RED_BG if differs else "black").pack(side="left", padx=(0, 5))
        if suffix:
            tk.Label(row, text=suffix, font=(FONT, 13), fg=GREY, bg="white").pack(side="left", padx=(6, 0))

    def ask_identify(self, area, entry, ev, q):
        self.label(area, f"Invoice says:   {q.line.description}", 15, pady=(0, 6))
        self._identify(area, entry, ev, q, allow_new=True)

    def ask_not_storable(self, area, entry, ev, q):
        self.label(area, f"Invoice says:   {q.line.description}", 15, pady=(0, 6))
        self._identify(area, entry, ev, q, allow_new=False)

    def _identify(self, area, entry, ev, q, allow_new):
        catalogue = self.session.ctx.catalogue

        # 1. Barcode: typed, or scanned (the scanner types it and presses Enter).
        self.label(area, "Scan or type the barcode of ONE piece:", 14, True, pady=(6, 2))
        row = tk.Frame(area, bg="white")
        row.pack(anchor="w")
        found = tk.Frame(area, bg="white")
        found.pack(anchor="w", fill="x")

        def find():
            for child in found.winfo_children():
                child.destroy()
            code = "".join(ch for ch in barcode.get() if ch.isdigit())
            codes = catalogue.by_barcode.get(code, [])
            if not codes:
                self.label(found, "No item has this barcode. Check it, or search by name below.", 13, color=RED_BG)
                if allow_new:
                    self.button(found, "It is a NEW item", lambda: self._new_item(area, entry, ev, q, code), size=12)
                return
            item = catalogue.items[codes[0]]
            if not item.storable:
                self.label(found, f"'{item.description}' holds no stock. Scan the barcode of ONE piece.", 13,
                           color=RED_BG)
                return
            self.label(found, f"Found:  {item.description}   (code {item.code})", 15, True)
            self.button(found, "Yes, this one", lambda: self.answer({"code": item.code}), GREEN, size=12)

        barcode = self.entry_box(row, width=20, on_enter=find)
        barcode.pack(side="left", padx=(0, 12))
        barcode.focus_set()
        self.button(row, "Find", find, size=12)

        # 2. Search by name.
        self.label(area, "Or search by name:", 14, True, pady=(10, 2))
        search = self.entry_box(area, q.line.description if q.line else "", width=40)
        search.pack(anchor="w")
        results = tk.Listbox(area, font=(FONT, 13), height=5, width=70, relief="solid", bd=1, activestyle="none")
        results.pack(anchor="w", pady=4)
        codes: list[str] = []

        def refresh(*_):
            nonlocal codes
            hits = search_items(search.get(), self.session.ctx, ev.invoice.supplier) if search.get().strip() else []
            codes = [c for c, _, _ in hits]
            results.delete(0, "end")
            for c, d, _ in hits:
                results.insert("end", f"{d}   (code {c})")
            if hits:
                results.selection_set(0)  # the best match is pre-selected

        def use():
            if results.curselection():
                self.answer({"code": codes[results.curselection()[0]]})

        pending = None

        def later(*_):  # search after the typing stops
            nonlocal pending
            if pending:
                self.root.after_cancel(pending)
            pending = self.root.after(300, refresh)

        search.bind("<KeyRelease>", later)
        results.bind("<Double-Button-1>", lambda _: use())
        refresh()
        row2 = tk.Frame(area, bg="white")
        row2.pack(anchor="w")
        self.button(row2, "Use the selected item", use, GREEN, size=12)
        if allow_new:
            self.button(row2, "It is a NEW item", lambda: self._new_item(area, entry, ev, q, ""), size=12)

    def _new_item(self, area, entry, ev, q, barcode):
        for child in area.winfo_children():
            child.destroy()
        ctx = self.session.ctx
        self.label(area, "New item: fill in every box", 16, True, pady=(0, 6))
        form = tk.Frame(area, bg="white")
        form.pack(anchor="w")
        categories = sorted(c for c in ctx.catalogue.category_codes if c.upper() != "CATEGORY")
        fields = {}

        def add(row, text, widget):
            tk.Label(form, text=text, font=(FONT, 13), bg="white", anchor="w").grid(row=row, column=0, sticky="w", pady=4,
                                                                                  padx=(0, 12))
            widget.grid(row=row, column=1, sticky="w", pady=4)
            return widget

        line = q.line
        # The barcode box starts empty unless staff scanned one on the previous screen: a pre-filled invoice
        # barcode gets accepted unchecked, and it is often the pack's, not one piece's.
        invoice_barcode = line.barcode if ean_is_valid(line.barcode) else ""
        fields["description"] = add(0, "Name of ONE piece\n(not the pack)", self.entry_box(form, line.description, width=36))
        barcode_cell = tk.Frame(form, bg="white")
        fields["barcode"] = self.entry_box(barcode_cell, barcode, width=20)
        fields["barcode"].pack(anchor="w")
        tk.Label(barcode_cell, text="Scan it from the item itself, not from the invoice.", font=(FONT, 11), fg=GREY,
                 bg="white").pack(anchor="w")
        add(1, "Barcode of ONE piece\n(scan or type)", barcode_cell)
        if invoice_barcode and not barcode:
            def use_invoice_barcode():
                if messagebox.askyesno(
                        "Check the barcode",
                        f"Look at ONE piece in your hand.\n\nIs this number printed on it?\n\n{invoice_barcode}\n\n"
                        "Press Yes only if it is the same number, or if one piece has no barcode at all."):
                    fields["barcode"].delete(0, "end")
                    fields["barcode"].insert(0, invoice_barcode)
            hint = tk.Frame(barcode_cell, bg="white")
            hint.pack(anchor="w")
            tk.Label(hint, text=f"Invoice barcode: {invoice_barcode}", font=(FONT, 11), fg=GREY,
                     bg="white").pack(side="left")
            tk.Button(hint, text="Use invoice barcode", command=use_invoice_barcode, font=(FONT, 10), relief="solid",
                      bd=1, bg="white", cursor="hand2").pack(side="left", padx=(8, 0))
        fields["pieces"] = add(2, "How many do you sell from\n1 unit on the invoice?", self.entry_box(form, "1", width=6))
        fields["price"] = add(3, "Selling price € (with VAT)", self.entry_box(form, "", width=8))
        category = ttk.Combobox(form, values=categories, state="readonly", font=(FONT, 13), width=30)
        suggestion = suggested_category(q.data.get("candidates"), ctx.catalogue)
        if suggestion in categories:
            category.set(suggestion)
        add(4, "Category", category)
        # More than 1 piece per unit usually means a pack of something we already sell (e.g. a 3-pack of
        # Kinder Bueno White when 1372 is already the single bar): offer those before a duplicate is made.
        # Beside the fields, where it catches the eye (the tool runs on PC screens, wide enough for it).
        stocked = tk.Frame(form, bg="white")
        stocked.grid(row=0, column=2, rowspan=5, sticky="nw", padx=(36, 0))
        shown_for = None

        def show_stocked(*_):
            nonlocal shown_for
            pieces = parse_number(fields["pieces"].get())
            name = fields["description"].get().strip() or line.description
            key = name if pieces and pieces > 1 else None
            if key == shown_for:
                return
            shown_for = key
            for child in stocked.winfo_children():
                child.destroy()
            hits = search_items(name, ctx, ev.invoice.supplier) if key else []
            hits = [h for h in hits if h[2] >= hits[0][2] - 8][:3] if hits else []  # only near the best match
            if not hits:
                return
            self.label(stocked, "Do we already sell ONE piece of it?\nThen use that item, don't make a new one:", 13,
                       True, wrap=420, pady=(4, 6))
            for c, d, _ in hits:
                row = tk.Frame(stocked, bg="white")
                row.pack(anchor="w")
                tk.Button(row, text="Use this one", command=lambda c=c: self.answer({"code": c}), font=(FONT, 11, "bold"),
                          fg="white", bg=GREEN, activebackground=GREEN, relief="flat", padx=10,
                          cursor="hand2").pack(side="left", pady=2)
                tk.Label(row, text=f"{d}   (code {c})", font=(FONT, 13), bg="white").pack(side="left", padx=(8, 0))
        # The cost is never typed: it comes from the invoice, per piece (D-012 amendment). It is shown so a
        # wrong 'how many' answer, or a selling price below cost, stands out.
        unit_cost = line.amount_excl_vat / line.quantity if line.quantity else 0.0  # one invoice unit, before VAT
        cost_label = self.label(area, "", 13, color=GREY, pady=(4, 0))

        def cost_per_piece():
            pieces = parse_number(fields["pieces"].get())
            return unit_cost / pieces if pieces and pieces >= 1 else None

        def show_cost(*_):
            cost, price = cost_per_piece(), parse_number(fields["price"].get())
            text = f"Cost per piece: €{cost:.2f} (before VAT)" if cost is not None else ""
            if cost is not None and price:
                text += f"    ·    selling price before VAT: €{price / (1 + line.vat_rate / 100):.2f}"
            cost_label.config(text=text)

        for name in ("pieces", "price"):
            fields[name].bind("<KeyRelease>", show_cost)
        fields["pieces"].bind("<KeyRelease>", show_stocked, add="+")
        fields["description"].bind("<KeyRelease>", show_stocked)
        show_cost()
        (fields["price"] if barcode else fields["barcode"]).focus_set()
        error = self.label(area, "", 12, color=RED_BG, pady=(4, 0))

        def save():
            name = fields["description"].get().strip()
            code = "".join(ch for ch in fields["barcode"].get() if ch.isdigit())
            pieces = parse_number(fields["pieces"].get())
            price = parse_number(fields["price"].get())
            if not name:
                return error.config(text="Type the name.")
            if len(code) < 6:
                return error.config(text="Scan or type the barcode of one piece.")
            if code in ctx.catalogue.by_barcode:
                existing = ctx.catalogue.items[ctx.catalogue.by_barcode[code][0]]
                return error.config(text=f"This barcode is already '{existing.description}' (code {existing.code}). "
                                         "Go back and pick that item instead.")
            if pieces is None or not pieces.is_integer() or pieces < 1:
                return error.config(text="Pieces in 1 unit must be a whole number (1 if it is a single item).")
            if price is None or price <= 0:
                return error.config(text="Type the selling price. It is required.")
            cost = cost_per_piece()
            if cost is not None and price / (1 + line.vat_rate / 100) <= cost:
                return error.config(text=f"The selling price is below the cost (€{cost:.2f} per piece). Check the "
                                         "price, and how many you sell from 1 unit.")
            if not category.get():
                return error.config(text="Choose a category.")
            self.answer({"new": {"description": name, "barcode": code, "pieces": int(pieces), "price": price,
                                 "category": category.get()}})

        row = tk.Frame(area, bg="white")
        row.pack(anchor="w", pady=(6, 0))
        self.button(row, "Save new item", save, GREEN, size=12)
        self.button(row, "Cancel", lambda: self.show_question(*self.current), size=12)

    def ask_fix_line(self, area, entry, ev, q):
        self.label(area, "Look at the picture and the paper. Correct any number that is wrong:", 14, pady=(0, 6))
        form = tk.Frame(area, bg="white")
        form.pack(anchor="w")
        boxes = {}
        for i, (name, label) in enumerate(q.data["labels"].items()):
            tk.Label(form, text=label, font=(FONT, 13), bg="white").grid(row=i, column=0, sticky="w", pady=3, padx=(0, 12))
            boxes[name] = self.entry_box(form, q.line.fields.get(name, ""), width=12)
            boxes[name].grid(row=i, column=1, sticky="w", pady=3)
        error = self.label(area, "", 12, color=RED_BG)

        def ok():
            values = {name: box.get().strip() for name, box in boxes.items()}
            if any(v and parse_number(v) is None for v in values.values()):
                return error.config(text="Only numbers, please.")
            self.answer(values)

        self.button(area, "OK, the numbers are right now", ok, GREEN, size=12)

    def ask_number(self, area, entry, ev, q):
        box = self.entry_box(area, width=20, on_enter=lambda: box.get().strip() and self.answer(box.get().strip()))
        box.pack(anchor="w", pady=4)
        box.focus_set()
        self.button(area, "OK", lambda: box.get().strip() and self.answer(box.get().strip()), GREEN)

    def ask_total(self, area, entry, ev, q):
        error = None

        def ok():
            value = parse_number(box.get())
            if value is None or value <= 0:
                return error.config(text="Type the total, e.g. 772.11")
            self.answer(value)

        row = tk.Frame(area, bg="white")
        row.pack(anchor="w")
        tk.Label(row, text="€", font=(FONT, 16), bg="white").pack(side="left")
        box = self.entry_box(row, width=12, on_enter=ok)
        box.pack(side="left", padx=(4, 12))
        box.focus_set()
        self.button(row, "OK", ok, GREEN)
        error = self.label(area, "", 12, color=RED_BG)

    def ask_duplicate(self, area, entry, ev, q):
        row = tk.Frame(area, bg="white")
        row.pack(anchor="w")
        self.button(row, "Skip it", lambda: self.answer("skip"), GREEN)

        def again():
            if messagebox.askyesno("Make it again?", "Only if the Excel was lost and NEVER uploaded.\n\nMake it again?"):
                self.answer("again")

        self.button(row, "Make the Excel again", again, RED_BG)

    def ask_zein(self, area, entry, ev, q):
        self.label(area, "Use the buttons at the bottom.", 13, color=GREY)

    # --- The end ---------------------------------------------------------------------------------

    def show_done(self):
        self.session.write_report()
        self.render_done()

    def render_done(self):
        self.clear()
        groups = self.session.summary()
        waiting = waiting_uploads()  # this run's files and any left from before
        row = tk.Frame(self.body, bg="white")
        row.pack(side="bottom", anchor="w")
        content = self.scroll_area()  # a long list of invoices scrolls; the buttons stay put
        self.label(content, "Done", 26, True, pady=(10, 10))
        if waiting:
            self.upload_steps(content, waiting)
        sections = [
            (RESCAN, "Scan again (all pages), then run again:", RED_BG, lambda e: f"{_where(e.entry)}\n      {e.note}"),
            (MANUAL, "Enter by hand:", GREY, lambda e: f"{_where(e.entry)}: {e.note}"),
            (ZEIN_LIST, "Waiting for Zein (do not upload):", RED_BG, lambda e: _where(e.entry)),
            (SKIPPED, "Skipped (already done before):", GREY, lambda e: _where(e.entry)),
        ]
        shown = bool(waiting)
        for status, title, color, text in sections:
            if groups.get(status):
                shown = True
                self.label(content, title, 15, True, color=color, pady=(10, 2))
                for e in groups[status]:
                    self.label(content, "   " + text(e), 13)
        if not shown:
            self.label(content, "Nothing to do. Put the scanned invoices in the 'input' folder first.", 15)
        if waiting:
            self.button(row, "Open 'Ready to upload'", lambda: os.startfile(READY_DIR.resolve()), GREEN)
        self.button(row, "Close", self.close_done)

    def upload_steps(self, parent, waiting):
        """What staff do next in PowerSoft, so nobody has to open each Excel to decide. New items (and,
        until Zein has checked D-008, cost changes) need Items import first; then every file is
        uploaded as a Purchase order. Then staff tick what they uploaded, and those files move to
        'Uploaded', so nothing can go in twice."""
        bg = "#eef5ee"
        box = tk.Frame(parent, bg=bg, padx=16, pady=10)
        box.pack(fill="x", pady=(0, 6))
        today = str(date.today())

        def name(w):
            return w["file"] + (f"   (from {w['made']})" if w["made"] and w["made"] != today else "")

        self.label(box, "What to do now in PowerSoft:", 15, True).configure(bg=bg)
        step = 1
        first = [w for w in waiting if w["items_import"]]
        if first:
            self.label(box, f"{step}.  Items import, with Modify ticked:", 14, True, pady=(6, 0)).configure(bg=bg)
            for w in first:
                self.label(box, f"      {name(w)}   ({w['items_import']})", 13).configure(bg=bg)
            step += 1
        what = "ALL the files" if len(waiting) > 1 else "the file"
        self.label(box, f"{step}.  Purchase order: {what} below.", 14, True, pady=(6, 0)).configure(bg=bg)
        if first:
            self.label(box, "Do step 1 first: the purchase order needs the new items and costs to be in PowerSoft.",
                       12, color=GREY, pady=(2, 0)).configure(bg=bg)
        self.label(box, f"{step + 1}.  When it is in PowerSoft, tick it and press 'Mark as uploaded':", 14, True,
                   pady=(10, 2)).configure(bg=bg)
        ticks = []
        for w in waiting:
            var = tk.BooleanVar(value=True)
            tk.Checkbutton(box, text=name(w), variable=var, font=(FONT, 13), bg=bg, activebackground=bg,
                           anchor="w").pack(anchor="w", padx=(18, 0))
            ticks.append((w["file"], var))

        def mark():
            names = [f for f, var in ticks if var.get()]
            if not names:
                return
            if not messagebox.askyesno("Uploaded?", f"Are these {len(names)} file(s) in PowerSoft now (both steps)?\n\n"
                                                    "They move to the 'Uploaded' folder."):
                return
            try:
                mark_uploaded(names)
            except PermissionError as e:
                return messagebox.showerror("Close Excel", str(e))
            self.render_done()

        self.button(box, "Mark as uploaded", mark, GREEN, size=12).configure(highlightbackground=bg)

    def close_done(self):
        if waiting_uploads() and not messagebox.askyesno(
                "Not uploaded yet", "Some files are not marked as uploaded.\n\nClose anyway? They will be shown "
                                    "again next time, so you can upload them later."):
            return
        self.root.destroy()

    def on_close(self):
        if self.current and not messagebox.askyesno(
                "Stop?", "Stop now?\n\nYour answers are saved. The other questions will come back next time."):
            return
        self.session.write_report()
        self.root.destroy()

    def fail(self, error: BaseException):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now().isoformat(timespec='seconds')}\n")
            f.write("".join(traceback.format_exception(error)))
        if isinstance(error, PermissionError):  # a file open in Excel: staff can fix that themselves
            messagebox.showerror("Close Excel", f"{error}\n\nNothing was saved for this invoice.")
        else:
            messagebox.showerror("Something went wrong", "Something went wrong. Please contact Zein.")
        self.root.destroy()


def run_window(session: Session, new_pdfs: list[Path], move: bool) -> None:
    try:  # sharp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001 - not Windows, or not supported: fine
        pass
    App(session, new_pdfs, move).run()
