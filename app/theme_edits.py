"""Undo for the theme editor (design/handoffs/ThemeEditor_UIHandoff.md, "Undo and edits").

Every edit route snapshots the `Theme` rows it is about to change (`snapshot`), makes its change, and
records it (`record`) in the same transaction. Undo puts the snapshots back (same ids, every column),
deletes the rows the edit created, and marks it undone. Only a column's newest active edit can be undone,
so undos always run newest first and a snapshot never overwrites a later edit. A theme rebuild or Look
inside Other rewrites themes without an edit record, so it clears the column's edits (`forget`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Theme, ThemeEdit

THEME_COLUMNS = [c.name for c in Theme.__table__.columns]


class UndoRefused(Exception):
    """This edit cannot be undone (not the newest, already undone, or gone)."""


def snapshot(rows: list[Theme]) -> list[dict]:
    """Every column of each row, as it is now. Call before changing them."""
    return [{c: getattr(t, c) for c in THEME_COLUMNS} for t in rows]


def record(
    db: Session, dataset_id: int, column: str, kind: str, summary: str, before: list[dict],
    created: list[Theme], touched: list[Theme], user_id: int | None,
) -> ThemeEdit:
    """Adds the edit; flushes so new rows have ids. The caller commits."""
    db.flush()
    edit = ThemeEdit(
        dataset_id=dataset_id, column_name=column, kind=kind, summary=summary, before=before,
        created_ids=[t.id for t in created], touched_ids=sorted({t.id for t in touched + created}),
        user_id=user_id,
    )
    db.add(edit)
    db.flush()
    return edit


def active_edits(db: Session, dataset_id: int, column: str) -> list[ThemeEdit]:
    """The column's edits that are not undone, newest first."""
    return list(db.scalars(
        select(ThemeEdit).where(
            ThemeEdit.dataset_id == dataset_id, ThemeEdit.column_name == column, ThemeEdit.undone_at.is_(None),
        ).order_by(ThemeEdit.id.desc())
    ).all())


def edited_ids(db: Session, dataset_id: int, column: str) -> set[int]:
    """Themes an active edit made or changed: the "edited" tag."""
    return {i for e in active_edits(db, dataset_id, column) for i in e.touched_ids or []}


def undo(db: Session, dataset_id: int, column: str, edit_id: int) -> ThemeEdit:
    """Reverses `edit_id`, the column's newest active edit. The caller commits."""
    edits = active_edits(db, dataset_id, column)
    if not edits or edits[0].id != edit_id:
        if any(e.id == edit_id for e in edits):
            raise UndoRefused("Undo the newer edits first.")
        raise UndoRefused("This edit was already undone or can no longer be undone.")
    edit = edits[0]
    for theme_id in edit.created_ids or []:
        row = db.get(Theme, theme_id)
        if row is not None:
            db.delete(row)
    db.flush()
    for snap in edit.before or []:
        row = db.get(Theme, snap["id"])
        if row is None:
            db.add(Theme(**snap))
        else:
            for c in THEME_COLUMNS:
                setattr(row, c, snap[c])
    edit.undone_at = datetime.now(timezone.utc)
    db.flush()
    return edit


def forget(db: Session, dataset_id: int, column: str) -> None:
    """Drops a column's edit history: its snapshots no longer match the themes. The caller commits."""
    for e in db.scalars(select(ThemeEdit).where(ThemeEdit.dataset_id == dataset_id, ThemeEdit.column_name == column)):
        db.delete(e)


def edit_dict(e: ThemeEdit) -> dict:
    return {"id": e.id, "undo_token": e.id, "kind": e.kind, "summary": e.summary,
            "created_at": e.created_at.isoformat() if e.created_at else None}
