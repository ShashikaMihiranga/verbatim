"""Projects list API (stream 9): lets a signed-in user see and reopen files they have already uploaded,
without needing to already know a dataset id.

GET    /api/projects            the signed-in user's own datasets, newest first: {id, filename, question,
                                 row_count, created_at, status}.
DELETE /api/datasets/{id}       owner-only, deletes one dataset and its Column/Theme/Finding/Report rows.

`status` is one of a small fixed set ("uploaded", "columns confirmed", "cleaned", "finding themes", "themes built",
"report ready"), computed by checking what already exists for that dataset - never a second copy of
`app.api_upload`'s/`app.api_cleaning`'s/`app.api_themes`'s/`app.api_report`'s own business logic:
  - "columns confirmed" reuses the exact same `"confirmed" in profile` check `app.api_upload._view` already
    uses for its own `confirmed` field.
  - "cleaned" reuses `app.api_cleaning._stored`, the module's own accessor for `Dataset.profile["cleaning"]`,
    and looks for the same `"report"` key `api_cleaning.apply_cleaning` writes once a plan has actually been
    applied (not just previewed).
  - "themes built" and "report ready" are a light, direct read of whether any `Theme`/`Report` row exists
    for the dataset - the brief for this stream calls this out explicitly as fine, rather than importing
    `app.api_themes`/`app.api_report`'s heavier column-scoped listing routes just to check existence.
See docs/DECISIONS.md (this stream's dated entry) for the full reasoning and what was deliberately left out.

Everything is owner-only (the same `current_user`/`_own_dataset` as every other data route in this app).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_cleaning import _stored as _cleaning_stored
from .api_upload import _discard_uploaded_bytes, _own_dataset, current_user
from .db import get_db
from .models import (CleanedFile, Column, Dataset, DatasetCollaborator, DatasetInviteLink, DatasetShareLink,
                     Finding, Job, Project, Report, Theme, ThemeEdit, User)

router = APIRouter(prefix="/api")

Status = Literal["uploaded", "columns confirmed", "cleaned", "finding themes", "themes built", "report ready"]


def _status(db: Session, ds: Dataset) -> Status:
    """One dataset's stage. Checked most-advanced-first so a dataset that has reached a later stage is
    never reported as an earlier one."""
    if db.scalar(select(Report.id).where(Report.dataset_id == ds.id).limit(1)) is not None:
        return "report ready"
    # A theme build in progress (the Uploads list links it to the waiting card). Only before any report:
    # a rebuild of a column that already has a report keeps "report ready".
    if db.scalar(select(Job.id).where(Job.dataset_id == ds.id, Job.kind == "themes", Job.status == "running")
                 .limit(1)) is not None:
        return "finding themes"
    if db.scalar(select(Theme.id).where(Theme.dataset_id == ds.id).limit(1)) is not None:
        return "themes built"
    if "report" in _cleaning_stored(ds):  # api_cleaning.py's own "cleaning has actually been applied" signal
        return "cleaned"
    if "confirmed" in (ds.profile or {}):  # same signal app.api_upload._view exposes as `confirmed`
        return "columns confirmed"
    return "uploaded"


def _project_view(db: Session, ds: Dataset) -> dict:
    confirmed = (ds.profile or {}).get("confirmed") or {}
    return {
        "id": ds.id,
        "filename": ds.filename,
        "question": confirmed.get("question"),  # only ever from the CONFIRMED profile; null otherwise
        "row_count": ds.row_count,
        "created_at": ds.created_at,
        "status": _status(db, ds),
    }


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(
        select(Dataset).join(Project).where(Project.user_id == user.id).order_by(Dataset.id.desc())
    ).all()
    return [_project_view(db, ds) for ds in rows]


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    # Sharing/roles (fixed 2026-10-22): deletion is owner-only - an editor collaborator can mutate a
    # dataset's content but must never be able to destroy the dataset itself.
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    # Explicit, ordered deletes - matching this codebase's existing convention (see api_upload.confirm_columns
    # and api_themes.build_themes, both of which delete old rows in a loop rather than relying on the
    # database to cascade) so this behaves the same on sqlite (tests) and Postgres (production) alike.
    for model in (Job, Finding, Report, Theme, ThemeEdit, Column,
                  DatasetCollaborator, DatasetInviteLink, DatasetShareLink):
        for row in db.scalars(select(model).where(model.dataset_id == ds.id)).all():
            db.delete(row)
    clean_hash = _cleaning_stored(ds).get("clean_hash")
    db.delete(ds)
    db.flush()
    # The raw and cleaned bytes are shared by hash between datasets, so only drop them once nothing uses them.
    _discard_uploaded_bytes(db, ds.file_hash)
    # shortcut: clean_hash lives in profile JSON, so this scans every dataset; add a column if datasets reach many thousands.
    if clean_hash and not any(_cleaning_stored(d).get("clean_hash") == clean_hash
                              for d in db.scalars(select(Dataset)).all()):
        row = db.get(CleanedFile, clean_hash)
        if row is not None:
            db.delete(row)
    db.commit()
    return {"ok": True}


__all__ = ["router"]
