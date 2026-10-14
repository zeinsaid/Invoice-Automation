# Invoice Automation

Turns scanned supplier invoices into PowerSoft-ready Excel files for **The Plug Business Center**, a 24/7 print shop and mini-market in Nicosia, Cyprus.

> **Status:** early development. The design is recorded in [DECISIONS.md](DECISIONS.md); code comes next.

## The problem

Stock arrives with paper invoices from ~20 suppliers. For each invoice, a staff member:
1. opens that supplier's Excel (PowerSoft's import format),
2. types in every quantity by hand,
3. deletes every row with quantity 0,
4. uploads the file to PowerSoft (the stock/POS system).

It is slow and error-prone, and cost prices are rarely updated because checking them takes even longer.

## What this tool does

```
input/  (scanned PDFs, possibly several invoices per PDF)
   │
   ├─ split into pages ─ detect supplier ─ group pages into invoices
   ├─ Azure Document Intelligence: read lines, quantities, prices (+ confidence)
   ├─ match each line to our item: learned mapping → barcode → fuzzy name
   ├─ convert invoice units (cartons, cases) to selling pieces; compute per-piece cost
   ├─ check that the lines add up to the invoice total
   └─ write the supplier's Excel: quantities filled, zero rows removed, issues highlighted
   │
output/ (one Excel per invoice + a short report)  → a person checks it, then uploads it to PowerSoft
```

**Flag, don't guess.** Anything uncertain is highlighted in the Excel. Yellow means check against the paper, orange means the price changed, red means contact the owner.

## For shop staff

1. Put the scanned invoices into `input/`.
2. Double-click **Process Invoices**.
3. When it says **Done**, open `output/1 - To Check`, check each file against its paper invoice, and upload it to PowerSoft.
4. After uploading a file, move it into `output/2 - Uploaded`.
5. If it says **Something went wrong**, or a file has **red** cells, don't upload it. Contact Zein.

## For developers

Requirements: Windows, Python 3.12, [uv](https://docs.astral.sh/uv/), and an Azure Document Intelligence resource (the free F0 tier is enough).

```powershell
uv sync
copy .env.example .env   # then fill in AZURE_DI_ENDPOINT and AZURE_DI_KEY
uv run invoice-automation
```

Real shop data (supplier Excels, invoices) lives in `data/`, which is git-ignored and never committed.

## Project docs

- [DECISIONS.md](DECISIONS.md): numbered design decisions with the reasoning behind each one
- [CLAUDE.md](CLAUDE.md): project brief and working agreement
