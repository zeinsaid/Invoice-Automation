# Decision Log

Numbered record of design decisions: what was decided, why, and what else was considered.

**Status values:** **Accepted** (agreed and in force) · **Proposed** (recommended, awaiting confirmation) · **Superseded by D-xxx**

| # | Decision | Status |
|---|---|---|
| D-001 | Local Excel generator; no PowerSoft API; staff review and upload manually | Accepted |
| D-002 | Double-click launcher with `input/` and `output/` folders; staff see only "Done" or "Contact Zein" | Accepted |
| D-003 | Azure Document Intelligence for extraction, not a vision LLM | Accepted |
| D-004 | Split every PDF into single pages before processing | Accepted |
| D-005 | Everything is stored per selling piece; invoice units are converted using supplier rules and known pack sizes | Accepted |
| D-006 | Matching order: learned mapping → barcode → fuzzy name; leftovers are asked; confirmed matches feed the mapping (LLM step dropped 2026-10-16) | Accepted, amended |
| D-007 | The per-supplier master Excels are the catalogue, and the tool keeps them up to date | Superseded by D-018 |
| D-008 | One output Excel per invoice, in the exact PowerSoft import format, with zero-quantity rows removed | Accepted |
| D-009 | Cost rules: per piece, before VAT, after discounts; free goods averaged in; price changes flagged and logged | Accepted |
| D-010 | Check that each invoice's lines add up to its printed total | Accepted |
| D-011 | Flag, don't guess: colour-coded cells plus a run report; new items are always red | Accepted |
| D-012 | Unknown products become new item rows with the next item code; retail price left for a human | Accepted |
| D-013 | Out of scope: handwritten invoices (ED Sport, Aristidou), automatic upload; every input PDF is treated as an invoice | Accepted (amended 2026-10-15) |
| D-014 | Real shop data stays local and git-ignored; anything public is synthetic | Accepted |
| D-015 | Supplier rollout order: Athenites first, then cigarette suppliers, then the rest | Accepted |
| D-016 | Python 3.12 + uv, src layout; runs from the Deep Freeze ThawSpace drive | Accepted |
| D-017 | Two-stage output: `To Check` → `Uploaded`; masters and mappings only change once a file is marked uploaded | Rejected |
| D-018 | The PowerSoft item export is the catalogue; one supplier-items table replaces the 23 masters; no approval step | Accepted |
| D-019 | One-off PowerSoft cleanup via a reviewed "modify items" upload, before building the tool | Accepted |
| D-020 | Athenites profile: barcode = purchase unit, VAT-inclusive amounts, pack factor learned per barcode | Accepted |
| D-021 | Use `prebuilt-layout` only; the supplier profile interprets the table | Accepted (amended 2026-10-15) |
| D-022 | Review window: staff answer questions from the paper and the shelf; the Excel is only written once an invoice is cleared | Accepted |
| D-023 | Deployment: uv + launchers on the ThawSpace drive; code and data in separate folders; one-click update with automatic rollback; data safety and automatic checks | Accepted |

---

## D-001: Local Excel generator; no PowerSoft API; staff review and upload manually

**Status:** Accepted · 2026-10-14

**Context.** Stock arrives with paper invoices. Today a staff member types each quantity into that supplier's Excel (the 20-column import format PowerSoft provides). They copy the file, delete the zero-quantity rows, and upload it to PowerSoft with the Excel import module. PowerSoft has an API that can read and edit items, but access goes through their sales team and they are slow to respond.

**Decision.** The tool reads scanned invoices and produces upload-ready Excel files. A person still reviews each file and uploads it to PowerSoft by hand. The tool never talks to PowerSoft.

**Alternatives considered.**
- *PowerSoft API (read the item list live, push stock in directly).* Cleaner long-term: no stale Excels, no manual upload. Rejected for now because it depends on a slow external vendor, may cost extra, and would block the whole project on their support. It stays the natural "phase 2".
- *Fully automatic upload (e.g. browser automation).* Rejected: it removes the human check, and a wrong quantity going straight into stock is the worst failure.

**Reasoning.** The Excel import already exists, works, and is what staff know. Producing that file removes about 95% of the manual work (reading and typing) with zero dependency on PowerSoft. The manual review is a cheap safety net, and the monthly stock count catches anything that slips through.

**Amendment (2026-10-19): the PowerSoft API is dropped for good, not deferred.** PowerSoft quoted about €2,000 up front plus about €40 a month, roughly €10,000 over the life of the system, to save staff one manual upload per invoice. That is not worth it. The "phase 2" above is withdrawn. Consequences: the item list stays a periodic export (D-018), and the rule from D-012 stays permanent: once the tool is live, staff never create items by hand in PowerSoft, so the tool's next item code can't clash with a hand-made one.

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

**Update (2026-10-15):** the single "Done / Contact Zein" pop-up became the review window of D-022, which asks staff questions they can answer from the paper. Staff now resolve most issues themselves; only "I'm not sure" and tool failures reach Zein. Processed scans move to `processed/<date>/`.

---

## D-003: Azure Document Intelligence for extraction, not a vision LLM

**Status:** Accepted · 2026-10-14 (the model question below was resolved by D-021: `prebuilt-layout` only)

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
- *Keep PDFs whole and only split when longer than 2 pages* (Zein was fine with either). Rejected: a 2-page PDF can still hold two suppliers, so per-page supplier detection is needed regardless. Splitting costs nothing extra, because DI bills per page either way.

**Reasoning.** The page is the only unit that is reliably "one supplier". Splitting costs nothing (it happens locally) and handles mixed scans and the free-tier limit in one go. Invoices longer than 2 pages are rare (big Athenites bulk orders), but they are handled by the same path.

**Amendment (2026-10-15): how pages are grouped.** A PDF is read first, then split into invoices:
- A page joins the invoice before it if the same supplier is recognised and the invoice numbers don't differ (a continuation page may not print the number).
- **A page no supplier recognises also joins the invoice before it** (Zein: page 2 almost always follows page 1). Two exceptions:
  - a page from a known enter-by-hand supplier (ED Sport, Aristidou, Asian Food Market) always stands alone, so it is still listed as "enter by hand";
  - if the joined page gives the invoice nothing (no lines, no total), staff get one yes/no question: "Is page N part of this invoice?". No = it stands alone and is entered by hand.

  The first rule is built. The join-and-confirm part is deferred (amendment below).
- Staff will normally scan one invoice per PDF, so this mostly matters when several invoices are scanned together.

**Amendment (2026-10-16): the unrecognised-page rule is deferred.** The full Athenites scan showed that page 2 repeats the supplier name and invoice number, so it joins page 1 under the first rule. Page 2's table has no header row and merged cells, so it is read by position: the number columns on the right keep their place, and the cells to their left are split into description and barcode. The rule for a page no supplier recognises (join the previous invoice, ask "Is page N part of this invoice?") is not built. *Why:* no sample needs it, and suppliers generally repeat their name or the invoice number on later pages. Agrotis (stationery, less than once a month) is the only candidate, and there staff typing the total from the paper is enough. Until then, an unrecognised page stands alone and is listed as "enter by hand". *Revisit* if the report shows real continuation pages listed that way.

---

## D-005: Everything is stored per selling piece; invoice units are converted using supplier rules and known pack sizes

**Status:** Accepted · 2026-10-14 (Zein supplies the rules per supplier as samples come in)

**Context.** PowerSoft quantity and cost are always per *selling piece*: whatever is scanned at the till (one cigarette pack, one Kinder Happy Hippo 10-pack, one 500 ml water). Invoices use different units:
- Cassandra: `FACT 10 × QTY 6` = 60 packs; price is per carton (e.g. 40.00 → 4.000/pack).
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

**Known risk (deferred).** Supplier conventions can drift. For example, the same Hell energy drink might be billed as one 24-pack on one invoice and as 24 cans on another. Mitigations to design later: compare the converted line against the printed line total (D-010), and flag a line when its implied per-piece cost is far from the master cost.

**Amendment (2026-10-15): printed pack sizes are checked by price.** When an invoice prints a pack size (Andrikian U.O.M., Agrotis UOM), it is used only if the price confirms it:
- If the price matches a single piece, our item *is* the pack, so the size is 1.
- If the price disagrees with the printed size, staff are asked, with the printed size suggested.

Cassandra's FACT is trusted outright, because cigarettes are always sold per pack. *Why:* Andrikian prints the single item's barcode but sells boxes, so without this check a matched barcode meant "1 box = 1 lighter". The same price check absorbs suppliers that print a piece unit on some lines and a pack unit on others.

**Amendment (2026-10-15): quantities always go to the storable item.** Some products exist in PowerSoft both as a single piece and as a pack (water 6-packs, beer 8-packs). The pack is set up as a **non-storable sub-item** that deducts from the single piece's stock when sold. The tool therefore always outputs the **storable** item, and never a non-storable one. A product bought as a pack is converted to pieces of the storable item. Items that exist as both single and pack but are *both* storable (e.g. Kinder Delice 177 bar / 1399 box) are a set-up problem. Zein is resolving them with staff (disable one, or make the pack a sub-item). Until then, the tool flags any line that matches either one of such a pair.

**Amendment (2026-10-19): packs are linked to their single piece by name, so staff aren't asked.**
*Context.* Until now, a line that matched a non-storable pack (by its barcode or its name) asked staff once: "Which single item is this?" Zein will add more packs (Kinder, 7-Up, Hell). PowerSoft has no export of sub-item links, only one item at a time. But every pack is already named like its single piece plus " xN" (KYKKOS WATER 500ML X12 → KYKKOS WATER 500ML).

*Decision.* When the export loads, each non-storable item named "<name> xN" (N ≥ 2) is linked to a storable single item:
1. **Same name** (after the usual name clean-up): linked.
2. Otherwise the **most similar name**, if it scores at least 85/100, beats the next item by at least 5 points, and contains every number in the pack's name. This covers a missing word (AQUA 500ML x12 → AQUA WATER 500ML) and a typo (Kidder → Kinder). The number rule stops 1.5 L from linking to 500 ML.
3. **Anything unclear is not linked.** For example, "7UP CAN x6" fits 7UP CAN and 7UP ZERO CAN equally well. Staff are then asked once, as before.

A line that matches a linked pack goes in as the single item, N pieces per invoice unit. N is checked by price like every pack size (D-020). If the price disagrees, staff are asked with N suggested. If there is no known cost to compare with, N is used. The result is learned like any confirmed answer and listed in Zein's report.

`uv run invoice-automation --packs` lists every link, marks near-name links "check it", and lists the packs it couldn't link. Zein runs it after loading a new export. Naming rule for new packs: **the single item's exact name + " xN"**.

*Alternatives considered.*
- A hand-kept list of pack links: rejected, because it is one more thing to keep in step with PowerSoft. The names already carry the link.
- Keep asking staff once per pack: works, but each new pack costs a question and relies on staff choosing the right single.
- A loose fuzzy match without the margin and number rules: rejected. A wrong link silently books the wrong item, which is worse than a question.

*Why.* PowerSoft already holds the link in the name, so reading it there means nothing to maintain. Strict rules plus the price check mean a wrong link is very unlikely to go unnoticed, and the `--packs` list lets Zein see every link at a glance.

---

## D-006: Matching order: learned mapping → barcode → fuzzy name → ask staff (LLM step dropped)

**Status:** Accepted · 2026-10-14

**Context.** Invoice names never exactly match our item names. A check of the samples found barcodes on 5 of 6 suppliers. 32 of 34 non-Cassandra invoice barcodes match our Excel exactly. Cassandra prints **carton** barcodes (0 of 25 match), because our system stores the barcode of the individual piece.

**Decision.** For each invoice line, in order:
1. **Learned mapping**: (supplier, supplier's code or barcode) → our Item Code, built from previously confirmed matches. This also fixes carton barcodes after the first confirmation.
2. **Barcode**: exact match against column D across all masters.
3. **Fuzzy name match** (e.g. RapidFuzz), first within that supplier's file, then the whole catalogue, with a strict score threshold.
4. **LLM suggestion** for leftovers.

Only steps 1–2 are trusted automatically. Results from steps 3–4 are written to the output but **flagged** for review until they are confirmed into the mapping. Athenites uses stricter thresholds (D-015).

**The mapping learns from every confirmed match.** A barcode match is written into the mapping straight away. A fuzzy or LLM match is stored as *provisional* and promoted to trusted under the rules in D-018. Over time, almost every line should resolve at step 1.

**Alternatives considered.**
- *Name matching only.* Misses the free, near-perfect barcode signal.
- *LLM first.* Slower, costs money, and can't explain its choices. Better kept as the last resort.

**Reasoning.** The cheapest, most certain signal goes first. The mapping file means each supplier/product pair only needs a human once.

**Barcode normalisation (2026-10-15).** Before comparing, barcodes are stripped of spaces and line breaks (Cosmos wraps 13-digit barcodes across two lines inside a cell) and of a trailing `-n`. Cosmos prints 8-digit barcodes as e.g. `40331423-n`; with the suffix removed, all 11 lines on the sample match PowerSoft exactly.

**Supplier wording vs PowerSoft wording.** When a barcode matches but the supplier's name differs (Athenites "DORITOS THAI SRIRACHA 90GR" = PowerSoft "DORITOS F1 Drive Mode 90G"; the pack says F1 Drive Mode), the supplier's wording is stored in the supplier-items table. No catalogue change is needed.

**Amendment (2026-10-15): supplier item codes are learning keys.** Besides barcodes, the tool learns each supplier's own item code (Pambos `CRYSTALVAPE14`, Jumbo `1171628`, Vassos new code), stored in the supplier-items table next to our Item Code. *Why:* codes stay on their row even when long descriptions spill into the next one (Pambos), and they work where names are Greek abbreviations that won't match ours (Jumbo). Not every supplier prints codes, which is why our own Item Codes can't simply be the suppliers' codes. The PowerSoft export is not edited (D-018): the link between supplier codes and our codes lives only in the supplier-items table.

**Amendment (2026-10-16): the LLM step is dropped.** Matching is learned mapping → barcode/supplier code → fuzzy name; anything left is asked of staff, and the answer is learned (D-018). *Why:* (1) an LLM match would always be flagged, so it can't save a question, only improve the suggestion; (2) on the full Athenites sample, every unmatched line (5 of 76) was a product we don't stock, which no matcher can find; (3) misses are one-off, because the confirmed answer becomes a learned mapping; (4) it would add an Azure OpenAI resource, a per-call cost, non-deterministic results and another failure point to a tool that has to run unattended. The same goes for the suggested category of a new item (D-012): it is taken from the most similar existing item. *Alternative considered:* keep it as a suggestion source for Greek or abbreviated names; supplier codes as learning keys already cover those. *Revisit* if the reports show many "not found" questions for items that do exist under very different wording.

---

## D-007: The per-supplier master Excels are the catalogue, and the tool keeps them up to date

**Status:** Superseded by D-018 · 2026-10-14

**Context.** There is one master Excel per supplier (zero quantities) with ~1,400 items in total. The Item Code is PowerSoft's permanent unique ID: never reused, never changed. Barcode, name, cost, supplier and price can change. The same Item Code may appear in several supplier files (e.g. Orbit in Athenites and Andrikian) and that is fine: a quantity upload only uses Item Code, cost and quantity. Each item has one "home" supplier in PowerSoft, which doesn't matter for stock.

**Decision.**
- `data/masters/<Supplier>.xlsx` is the source of truth. The tool loads all of them into one in-memory catalogue keyed by Item Code.
- The tool **writes back** to the masters:
  - cost changes (D-009)
  - new items (D-012)
  - an item bought from a supplier whose file doesn't list it: the row is copied into that supplier's master with the same Item Code
- Masters always keep quantity 0. Masters are backed up before every write.

**Storage.** The masters live on the shop PC's Deep Freeze ThawSpace drive, which keeps changes across restarts (D-016). (D-017's approval-gated write-back was rejected; see D-018.)

**Reasoning.** It matches the current manual process and keeps the files Zein already knows as the single truth. Write-back is what stops a new item or price change from being "new" again next week.

---

## D-008: One output Excel per invoice, in the exact PowerSoft import format, with zero-quantity rows removed

**Status:** Accepted · 2026-10-14

**Context.** PowerSoft rejects rows with quantity 0. It doesn't care about row order, formulas or file names. When uploading, it asks which supplier and which invoice number the upload belongs to.

**Decision.** Each invoice produces one file, `output/<Supplier> <InvoiceNo> <Date>.xlsx`. It is a copy of that supplier's master, with quantities and costs filled in, zero-quantity rows deleted, and the original 20 columns and order unchanged.

**Alternatives considered.**
- *One file per supplier per run (merge same-day invoices).* PowerSoft allows it, but it breaks the one-to-one link between paper and file that staff use to check their work and that the invoice-total check (D-010) relies on.
- *One combined Excel for all invoices.* Desirable later (one upload per run), but needs per-row supplier and invoice number support in PowerSoft. Zein is checking. Revisit before the end of the project.

**Reasoning.** One paper invoice → one file → one upload is the easiest flow for staff to check, and it keeps supplier spend attributable in PowerSoft. Multiple invoices from one supplier on the same day are rare; mostly it is Athenites, when there are morning and afternoon runs. Zein used to merge those only to save time, and the tool removes that need.

**Totals live in the report, not the upload file.** A "total" row in the Excel would look like an item row with no Item Code, and that could break the import. The run report shows each file's computed total next to the invoice's printed total instead.

**Update (2026-10-15):** files are written to `output/Ready to upload/`, and only once every review question on the invoice is answered (D-022). File name: `<Supplier> <InvoiceNo> <Date>.xlsx`.

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
- **Which column PowerSoft reads (confirmed).** The quantity upload reads only field 1 (B, Item Code), field 5 (F, Quantity), field 7 (**H, Unit Price excl. VAT**) and field 9 (J, Line Discount %, always 0). K ("Last Unit Price") is not read, so the tool writes the cost to H only. It is not yet known whether this upload also updates the item's stored cost in PowerSoft. A one-item test is needed; if it doesn't, cost updates need an "Upload Items" pass with "modify" ticked.
- **Costs are per supplier.** The same item can cost different amounts from different suppliers (e.g. the same chewing gum at 2.50 from one supplier and 3.10 from another). So a "price change" means a change versus *that supplier's* last price, not versus PowerSoft's single cost (see D-018).

**Reasoning.** Up-to-date costs are a free by-product once the invoice is read anyway. The report turns silent supplier price rises into something visible.

---

## D-010: Check that each invoice's lines add up to its printed total

**Status:** Accepted · 2026-10-14

**Decision.** For each invoice, recompute Σ(quantity × price − discounts) and compare it with the printed net or total (allowing for VAT and rounding). If they differ beyond a small tolerance, the whole invoice is flagged. A mismatch usually means a misread digit, a missed line, a wrong pack factor, or a discount the supplier forgot to apply (as on the latest ED Sport invoice).

**Reasoning.** It is an independent check that is almost free and catches exactly the errors that are otherwise silent: a missed row or a misread quantity.

**Amendment (2026-10-15): missing total = possibly missing page.** The tool always computes the total itself from the lines. If no printed total is found (e.g. page 2 of a long Athenites invoice was not scanned, as on the first sample), the invoice is flagged **red**: "Total not found. Were all pages scanned?". Page 2 may hold more lines, so the file may be incomplete.

**Amendment (2026-10-15): every line is checked too.** Where the invoice prints quantity, unit price and line amount, the tool checks quantity × price (+ discount) = line amount, allowing 2 cents for printed rounding. A mismatch flags that line **yellow** ("check against the paper"). This catches a misread quantity on the exact line, even when the invoice total is missing (a page wasn't scanned) or two errors cancel out in the total. Every sample supplier prints all three numbers.

---

## D-011: Flag, don't guess: colour-coded cells plus a run report; new items are always red

**Status:** Accepted · 2026-10-14

**Decision.**
- **Yellow:** check against the paper. Low DI confidence, or a fuzzy match.
- **Orange:** cost changed (D-009).
- **Red:** do not upload; contact Zein. Unmatched product, **any new item** (even with a retail price filled in), unknown pack factor, or invoice total mismatch.

**Why new items are always red.** Item Codes are permanent (D-007). If the tool wrongly decides an existing product is "new", uploading it creates a duplicate item that can never be deleted, only repurposed. A human must confirm every new item before it reaches PowerSoft.

Each run also writes a short report (Excel or text) listing every flag in plain language. A clean file has no colours.

**Alternatives considered.**
- *Separate "review" sheet only.* Rejected: staff look at the main sheet, so the flag must be on the cell itself.

**Reasoning.** Staff aren't expected to fix anything, only to recognise "red = call Zein", "yellow/orange = compare with the paper". PowerSoft accepts files with coloured cells (confirmed by Zein 2026-10-15: highlighted files have been uploaded before). Cell comments (hover notes) are still to be checked on the first test upload.

**Update (2026-10-15):** D-022 turned flags into questions. Yellow and red issues are now asked in the review window before any Excel exists, so an uploadable file normally has no yellow or red. Orange (cost changed) stays as a cell colour with a comment, and every flag still appears in Zein's run report (`data/reports/`).

**Amendment (2026-10-19): new items are red again.** The D-022 rework (flags become questions) dropped this by accident: an uploadable file had no red at all. Zein noticed it in the final test. A new item issued on this invoice now has its whole row red, with the comment "NEW item: check the name, barcode, price, category and brand before uploading". *Why:* a new item is the one row that creates something in PowerSoft rather than adding stock, so whoever uploads should look at it. Items issued on an earlier invoice are not red again.

---

## D-012: Unknown products become new item rows with the next item code; retail price left for a human

**Status:** Accepted · 2026-10-14

**Context.** New products are created in PowerSoft by uploading an Excel row with a new Item Code. Codes are arbitrary unique strings (letters are allowed; gaps don't matter). By convention they are numeric and sequential. The highest in PowerSoft is **1633** per the 2026-10-14 export (staff jumped from 1452 to 1553 at some point). On upload, PowerSoft only reads new codes, unless "modify items" is ticked, which overwrites existing items. The tool must therefore never require that tick.

**Decision.** When an invoice line matches nothing (after D-006):
- create a full row with Item Code = highest known + 1, filled from the invoice (description, barcode, supplier code/name, cost, VAT %)
- fill in a **suggested category** (from the most similar existing item; see the D-006 amendment), flagged for checking
- leave **Retail price empty** (PowerSoft accepts a blank, but then asks the cashier for a price at every sale, which is only meant for things like printing)
- the whole row is **red** (D-011)

**Fields PowerSoft's "Upload Items" reads** (field numbers start at 0 = column A):
| Field | Column | Meaning |
|---|---|---|
| 1 | B | Item Code |
| 3 | D | Barcode |
| 4 | E | Description |
| 6 | G | Unit of Measure (always PCS) |
| 7 | H | Unit Price excl. VAT (cost) |
| 11 | L | Retail price incl. VAT |
| 12, 13 | M, N | Category code, name |
| 14, 15 | O, P | Department code, name (unused) |
| 16, 17 | Q, R | Supplier code, name |
| 18 | S | Brand (optional) |
| 19 | T | VAT as a plain number: 0, 5 or 19 |

The import mapping was set up by PowerSoft and can be changed if a better template is ever needed.

**How it is uploaded (confirmed by Zein).** The same output file serves both of PowerSoft's import destinations, in this order:
1. **Upload Items:** reads item details and skips every Item Code that already exists, so only the new rows are added. It ignores quantity.
2. **Upload invoice (quantities):** run only after step 1. It fails for the *whole* file if any Item Code is unknown.

No separate new-items file is needed.

**Avoiding double-issued codes.** The tool keeps a small ledger of codes it has handed out. The next code is max(highest code in the PowerSoft export, highest code in the ledger) + 1, so a code that was issued but never uploaded is simply skipped. Gaps are harmless.

**Reasoning.** It mirrors exactly what Zein does by hand. Leaving the retail price to a human keeps pricing decisions out of the tool.


**Amendment (2026-10-16): codes stay sequential; the new-item form never asks for a cost.**
- *Codes.* The full review found a risk: if staff create an item by hand in PowerSoft between exports, the tool can issue the same code for a different product. "Upload Items" then skips the tool's row, and the quantity upload adds the stock to the hand-made item. A separate range for the tool (5000+, or a letter prefix) was considered and **rejected by Zein**: it would let the same product be created twice under two codes, and PowerSoft drops the barcode of the second one, which is worse than a visible clash. Instead, once the tool is live, **staff never create items by hand**; new items only come through the tool, and anything odd goes to Zein. The PowerSoft API, if it is affordable, would remove the risk entirely (the tool could read live codes and create items itself). Zein is asking PowerSoft about it.
- *Cost.* Staff never type a cost. It is the invoice amount per piece (line amount / quantity / "how many do you sell from 1 unit"), averaged over every line of that product. *Why:* hand-typed costs are how VAT-inclusive costs got into PowerSoft (1634-1637). The form shows the cost per piece as staff type, and refuses a selling price at or below it, which also catches a wrong "how many" answer (a 3-pack priced as one bar).
- *Barcode.* Pre-filled from the invoice line and editable. Every item must have a barcode: if a single piece has none, the pack's barcode is used and Zein can remove it in PowerSoft later.

**Amendment (2026-10-19): the form steers staff away from duplicate packs.** *Context:* a staff member created "Kinder Bueno White T3" as a new item although 1372 (one Kinder Bueno White bar) already existed. The invoice's barcode was pre-filled, and it was the 3-pack's.
- *Already stocked.* When "how many do you sell from 1 unit" is more than 1, the form lists up to 3 items we already sell with a similar name (only those within 8 points of the best match), each with a "Use this one" button. That answers the question exactly like picking the item from the search list, so the normal pack-size check follows.
- *Barcode no longer pre-filled* (replaces the 2026-10-16 barcode point). The box starts empty with the hint "Scan it from the item itself, not from the invoice". The invoice barcode is shown beside it with a "Use invoice barcode" button, which first asks "Look at ONE piece in your hand. Is this number printed on it?" A barcode staff scanned on the previous screen is still filled in, because that one came from the item.
- *Name hint.* The name box is labelled "Name of ONE piece (not the pack)". Zein tells staff this means the unit we sell in.
- *Alternatives.* Keep pre-filling and only add a hint: rejected, because a filled-in box looks already checked and gets accepted. No invoice barcode at all: rejected, because items with no barcode of their own still need one (see above).
- *Why:* a duplicate item splits stock across two codes, and PowerSoft drops the barcode of the second one. One extra click for a real new item is cheaper than cleaning up a duplicate.

**Amendment (2026-10-19): new items get a brand, and a supplier code is checked.**
- *Brand, filled in by the tool.* Every stocked item in PowerSoft has a brand (357 in use), and new items had none. Nothing in the shop uses the brand, so Zein doesn't want staff asked: the tool fills it in. If the name starts with a brand we already use, that brand (KINDER BUENO… → KINDER; the longest wins, so 7UP ZERO before 7UP); otherwise the name's first word (TOBLERONE MILK 100G → TOBLERONE). *Alternatives:* a required brand box for staff (tried the same day, dropped as padding for a field nobody uses); a similar item's brand (rejected: for Toblerone the most similar item is an ION bar).
- *Supplier code.* A new item takes the invoice's supplier, with its code from `suppliers.xlsx`. Every real supplier profile has one (checked 2026-10-19). If a profile's supplier ever has no code, Zein's report says so at once, and a new item from it gets its supplier cells marked red with the reason. The made-up demo supplier is the only one without a code, on purpose.
- Existing items keep PowerSoft's supplier and brand: the tool never edits item data (D-018).

---

## D-013: Out of scope: handwritten invoices (ED Sport, Aristidou), automatic upload; every input PDF is treated as an invoice

**Status:** Accepted · 2026-10-14 · amended 2026-10-15

**Decision.** The tool does not handle:
- **credit notes/returns.** Staff never put them in `input/`; returns are edited by hand in PowerSoft, which has no Excel upload for them. The tool therefore **assumes every page is an invoice** and does no credit-note detection. (Pambos and Rainbow print "Credit Invoice", meaning *sold on credit*, so detecting the word "credit" would have been wrong anyway.)
- **handwritten invoices:**
  - **ED Sport:** rare, and the names can't be matched without seeing the stock.
  - **Aristidou (Aqua water):** set aside for now. It is a pre-printed form with handwritten quantities, almost always the same two items, so it is faster for staff to do by hand than for the tool to read it.
- **PowerSoft upload or API** (D-001).

**On probation: Asian Food Market.** A thermal till receipt with shortened names and no barcodes, which can group flavours into one line (e.g. "Bulldog"). It stays in scope until Zein checks with staff whether lines are reliable enough. If not, it joins the list above.

**Amendment (2026-10-15):** Asian Food Market is entered by hand for now; it is listed as "enter by hand" in the run. To be revisited and tested once everything else is done.

When the tool recognises an out-of-scope supplier, it skips the page and says so in the report ("Aristidou: please enter by hand") instead of failing.

**Reasoning.** Each one adds a lot of complexity for very little volume. Excluding them keeps the core reliable.

---

## D-014: Real shop data stays local and git-ignored; anything public is synthetic

**Status:** Accepted · 2026-10-14

**Decision.**
- All real data lives under `data/`, which is git-ignored:
  - `powersoft/`: item export, code tables, master item list
  - `reference/`: legacy supplier lists (from the deleted per-supplier Excels)
  - `samples/`: real invoices
  - later: mappings and logs

  The old UPSTAIRS sheet (previous owner's stock, never re-ordered) was deleted. Its codes (1123–1178) are all below the current maximum, so removing it can't cause a code collision.
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

**Note (updated 2026-10-15).** One Athenites sample is in `data/samples/` (49 lines). Its second page, which holds the totals, is being re-scanned. Zein says Athenites invoices don't vary in layout, so one sample is enough to start, and more will be collected for evaluation.

---

## D-016: Python 3.12 + uv, src layout; runs from the Deep Freeze ThawSpace drive

**Status:** Accepted · 2026-10-14

**Shop PC storage.** C: may be frozen by Deep Freeze, which undoes every change on restart. The tool, its data (masters, mappings, logs) and the `input/`/`output/` folders live on the ThawSpace drive, where the master Excels already sit. Nothing the tool needs to keep may be written to C:.

**Decision.** Python 3.12, with dependencies managed by `uv` (as in Shop Assistant) and code in `src/invoice_automation/`. Expected libraries:
- `openpyxl`: read and write Excel while keeping formatting
- `pymupdf`: split PDFs and render pages
- `azure-ai-documentintelligence`: the official DI SDK
- `rapidfuzz`: fuzzy matching

How it gets onto the shop PC (bundled `.exe` vs. uv + launcher script) is decided when we reach deployment. Either way it lives on the ThawSpace drive. *Decided in D-023: uv + launchers.*

**Libraries actually used (2026-10-15):** the four above plus `python-dotenv` (reads `.env`), `pillow` (line pictures in the window), `tkinter` (the window; comes with Python) and `pytest` (tests).

---

## D-017: Two-stage output: `To Check` → `Uploaded`; masters and mappings only change once a file is marked uploaded

**Status:** Rejected · 2026-10-14. Zein: staff will forget to move files, and a forgotten move must never break the system. The problem it solved is handled by D-018 instead.

**Context.** The tool learns from each run: new items, price changes, and confirmed product matches. If it writes those to the masters as soon as it produces an output, an output that is never uploaded (forgotten, or rejected because of a red flag) leaves the masters out of sync with PowerSoft. For example, an item would exist in the Excel but not in the system.

**Decision.**
```
output/
  1 - To Check/   ← the tool writes new files here
  2 - Uploaded/   ← staff move a file here after uploading it to PowerSoft
```
- The tool **stages** every change (new items, cost changes, new mappings) alongside each output file. Nothing touches the masters yet.
- At the start of every run, the tool first processes `2 - Uploaded/`. It commits each file's staged changes to the masters and the mapping, then archives the file and its matching scan.
- The commit reads the file **as it is in `Uploaded/`**. If Zein corrected a wrong match or quantity before uploading, the correction is what gets learned.
- A new item that is still waiting in `To Check/` reserves its Item Code. Later runs match against it and don't hand out the same code twice.

**Alternatives considered.**
- *Write to the masters immediately.* Simplest, but creates the out-of-sync problem above.
- *An "Approve" button or second launcher.* Moving a file between two folders is already the approval, with nothing new to learn.
- *Never write back automatically (Zein updates the masters).* Safest, but the tool would never learn, so the same items and prices would be flagged every week.

**Reasoning.** "I've uploaded this" is the one moment the masters and PowerSoft are known to agree, so it is the right moment to commit. It costs staff one drag-and-drop per file. They already open the folder to check the file, so it fits how they work.

---

## D-018: The PowerSoft item export is the catalogue; one supplier-items table replaces the 23 masters; no approval step

**Status:** Accepted · 2026-10-14 (supersedes D-007; amended on point 4, new items, see below)

**Context.** Zein exported PowerSoft's full item list (1,525 items) on 2026-10-14. Compared with the 23 master Excels:
- **194 PowerSoft items are in no master.** That includes ~190 added since the masters were last copied (codes up to **1633**, not 1421).
- **14 master codes don't exist in PowerSoft at all.**
- **6 master codes point to a different product in PowerSoft.** For example, Agrotis master 1024 is "SELECT SQUARED EXERCISE BOOK A4", but PowerSoft 1024 is "SMOKING BROWN REGULAR PAPER X 50". Uploading the Agrotis Excel would have added stock to the wrong item.
- **190 barcodes and 167 descriptions differ.** PowerSoft is right for barcodes (edited there when packaging changes). Most description differences are the master using the **supplier's own invoice wording** (e.g. Athenites `7DAYS SGL CROIS/COCOA VAN/70GR`), which is valuable matching data.
- **Costs differ per supplier for the same item** (e.g. 2.50 from one supplier, 3.10 from another). PowerSoft stores only one cost.

Zein's rule: **PowerSoft is the truth** (except perhaps cost). Staff, not Zein, now maintain the Excels, so the copies will keep drifting.

Zein also rejected D-017: staff must not have any step they can forget.

**Decision.**
1. **Catalogue = the latest PowerSoft export**, dropped into `data/powersoft/`. The tool reads item identity from it: code, description, barcode, VAT, category, home supplier. The tool **never edits item data itself**. To refresh, drop in a new export. Zein can do this remotely, as he did today. The run report warns if the export is more than N days old.
2. **One supplier-items table** (`data/supplier_items.xlsx`) replaces the 23 masters. One row per (supplier, item) holds:
   - the supplier's own description and code/barcode for it (the learned mapping, D-006)
   - pack factor (D-005)
   - that supplier's last cost and date (D-009)
   - match status (trusted / provisional)

   It is seeded once from `data/reference/legacy_supplier_lists.xlsx`, which was extracted from the old masters before they were deleted.
3. **Output files are generated from the catalogue** using the 20-column template, with only the invoiced rows. There is no "copy the master and delete zero rows" step.
4. **No approval step; staff only use `input/` and `output/`.** Each kind of learning has its own safe rule:
   - **Costs:** the invoice is the truth whether or not it gets uploaded, so the supplier's last cost updates immediately.
   - **Barcode matches:** certain, so they are learned immediately.
   - **Fuzzy matches:** stored as *provisional* (still yellow on later invoices). They are promoted to *trusted* when the invoice they came from passes the total check (D-010) **and** the implied per-piece cost is within ±15% of the item's known cost, or when Zein confirms them.
   - **New items:** red the **first** time (D-011). The tool then adds the item to its own *local additions* list, which is merged on top of the export, so later invoices match it without Zein having to re-export. When a fresh export contains the code, the local entry is dropped. (Amended: Zein doesn't want to re-export for every new item.) The code ledger (D-012) means a never-uploaded item can't cause a clash.
   - **Duplicate scans:** the tool keeps a log of processed invoices (supplier + invoice number). If the same invoice is dropped in twice, it is flagged red instead of producing a second file that would double the stock.
5. **Invoices also correct item details.** When an invoice disagrees with the catalogue on more than cost, the run report lists it as a suggested PowerSoft fix (e.g. a different supplier, VAT rate or barcode). The tool doesn't edit item data itself (point 1). Many details in PowerSoft were entered by hand and may be wrong; the invoice is the truth.
6. **Manual fallback.** For invoices the tool skips (handwritten, credit notes), it can regenerate a classic per-supplier blank Excel from the catalogue on request, so staff never work from a stale copy.

**Alternatives considered.**
- *Fix the 23 masters and keep them as the catalogue (D-007).* Rejected: they are copies of PowerSoft maintained by hand in 23 places, and they have already drifted badly. They would drift again.
- *Two-stage approval folders (D-017).* Rejected by Zein: it relies on staff remembering a step.
- *SQLite database instead of an Excel table.* Sturdier, but Zein couldn't open and read it as easily. Excel keeps everything inspectable. (Columns are stored as text, so barcodes with leading zeros survive; the tool shows a readable error if the file is open in Excel while it runs.)

**Reasoning.** It removes the drift problem rather than cleaning it up once. Every piece of state has exactly one owner:
- PowerSoft owns what an item *is*.
- The supplier-items table owns what the tool has *learned* about suppliers.
- Invoices own *costs*.

That is what lets the human approval step go away without risk.

---

## D-019: One-off PowerSoft cleanup via a reviewed "modify items" upload, before building the tool

**Status:** Accepted · 2026-10-14

**Context.** D-018 makes PowerSoft the catalogue, so PowerSoft's own data quality now matters. Every item in the 2026-10-14 export was reviewed (1,525). Problems found:
- truncated brands (`G.`, `OLD`, `PALL`)
- wrong brands (Korean noodles under HEINEKEN, Doritos under LAYS)
- wrong categories (tortillas, oil and cereal under "Ice Cream"; USB cables under "Cleaning")
- 5% VAT on some beers and wines
- suppliers assigned at random to recent items
- typos

The export also **drops `& ' % ( )` from names and rounds costs**, so re-uploading it unchanged would damage good data.

**Decision.** Build a fix file in the 20-column template, for Zein to upload once with "modify items" ticked:
- Names: punctuation restored from the old Excels, whitespace normalised, Greek look-alike letters replaced, typos fixed.
- Brands: rebuilt from the item name.
- Categories, VAT and suppliers: corrected only where the item is inconsistent with every similar item. VAT and supplier changes are marked "PLEASE CONFIRM".
- Costs: the more precise value from the old Excels is kept where it rounds to the export's value.
- Excluded: service items (Smoov, printing, cafeteria, plastic bag), non-storable pack items, and junk/test items. Excluded items are not in the file, so "modify" leaves them untouched.
- Prices: retail prices and costs are never changed. Anomalies (price below cost, duplicates) are listed for Zein instead.

Outputs (git-ignored, `data/powersoft_fix/`, deleted after the upload on 2026-10-14):
- `CHANGED_ITEMS_ONLY.xlsx`: recommended for upload
- `ALL_ITEMS_FIXED.xlsx`
- `REVIEW_CHANGES.xlsx`: every change with its reason, plus flags and exclusions

**Alternatives considered.**
- *Fix by hand in PowerSoft.* Hundreds of edits. Slow and error-prone.
- *Upload the full file.* It would rewrite 1,000+ unchanged items with export-rounded values, for no benefit. The changed-only file limits the blast radius.

**Zein's answers (2026-10-14).**
- `&` and `'` are stored in PowerSoft: every item was created by Excel upload, so the export is what strips them.
- Service items (Smoov, printing, cafeteria, plastic bag) and multipacks stay excluded.
- Items added after the masters (codes 1422+) were entered by a new staff member and are the most error-prone. They may be corrected at discretion, with **Athenites as the default supplier** when the real one is unclear (it may later turn out to be, e.g., Andrikian; invoices will settle it, see D-018 point 5).
- Palestina drinks go under the same supplier as Almarai (FINERICO).
- Brand is low priority; categories are internal to the shop.

**Safety.** Test-upload 2–3 rows first and check them in PowerSoft:
- Did `&` and `'` survive?
- Are any extra barcodes on the item kept? (The template has only one barcode column.)
- Are cost and retail price unchanged?

**Result (verified against the 2026-10-14 CSV export).**
- Applied: names, brands, categories, suppliers and the retail price fix.
- Not applied: **VAT**. "Upload Items" with modify does not change the VAT of existing items. The 11 VAT corrections are being made by hand, so VAT fixes always need a manual step in PowerSoft.
- Removed: the old per-supplier masters, replaced by `data/powersoft/MASTER_ITEM_LIST.xlsx` and `data/reference/legacy_supplier_lists.xlsx`.

**Correction (2026-10-14).** It is PowerSoft itself, not the export, that strips `& ' % ( )` from item names on save (the uploaded names with `&`/`'` came back without them). Costs are stored to 2 decimals. So the export is an exact copy of what PowerSoft holds. Two consequences for the tool:
- When matching names, the tool must ignore those characters on both sides.
- Rows it writes don't need them.

The 11 VAT corrections were made by hand and verified in the second 2026-10-14 export. `MASTER_ITEM_LIST.xlsx` is rebuilt from that export exactly as exported.

---

## D-020: Athenites profile: barcode = purchase unit, VAT-inclusive amounts, pack factor learned per barcode

**Status:** Accepted · 2026-10-15

**Context.** Shop staff collect Athenites orders in person. Athenites prepares the order, but it goes through their normal checkout till, so the invoice is the same till printout any customer gets. A check of the first sample (49 lines) against the PowerSoft catalogue found:
- **38 of 49 barcodes match a PowerSoft item exactly.** All 11 that don't are multipacks: Monster and Hell cases, Schweppes 6-packs, Perrier 4-packs, Kinder 3-packs.
- **The printed barcode is whatever the Athenites cashier scanned.** If their system has the pack barcode, they scan the pack. If not, they scan one piece and multiply. So the same product can arrive either way: Monster Zero came as 24 single cans, while two other Monster products came as cases on the same invoice.
- **Prices and line amounts include VAT.** VAT is a letter code: B = 5%, D = 19% (checked against the catalogue on every matched line).
- **There is a discount column per line.**
- **The printed unit price is rounded.** For one line, 8 × 4.85 = 38.80, but the line says 38.79.
- **The till doesn't merge repeat scans.** If a cashier scans an item, then something else, then the first item again, it prints two lines.
- Most item names in PowerSoft were originally copied from Athenites invoices, so names usually match word for word.
- Several newer items have Athenites' VAT-inclusive price stored as their cost, because staff didn't realise the invoice includes VAT.

**Decision.**
- **Unit:** the printed barcode identifies the purchase unit. The supplier-items table (D-018) stores (Athenites, barcode) → (Item Code, pack factor). The same barcode always means the same pack, so each barcode is learned once.
- **Cost per piece** = line amount ÷ quantity ÷ pack factor ÷ (1 + VAT rate). This uses the line amount, which is already net of the line discount, and never the printed unit price.
- **VAT letters** map to rates in the supplier profile (B = 5%, D = 19%). An unknown letter is flagged red.
- **Lines with the same barcode are summed** before output.
- **Pack-factor suggestion** for a barcode not yet learned: divide the cost per invoice unit (before VAT) by the item's known cost per piece.
  - Within ±10% of a common pack size (3, 4, 6, 9, 12, 24) → that size is suggested, **yellow**. (3 added 2026-10-15: Kinder Bueno comes in 3-packs and is sold as single bars.)
  - Any other whole number (e.g. 13) → suggested, **red**.
  - Not near a whole number → **red**, with no suggestion.

  Zein confirms each one once, and it is then remembered. The list of common sizes grows with confirmed factors.
- **Matching** for a barcode not yet learned:
  - an exact barcode match against PowerSoft first
  - otherwise a fuzzy name match against Athenites' own past wording (legacy lists, then learned descriptions), then against the whole catalogue
  - always with the strict Athenites thresholds of D-015
  - always resolving to the storable item (D-005 amendment)
- **Existing VAT-inclusive costs** are corrected by normal D-009 price-change handling: they show orange on the first run and appear in the price-change report.

**Alternatives considered.**
- *Read the pack size from the name ("T48", "X3", "19X165GR").* Unreliable: Duplo "T48" and Pringles "19X165GR" are billed per piece, while Kinder Delice "T10" is billed per box.
- *Add the case barcodes to PowerSoft as extra barcodes on the single item.* Rejected by Zein: a cashier scanning a case would sell it for the price of one piece.
- *Rely on Zein's memory of pack sizes.* That's how it's done today. The price-ratio check is the same method Zein uses to double-check without going to the storeroom, now done automatically.

**Amendment (2026-10-16): exact barcode matches are price-checked too.** The first rehearsal turned up PowerSoft item 310 (Chupa Chups, sold and costed as one lollipop at 0.20) holding the barcode of the bag of 10. An exact barcode match was taken as 1 piece without a check, so 6 bags became 6 lollipops at 2.00 each. Now, if a barcode-matched line costs **1.5× or more** the item's known cost, the pack-size question is asked as for any other line. Below 1.5× it stays 1 piece and the difference goes to the price-change report (D-009), so out-of-date or VAT-inclusive costs don't add questions. *Why 1.5×:* the smallest real pack is 2, and a genuine price change is very unlikely to be +50%.

**Reasoning.** It turns the riskiest error (one case entered as one can) into a fact learned once per barcode, with an independent check from price. Using the line amount handles discounts and rounding in one go.


**Amendment (2026-10-16): pack suggestions check both known costs, and learned sizes are re-checked.** From the rehearsal and the full review:
- *Two references.* The price is compared with this supplier's last cost **and** PowerSoft's cost. A promotion on the last invoice (a can on offer at 0.70 instead of 0.85 made a case of 24 look like 29) or an out-of-date PowerSoft cost only spoils one of them.
- *Which size is suggested.* Within 10% of 1 piece: 1, no question. Within **1%** of a whole number: that number (13.0x is 13). Otherwise a normal size (3, 4, 6, 9, 12, 24) within 10% (25.5x suggests 24, not 26). Otherwise the nearest whole number in red, or no suggestion. The 1% band allows for PowerSoft keeping costs to 2 decimals (about 0.6% rounding). Every suggestion is still a question: staff count the box.
- *Learned sizes are checked by price too* (Zein: "anything that can be checked should be checked"). If the price no longer fits the learned size against either known cost (outside 1.5x either way: the supplier changed the box from 24 to 12, or the first answer was wrong), the question comes back with "Last time 1 unit was 24 pieces, but the price has changed a lot", and the new answer replaces the old one.

---

## D-021: Use `prebuilt-layout` only; the supplier profile interprets the table

**Status:** Accepted · 2026-10-15 (resolves the open model question in D-003)

**Context.** D-003 left open which Document Intelligence (DI) model to use. A test (`scripts/di_spike.py`) ran both candidates on the Athenites sample and compared them with a hand transcription of all 49 lines:
- **`prebuilt-layout`:** 49/49 rows, and all 147 quantities, amounts and barcodes correct.
  - Cell confidence (the weakest word in the cell) was 0.98 or higher on every number.
  - The only low scores were the two cells crossed by a pen stroke (0.149 and 0.767).
  - Pen ticks were read as checkboxes (`:selected:`) and added to descriptions.
- **`prebuilt-invoice`:**
  - missed 3 barcodes and added an empty row
  - scored correct values at about 0.3, so its confidence can't separate right from wrong
  - read the supplier name from the Greek logo
  - did get the invoice number and date right

**Decision.**
- Each page is analysed **once, with `prebuilt-layout`**.
- The supplier profile (D-005) says which printed column means what (by header text) and where the invoice number, date and total are.
- Cell confidence = the lowest confidence of the words in the cell. Below a threshold (to be set from more samples; around 0.9 for Athenites) → yellow (D-011).
- Checkbox text (`:selected:`, `:unselected:`) is removed from every cell.
- The supplier is identified from the page text (name, VAT number), not from a model field.
- `prebuilt-invoice` isn't used. A custom model stays an option for a supplier where layout plus a profile turns out to be insufficient.
- Every DI response is cached on disk by file content, page and model, so re-processing or re-testing a scan costs no pages.

**Alternatives considered.**
- *`prebuilt-invoice` for the header plus `prebuilt-layout` for the lines (the earlier expectation in D-003).* It doubles page usage for two header fields that layout's text already contains, and its supplier detection was worse.
- *`prebuilt-invoice` alone.* Lost data, and its confidence scores are unusable for flagging.
- *Custom extraction model.* Needs about 5 labelled samples per layout and adds training and upkeep. It isn't needed while layout reads everything correctly.

**Reasoning.** Layout reads what's printed and makes no guesses, and its confidence actually goes down on damaged cells. Interpreting columns in our own code keeps every supplier's rules visible and testable. One request per page also halves free-tier usage.

**Amendment (2026-10-15): arithmetic beats confidence.** When a line's own arithmetic checks out (quantity × price = line amount, D-010 amendment), those numbers are treated as correctly read whatever their confidence score, and get no "hard to read" flag. Confidence is only used for numbers no check covers (e.g. Cassandra's FACT column). Barcodes are vouched for by their check digit and names go through matching, so neither gets a confidence flag.

*Why:* on Cassandra, confidence put about 40 yellow flags on cells that were all correct (product names, `0`s in the SUB column). A passing check means all three numbers were read correctly: for it to pass with wrong numbers, the misreads would have to cancel out exactly, which is practically impossible. So the check is a far stronger signal than any single cell's score.

---

## D-022: Review window: staff answer questions from the paper and the shelf; the Excel is only written once an invoice is cleared

**Status:** Accepted · 2026-10-15 (refines D-002 and D-011: flags become questions)

**Context.** Flags (D-011) only help if someone acts on them, and nothing stops staff uploading a file they didn't check. The tool's memory file (`supplier_items.xlsx`) is not for humans to edit. Zein runs the shop remotely from Dubai with a co-owner on site and wants to stay out of the daily flow: staff already add new items and set retail prices today. Staff read English fine for short, simple screens. About 10 minutes of training is acceptable. A USB barcode scanner is available; it types the barcode and presses Enter, just like typing by hand.

**Decision.**
- After processing, a **review window** asks staff one question at a time. Each question shows the invoice line cropped from the scan (DI gives each cell's position) next to what the tool understood. English only, short words, big buttons.
- **Staff resolve everything the paper or the product can answer:**

  | Situation | Question |
  |---|---|
  | Pack size suggested | "1 unit = 24 pieces?" Yes / No → type the number |
  | Pack size unknown or unusual | "How many pieces in 1 unit?" |
  | Close (not exact) match, provisional match, single/pack pair | "Is it this item?" Yes / No → identify it |
  | Identify an item | Scan or type its barcode, or search by name, or "It's a new item" |
  | New item | Name (pre-filled), barcode of **one piece** (scan or type; the invoice may show a pack barcode), pieces per invoice unit, **retail price (required)**, category (suggested) |
  | Non-storable pack item matched | Identify the single item instead |
  | Line doesn't add up, or a number is unreadable | Type the numbers as printed on the paper |
  | Invoice number not found | Type it |
  | Printed total missing or not matching | Type the total from the paper. If it still doesn't match the lines: "a page may be missing, scan all pages and run again" |
  | Same invoice already processed | "Already done on <date>. Only make it again if the Excel was lost and never uploaded." Skip / Make it again |
- **No staff question for:**
  - price changes (report only)
  - unsupported or handwritten suppliers ("enter this one by hand")
- An invoice's **Excel is written only when every question is answered**, to `output/Ready to upload/`, the only folder staff upload from. Unanswered questions persist and come back on the next run, so nothing depends on staff remembering a step.
- Every screen has **"I'm not sure"**. That, and problems staff can't answer from the paper (unknown VAT code, an unexpected column filled in), put the invoice on **Zein's list**. He resolves it over AnyDesk in the same window, which has extra options for him. *Confirmed after the first rehearsal (2026-10-16):* the rest of that invoice's questions are not asked. Zein's fix usually changes the inputs (a fresh PowerSoft export, a corrected item), so redoing the invoice from the start is safer than continuing with answers given before the fix.
- Every answer is learned like a confirmation (D-018). The report lists what staff confirmed, and learned answers stay subject to the arithmetic and cost checks.
- Built as a desktop window (tkinter + Pillow); no browser or server.

**Alternatives considered.**
- *Zein edits `supplier_items.xlsx`.* The file is large and awkward to edit, it keeps Zein in the daily loop, and staff must not have access.
- *Staff correct the output Excel and the tool learns from it.* The tool can't tell a corrected file from an unchecked one.
- *A tick column in the Excel, or "was it opened?" detection.* It shows a box was ticked, not that the paper was checked, and it's fragile.
- *Route "No" answers and new items to Zein.* It keeps the owner in the daily loop for things staff already handle today.
- *Skip duplicates silently.* It leaves no way to regenerate an Excel that was deleted before upload.

**Reasoning.** Making the safe path the only path is stronger than detecting mistakes afterwards. Each question is something a person holding the invoice (and the product) can answer for certain. Every answer is learned, so questions get fewer each week, and Zein only hears about genuine tool failures.

**Amendment (2026-10-16): changes after the full review.**
- *One answer per product per invoice.* Lines with the same barcode (or, without one, the same supplier code) share their item and pack answers. Before, a product scanned twice at the Athenites till was asked twice, and a new product on two lines got two item codes.
- *"< Previous question"* takes back the last answer on the current invoice (a mis-click would otherwise be learned). The new-item form's own button is "Cancel".
- *"Is it this item?"* shows the words that differ in red ("A2" / "A3", "Black" / "Blue", "120GR" / "130GR"). Near-misses are still asked, not rejected, because a product can change size and stay the same item.
- *Items that hold no stock* (Storable = No in PowerSoft) can never be chosen or written to an Excel: the search hides them, a scanned barcode of one is refused, and a match to one always asks for the single item (D-005).
- *Negative quantities* are a misread: invoices never print one, and returns come on their own slip with positive numbers and are entered by hand, not through the tool. Staff are asked to type the numbers from the paper; if they confirm a negative, the invoice goes to Zein.
- *A file open in Excel* (the output, or `supplier_items.xlsx`) stops the invoice before anything is written, with "Close it and run again" instead of "contact Zein". Before, new codes could be issued and the Excel written with the learned table left unsaved.

**Amendment (2026-10-19): every screen scrolls.** In the final test, on a smaller monitor, the new-item form ran under the fixed bottom buttons and "Save new item" could not be reached. The question area (and the Done list) now scrolls, with the mouse wheel and a scroll bar that appears only when needed, while the bottom buttons stay in place. Checked at 1000×620. The "Do we already sell ONE piece of it?" list stays beside the form: it was briefly moved under it for narrow windows, but Zein preferred it on the right, where it catches the eye, and the tool only runs on PC screens wide enough for it. *Why:* the shop monitor is large, but a window can be resized or moved to another screen, and a button out of reach is a dead end for staff.

---

## D-023: Deployment: uv + launchers on the ThawSpace drive; code and data in separate folders; one-click update with automatic rollback; data safety and automatic checks

**Status:** Accepted · 2026-10-19

**Context.** The tool goes onto the shop PC. Deep Freeze resets C: at every restart; every other drive is ThawSpace and keeps its changes. Zein maintains it from Dubai over AnyDesk. Over months, the tool builds up what staff have taught it (the supplier-items table, issued item codes, pack sizes). Zein's requirements: losing that must be close to impossible, fixes must be easy to ship, and anything that can be automatic should be, so there is less room for human error.

**Decision.**

1. **Folder layout on the ThawSpace drive.** `app\` holds only the code. Everything the tool keeps sits beside it: `data\`, `input\`, `output\`, `processed\`, `logs\` and `.env` (the Azure key). `tools\` holds uv, Python and the libraries. The launchers run the tool from the tool folder, and every path in the code is relative to it, so the code never writes inside `app\`.
2. **uv + launchers, not a bundled .exe.** `Process Invoices.bat` (staff; a desktop shortcut) and `Admin.bat` (Zein's menu: admin mode, update, undo, pack check). Through environment variables, uv puts Python, the libraries and its cache in `tools\`; by default it would use the user profile on C:, which Deep Freeze wipes. `uvw` (uv without a console window) runs the tool, so staff see only its window.
3. **Updates: one click, nothing in data touched, automatic rollback.** `update.ps1` downloads the newest commit of the public GitHub repo as a zip (no git or login needed on the shop PC) and keeps the previous code as `app.old`. It then installs the libraries and starts the tool far enough to read the real export. If that fails, the old code is put back by itself. "Undo" puts the previous version back by hand. The running version (commit) is written to `tools\version.txt`.
4. **First install:** `setup.ps1` refuses to run on C:, installs a pinned uv into `tools\`, runs the update, copies the launchers and makes the desktop shortcut. It then lists the data files still to copy in from Zein's PC.
5. **Data safety:**
   - *Crash-safe saves.* Every file the tool keeps (learned table, queue, state CSVs, DI cache, output Excel) is written to a temporary copy and swapped in with one rename, so a power cut mid-save leaves the old file, never half a file.
   - *Daily backup.* The first run each day zips the learned table, `flag_items.csv` and `data\state\` into `data\backups\` and keeps 30 days.
   - *A missing learned table stops the tool.* If invoices were processed before but `supplier_items.xlsx` is gone, the tool stops with "contact Zein" (details in the log) instead of quietly starting again from the old supplier lists.
   - *A bad export can't be used.* If the newest PowerSoft export is missing a needed column, or has under 90% of the previous export's items (cut off), the previous export is used and Zein's report says why. A bad export can never delete learned data anyway: rows for items an export lacks are skipped, not removed.
   - *Start-up errors* go to `logs\error.log`, and staff see "The invoice tool could not start. Please contact Zein."
6. **Automatic checks in Zein's report:** when a new export comes into use, the report lists every pack link and flags near-name and unlinked packs (D-005 amendment), so `--packs` is optional. It also reminds Zein when the export is more than 45 days old.
7. **Measured time per invoice.** The tool logs, per invoice, the lines, the questions and the time from the first question to done (`data\state\timings.csv`, also in the report). The time saved can then be measured instead of estimated.
8. **The PowerSoft export stays Zein's job,** about once a month: the export needs a custom column choice that staff shouldn't have to remember. He drops it into `data\powersoft\`; the tool takes the newest usable one.

**Alternatives considered.**
- *A bundled .exe (PyInstaller).* One file to copy, no Python on the PC. Rejected: every fix means a rebuild and a copy over AnyDesk, home-made .exe files are often flagged by antivirus, and the data would still need its own folder.
- *Updating with git on the shop PC.* Git for Windows installs to C: (wiped) unless a portable copy is kept, and a pull can leave a half-updated folder. A zip download into a new folder, then a swap, is all-or-nothing and needs nothing installed.
- *Updating automatically at every start.* No clicks, but a bad push would reach staff mid-shift with nobody watching. Updates stay a deliberate click by Zein, with the check and rollback.
- *Backups off the PC (cloud).* Safer against a dead disk, but needs an account and credentials on the shop PC. Deferred: the daily zip covers mistakes and corruption, and Zein can copy `data\` off over AnyDesk now and then.

**Reasoning.** The design splits what changes often (code) from what must never be lost (data), so the risky operation, an update, can only ever touch the replaceable half. Every remaining failure is either prevented (crash-safe saves, refusing a bad export, refusing to start without the learned table) or recoverable in a minute (daily backup, undo). Automatic report notes replace things Zein would otherwise have to remember.

**Amendment (2026-10-19, after the final test): what to upload, and the export's fixed name.**
- *The Done screen says what to do next in PowerSoft,* so staff don't open each Excel to decide. Step 1, **Items import with Modify ticked**, lists only the files that need it and why ("1 new item, 10 cost changes"). Step 2, **Purchase order**, is every file. Step 1 comes first because the purchase order needs the new items to exist. Zein's report repeats it per invoice. Cost changes count for step 1 only until Zein checks whether a purchase order updates an item's stored cost (D-008, `COSTS_NEED_ITEMS_IMPORT`); if it does, only new items will need Items import.
- *The export keeps PowerSoft's own name.* Zein saves `itemsList.csv` into `data\powersoft\`, over the last one. The tool keeps a dated copy of each new version (`items_export_<date>.csv`, the last 6) and works from those, so falling back to the previous export (point 5) still works.
- *Guides.* `Staff guide.html` sits beside the launcher; `Admin guide.html` (updates, undo, logs, reports, backups, the export's columns) sits in `data\`, out of the way but not locked. Both live in `deploy\guides\` and every update refreshes them.
- *Everything from PowerSoft can be refreshed:* the item export as above, and `suppliers.xlsx` and `categories.xlsx` by replacing them, with the same names. They are read fresh at every start.
