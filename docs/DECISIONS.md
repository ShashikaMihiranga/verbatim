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

## 2026-09-20 (upload + profiling stream)
- Dataframe library: pandas (with openpyxl for .xlsx, xlrd for .xls). CSVs are read with the stdlib `csv` module into rows first, so ragged rows, title rows above the header and odd delimiters cannot break the parser. Pinned in `requirements.txt`, plus `python-multipart` for uploads.
- Column kinds are `open_text, short_text, score, date, segment, numeric, yes_no, id_or_junk` (SPEC sections 3 and 9.1). `columns.kind` now stores these values (the old comment listing text/number/category/id/ignore in `app/models.py` is superseded). No migration needed: the user's confirmed choices live in `datasets.profile["confirmed"]` and in `columns.kind` / `columns.stats` (`off`, `sensitive`, `unit`, `guessed_kind`).
- Nothing is silent: the loader writes what it changed (skipped rows, blank rows, "n/a" cells turned blank, encoding, delimiter) to `profile["notes"]` and the Check columns screen lists it.
- Files are stored as `UPLOAD_DIR/<sha256><ext>` (default `~/.verbatim/uploads`, outside the repo). File names from users are display-only and sanitized. Same hash for the same user reuses the existing dataset record. `MAX_UPLOAD_MB` defaults to 50. Zip-bomb check for .xlsx (uncompressed size and ratio), row cap 500,000, column cap 300.
- Sensitive flag (age, sex/gender, income, and similar) is set by column name and by values. Sample values for sensitive columns are limited to 3 common values, and are never sent to Claude.
- `app/profiling/claude_hook.py` calls Anthropic only when `ANTHROPIC_API_KEY` is set (headers plus up to 30 distinct samples per column, one call, model `claude-haiku-4-5`, override with `VERBATIM_CLAUDE_MODEL`). The `anthropic` package is imported lazily and is not in requirements.
- `current_user()` in `app/api_upload.py` is a dev-user stub to be replaced by the Clerk dependency (stream 3).
