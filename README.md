# Verbatim

Project goal and decisions: [docs/PROJECT_VISION.md](docs/PROJECT_VISION.md).

Open-ended survey answers to themes, sentiment and charts. See [SPEC.md](SPEC.md) for the product plan.

## Run locally

Backend (Python 3.12):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # optional; defaults to sqlite:///./dev.db
alembic upgrade head            # create/upgrade tables
uvicorn app.main:app --reload   # http://localhost:8000
```

Frontend (Node 22+), in a second terminal. Vite proxies `/api` and `/frame` to port 8000:

```bash
cd frontend && npm ci && npm run dev   # http://localhost:5173
```

If `frontend/dist` exists (`npm run build`), FastAPI serves it at `/` with SPA fallback; otherwise `/` shows the chart index. Each chart is at `/frame/<id>` (for example `/frame/sunburst`).

Tests: `pytest`. New migration after editing `app/models.py`: `alembic revision --autogenerate -m "message"`.

## Upload and column profiling

`POST /api/upload` (.csv, .xlsx, .xls), `GET /api/datasets/{id}/profile`, `PATCH /api/datasets/{id}/columns`. The profiler in `app/profiling/` guesses each column's kind, unit and sensitivity and reports what it cleaned; the user confirms on the Check columns screen (`/upload`, `/check-columns`). Settings (environment): `UPLOAD_DIR` (default `~/.verbatim/uploads`), `MAX_UPLOAD_MB` (default 50). Optional: set `ANTHROPIC_API_KEY` (and `pip install anthropic`) to let Claude refine the guesses from headers and about 30 samples per column; without it nothing leaves the server. Auth is a dev stub until Clerk lands.

## Adaptive cleaning

After Check columns the app proposes a cleaning plan that fits the data, shows what it did, and only then continues (`/cleaning`). `app/cleaning/` holds a planner (`plan_cleaning(df, profile)`) and executor (`apply_plan(df, plan)`); each step is a small function with a plain-English description, counts and before/after examples. A file with no text column gets no text steps, and thresholds (repeat limit, keyboard-mash vowel cut-off, length outliers, score scale, typo match level, tiny-group size) are worked out from the data.

- API (owner only, same sign-in and ownership check as uploads): `POST /api/datasets/{id}/clean/plan` (plan plus preview report), `PATCH .../clean/plan` (toggle steps, edit merge tables, set scale, date order or tiny-group size), `POST .../clean/apply` (writes `UPLOAD_DIR/<sha256>.clean.csv` next to the untouched original), `GET .../clean/report`. The plan and report are stored in `datasets.profile["cleaning"]` (no migration).
- Nothing is silent: removed rows are listed by number with the step and reason, and `accounted_for` is true only when rows in minus rows out equals the listed removals. Impossible dates are blanked and flagged (original kept in `_verbatim_flags`), outliers are flagged and kept, ID and junk columns are excluded from analysis but never deleted. A score scale read from the column header ("0-10", "out of 5") or set by you may blank out-of-range answers; a scale guessed only from the answers never does, it flags them and asks you to confirm the scale. A repeated long answer is flagged, not removed; only a row identical in every column is removed (and listed).
- Personal details in text (emails, phone numbers including bare digit runs, links, obvious ID numbers) are masked by `app/cleaning/redact.py`, on by default and reviewable. Names and street addresses are masked on a best-effort basis only (a name after "my name is", "I'm", "Dr" and so on; number plus street name plus Street/Rd/Ave; AU, US and UK postcodes), and the report warns when a text column still looks like it holds names. This is a heuristic, not a guarantee: a name with no cue, a lowercase address or a non-English cue is missed. Send text to a model only through `app/cleaning/payload.py`, which masks again.
- Non-English text: keyboard-mash rules are skipped for answers with non-ASCII letters, and non-answers include common Spanish, French, German and Portuguese phrases; you can add your own terms in the review step.
- Downloads: never serve the internal `.clean.csv` directly. Use `app/cleaning/export.py` (`csv_safe_frame` / `csv_safe_bytes`), which prefixes cells starting with `=`, `+`, `-`, `@`, tab or carriage return with a quote so a spreadsheet cannot run them as formulas.
- Sensitive columns: groups under `MIN_GROUP_SIZE` (default 30) are marked hidden with counts withheld, and no examples or raw rows of those columns appear in any report.
- Limits (environment): `CLEAN_MAX_ROWS` (200000), `CLEAN_MAX_COLUMNS` (300), `CLEAN_TIMEOUT_SECONDS` (30), `CLEAN_CONCURRENCY` (2 jobs at once, then 429). Fuzzy matching uses `rapidfuzz` (pinned).

## Rate limiting and request size (public deployment)

`app/ratelimit.py` is a pure ASGI middleware, registered in `app/main.py`. Per client IP and minute: 120 requests for `/api` overall, 10 for `POST /api/upload`, 30 for `/api/signin-variant` and `/api/auth*`, 300 for everything else; `/health` is exempt. Over the limit it answers 429 with `Retry-After` and a generic JSON body. Environment: `RATE_LIMIT_API_PER_MIN`, `RATE_LIMIT_UPLOAD_PER_MIN`, `RATE_LIMIT_AUTH_PER_MIN`, `RATE_LIMIT_OTHER_PER_MIN`, `RATE_LIMIT_WINDOW_SECONDS`, `RATE_LIMIT_MAX_KEYS` (50000), `RATE_LIMIT_ENABLED` (default true).

- Set `TRUST_PROXY=true` on Railway so the client IP comes from `X-Forwarded-For` (first address; `PROXY_XFF_POSITION=last` if the platform appends to a client-supplied header). Without it the header is ignored and the socket address is used, so a spoofed header cannot dodge a limit. Leave it off for local runs.
- Body size: `POST /api/upload` with a `Content-Length` above `MAX_UPLOAD_MB` + 1 MB gets 413 before the body is read (the streaming check in the upload route stays); other `/api` bodies above `MAX_API_BODY_KB` (1024) get 413.
- Per instance only: counters live in process memory, so with several instances or workers each keeps its own and a client can get N times the limit. When scaling out, move the counters to Redis (INCR plus EXPIRE per client and bucket) and keep the rules; a coarse limit at the platform edge also helps.

## Layout

- `app/charts.py`: chart renderers. Each `f_*(data: ReportData)` returns HTML with inline SVG, using the CSS variables in `CSS`; `render(frame_id, data=None)` defaults to the EV sample.
- `app/chart_data.py`: typed data classes (`ReportData`, `ThemeNode`, ...) that charts read. `app/fixtures/ev_sample.py`: the EV sample as a `ReportData`. `app/api_charts.py`: `GET /api/charts` and `GET /api/charts/{id}`.
- `tests/golden/*.html`: byte-for-byte snapshots of the 20 frames on the EV sample (regression guard in `tests/test_charts_data.py`).
- `app/main.py`: FastAPI routes and static serving. `app/api.py`: JSON API under `/api`. `app/config.py`, `app/db.py`, `app/models.py`: settings, SQLAlchemy, tables. `migrations/`: Alembic. `frontend/`: React + Vite + TypeScript.
- `railway.json` (build, pre-deploy migration, start, health check `/health`), `nixpacks.toml` (adds Node), `Procfile` (fallback start command).

## Next steps

1. Add `POST /api/analyze` (upload, clean, embed, cluster, label).
2. Add the chart-selection engine from SPEC.md section 4.

## Deploy to Railway

1. Push this folder to a GitHub repo.
2. In Railway: New Project, Deploy from GitHub repo, choose the repo.
3. Railway reads `railway.json`, builds Python deps and the frontend with Nixpacks, runs `alembic upgrade head`, and starts uvicorn on `$PORT`. Add a Postgres service and set `DATABASE_URL` (reference variable).
4. Settings, Networking, Generate Domain.
5. When the analysis step arrives, add `ANTHROPIC_API_KEY` under Variables. Never commit it.
