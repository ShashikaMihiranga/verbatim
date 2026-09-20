# Decision log (append only)

## 2026-09-20
- Main goal recorded in `docs/PROJECT_VISION.md`.
- Sign-in page: server rotates between designs A to D per visit, logged for comparison.
- Auth: Clerk custom flow. Database: Railway Postgres. Front end: React plus FastAPI JSON API.
- `app/charts.py` stays as the SVG source at first and is ported to JS only where needed.

## 2026-09-20 (foundation stream)
- `DATABASE_URL` values starting `postgres://` or `postgresql://` are rewritten to `postgresql+psycopg://` (psycopg 3 driver).
- Railway runs `alembic upgrade head` as `preDeployCommand`; `nixpacks.toml` adds Node so one image builds the frontend and serves it.
- Procfile kept as a fallback; `railway.json` also carries the start command.
- Extra tables columns beyond the brief: `datasets.filename/row_count`, `columns.kind/stats`, `themes.answer_refs` (row indexes, for the "link back to real answers" rule).
- No frontend test runner added (skipped to keep the scaffold small).

## 2026-09-20 (charts-to-data stream)
- Charts take a `ReportData` dataclass (`app/chart_data.py`); the EV sample lives in `app/fixtures/ev_sample.py` and is the default for `render()` so `/frame/<id>` is unchanged.
- Regression guard: full HTML of the 20 frames is committed in `tests/golden/` (about 330 KB) and compared byte for byte.
- Design constants (theme on-colours `TH_ON`, dim opacity, axis scales) stay in `charts.py`; only sample data moved. Demo view states (selected, hover) are data fields `selected_theme` / `hover_theme` so custom data never references EV theme names.
- `GET /api/charts/{id}` returns the full standalone document in `html` (same as `/frame/<id>`), plus width and height.
- `f_freq`, `f_phrases`, `f_quotes` are not in `FRAMES` (not among the 20); they take data too but are unregistered.
