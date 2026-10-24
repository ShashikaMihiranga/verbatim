"""The report's question-context correction: the user can replace Verbatim's keyword guess of what the
question asks for ("reasons", "facts", ...). Saved per dataset + column under
`Dataset.profile["question_kinds"]`; `app.findings.build_report_data` reads it back, so every report
view and rebuild shows the corrected type. Framing and answer length are measured from the data, not
guessed, so they are not editable here.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_upload import _own_dataset, current_user
from .db import get_db
from .findings import QUESTION_KINDS, _classify_question_kind, question_for, stored_question_kind
from .models import Column, User

router = APIRouter(prefix="/api")


class QuestionKindUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    kind: str | None  # None resets to Verbatim's own guess


def _state(ds, column: str) -> dict:
    guessed = _classify_question_kind(question_for(ds, column))
    kind = stored_question_kind(ds, column) or guessed
    return {"column": column, "kind": kind, "guessed_kind": guessed, "corrected": kind != guessed,
            "options": list(QUESTION_KINDS)}


def _require_column(db: Session, dataset_id: int, column: str) -> None:
    if db.scalar(select(Column.id).where(Column.dataset_id == dataset_id, Column.name == column)) is None:
        raise HTTPException(404, "Column not found")


@router.get("/datasets/{dataset_id}/question-kind")
def get_question_kind(dataset_id: int, column: str, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id)
    _require_column(db, ds.id, column)
    return _state(ds, column)


@router.put("/datasets/{dataset_id}/question-kind")
def set_question_kind(dataset_id: int, body: QuestionKindUpdate, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    _require_column(db, ds.id, body.column)
    if body.kind is not None and body.kind not in QUESTION_KINDS:
        raise HTTPException(422, f"kind must be one of: {', '.join(QUESTION_KINDS)}")
    guessed = _classify_question_kind(question_for(ds, body.column))
    profile = dict(ds.profile or {})
    kinds = dict(profile.get("question_kinds") or {})
    if body.kind is None or body.kind == guessed:
        kinds.pop(body.column, None)  # matching the guess is not a correction; keep the profile clean
    else:
        kinds[body.column] = body.kind
    profile["question_kinds"] = kinds
    ds.profile = profile  # reassign: the JSON column only notices a new object, not in-place edits
    db.commit()
    return _state(ds, body.column)
