# Decision log (append only)

## 2026-09-20
- Main goal recorded in `docs/PROJECT_VISION.md`.
- Sign-in page: server rotates between designs A to D per visit, logged for comparison.
- Auth: Clerk custom flow. Database: Railway Postgres. Front end: React plus FastAPI JSON API.
- `app/charts.py` stays as the SVG source at first and is ported to JS only where needed.
