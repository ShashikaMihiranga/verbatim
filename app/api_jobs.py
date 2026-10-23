"""Job status API (async build jobs stream).

GET /api/jobs                                            every job across every dataset the caller OWNS
                                                          (docs/TODO.md, 2026-10-23 "Jobs" dashboard),
                                                          most recent first - the one place to watch
                                                          everything running at once instead of polling
                                                          one dataset+column+kind at a time.
GET /api/datasets/{id}/jobs/{job_id}                     one job's status/step/error
GET /api/datasets/{id}/jobs/latest?column=...&kind=...   the current (or most recent) job for a
                                                          dataset+column+kind, without already knowing its
                                                          id - lets a reloaded page resume watching a build
                                                          it did not start in this browser session.

Owner-only, same `current_user`/`_own_dataset` pattern as every other data route. Both `app/api_themes.py`
and `app/api_report.py` create `Job` rows (via `app/jobs.py`); this module only reads them.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_upload import _own_dataset, current_user
from .db import get_db
from .jobs import job_dict
from .models import Dataset, Job, Project, User

router = APIRouter(prefix="/api")

_MAX_LIMIT = 200


@router.get("/jobs")
def list_jobs(
    status: str | None = None,
    limit: int = Query(default=50, le=_MAX_LIMIT, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Same "my own datasets only" scope `list_projects` (app/api_projects.py) already uses for the
    Projects page - a shared/collaborator dataset's jobs are not included here, consistent with that
    page never listing anything shared TO this user either, only what they own. `status` is an optional
    exact-match filter ("running" | "done" | "failed") for a dashboard that wants to show only what's
    still in flight; omitted shows everything, newest first, capped at `limit`."""
    if status is not None and status not in ("running", "done", "failed"):
        raise HTTPException(422, "Unknown status filter.")
    q = (
        select(Job, Dataset.filename)
        .join(Dataset, Dataset.id == Job.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .where(Project.user_id == user.id)
        .order_by(Job.id.desc())
        .limit(limit)
    )
    if status is not None:
        q = q.where(Job.status == status)
    rows = db.execute(q).all()
    return [{**job_dict(job), "dataset_name": filename} for job, filename in rows]


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
