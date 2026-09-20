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
## 2026-09-20 (upload + profiling stream)
- Dataframe library: pandas (with openpyxl for .xlsx, xlrd for .xls). CSVs are read with the stdlib `csv` module into rows first, so ragged rows, title rows above the header and odd delimiters cannot break the parser. Pinned in `requirements.txt`, plus `python-multipart` for uploads.
- Column kinds are `open_text, short_text, score, date, segment, numeric, yes_no, id_or_junk` (SPEC sections 3 and 9.1). `columns.kind` now stores these values (the old comment listing text/number/category/id/ignore in `app/models.py` is superseded). No migration needed: the user's confirmed choices live in `datasets.profile["confirmed"]` and in `columns.kind` / `columns.stats` (`off`, `sensitive`, `unit`, `guessed_kind`).
- Nothing is silent: the loader writes what it changed (skipped rows, blank rows, "n/a" cells turned blank, encoding, delimiter) to `profile["notes"]` and the Check columns screen lists it.
- Files are stored as `UPLOAD_DIR/<sha256><ext>` (default `~/.verbatim/uploads`, outside the repo). File names from users are display-only and sanitized. Same hash for the same user reuses the existing dataset record. `MAX_UPLOAD_MB` defaults to 50. Zip-bomb check for .xlsx (uncompressed size and ratio), row cap 500,000, column cap 300.
- Sensitive flag (age, sex/gender, income, and similar) is set by column name and by values. Sample values for sensitive columns are limited to 3 common values, and are never sent to Claude.
- `app/profiling/claude_hook.py` calls Anthropic only when `ANTHROPIC_API_KEY` is set (headers plus up to 30 distinct samples per column, one call, model `claude-haiku-4-5`, override with `VERBATIM_CLAUDE_MODEL`). The `anthropic` package is imported lazily and is not in requirements.
- `current_user()` in `app/api_upload.py` is a dev-user stub to be replaced by the Clerk dependency (stream 3).
## 2026-09-20 (adaptive cleaning stream)
- Cleaning lives in `app/cleaning/` (planner `plan_cleaning`, executor `apply_plan`, `redact.py`, `payload.py`) with routes in `app/api_cleaning.py`. The plan is built by running steps in order on a working copy, so thresholds and merge tables reflect the data at that point and steps that would change nothing are omitted (only `mask_pii`, `exclude_columns`, `check_score_range` and `parse_dates` are always listed, so the user sees the scale and date order we assumed).
- Storage: plan and report are JSON in `datasets.profile["cleaning"]`; no new column or migration. The cleaned copy is `UPLOAD_DIR/<sha256 of its bytes>.clean.csv`; the original is never modified. User edits are stored as `plan.overrides` and the plan is rebuilt from the data on every PATCH, so the preview always matches what apply will do.
- Non-answers, keyboard mash and out-of-range scores blank the cell, not the row: the row's other columns still count. Rows are removed only when completely empty, or as exact repeats of a long open-ended answer (default on, length limit from the data, min 3 and max 10 words; short answers like "Price" are never collapsed). Every removed row is listed by number, step and reason; `accounted_for` checks rows in minus rows out.
- Identical whole rows are reported and flagged, not removed (no ID column means we cannot tell a double submission from two people).
- Fuzzy matching: `rapidfuzz==3.14.6` (ratio cut-off 86/90/93 depending on how many distinct answers there are, plus a one-letter-typo rule when there are 300 or fewer; guards against digit differences and one- or two-letter tokens such as Model X vs Model Y). The merge table is the source of truth: apply uses exactly the table the user reviewed.
- Dates: numeric d/m/y is classified per value. A first number above 12 proves day first, a second above 12 proves month first; if the file has neither, ambiguous dates are read month first, flagged, and a warning says so. Impossible dates (31/02) are blanked and flagged, not repaired.
- Scores: scale chosen from 1-5, 0-5, 1-7, 0-10, 1-10 as the smallest scale covering at least 95% of values (2% tolerance); it is editable. Numbers: "1,234" is read as one thousand two hundred thirty-four; "1.234,56" and "12,5" are read European style.
- PII masking (emails, phones, links, Luhn-valid cards, SSN-style and 9 to 15 digit runs) is regex based with bounded quantifiers, on by default, and `model_safe_samples` masks again and refuses sensitive columns. Names and street addresses are NOT detected; that needs a model or NER and is out of scope for now.
- Suppression: sensitive columns get `groups` metadata with `hidden: true` and `count: null` under `MIN_GROUP_SIZE` (default 30, env). No examples are produced for sensitive columns, and merge tables hide counts under the minimum.
- Public-app hardening: owner check via `_own_dataset`, row (200k) and column (300) caps, a 30 second deadline checked between steps and every 2,000 distinct values, at most 2 concurrent cleaning jobs (429 after that), request bodies validated with `extra=forbid` and size limits, only whitelisted params editable, cleaned file named from its hash, nothing evaluated. Examples are returned as JSON strings with control and bidi characters removed; the UI renders them as text.
- Known gap: the cleaned CSV can contain cells starting with `=`, `+`, `-` or `@`. There is no download route yet; when one is added, prefix such cells or export with a formula guard.

## 2026-09-20 (auth stream)
- Auth is Clerk with a custom flow (`@clerk/clerk-react` 5.61.10 hooks: `useSignIn`, `useSignUp`, `useAuth`, `useClerk`), styled to our designs. Google and Microsoft use `authenticateWithRedirect` with `/sso-callback`. Only the publishable key (`VITE_CLERK_PUBLISHABLE_KEY`, build time) is in the frontend; the Clerk secret key is not used anywhere.
- Backend (`app/auth.py`) verifies `Authorization: Bearer <jwt>` with PyJWT 2.14.0: RS256 only (checked from the header before any key lookup, so `none`, HS* and other algorithms are refused), signature against the JWKS at `CLERK_JWKS_URL`, `iss` equal to `CLERK_ISSUER`, `exp` required, `nbf` checked, 10 s leeway, `azp` must be in `CLERK_AUTHORIZED_PARTIES` when that is set, Clerk `sts` must be active if present. The JWKS is cached for an hour and an unknown `kid` can refetch at most once a minute (junk tokens cannot make us hammer Clerk). `CLERK_JWKS_URL` must be https outside dev.
- Every failure is the same 401 `{"detail":"Sign-in is required."}`; the real reason is logged at info level on the server. Missing Clerk settings in production also give 401 (fail closed).
- `token.sub` maps to `users.clerk_id`; the row is created on first sight (a race on the unique key is retried). `current_user` in `app/api_upload.py` keeps its name and now calls `app.auth.authenticate`. The dev user requires `ENV=dev` and `ALLOW_DEV_USER=true`; `tests/conftest.py` sets both by monkeypatch.
- `GET /api/me` returns `{id, email?}`; email only if the token carries an `email` claim (Clerk session tokens omit it unless a custom claim is added in the Clerk dashboard).
- Dynamic sign-in: `GET /api/signin-variant` picks a, b, c or d at random (`SIGNIN_VARIANT_WEIGHTS`, default equal) and writes `signin_variant_log(variant, created_at)`, nothing else. The client keeps the choice in `sessionStorage` for the tab session so a refresh does not re-roll or re-count. The optional outcome endpoint was NOT built: the table has no outcome column and adding one needs a migration; revisit when the designs are compared.
- The four designs share one form component; only the layout and decorative side panel (`frontend/src/auth/SidePanel.tsx`) differ.
- CSP (`app/security.py`): when `CLERK_FRONTEND_API` is a plain host name, `https://<host>` is added to script-src, connect-src, frame-src and img-src; `https://img.clerk.com` to img-src; `https://challenges.cloudflare.com` to script-src, frame-src and connect-src; and `worker-src 'self' blob:` (Clerk's script uses a blob worker). No `unsafe-inline` or `unsafe-eval` for scripts. Invalid values are ignored so the variable cannot inject directives.
- Error wording never reveals whether an email has an account: unknown email and wrong password both say "Email or password is not right."; the reset flow shows the code step whatever the answer; sign-up with an existing email gets a neutral message.
- Frontend `authFetch` (`frontend/src/authFetch.ts`) adds the Clerk session token to every `/api` call (uploads use XHR and set the header too) and sends the user to `/sign-in` on a 401. `/projects`, `/upload`, `/check-columns`, `/cleaning`, `/report` redirect to `/sign-in` when signed out.
- Vitest added for the password rules, the variant parser and the side panels.

