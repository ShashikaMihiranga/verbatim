from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .api_charts import router as charts_router
from .api_cleaning import router as cleaning_router
from .api_upload import router as upload_router
from .charts import FRAMES, render
from .config import get_settings
from .security import SecurityHeadersMiddleware

_dev = get_settings().env == "dev"
app = FastAPI(
    title="Verbatim",
    docs_url="/docs" if _dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _dev else None,
)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(api_router)
app.include_router(charts_router)
app.include_router(upload_router)
app.include_router(cleaning_router)

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
