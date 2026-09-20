from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .charts import FRAMES, render

app = FastAPI(title="Verbatim")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    links = "".join(f'<li><a href="/frame/{k}">{k}</a></li>' for k in FRAMES)
    return f"<!doctype html><title>Verbatim</title><body style='font-family:sans-serif;padding:32px'><h1>Verbatim</h1><ul>{links}</ul></body>"


@app.get("/frame/{frame_id}", response_class=HTMLResponse)
def frame(frame_id: str):
    if frame_id not in FRAMES:
        raise HTTPException(404, "Unknown frame")
    return render(frame_id)
