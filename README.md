# Invoice Automation

Turns scanned supplier invoices into PowerSoft-ready Excel files for **The Plug Business Center**, a 24/7 print shop and mini-market in Nicosia, Cyprus.

> **Status:** early development. Athenites and the cigarette suppliers (Cassandra, Cosmos, Fereos) work end to end; the rest come next (D-015). The design is recorded in [DECISIONS.md](DECISIONS.md).

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

1. Put the scanned invoices into `input/` (all pages of an invoice in one PDF).
2. Double-click **Process Invoices**.
3. Answer the questions in the window, using the paper invoice (and the product, for barcodes). If you can't answer one, press **I'm not sure**.
4. When it says **Done**, upload the files in `output/Ready to upload/` to PowerSoft.

## For developers

Requirements: Windows, Python 3.12, [uv](https://docs.astral.sh/uv/), and an Azure Document Intelligence resource (the free F0 tier is enough).

```powershell
uv sync
copy .env.example .env   # then fill in AZURE_DI_ENDPOINT and AZURE_DI_KEY
uv run invoice-automation                 # process everything in input/ (moved to processed/), open the review window
uv run invoice-automation path/to/scan.pdf # process specific files and leave them where they are
uv run invoice-automation --zein          # Zein's mode: also work through invoices staff sent to Zein
uv run invoice-automation --no-window     # no window: finish what needs no questions (testing)
uv run pytest                             # unit tests (synthetic data only)
```

Document Intelligence responses are cached in `data/cache/di/`, so re-running a scan costs no Azure pages.
Open questions and answers live in `data/state/queue.json`; Zein's run reports in `data/reports/`; errors in `logs/error.log`.

Real shop data (supplier Excels, invoices) lives in `data/`, which is git-ignored and never committed.

## Project docs

- [DECISIONS.md](DECISIONS.md): numbered design decisions with the reasoning behind each one
- [CLAUDE.md](CLAUDE.md): project brief and working agreement
