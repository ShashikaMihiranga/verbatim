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
