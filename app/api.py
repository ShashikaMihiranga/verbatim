from fastapi import APIRouter
from sqlalchemy import text

from .db import engine

router = APIRouter(prefix="/api")


@router.get("/health")
def api_health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = True
    except Exception:
        db = False
    return {"status": "ok", "db": db}
