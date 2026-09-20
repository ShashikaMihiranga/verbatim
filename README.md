# Verbatim

Project goal and decisions: [docs/PROJECT_VISION.md](docs/PROJECT_VISION.md).

Open-ended survey answers to themes, sentiment and charts. See [SPEC.md](SPEC.md) for the product plan.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. Each chart is served at `/frame/<id>` (for example `/frame/sunburst`).

## Layout

- `app/charts.py`: chart renderers. Each `f_*` function returns HTML with inline SVG, using the CSS variables in `CSS`. Data is still the EV sample at the top of the file.
- `app/main.py`: FastAPI routes.
- `railway.json` and `Procfile`: Railway start command and health check (`/health`).

## Next steps

1. Move the sample data out of `charts.py` into an input object, so every `f_*` takes `data` as an argument.
2. Add `POST /api/analyze` (upload, clean, embed, cluster, label).
3. Add the chart-selection engine from SPEC.md section 4.

## Deploy to Railway

1. Push this folder to a GitHub repo.
2. In Railway: New Project, Deploy from GitHub repo, choose the repo.
3. Railway reads `railway.json`, builds with Nixpacks and starts uvicorn on `$PORT`.
4. Settings, Networking, Generate Domain.
5. When the analysis step arrives, add `ANTHROPIC_API_KEY` under Variables. Never commit it.
