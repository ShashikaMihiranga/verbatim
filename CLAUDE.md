# Verbatim

Web app that turns a spreadsheet into a short, visual report. Open-ended text is the centrepiece (themes, sentiment); numeric and category columns (age, sex, income, score, date) feed cross-cuts and findings.

Read first: `docs/PROJECT_VISION.md` (the main goal and decisions), then `SPEC.md`.

Also read: `SPEC.md` (product decisions, data flow, chart-selection rules, structured-column plan).

## Layout
- `app/main.py`: FastAPI routes. `app/charts.py`: chart renderers (inline SVG/HTML with CSS variables), still on EV sample data.
- `design/screens/*.dc.html`: approved and candidate designs (charts, sign-in options A-D, upload, check-columns, three sample reports). `.dc.html` files only render inside the Claude Design canvas; treat them as visual reference and copy values from them.
- `design/*.py`: scripts that generated the designs. Their output paths are hard-coded to a scratch folder; they are reference, not part of the app.

## Design rules (keep)
- Font: Jost only (300 big numbers and headlines, 400 body, 500 labels, 600 titles). Body 16px/1.55, tabular numbers.
- Tokens as CSS variables: `--bg --surface --ink --muted --line --accent`, themes `--t1..--t7 --other`, tone `--neg --neu --pos`, heatmap `--ramp`. Light theme only for now.
- Theme colours only identify themes; tone colours only show sentiment. Colour is never the only carrier: print the number.
- No pie/donut, word cloud, 3D, or network graphs. No gradients or shadows. Charts sit on the page; only the primary chart may sit on a raised surface.
- Reports: one insight per block (one sentence, one visual), "Solid" or "Tentative" badge, a "Also checked, nothing notable" line, max about 5 blocks.
- No exact record counts on marketing or login screens.

## Product rules
- Claude sees samples and aggregated numbers only, never the whole dataset. Cheap steps (embeddings, clustering, sentiment lexicon) do the bulk.
- Every theme and every sentence must link back to real answers.
- Hide groups smaller than a minimum size. Never show individual rows of demographic columns.

## Commands
- Run: `uvicorn app.main:app --reload`
- Deploy: Railway reads `railway.json`; health check `/health`.

## Next tasks (in order)
1. Make `charts.py` take a data object instead of module-level EV sample data.
2. Auth (use a proven provider; do not hand-roll password storage) and per-user project storage.
3. `POST /api/upload` for .xlsx/.csv and the column-profiling step ("Check columns" screen).
4. Text pipeline: clean, embed, cluster, label with Claude, sentiment.
5. Findings engine and chart-selection rules (SPEC.md sections 4 and 9).
