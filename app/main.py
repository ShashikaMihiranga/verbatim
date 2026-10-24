import logging
from pathlib import Path

from dotenv import load_dotenv

# `Settings` (config.py) uses pydantic-settings' own `env_file=".env"` to populate ITS fields (env,
# database_url, clerk_*) - but that loading is private to that one model, it never touches the process's
# actual os.environ. Every other config value in this app (VOYAGE_API_KEY, ANTHROPIC_API_KEY,
# TYPESAFE_API_KEY, ALLOW_DEV_USER, THEMES_DEADLINE_SECONDS, JEV_CLASSIFY_CONCURRENCY, ...) is read via
# plain os.environ.get(...) in whichever module needs it (embeddings.py, findings.py, jev_sentiment.py,
# auth.py, api_themes.py, other_classify.py), so none of those ever saw .env's values unless the launching
# shell had already exported them itself. python-dotenv was already a listed dependency for exactly this.
# load_dotenv() populates the real process environment (unlike pydantic-settings' private loading), so
# every os.environ.get(...) call anywhere benefits, with no other module needing a change - PROVIDED this
# runs before any of those modules are imported. `api_themes.py` and `other_classify.py` read several of
# these as MODULE-LEVEL constants (evaluated once, at import time, not per-call) - confirmed live,
# 2026-10-23: with this call placed after the `from .api_* import ...` lines below, THEMES_DEADLINE_SECONDS
# and JEV_CLASSIFY_CONCURRENCY silently kept their hardcoded defaults from `.env` alone (a shell that had
# already exported them worked purely by accident, which is why VOYAGE/ANTHROPIC/TYPESAFE keys - read
# lazily inside functions, not at import time - were never affected the same way). This call must stay
# the first thing this module does, before any local import.
# Safe in production: it never overrides a variable that's already set (Railway's own dashboard-configured
# env vars win), and does nothing at all when no .env file exists (true on every deploy - .env is
# git-ignored, never shipped).
load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .api import router as api_router  # noqa: E402
from .api_auth import router as auth_router  # noqa: E402
from .api_charts import router as charts_router  # noqa: E402
from .api_context import router as context_router  # noqa: E402
from .api_cleaning import router as cleaning_router  # noqa: E402
from .api_jobs import router as jobs_router  # noqa: E402
from .api_projects import router as projects_router  # noqa: E402
from .api_report import router as report_router  # noqa: E402
from .api_sharing import router as sharing_router  # noqa: E402
from .api_themes import router as themes_router  # noqa: E402
from .api_upload import router as upload_router  # noqa: E402
from .charts import FRAMES, render  # noqa: E402
from .config import get_settings  # noqa: E402
from .ratelimit import RateLimitMiddleware  # noqa: E402
from .security import SecurityHeadersMiddleware  # noqa: E402

# Without this, every `log.info(...)` call anywhere in this codebase (e.g. labeling.py's cluster-count/
# max_tokens line, clustering.py's noise-diagnostic line) is silently dropped - confirmed live, 2026-10-21:
# nothing in this process ever called `logging.basicConfig`, so the root logger's effective level stays
# at Python's own WARNING default, and INFO never reaches Railway's logs at all (only WARNING/ERROR did,
# via Python's own `lastResort` handler - which is exactly why `_retry_on_labeling_error`'s
# `log.warning(...)` calls were always visible but nothing at INFO ever was). `alembic upgrade head`
# configures its OWN logging via `alembic.ini`, but that runs as a separate `preDeployCommand` process
# before this one ever starts, so it has no effect here. Set once, at import time, before any router or
# background job can log anything.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_dev = get_settings().env == "dev"
app = FastAPI(
    title="Verbatim",
    docs_url="/docs" if _dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _dev else None,
)
app.add_middleware(RateLimitMiddleware)  # limits and size guards run before any route; 429 still gets security headers
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(api_router)
app.include_router(charts_router)
app.include_router(upload_router)
app.include_router(auth_router)
app.include_router(cleaning_router)
app.include_router(themes_router)
app.include_router(report_router)
app.include_router(context_router)
app.include_router(projects_router)
app.include_router(jobs_router)
app.include_router(sharing_router)

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/frame/{frame_id}", response_class=HTMLResponse)
def frame(frame_id: str):
    if frame_id not in FRAMES:
        raise HTTPException(404, "Unknown frame")
    return render(frame_id)


if (DIST / "index.html").exists():
    # Built React app: static assets plus SPA fallback (registered last, so API/frame/health win).
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.split("/")[0] in ("api", "frame", "health"):
            raise HTTPException(404)
        file = (DIST / path).resolve()
        if path and file.is_file() and DIST in file.parents:
            return FileResponse(file)
        return FileResponse(DIST / "index.html")
else:

    @app.get("/", response_class=HTMLResponse)
    def index():
        links = "".join(f'<li><a href="/frame/{k}">{k}</a></li>' for k in FRAMES)
        return f"<!doctype html><title>Verbatim</title><body style='font-family:sans-serif;padding:32px'><h1>Verbatim</h1><ul>{links}</ul></body>"
