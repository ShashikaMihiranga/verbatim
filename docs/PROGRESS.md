# Verbatim: progress and how to resume

Last updated: 2026-09-21. Read `docs/PROJECT_VISION.md` first (the goal), then this file, then `SPEC.md`.

## Where things are
- Repo: https://github.com/ShashikaMihiranga/verbatim (private), branch `main`. Local folder: `~/Desktop/Open Ended Response Visualation/verbatim-app`.
- Live app: https://web-production-ea707.up.railway.app (Railway, Docker build). Health check `/health`.
- Tests at last check: 314 backend (`.venv/bin/python -m pytest -q`), 8 front end (`cd frontend && npm test`). Front end builds and lints clean.

## Build streams
| # | Stream | Status |
|---|---|---|
| 1 | Foundation (Git, pinned deps, Postgres models, Alembic, React scaffold, Railway config) | Done |
| 2 | Charts take a data object (`app/chart_data.py`, `app/fixtures/ev_sample.py`, `/api/charts`) | Done |
| 3 | Clerk sign-in, designs A to D rotate per visit | Built and tested with fake keys only. Never run against a real Clerk app |
| 4 | Upload and column profiling, Upload and Check columns screens | Done. Screens never viewed in a browser |
| 5 | Adaptive cleaning, PII masking, rate limiting, formula guard | Done. Cleaning screen never viewed in a browser |
| 6 | Text pipeline: embed, cluster, label with Claude, sentiment, verbatim drill-down | Not started. Needs an `ANTHROPIC_API_KEY` |
| 7 | Findings engine and chart selection (SPEC sections 4 and 9) | Not started |
| 8 | Dynamic report UI from the `report-*` designs | Not started |
| 9 | Final review, hardening, deploy checks | Ongoing |

## Railway state (what still needs doing)
The build was fixed by switching from Nixpacks to `Dockerfile` (Nixpacks had Node 22.10 and skipped rolldown's native binding). The start command in `railway.json` is wrapped in `sh -c` so `$PORT` expands. After the last push the deploy had not yet been confirmed healthy.

Variables still to set on the `web` service:
- `VITE_CLERK_PUBLISHABLE_KEY`: the `pk_` key from Clerk (build time, so redeploy after).
- `CLERK_FRONTEND_API`, `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_AUTHORIZED_PARTIES`: see "Set up Clerk" in README. The Clerk Account Portal is `saved-pug-286.accounts.dev`; the Frontend API host is probably `saved-pug-286.clerk.accounts.dev`. Not yet confirmed: open `https://<host>/.well-known/jwks.json` and check it returns `{"keys":[`.
- `TRUST_PROXY=true`. Also check whether Railway appends or replaces `X-Forwarded-For`; if it appends, set `PROXY_XFF_POSITION=last`.
- `DATABASE_URL=${{Postgres.DATABASE_URL}}` after adding a Postgres service.
- In Clerk: allow the Railway origin and `/sso-callback`.
- Never set `ALLOW_DEV_USER` in production. Never add the Clerk secret key (`sk_`) anywhere.
- ~~Uploaded files sit on the container disk and vanish on redeploy. Add a Railway volume and set `UPLOAD_DIR` before real use.~~ Fixed (2026-09-27): uploaded/cleaned file bytes now live in Postgres (`uploaded_files`/`cleaned_files`), which already survives redeploys. No volume needed - see docs/DECISIONS.md.

Until Clerk is configured, every data route answers 401 by design.

## Known weaknesses (be honest about these)
- Name and address masking catches perhaps a third to a half of names in free text. It is a helper, not a guarantee.
- Long digit strings in text columns are masked as phone numbers.
- Cleaning heuristics are English-first. Only Spanish, French, German and Portuguese non-answer lists exist.
- Column profiler was tested on fixtures written with its own rules. Real files will expose gaps (small whole-number columns, day/month order, two-row headers).
- Rate limiting is per server instance. Scaling out needs Redis.
- The sign-in comparison only counts how often each design is shown, not which converts. No second-factor path.
- The Clerk screens, CSP against real Clerk hosts, and visual match to the designs are unchecked.
- Export downloads do not exist yet. When added, pass output through `app/cleaning/export.py` (`csv_safe_frame`).

## How to resume
```
cd "/Users/shashikamihiranga/Desktop/Open Ended Response Visualation/verbatim-app"
git pull
python3 -m venv .venv && source .venv/bin/activate     # only if .venv is missing
pip install -r requirements.txt -r requirements-dev.txt
ENV=dev ALLOW_DEV_USER=true uvicorn app.main:app --reload   # backend on :8000
cd frontend && npm ci && npm run dev                        # front end with proxy
```
Suggested first message to Claude: "Read docs/PROJECT_VISION.md and docs/PROGRESS.md, check the Railway deploy is healthy, then continue with the next step."

Next steps, in order:
1. Confirm the Railway deploy is Active and the home page loads. Set the variables above.
2. Test sign-up and sign-in in a real browser. Fix any blocked hosts named in the console (CSP).
3. Look at the Upload, Check columns and Cleaning screens in a browser with a real spreadsheet.
4. Stream 6: text pipeline. Send text to a model only through `app/cleaning/payload.py:model_safe_samples`.
5. Streams 7 and 8: findings engine and the dynamic report.

## Working method that worked
- One sub-agent per stream, each in its own git worktree with a written brief. Verify its tests yourself, review security-sensitive code, then merge.
- macOS `sed -i` chokes on some scripts. Use `python3` to edit files, and do not chain a commit after an edit with `&&` unless the edit is proven.
- Decisions go in `docs/DECISIONS.md`.
