"""Record the review window working through the made-up invoice, for the README and LinkedIn.

The window is driven by this script (the clicks and typing a staff member would do) and captured
on its own with PrintWindow while almost transparent, so nothing else on the screen is recorded.
Each frame gets a caption. Output: docs/demo/demo.gif (README) and docs/demo/demo.mp4 (LinkedIn).

Start from an empty memory, so the tool asks what it would ask the first time:
    rm -rf data/state data/supplier_items.xlsx data/reports "output/Ready to upload"
    uv run --with imageio --with imageio-ffmpeg python scripts/record_demo.py
"""

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import ttk

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from invoice_automation.session import Session
from invoice_automation.ui import App

PDF = Path("docs/demo/example-invoice.pdf")
OUT = Path("docs/demo")
SIZE = (1280, 960)  # window size; frames are scaled to WIDTH
WIDTH = 1100
CAPTION_H = 78
FONT = ImageFont.truetype("segoeuib.ttf", 26)
SMALL = ImageFont.truetype("segoeui.ttf", 19)

frames: list[tuple[Image.Image, float]] = []  # (frame, seconds on screen)


def framed(img: Image.Image, caption: str, sub: str = "") -> Image.Image:
    img = img.convert("RGB")
    img = img.resize((WIDTH, round(img.height * WIDTH / img.width)), Image.LANCZOS)
    out = Image.new("RGB", (WIDTH, img.height + CAPTION_H), "#10131c")
    out.paste(img, (0, CAPTION_H))
    d = ImageDraw.Draw(out)
    d.text((22, 10 if sub else 20), caption, font=FONT, fill="white")
    if sub:
        d.text((22, 44), sub, font=SMALL, fill="#aab4c8")
    return out


def add(img, caption, sub="", seconds=3.0):
    frames.append((framed(img, caption, sub), seconds))


def grab(app) -> Image.Image:
    app.root.update()
    user32, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = user32.GetParent(app.root.winfo_id())
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    gdi.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)

    class BIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
                    ("x", ctypes.c_int32), ("y", ctypes.c_int32), ("used", ctypes.c_uint32),
                    ("important", ctypes.c_uint32)]

    bih = BIH(ctypes.sizeof(BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    return img.crop((8, 0, w - 8, h - 8))  # the invisible resize border


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def button(app, text):
    return next(w for w in walk(app.body) if isinstance(w, tk.Button) and w.cget("text") == text)


def entries(app):
    return [w for w in walk(app.body) if isinstance(w, tk.Entry)]


def type_into(app, box, text, caption, sub="", every=99):
    box.focus_force()
    box.delete(0, "end")
    for i, ch in enumerate(text, 1):
        box.insert("end", ch)
        box.event_generate("<KeyRelease>")
        if i % every == 0 and i < len(text):
            add(grab(app), caption, sub, 0.25)
    add(grab(app), caption, sub, 2.2)


def title(app):
    return app.current[2].title if app.current else ""


def run(app):
    add(scan_image(), "A supplier invoice arrives on paper and is scanned",
        "Made-up for this demo: the supplier and every price are fictional", 3.5)

    # 1. A case barcode the tool has never seen: the price says 24 cans.
    assert title(app) == "How many pieces in 1 unit?", title(app)
    add(grab(app), "7 of 12 lines went straight in. 5 questions are left.",
        "Q1: a new case barcode. Its price is 24.7x one can, so the tool suggests 24", 4.5)
    button(app, "YES").invoke()

    # 2. A misspelling.
    add(grab(app), "Q2: a near match is confirmed, never assumed",
        "The words that differ are in red", 3.5)
    button(app, "YES").invoke()

    # 3. A pack of an item we already sell.
    add(grab(app), "Q3: not found in our items", "Staff can scan the item, search by name, or add a new item", 3)
    button(app, "It is a NEW item").invoke()
    add(grab(app), "The new-item form", "The barcode must come from the item itself, not the invoice", 3)
    pieces = entries(app)[2]
    pieces.focus_force()
    pieces.delete(0, "end")
    pieces.insert(0, "3")
    pieces.event_generate("<KeyRelease>")
    app.root.update()
    next(w for w in walk(app.body) if isinstance(w, tk.Canvas)).yview_moveto(1.0)  # the screen scrolls
    add(grab(app), "1 unit holds 3 bars...",
        "...so the form offers the single bar we already sell, instead of a duplicate item", 3.5)
    button(app, "Use this one").invoke()
    if title(app) == "How many pieces in 1 unit?":
        add(grab(app), "Booked as 3 single bars per pack", "The price confirms it: 3x one bar", 3)
        button(app, "YES").invoke()

    # 4. A really new product.
    add(grab(app), "Q4: a product we have never stocked", "", 2.5)
    button(app, "It is a NEW item").invoke()
    name, barcode, pieces, price = entries(app)[:4]
    type_into(app, name, "TOBLERONE MILK 100G", "Staff fill in a new item", "", every=6)
    type_into(app, barcode, "2000000000046", "Staff fill in a new item", "Barcode scanned from the bar itself", every=7)
    type_into(app, price, "1.20", "Staff fill in a new item",
              "The cost comes from the invoice, never typed: 1.52 per bar before VAT")
    combo = next(w for w in walk(app.body) if isinstance(w, ttk.Combobox))
    if not combo.get():
        combo.set(next((c for c in combo.cget("values") if "CHOC" in c.upper()), combo.cget("values")[0]))
    button(app, "Save new item").invoke()
    add(grab(app), "A selling price below cost is refused", "It also catches a wrong 'how many' answer", 3.5)
    price.delete(0, "end")
    price.insert(0, "2.50")
    button(app, "Save new item").invoke()

    # 5. A line that doesn't add up.
    add(grab(app), "Q5: 10 x 0.60 is not 6.60", "Every line's sum and the invoice total are checked. "
        "Staff type the numbers as printed", 4)
    button(app, "OK, the numbers are right now").invoke()

    add(grab(app), "Done: the PowerSoft import file is written", "Staff upload it. Every answer is remembered, "
        "so the next invoice from this supplier asks less", 3.5)
    add(excel_image(), "The import file, in selling pieces and cost per piece",
        "2 cases = 48 cans · 5 water packs = 60 bottles · 6 Kinder 3-packs = 18 bars", 5)
    app.root.destroy()


def excel_image() -> Image.Image:
    """Four columns of the Excel the tool wrote (the real file has PowerSoft's 20)."""
    import openpyxl
    path = sorted(Path("output/Ready to upload").glob("Example Wholesale*.xlsx"))[-1]
    rows = list(openpyxl.load_workbook(path).active.iter_rows(min_row=2, values_only=True))
    img = Image.new("RGB", (SIZE[0] - 16, SIZE[1] - 8), "white")
    d = ImageDraw.Draw(img)
    head = ImageFont.truetype("segoeuib.ttf", 21)
    body = ImageFont.truetype("segoeui.ttf", 21)
    d.text((40, 30), path.name, font=head, fill="#333333")
    cols = [(40, "Item Code", 1, False), (210, "Description", 4, False), (760, "Quantity", 5, True),
            (1110, "Cost per piece (excl. VAT)", 7, True)]
    y = 90
    d.rectangle((30, y - 8, img.width - 30, y + 30), fill="#e8f0e8")
    for x, label, _, right in cols:
        d.text((x, y), label, font=head, fill="black", anchor="ra" if right else "la")
    for r in rows:
        y += 42
        for x, _, i, right in cols:
            v = r[i]
            text = f"{v:.3f}" if i == 7 else str(v)
            d.text((x, y), text, font=body, fill="black", anchor="ra" if right else "la")
        d.line((30, y + 34, img.width - 30, y + 34), fill="#dddddd")
    return img


def scan_image() -> Image.Image:
    pix = pymupdf.open(PDF)[0].get_pixmap(dpi=130, clip=pymupdf.Rect(0, 0, 595, 420))
    page = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    canvas = Image.new("RGB", (SIZE[0] - 16, SIZE[1] - 8), "#e9ebef")
    page.thumbnail((canvas.width - 80, canvas.height - 60))
    canvas.paste(page, ((canvas.width - page.width) // 2, 30))
    return canvas


def same_size() -> None:
    """Pad every frame to one size (a multiple of 16, which video encoders want)."""
    w = max(f.width for f, _ in frames)
    h = max(f.height for f, _ in frames)
    w, h = w + -w % 16, h + -h % 16
    for i, (f, s) in enumerate(frames):
        canvas = Image.new("RGB", (w, h), "#10131c")
        canvas.paste(f, (0, 0))
        frames[i] = (canvas, s)


def save():
    same_size()
    gif = [f.resize((880, round(f.height * 880 / f.width)), Image.LANCZOS) for f, _ in frames]
    gif[0].save(OUT / "demo.gif", save_all=True, append_images=gif[1:], optimize=True,
                duration=[round(s * 1000) for _, s in frames], loop=0)
    import imageio.v2 as imageio  # only needed here (uv run --with imageio --with imageio-ffmpeg)
    fps = 4
    with imageio.get_writer(OUT / "demo.mp4", fps=fps, codec="libx264", quality=8,
                            macro_block_size=16) as w:
        for f, s in frames:
            for _ in range(max(1, round(s * fps))):
                w.append_data(__import__("numpy").asarray(f))
    print(f"{len(frames)} frames -> {OUT / 'demo.gif'}, {OUT / 'demo.mp4'}")


if __name__ == "__main__":
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    app = App(Session(), [PDF], move=False)
    app.root.state("normal")
    app.root.geometry(f"{SIZE[0]}x{SIZE[1]}+0+0")
    app.root.attributes("-alpha", 0.01)
    failed = []
    # A script error stops the recording quietly, instead of the tool's "contact Zein" box on screen.
    app.root.report_callback_exception = lambda *exc: (failed.append(exc[1]), app.root.destroy())

    def start():
        if app.current is None:
            return app.root.after(300, start)
        try:
            run(app)
        except Exception as e:  # noqa: BLE001 - re-raised once the window is gone
            failed.append(e)
            app.root.destroy()

    app.root.after(300, start)
    app.run()
    if failed:
        raise failed[0]
    if not frames or len(frames) < 10:
        sys.exit("Recording stopped early")
    save()
