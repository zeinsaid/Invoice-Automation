# Where we left off

Last session: 2026-10-15. Decisions D-001 to D-022 are in [DECISIONS.md](DECISIONS.md).

## State of the tool

- **Works end to end** on every printed supplier: Athenites, Cassandra, Cosmos, Fereos, Andrikian, Vassos, Agrotis, Rainbow, Pambos, Party Ice, Jumbo. All 16 sample invoices go through to `output/Ready to upload/`.
- **Review window** (D-022) built and screen-checked: pack sizes, "is it this item?", identify by barcode/search, new-item form (retail price required), fix numbers from the paper, invoice total, duplicates, "I'm not sure", Zein mode (`--zein`).
- **Entered by hand:** ED Sport, Aristidou (handwritten), Asian Food Market (on probation, D-013).
- 16 unit tests pass (`uv run pytest`).
- **Clean state:** the tool's memory (`data/supplier_items.xlsx`, `data/state/`) was wiped after testing with made-up answers. The DI cache (`data/cache/di/`) is kept.
- **Not done yet:** deployment to the shop PC, the staff cheat sheet, the LLM matching step (D-006 step 4), a real PowerSoft test upload.

## Waiting on Zein

- [ ] Full scans of **Athenites** and **Agrotis** including page 2 (staff asked). Drop them into `data/samples/`.
- [ ] Staff answer on the **single vs pack pairs** (Kinder Delice 177/1399, Tronky 183/1404, Kinder Cards 1403/174, Nutella Biscuits 1375/194, Snickers 213/212). Then update `data/flag_items.csv` and PowerSoft (disable one, or make the pack a non-storable sub-item).
- [ ] Upgrade the Azure free trial to **pay-as-you-go before ~14 Nov 2026**, and set a €5 budget alert (the F0 resource stays free).

## Next, in order

1. **When the page-2 scans arrive** (D-004 amendment, D-010):
   - Build the page-joining rule: an unrecognised page joins the invoice before it, unless it's an enter-by-hand supplier; if the joined page adds no lines and no total, ask staff "Is page N part of this invoice?".
   - Set the `TOTAL` patterns for Athenites and Agrotis from the real page 2, so staff stop typing the total.
   - Run both through the tool and check them against the paper.
2. **Deployment** (step 3; Zein said wait until he's ready):
   - Decide how it goes on the shop PC (D-016): a bundled `.exe` or uv + a launcher script. Recommend one, then log the decision.
   - Double-click launchers: **Process Invoices** (staff) and **Fix Issues** (`--zein`, for Zein over AnyDesk).
   - Everything on the ThawSpace drive: code, `data/`, `input/`, `output/`, `.env`.
   - A setup section in the README that Zein can follow over AnyDesk.
   - A **one-page cheat sheet** for staff (English, pictures of each screen), kept on the shop PC.
3. **Test run** on the shop PC with a real order (Zein, in a couple of days), plus a real PowerSoft upload of one output file: does the quantity import accept it, are cell comments OK (D-011), does it update the cost (D-009)?
4. **Later:** the LLM suggestion step for unmatched lines (D-006 step 4), Asian Food Market (D-013), Aristidou if ever wanted.

## Tips for the next session

- Re-running on samples costs nothing: `uv run invoice-automation "data/samples/<file>.pdf"` (files given by path stay where they are). Wipe `data/supplier_items.xlsx`, `data/state/`, `data/reports/` and `output/Ready to upload/` after testing with made-up answers.
- `uv run invoice-automation --no-window <pdfs>` finishes what needs no questions and prints the first open question.
- To screenshot the window for checking: make it nearly transparent (`root.attributes("-alpha", 0.01)`) and capture the window itself with Win32 `PrintWindow`. Never capture the screen.
- The legacy wording seeding of `supplier_items.xlsx` happens automatically the first time the tool runs.
