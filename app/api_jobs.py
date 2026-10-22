"""Job status API (async build jobs stream).

GET /api/datasets/{id}/jobs/{job_id}                     one job's status/step/error
GET /api/datasets/{id}/jobs/latest?column=...&kind=...   the current (or most recent) job for a
                                                          dataset+column+kind, without already knowing its
                                                          id - lets a reloaded page resume watching a build
                                                          it did not start in this browser session.

Owner-only, same `current_user`/`_own_dataset` pattern as every other data route. Both `app/api_themes.py`
and `app/api_report.py` create `Job` rows (via `app/jobs.py`); this module only reads them.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_upload import _own_dataset, current_user
from .db import get_db
from .jobs import job_dict
from .models import Job, User

router = APIRouter(prefix="/api")


@router.get("/datasets/{dataset_id}/jobs/latest")
def latest_job(
    dataset_id: int,
    column: str,
    kind: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id)
    if kind not in ("themes", "report", "look_inside_other", "split_theme"):
        raise HTTPException(422, "Unknown job kind.")
    job = db.scalar(
        select(Job)
        .where(Job.dataset_id == ds.id, Job.column_name == column, Job.kind == kind)
        .order_by(Job.id.desc())
    )
    if job is None:
        raise HTTPException(404, "No job has been started yet for this dataset, column and kind.")
    return job_dict(job)


@router.get("/datasets/{dataset_id}/jobs/{job_id}")
def get_job(
    dataset_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id)
    job = db.get(Job, job_id)
    if job is None or job.dataset_id != ds.id:
        raise HTTPException(404, "Job not found.")
    return job_dict(job)
