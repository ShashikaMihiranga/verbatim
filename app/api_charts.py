from fastapi import APIRouter, HTTPException

from .charts import FRAMES, TITLES, render, render_parts

router = APIRouter(prefix="/api/charts")


@router.get("")
def list_charts():
    return [{"id": k, "title": TITLES.get(k, k)} for k in FRAMES]


@router.get("/{chart_id}")
def get_chart(chart_id: str):
    if chart_id not in FRAMES:
        raise HTTPException(404, "Unknown chart")
    _, w, h = render_parts(chart_id)
    # html is the full standalone document, identical to /frame/<id>.
    return {"id": chart_id, "width": w, "height": h, "html": render(chart_id)}
