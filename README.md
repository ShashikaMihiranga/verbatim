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

`POST /api/upload` (.csv, .xlsx, .xls), `GET /api/datasets/{id}/profile`, `PATCH /api/datasets/{id}/columns`. The profiler in `app/profiling/` guesses each column's kind, unit and sensitivity and reports what it cleaned; the user confirms on the Check columns screen (`/upload`, `/check-columns`). Settings (environment): `UPLOAD_DIR` (default `~/.verbatim/uploads`), `MAX_UPLOAD_MB` (default 50). Optional: set `ANTHROPIC_API_KEY` (and `pip install anthropic`) to let Claude refine the guesses from headers and about 30 samples per column; without it nothing leaves the server. Every data route needs a signed-in user (see "Set up Clerk").

## Adaptive cleaning

After Check columns the app proposes a cleaning plan that fits the data, shows what it did, and only then continues (`/cleaning`). `app/cleaning/` holds a planner (`plan_cleaning(df, profile)`) and executor (`apply_plan(df, plan)`); each step is a small function with a plain-English description, counts and before/after examples. A file with no text column gets no text steps, and thresholds (repeat limit, keyboard-mash vowel cut-off, length outliers, score scale, typo match level, tiny-group size) are worked out from the data.

- API (owner only, same sign-in and ownership check as uploads): `POST /api/datasets/{id}/clean/plan` (plan plus preview report), `PATCH .../clean/plan` (toggle steps, edit merge tables, set scale, date order or tiny-group size), `POST .../clean/apply` (writes `UPLOAD_DIR/<sha256>.clean.csv` next to the untouched original), `GET .../clean/report`. The plan and report are stored in `datasets.profile["cleaning"]` (no migration).
- Nothing is silent: removed rows are listed by number with the step and reason, and `accounted_for` is true only when rows in minus rows out equals the listed removals. Impossible dates are blanked and flagged (original kept in `_verbatim_flags`), outliers are flagged and kept, ID and junk columns are excluded from analysis but never deleted. A score scale read from the column header ("0-10", "out of 5") or set by you may blank out-of-range answers; a scale guessed only from the answers never does, it flags them and asks you to confirm the scale. A repeated long answer is flagged, not removed; only a row identical in every column is removed (and listed).
- Personal details in text (emails, phone numbers including bare digit runs, links, obvious ID numbers) are masked by `app/cleaning/redact.py`, on by default and reviewable. Names and street addresses are masked on a best-effort basis only (a name after "my name is", "I'm", "Dr" and so on; number plus street name plus Street/Rd/Ave; AU, US and UK postcodes), and the report warns when a text column still looks like it holds names. This is a heuristic, not a guarantee: a name with no cue, a lowercase address or a non-English cue is missed. Send text to a model only through `app/cleaning/payload.py`, which masks again.
- Non-English text: keyboard-mash rules are skipped for answers with non-ASCII letters, and non-answers include common Spanish, French, German and Portuguese phrases; you can add your own terms in the review step.
- Downloads: never serve the internal `.clean.csv` directly. Use `app/cleaning/export.py` (`csv_safe_frame` / `csv_safe_bytes`), which prefixes cells starting with `=`, `+`, `-`, `@`, tab or carriage return with a quote so a spreadsheet cannot run them as formulas.
- Sensitive columns: groups under `MIN_GROUP_SIZE` (default 30) are marked hidden with counts withheld, and no examples or raw rows of those columns appear in any report.
- Limits (environment): `CLEAN_MAX_ROWS` (200000), `CLEAN_MAX_COLUMNS` (300), `CLEAN_TIMEOUT_SECONDS` (30), `CLEAN_CONCURRENCY` (2 jobs at once, then 429). Fuzzy matching uses `rapidfuzz` (pinned).

## Text pipeline: embeddings and clustering

`app/text_pipeline/` turns a cleaned open-ended column into themes: `embed_and_cluster(clean_df, plan, column, client)` (`pipeline.py`) reads every answer through `app.cleaning.payload.model_safe_column` (the masked, full-column sibling of `model_safe_samples`, which only returns a capped sample), embeds the non-empty ones, and clusters the vectors with scikit-learn's `HDBSCAN` (`clustering.py`) - no LLM involved in clustering itself. `embeddings.py` defines the `EmbeddingClient` interface: `VoyageEmbeddingClient` is the real, network-backed implementation (Voyage AI), and `FakeEmbeddingClient` is a deterministic, hash-based stand-in used everywhere in tests so the suite never touches the network. `min_cluster_size` is picked adaptively from the answer count (roughly one theme per 50 answers, clamped to 5-50) unless a caller overrides it. Answers HDBSCAN cannot confidently place become `ClusterResult.noise`, never silently dropped; labelling clusters with Claude, sentiment and verbatim drill-down are the next streams, built on `ClusterResult` (`schema.py`).

`VOYAGE_API_KEY` is **optional but required to run** the real embedding client - never a build variable, never committed. Without it, `VoyageEmbeddingClient()` raises `EmbeddingNotConfigured` immediately, before any network call; the rest of the app (including all tests) works with no key set at all, using `FakeEmbeddingClient` instead. Optional: `VOYAGE_MODEL` overrides the embedding model (default `voyage-3.5`).

### Jev sentiment trial (optional)

`app/text_pipeline/jev_sentiment.py` and `sentiment.score_column_with_jev` offer a second, **opt-in only** way to score an answer's tone, using Jev, an AI model from TypeSafe AI. This is a narrow, approved trial scoped to sentiment scoring alone - nothing else in the app calls Jev, and nothing calls it automatically; a caller has to choose `score_column_with_jev` explicitly over the default `score_column`. The free lexicon scorer (`score_text`/`score_column`) remains the default, runs for every answer with zero external calls, and needs no key at all.

`TYPESAFE_API_KEY` is **optional**, a runtime variable only (never a build variable, never committed). Without it, `HttpJevClient()` raises `JevNotConfigured` immediately, before any network call; tests use `FakeJevClient` instead, so the suite never touches the network. Get a key only from **console.typesafe.ai** - no other site issues valid keys for this service.

## Build themes

`app/api_themes.py` wires the text pipeline above to storage and an owner-only API, and `/report` (after `/cleaning`) is the screen: pick the confirmed open-text column, "Build themes", then theme cards (label, one-line description, share of answers, a tone bar) each with "See answers" for the real verbatim text behind that theme.

- API: `POST /api/datasets/{id}/themes/build` (`{"column": str, "use_jev_sentiment": bool = false}`) embeds, clusters, labels and scores the column, replacing any themes already stored for that dataset + column; `GET /api/datasets/{id}/themes?column=...` lists them; `GET /api/datasets/{id}/themes/{tid}/answers?limit=&offset=` returns paginated, **real, unmasked** cleaned text for the rows behind one theme (the dataset owner viewing their own answers, not a boundary to a model - `model_safe_column` is not used there).
- Needs both `VOYAGE_API_KEY` and `ANTHROPIC_API_KEY` set; either missing gives a clear `503`, before any network call, never a generic error. `use_jev_sentiment: true` additionally needs `TYPESAFE_API_KEY` (same clear `503` if missing) and replaces the free lexicon with Jev's per-row tone classifier for that build.
- This can be slow: a real build does an embedding call plus one batched Claude call over the whole column, so `THEMES_CONCURRENCY` (default 1) caps concurrent jobs and `THEMES_DEADLINE_SECONDS` (default 300) is a soft per-request deadline - see `docs/DECISIONS.md` (2026-09-25) for why it is soft, not a hard kill. The `/report` screen says up front that this can take a minute or two.

## Set up Clerk

Sign-in uses Clerk with our own screens (custom flow). The backend only needs Clerk's public key list; the Clerk **secret key is not used anywhere** and must never be added to this repo, the frontend or Railway variables for this app.

1. Create an application at https://dashboard.clerk.com. Under User & authentication, enable Email (with password and email verification code), Google and Microsoft. Turn on bot protection (Attack protection) if you want it.
2. Under API keys, copy the **Publishable key** (starts with `pk_`; it is public by design). In Railway, add it as a **build variable** named `VITE_CLERK_PUBLISHABLE_KEY` (Vite bakes it in at build time, so redeploy after setting it). Without it the app still runs and shows "Sign-in is not configured yet".
3. Find your Frontend API host (Configure, Domains, or the decoded publishable key; it looks like `xxxx.clerk.accounts.dev` in development or `clerk.yourdomain.com` in production). In Railway, set these service variables:
   - `CLERK_FRONTEND_API` = that host only (no `https://`). Used for the Content-Security-Policy.
   - `CLERK_JWKS_URL` = `https://<frontend-api-host>/.well-known/jwks.json`
   - `CLERK_ISSUER` = `https://<frontend-api-host>` (must match the token `iss` exactly, no trailing slash)
   - `CLERK_AUTHORIZED_PARTIES` = your public site origin(s), comma separated, e.g. `https://your-app.up.railway.app` (checked against the token `azp` claim; set it, since it blocks tokens minted for other sites)
4. Add your Railway domain to Clerk's allowed origins / redirect URLs, including `/sso-callback` (Google and Microsoft return there).
5. Redeploy, then open `/sign-up`, create an account, enter the emailed code, and confirm you land on `/upload`. `GET /api/me` with a valid token returns your user id.

Rules to keep: **`ALLOW_DEV_USER` must never be set on Railway.** The shared dev user only works when `ENV=dev` and `ALLOW_DEV_USER=true` together, and production ignores it. If `CLERK_JWKS_URL` or `CLERK_ISSUER` is missing, every data route answers 401 (fail closed). Optional: `SIGNIN_VARIANT_WEIGHTS` (for example `a=1,b=1,c=2,d=1`) changes how often each sign-in design (A to D) is shown; each visit is counted in `signin_variant_log` (variant and time only, no IP or browser data). Note: "Keep me signed in" is not shown because Clerk sets session length in its dashboard.

Local development without Clerk: `ENV=dev ALLOW_DEV_USER=true uvicorn app.main:app --reload` uses one shared dev user and the sign-in pages show "not configured". Frontend tests: `cd frontend && npm test`.
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

## Deploy to Railway (Docker build)

Railway builds with the `Dockerfile` (front end on Node 22, runtime on Python 3.12). Nixpacks is no longer used, because its Node was too old for Vite 8 and skipped the native build engine.

- Build variable: `VITE_CLERK_PUBLISHABLE_KEY` (Railway passes service variables to the Dockerfile `ARG`).
- Runtime variables: see "Set up Clerk", plus `DATABASE_URL`, and `TRUST_PROXY=true`.
- Migrations run before each deploy (`preDeployCommand` in `railway.json`).
- Uploaded files live in the container's disk and are lost on redeploy. Attach a Railway volume and set `UPLOAD_DIR` to its mount path before real use.
