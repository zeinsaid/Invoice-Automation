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

## The project (starting point, open to refinement)

**Current manual process:** Supplier invoices arrive (scanned/PDF). Staff open that supplier's prepared Excel (one per supplier, listing all their products), type in the quantities, then upload the Excel to our POS/inventory system (PowerSoft).

**Target workflow (keep it lightweight):**
- A script runs locally on the shop PC with two folders: `input/` and `output/`.
- Staff drop scanned invoices into `input/`.
- The script reads each invoice, works out the supplier, fills in that supplier's Excel (mainly the quantity column), and writes it to `output/`.
- Staff **review** the output Excel, then upload it to PowerSoft themselves. This manual check is intentional; we're not automating the upload or using the PowerSoft API.
- Output must keep the **exact format** of the existing supplier Excels so it still imports cleanly.

**Direction already discussed (to confirm with me):**
- **Azure Document Intelligence (prebuilt invoice model)** for extraction rather than a pure vision LLM, because LLMs can misread or invent digits and a wrong quantity is the worst error. It also returns confidence scores. Volume is roughly 10–50 invoices a week, so the free tier should cover it (verify current limits).
- **Product matching is the hard part:** invoice product names won't match our Excel/PowerSoft names exactly. Plan: fuzzy matching first, an LLM only for the leftovers, and a mapping file of confirmed matches that grows over time.
- **Flag, don't guess:** highlight low-confidence values or unmatched products (e.g. yellow cells) so staff check them.
- I'll explain more challenges directly in chat.

## What's in the folder

All real shop data is under `data/` (git-ignored, never commit it):
- `data/powersoft/`: PowerSoft is the source of truth for items (D-018).
  - `items_export_<date>.csv`: the latest item export, encoded cp1253. PowerSoft itself strips `& ' % ( )` from item names when it saves them, and stores costs to 2 decimals.
  - `categories.xlsx`, `suppliers.xlsx`: code tables.
  - `MASTER_ITEM_LIST.xlsx`: every item in the 20-column import format, for reference.
- `data/reference/legacy_supplier_lists.xlsx`: which items each supplier sold us, at what price, under what name. Extracted from the old per-supplier Excels (now deleted); seed data for the supplier-items table.
- `data/samples/`: real past invoices (image-only scans, some with several suppliers merged in one PDF). Use them to judge layouts, variations and edge cases.
- Shop PC: everything the tool writes (masters, mappings, logs, input/output) lives on the Deep Freeze ThawSpace drive, never on C: (D-016).
- There's no separate "expected output" file. The expected output is the same supplier Excel with the quantity column (and anything else I specify) filled in correctly.
- `DECISIONS.md` holds the decision log. Read it before proposing changes.

## Constraints

- **Privacy:** the repo may go public as a portfolio piece. Real invoices, supplier Excels and prices must **not** be committed. Keep them in a git-ignored folder and use anonymised or synthetic samples for anything public. Never commit Azure keys; use a `.env` file.
- **Staff-friendly:** shop staff aren't technical. Running it should be close to "drop the file in, open the result". Errors should be readable, not stack traces.
- **Runs on a Windows shop PC** (confirm with me), so keep setup simple and document it in the README.
- Python preferred (I used `uv` for my last project).

## First steps

1. Look through the supplier Excels and sample invoices, then summarise what you see: suppliers, layouts, how product names differ, and anything that looks tricky.
2. Ask me the questions you need answered about the real workflow.
3. Propose the architecture and the first DECISIONS.md entries for me to confirm.
