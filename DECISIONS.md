# Decision Log

Numbered record of design decisions: what was decided, why, and what else was considered.

**Status values:** **Accepted** (agreed and in force) · **Proposed** (recommended, awaiting confirmation) · **Superseded by D-xxx**

| # | Decision | Status |
|---|---|---|
| D-001 | Local Excel generator; no PowerSoft API; staff review and upload manually | Accepted |
| D-002 | Double-click launcher with `input/` and `output/` folders; staff see only "Done" or "Contact Zein" | Accepted |
| D-003 | Azure Document Intelligence for extraction, not a vision LLM | Accepted |
| D-004 | Split every PDF into single pages before processing | Accepted |
| D-005 | Everything is stored per selling piece; invoice units are converted using supplier rules and known pack sizes | Proposed |
| D-006 | Matching order: learned mapping → barcode → fuzzy name → LLM suggestion (always flagged) | Proposed |
| D-007 | The per-supplier master Excels are the catalogue, and the tool keeps them up to date | Accepted |
| D-008 | One output Excel per invoice, in the exact PowerSoft import format, with zero-quantity rows removed | Proposed |
| D-009 | Cost rules: per piece, before VAT, after discounts; free goods averaged in; price changes flagged and logged | Accepted |
| D-010 | Check that each invoice's lines add up to its printed total | Accepted |
| D-011 | Flag, don't guess: colour-coded cells plus a run report | Proposed |
| D-012 | Unknown products become new item rows with the next item code; retail price left for a human | Accepted |
| D-013 | Out of scope: credit notes/returns, handwritten invoices, automatic upload | Accepted |
| D-014 | Real shop data stays local and git-ignored; anything public is synthetic | Accepted |
| D-015 | Supplier rollout order: Athenites first, then cigarette suppliers, then the rest | Accepted |
| D-016 | Python 3.12 + uv, src layout | Accepted |

---

## D-001: Local Excel generator; no PowerSoft API; staff review and upload manually

**Status:** Accepted · 2026-10-14

**Context.** Stock arrives with paper invoices. Today a staff member types each quantity into that supplier's Excel (the 20-column import format PowerSoft provides). They copy the file, delete the zero-quantity rows, and upload it to PowerSoft with the Excel import module. PowerSoft has an API that can read and edit items, but access goes through their sales team and they are slow to respond.

**Decision.** The tool reads scanned invoices and produces upload-ready Excel files. A person still reviews each file and uploads it to PowerSoft by hand. The tool never talks to PowerSoft.

**Alternatives considered.**
- *PowerSoft API (read the item list live, push stock in directly).* Cleaner long-term: no stale Excels, no manual upload. Rejected for now because it depends on a slow external vendor, may cost extra, and would block the whole project on their support. It stays the natural "phase 2".
- *Fully automatic upload (e.g. browser automation).* Rejected: it removes the human check, and a wrong quantity going straight into stock is the worst failure.

**Reasoning.** The Excel import already exists, works, and is what staff know. Producing that file removes about 95% of the manual work (reading and typing) with zero dependency on PowerSoft. The manual review is a cheap safety net, and the monthly stock count catches anything that slips through.

---

## D-002: Double-click launcher with `input/` and `output/` folders; staff see only "Done" or "Contact Zein"

**Status:** Accepted · 2026-10-14

**Context.** Staff are not technical and should not make decisions or fix problems. The shop PC runs Windows, has reliable internet, is restarted regularly, and may run Deep Freeze (which restores the disk to a snapshot on every restart).

**Decision.** A shop folder contains `input/`, `output/` and a double-click launcher (e.g. `Process Invoices`). Staff drop scans into `input/` and double-click. The tool processes everything and shows one pop-up:
- **"Done. Check the output folder."**, or
- **"Something went wrong. Please contact Zein."**

There are no options, menus or prompts. Technical detail (errors, what was flagged, timings) goes to a log file for Zein, never on screen. Processed scans are moved out of `input/` so nothing is processed twice.

**Alternatives considered.**
- *Background folder watcher / Windows service.* Rejected: it has to survive restarts and Deep Freeze, it fails silently when it isn't running, and staff can't tell whether it ran.
- *Small GUI with options.* Rejected: every option is a decision staff could get wrong.
- *Email/Telegram alerts to Zein on failure.* Deferred: staff already message Zein directly. It may be added later for log keeping.

**Reasoning.** A double-click is the most reliable trigger a non-technical user can perform, and it is obvious whether it ran. Keeping all decisions inside the tool or with Zein matches how the shop actually works.

---

## D-003: Azure Document Intelligence for extraction, not a vision LLM

**Status:** Accepted · 2026-10-14 (which DI model to use is still open, see below)

**Context.** The invoices are image-only scans (no text layer), skewed and slightly noisy, in Greek, English or both, with very different layouts per supplier. A wrong quantity is the worst possible error.

**Decision.** Use Azure AI Document Intelligence (DI) to read invoices: text, tables and fields, each with a confidence score. Language models are only allowed downstream to *suggest* product matches (D-006). They never read numbers off the page.

**Which DI model (open, to be decided by testing on the samples):**
- `prebuilt-invoice` returns structured fields (vendor, invoice ID, totals, line items) out of the box. It is weak on supplier-specific columns such as Cassandra's `FACT` or Vassos's case/fraction split.
- `prebuilt-layout` returns every table cell exactly as printed. Supplier rules (D-005) then interpret the columns.
- *Custom extraction model* is trained on our own labelled invoices. Likely the most accurate per supplier, but needs ~5+ labelled samples per layout.

My current expectation: start with `prebuilt-invoice` for supplier and totals, use `prebuilt-layout` tables for line items, and move to a custom model only for suppliers where that isn't good enough.

**Pricing tier facts (verified 2026-10-14, Microsoft Learn service limits + pricing page).** Free tier **F0**: 500 pages/month free; **only the first 2 pages of each request are analysed**; 4 MB max file; 1 request/second. At 10–50 invoices/week (roughly 50–250 pages/month) F0 should be enough. D-004 removes the 2-page problem.

**Alternatives considered.**
- *Vision LLM (GPT-4o / Claude) reads the whole invoice.* Very flexible with messy layouts, but it can misread or invent digits with no confidence score. Rejected for the numbers.
- *Local OCR (Tesseract).* Free and offline, but much worse on skewed Greek/English scans and has no table understanding.

**Reasoning.** DI gives per-value confidence, which makes "flag, don't guess" possible. It also handles tables well, and it is directly on the AI-103 exam syllabus.

---

## D-004: Split every PDF into single pages before processing

**Status:** Accepted · 2026-10-14

**Context.** Staff sometimes scan several invoices from different suppliers into one PDF (one of the samples contains Fereos, Andrikian and ED Sport). Some single invoices may run over two pages. The F0 tier only analyses the first 2 pages of a request.

**Decision.** Every PDF is split into single pages locally first. Each page is analysed separately and assigned a supplier. Consecutive pages are then merged back into one invoice when they belong together (same supplier and same invoice number, or a page with no header that follows a page with no totals).

**Alternatives considered.**
- *Require one invoice per PDF.* Staff will be asked to do this, but the tool shouldn't rely on it.
- *Send whole PDFs to DI.* Breaks on mixed PDFs and on the F0 2-page cap.

**Reasoning.** The page is the only unit that is reliably "one supplier". Splitting costs nothing (it happens locally) and handles mixed scans and the free-tier limit in one go.

---

## D-005: Everything is stored per selling piece; invoice units are converted using supplier rules and known pack sizes

**Status:** Proposed · 2026-10-14 (the requirement is agreed; the mechanism awaits confirmation once we have more invoice samples)

**Context.** PowerSoft quantity and cost are always per *selling piece*: whatever is scanned at the till (one cigarette pack, one Kinder Happy Hippo 10-pack, one 500 ml water). Invoices use different units:
- Cassandra: `FACT 10 × QTY 6` = 60 packs; price is per carton (39.37 → 3.937/pack).
- Vassos: cases plus a loose "fraction"; the NET PRICE column is already per piece.
- Andrikian: `QTY × U.O.M.` (1 × 6 = 6); price is per pack, after a 10% discount, ÷ U.O.M.
- Fereos, Pambos: already per piece.
- Some suppliers print nothing at all (e.g. "Hell energy 24-pack, qty 1").

**Decision.** Use two layers of knowledge:
1. **Supplier profile** (one small config per supplier): which column holds quantity, pack factor, price, whether the price is per pack or per piece, and any invoice-wide discount.
2. **Pack-size table** (per item, learned): "this invoice line = N selling pieces". Filled from the invoice when it prints the factor, otherwise confirmed once by Zein and remembered.

If a factor can't be determined, the line is **flagged, never guessed**.

**Alternatives considered.**
- *Infer pack sizes from the product name ("24X41.5G", "×25").* Useful as a *hint* for a suggestion, but names are inconsistent ("12X3c" means 12 boxes of 3). Never trusted on its own.
- *One generic rule for all suppliers.* The samples already show four incompatible conventions.

**Reasoning.** Unit conversion is the main source of silent quantity errors (1 instead of 24). Making it explicit per supplier and per item turns it into data that can be checked and grows over time, instead of logic hidden in code.

---

## D-006: Matching order: learned mapping → barcode → fuzzy name → LLM suggestion (always flagged)

**Status:** Proposed · 2026-10-14 (barcode-first with fuzzy fallback is agreed; the full order awaits confirmation)

**Context.** Invoice names never exactly match our item names. A check of the samples found barcodes on 5 of 6 suppliers. 32 of 34 non-Cassandra invoice barcodes match our Excel exactly. Cassandra prints **carton** barcodes (0 of 25 match), because our system stores the barcode of the individual piece.

**Decision.** For each invoice line, in order:
1. **Learned mapping**: (supplier, supplier's code or barcode) → our Item Code, built from previously confirmed matches. This also fixes carton barcodes after the first confirmation.
2. **Barcode**: exact match against column D across all masters.
3. **Fuzzy name match** (e.g. RapidFuzz), first within that supplier's file, then the whole catalogue, with a strict score threshold.
4. **LLM suggestion** for leftovers.

Only steps 1–2 are trusted automatically. Results from steps 3–4 are written to the output but **flagged** for review until they are confirmed into the mapping. Athenites uses stricter thresholds (D-015).

**Alternatives considered.**
- *Name matching only.* Misses the free, near-perfect barcode signal.
- *LLM first.* Slower, costs money, and can't explain its choices. Better kept as the last resort.

**Reasoning.** The cheapest, most certain signal goes first. The mapping file means each supplier/product pair only needs a human once.

---

## D-007: The per-supplier master Excels are the catalogue, and the tool keeps them up to date

**Status:** Accepted · 2026-10-14

**Context.** There is one master Excel per supplier (zero quantities) with ~1,400 items in total. The Item Code is PowerSoft's permanent unique ID: never reused, never changed. Barcode, name, cost, supplier and price can change. The same Item Code may appear in several supplier files (e.g. Orbit in Athenites and Andrikian) and that is fine: a quantity upload only uses Item Code, cost and quantity. Each item has one "home" supplier in PowerSoft, which doesn't matter for stock.

**Decision.**
- `data/masters/<Supplier>.xlsx` is the source of truth. The tool loads all of them into one in-memory catalogue keyed by Item Code.
- The tool **writes back** to the masters:
  - cost changes (D-009)
  - new items (D-012)
  - an item bought from a supplier whose file doesn't list it: the row is copied into that supplier's master with the same Item Code
- Masters always keep quantity 0. Masters are backed up before every write.

**Open question.** If Deep Freeze is active, every write to the masters (and the mapping file) is lost on restart. Storage must be on a thawed drive or synced folder. To be confirmed.

**Reasoning.** It matches the current manual process and keeps the files Zein already knows as the single truth. Write-back is what stops a new item or price change from being "new" again next week.

---

## D-008: One output Excel per invoice, in the exact PowerSoft import format, with zero-quantity rows removed

**Status:** Proposed · 2026-10-14

**Context.** PowerSoft rejects rows with quantity 0. It doesn't care about row order, formulas or file names. When uploading, it asks which supplier and which invoice number the upload belongs to.

**Decision.** Each invoice produces one file, `output/<Supplier> <InvoiceNo> <Date>.xlsx`. It is a copy of that supplier's master, with quantities and costs filled in, zero-quantity rows deleted, and the original 20 columns and order unchanged.

**Alternatives considered.**
- *One file per supplier per run (merge same-day invoices).* PowerSoft allows it, but it breaks the one-to-one link between paper and file that staff use to check their work and that the invoice-total check (D-010) relies on.
- *One combined Excel for all invoices.* Desirable later (one upload per run), but needs per-row supplier and invoice number support in PowerSoft. Zein is checking. Revisit before the end of the project.

**Reasoning.** One paper invoice → one file → one upload is the easiest flow for staff to check, and it keeps supplier spend attributable in PowerSoft.

---

## D-009: Cost rules: per piece, before VAT, after discounts; free goods averaged in; price changes flagged and logged

**Status:** Accepted · 2026-10-14

**Context.** Column H (Unit Price excl. VAT) has not been kept up to date because checking every price by hand is slow, and some suppliers have quietly raised prices.

**Decision.**
- **Cost = per selling piece, excluding VAT, after all discounts.** That includes line discounts and supplier-wide discounts (e.g. ED Sport 10%, Andrikian 10%), which are stored in the supplier profile (D-005).
- **Free goods** (e.g. Andrikian "buy 2 get 1" lines with no price): add the free quantity to the item's total. Cost = total paid ÷ total pieces received, so the discount is spread over every piece.
- **Price change** (new cost ≠ master cost beyond rounding):
  - the output gets the new cost and the cell is highlighted
  - the change is written to a price-change report (item, old → new, % change, invoice)
  - the master is updated
- **Which column PowerSoft reads** (H "Unit Price" vs K "Last Unit Price", currently `=H`) is still being checked by Zein. Until then both are written with the new cost.

**Reasoning.** Up-to-date costs are a free by-product once the invoice is read anyway. The report turns silent supplier price rises into something visible.

---

## D-010: Check that each invoice's lines add up to its printed total

**Status:** Accepted · 2026-10-14

**Decision.** For each invoice, recompute Σ(quantity × price − discounts) and compare it with the printed net or total (allowing for VAT and rounding). If they differ beyond a small tolerance, the whole invoice is flagged. A mismatch usually means a misread digit, a missed line, a wrong pack factor, or a discount the supplier forgot to apply (as on the latest ED Sport invoice).

**Reasoning.** It is an independent check that is almost free and catches exactly the errors that are otherwise silent: a missed row or a misread quantity.

---

## D-011: Flag, don't guess: colour-coded cells plus a run report

**Status:** Proposed · 2026-10-14

**Decision.**
- **Yellow:** check against the paper. Low DI confidence, or a fuzzy/LLM match.
- **Orange:** cost changed (D-009).
- **Red:** do not upload; contact Zein. Unmatched product, new item missing a retail price, unknown pack factor, or invoice total mismatch.

Each run also writes a short report (Excel or text) listing every flag in plain language. A clean file has no colours.

**Alternatives considered.**
- *Separate "review" sheet only.* Rejected: staff look at the main sheet, so the flag must be on the cell itself.

**Reasoning.** Staff aren't expected to fix anything, only to recognise "red = call Zein", "yellow/orange = compare with the paper". Open: PowerSoft must accept files that carry cell colours (very likely; formatting isn't data). To be checked on the first test upload.

---

## D-012: Unknown products become new item rows with the next item code; retail price left for a human

**Status:** Accepted · 2026-10-14

**Context.** New products are created in PowerSoft by uploading an Excel row with a new Item Code. Codes are assigned sequentially; the current highest across all masters is **1421** (to be confirmed by Zein). On upload, PowerSoft only reads new codes, unless "modify items" is ticked, which overwrites existing items. The tool must therefore never require that tick.

**Decision.** When an invoice line matches nothing (after D-006):
- create a full row with Item Code = highest known + 1, filled from the invoice (description, barcode, supplier code/name, cost, VAT %)
- leave **Retail price empty and red**
- add the row to the supplier's master so the item isn't "new" again next time

**Open questions.**
- Can new-item rows go in the same upload as the quantity rows, or do they need a separate file?
- Should the master be updated immediately, or only once the upload is confirmed? (If staff never upload, the master claims an item that PowerSoft doesn't have.)

**Reasoning.** It mirrors exactly what Zein does by hand. Leaving the retail price to a human keeps pricing decisions out of the tool.

---

## D-013: Out of scope: credit notes/returns, handwritten invoices, automatic upload

**Status:** Accepted · 2026-10-14

**Decision.** The tool does not handle:
- credit notes/returns (staff handle them directly)
- handwritten invoices (currently only ED Sport, which is rare)
- PowerSoft upload or API (D-001)

When it recognises one of these, it skips the page and says so in the report instead of failing.

**Reasoning.** Each one adds a lot of complexity for very little volume. Excluding them keeps the core reliable.

---

## D-014: Real shop data stays local and git-ignored; anything public is synthetic

**Status:** Accepted · 2026-10-14

**Decision.**
- All real data lives under `data/`, which is git-ignored:
  - `masters/`: supplier Excels
  - `samples/`: real invoices
  - `reference/`: UPSTAIRS, which is never ordered
  - later: mappings and logs
- `input/` and `output/` contents are git-ignored too.
- Azure keys live in `.env` (git-ignored); `.env.example` is the committed template.
- Anything shown publicly (README, tests, demo) uses anonymised or synthetic invoices and Excels.
- The GitHub repo starts private.

**Reasoning.** The repo is meant to become a public portfolio piece. Supplier prices and invoices are commercially sensitive.

---

## D-015: Supplier rollout order: Athenites first, then cigarette suppliers, then the rest

**Status:** Accepted · 2026-10-14

**Context.** Athenites is the biggest and most frequent supplier (cheaper than buying direct). The cigarette suppliers (Cassandra, Cosmos, Fereos) are next by volume. 99% accuracy elsewhere is acceptable if Athenites is 100%.

**Decision.** Supplier profiles, tests and accuracy work are prioritised in that order. Athenites gets the strictest settings: higher match thresholds, and anything below "certain" is flagged.

**Note.** There is currently **no Athenites sample invoice**. Collecting several is the first blocker for real testing.

---

## D-016: Python 3.12 + uv, src layout

**Status:** Accepted · 2026-10-14

**Decision.** Python 3.12, with dependencies managed by `uv` (as in Shop Assistant) and code in `src/invoice_automation/`. Expected libraries:
- `openpyxl`: read and write Excel while keeping formatting
- `pymupdf`: split PDFs and render pages
- `azure-ai-documentintelligence`: the official DI SDK
- `rapidfuzz`: fuzzy matching

How it gets onto the shop PC (bundled `.exe` vs. uv + launcher script) is decided once Deep Freeze is clarified.
