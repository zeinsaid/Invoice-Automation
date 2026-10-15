# CLAUDE.md — Invoice Automation (The Plug)

## Who I am and why this project exists

I'm Zein Said, a CS (AI) graduate (Heriot-Watt, First Class) with about 2 years as an AI engineer in Dubai. I'm a versatile generalist rather than a deep specialist. I'm job hunting for AI and automation roles, mainly in Cyprus.

I also co-own **The Plug Business Center**, a 24/7 print shop, mini-market and kiosk in Nicosia, Cyprus. This project automates a real, tedious task there: staff typing supplier invoice quantities into Excel by hand.

This is one of three portfolio projects, all built around the shop:
1. **Shop Assistant**: an AI receptionist (done, public at github.com/zeinsaid/Shop-Assistant)
2. **Invoice automation**: this repo
3. A classical ML sales analysis/forecasting project (next)

This is the one project I actually want **deployed and used by staff** on the shop PC, not just demoed. A CV line like "cut invoice entry from X hours to Y per week" is the goal, so a working, reliable tool matters more than polish.

It's also my hands-on prep for the **Microsoft AI-103** exam (Azure AI Apps and Agents Developer Associate). I have AI-900 but no real Azure work experience. When we touch Azure (resources, keys, endpoints, SDK, pricing tiers, models), explain the concepts properly, as if to someone new to Azure.

## How I work (important)

- **You write the code; I own the design.** I don't want to type the code myself, but I want to understand every concept, decision and line. Explain things clearly, as if to someone new to the topic. Don't assume I already know a library or pattern.
- **Propose before deciding.** For anything architectural, lay out the reasoning and a recommendation, then let me confirm. I prefer one direct recommendation over a long list of options.
- **DECISIONS.md log.** Keep a numbered decision log (D-001, D-002, …). Whenever a decision is made, write out the **full entry ready to copy-paste** (context, decision, alternatives considered, reasoning), not just a description of it.
- I need to be able to explain every design choice in an interview without notes, so the "why" matters as much as the "what".
- Ask me about the shop's real workflow when you're unsure. I know details that aren't in the files.

## The project

**Old manual process:** supplier invoices arrive on paper. Staff open that supplier's Excel (PowerSoft's 20-column import format), type every quantity, delete the zero rows, and upload it to PowerSoft (our POS/stock system).

**What the tool does now (details and reasons in DECISIONS.md):**
- Staff put scans in `input/` and double-click **Process Invoices** (D-002).
- Each page is read with Azure Document Intelligence `prebuilt-layout` (D-003, D-021); responses are cached so a scan is never sent twice.
- A **supplier profile** per supplier reads its table and turns invoice units into selling pieces (D-005, D-020).
- Lines are matched to our items: learned mapping, then barcode, then name, then similar name (D-006); every line's arithmetic and every invoice total are checked (D-010).
- A **review window** asks staff yes/no and fill-in questions from the paper and the shelf; the PowerSoft Excel is only written, to `output/Ready to upload/`, once an invoice is cleared (D-022). Staff upload it themselves (D-001). "I'm not sure" sends it to me.
- Everything staff confirm is learned, so questions get fewer over time (D-018).

## What's in the folder

**Code** (`src/invoice_automation/`, read the module docstrings):
- `extract.py`: DI calls + cache · `layout.py`: tables, numbers, barcodes · `crops.py`: line pictures for the window
- `suppliers/`: one profile per supplier on the shared `base.py`
- `catalogue.py` (PowerSoft export), `supplier_items.py` (the learned table), `matching.py`
- `pipeline.py` (queue, evaluate -> questions, finalize -> Excel), `session.py`, `ui.py` (the window), `output.py`
- `tests/`: unit tests on synthetic data only. `scripts/`: one-off checks (DI model spike, layout survey).

**Real shop data**, all under `data/` (git-ignored, never commit it):
- `data/powersoft/`: PowerSoft is the source of truth for items (D-018).
  - `items_export_<date>.csv`: the latest item export, encoded cp1253. PowerSoft itself strips `& ' % ( )` from item names when it saves them, and stores costs to 2 decimals.
  - `categories.xlsx`, `suppliers.xlsx`: code tables. `MASTER_ITEM_LIST.xlsx`: every item in the import format, for reference.
- `data/reference/legacy_supplier_lists.xlsx`: each supplier's old wording and prices; seeds the supplier-items table.
- `data/samples/`: real invoices (one per supplier, plus older mixed scans). `data/eval/`: hand transcription of the Athenites sample.
- `data/cache/di/`: cached DI responses (keep: re-running costs no Azure pages).
- Created by running the tool (safe to wipe while testing): `data/supplier_items.xlsx`, `data/state/` (queue, new-item codes, processed invoices, price changes), `data/reports/`, `output/Ready to upload/`, `logs/`.
- `data/flag_items.csv`: items that always get a question (single/pack pairs).

**Docs:** `DECISIONS.md` (read it before proposing changes), `README.md`, `TODO.md` (where we left off).

## Constraints

- **Privacy:** the repo may go public as a portfolio piece. Real invoices, supplier Excels and prices must **not** be committed. Keep them in a git-ignored folder and use anonymised or synthetic samples for anything public. Never commit Azure keys; use a `.env` file.
- **Staff-friendly:** shop staff aren't technical. English only, short words, big buttons. Errors should be readable ("contact Zein"), with details in a log, never stack traces.
- **Runs on the Windows shop PC** with Deep Freeze: everything the tool keeps lives on the ThawSpace drive, never C: (D-016). I'm in Dubai and reach it over AnyDesk, so deployment and fixes must be simple.
- Python 3.12 with `uv`.
- **Azure:** my work Microsoft account, free trial subscription (billing country UAE), resource group `rg-invoice-automation`, Document Intelligence `di-theplug-invoices` on the free F0 tier in North Europe (West Europe refused new customers). Endpoint and key are in `.env`. Upgrade to pay-as-you-go before the trial ends (around 14 Nov 2026) or the resource stops.
- **Testing the window:** never screenshot the screen (it captures whatever else is open). Capture the window itself (PrintWindow) with it nearly transparent; see TODO.md.

## Start here

Read `TODO.md` for where we left off and what's next, then `DECISIONS.md`.
