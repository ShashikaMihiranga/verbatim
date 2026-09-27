# Verbatim

Web app that turns a spreadsheet into a short, visual report. Open-ended text is the centrepiece (themes, sentiment); numeric and category columns (age, sex, income, score, date) feed cross-cuts and findings.

Read first: `docs/PROJECT_VISION.md` (the main goal and decisions), then `SPEC.md`.

Also read: `SPEC.md` (product decisions, data flow, chart-selection rules, structured-column plan).

## Layout
- `app/main.py`: FastAPI routes. `app/charts.py`: chart renderers (inline SVG/HTML with CSS variables); every chart takes a `ReportData` (`app/chart_data.py`), EV sample in `app/fixtures/ev_sample.py`.
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
1. ~~Make `charts.py` take a data object instead of module-level EV sample data.~~ Done: see `app/chart_data.py`, `app/fixtures/ev_sample.py`.
2. Auth (use a proven provider; do not hand-roll password storage) and per-user project storage.
3. `POST /api/upload` for .xlsx/.csv and the column-profiling step ("Check columns" screen).
4. Text pipeline: ~~clean~~ (done 2026-09-20: `app/cleaning/`, `app/api_cleaning.py`, `/cleaning` screen), ~~embed, cluster, label with Claude, sentiment~~ (done 2026-09-25: `app/text_pipeline/`), ~~wire to storage, API and a screen~~ (done 2026-09-25: `app/api_themes.py`, `/report` screen - `Theme` rows, "Build themes" trigger, theme cards with "See answers" verbatim drill-down). Send text to a model only through `app/cleaning/payload.py:model_safe_samples`/`model_safe_column`.
5. ~~Findings engine and chart-selection rules (SPEC.md sections 4 and 9)~~ Done, first pass (2026-09-27): `app/findings.py` - `build_report_data`, `candidate_findings` (tone-contrast and dominant/long-tail kinds only; score/segment/date-driven kinds are step 3, below), `label_confidence`, `pick_chart`, `write_headline` (one batched Claude call), `build_findings` (writes `Finding`/`Report` rows). Wires real data into `overview`, `treemap`, `rank`, `sentsun` and `quality` from `app/charts.py`. Sub-theme wiring, and the score/segment/date-driven finding kinds, are not done - see `docs/DECISIONS.md` (2026-09-27 entry). The dynamic report layout itself (blocks, badges, filters, the HTTP layer for building/reading a report) is also still to build - `/report` currently shows theme cards only, not the full SPEC.md section 5 report.
