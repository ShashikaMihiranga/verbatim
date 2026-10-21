"""Shared background-job runner for build-themes and build-report (async build jobs stream).

Both `app/api_themes.py`'s `build_themes` and `app/api_report.py`'s `build_report` used to run their whole
pipeline inside the HTTP request, blocking on a soft internal deadline (`ThreadPoolExecutor.result(timeout=
...)`) that could not actually stop the work - Python cannot kill a running thread. A caller who gave up
(or hit the deadline) saw an error, but the real embedding/Claude calls kept running server-side with
nothing left to check on them afterward. This was confirmed live: Railway's CPU graph stayed busy well
after the browser showed a timeout.

The fix: validate everything that can fail cheaply and instantly (ownership, column exists, API keys
configured) BEFORE returning from the request - those stay synchronous HTTP errors, unchanged. Once
validated, `start_job` below creates a `Job` row and hands the real work to a plain daemon thread that
updates `job.step`/`job.status`/`job.error` as it goes, each update committed through its OWN short-lived
`Session` (never the request's session, which closes the moment the request returns). A poller (or a
reloaded page, via `GET .../jobs/latest`) watches that row instead of holding a connection open.

Shared, not duplicated: both routers' pipelines differ in shape (themes runs embed -> cluster -> label ->
score; report runs one `build_findings` call plus a render pass), but "create a Job row, run a callable in
a background thread, translate a known exception into `job.error`, release the concurrency slot when real
work finishes" is identical in both - that part is written once, here.
"""
from __future__ import annotations

import threading
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as _db
from .models import Job

# A step callback a pipeline calls at each phase boundary: `step("Naming each group")`.
StepFn = Callable[[str], None]

# `_db.SessionLocal()` (a late lookup of the module ATTRIBUTE at call time), never `from .db import
# SessionLocal` (which would bind this module's own name to the original sessionmaker object forever,
# whatever `app.db.SessionLocal` is reassigned to later): tests build a fresh engine per test and override
# `app.db.SessionLocal` itself (`monkeypatch.setattr(app.db, "SessionLocal", Session)`), the same way they
# already override the `get_db` FastAPI dependency for request-scoped sessions - background threads are not
# requests, so they need their own hook into that same per-test engine. `app/api_themes.py` and
# `app/api_report.py` follow the same `from . import db as _db` / `_db.SessionLocal()` pattern for exactly
# this reason.


def create_job(db: Session, dataset_id: int, column: str, kind: str) -> Job:
    """Mirrors `build_themes`'s existing "delete old rows before adding new ones" convention for `Theme`:
    a fresh build replaces any earlier job for this exact dataset+column+kind, so `GET .../jobs/latest`
    never has more than one candidate row to choose from.

    The delete and the insert are flushed in ONE commit (not two), deliberately - on SQLite, a plain
    integer primary key's rowid can be reused once a table is completely empty, so deleting the prior job
    and committing that alone BEFORE inserting the new one would let the new job land back on the same id
    the old one had (observed in this stream's own tests). `Theme`'s existing rebuild code avoids this the
    same way: delete and `add_all` happen in the same flush, so the table is never observably empty between
    the two.
    """
    for old in db.scalars(
        select(Job).where(Job.dataset_id == dataset_id, Job.column_name == column, Job.kind == kind)
    ).all():
        db.delete(old)
    job = Job(dataset_id=dataset_id, column_name=column, kind=kind, status="running", step="Starting")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _set_step(job_id: int, step: str) -> None:
    with _db.SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return  # the dataset (and its jobs) may have been deleted, or a watchdog already closed this out
        job.step = step
        db.commit()


def _mark_done(job_id: int) -> None:
    with _db.SessionLocal() as db:
        job = db.get(Job, job_id)
        # Only a still-"running" job is touched: a watchdog (see `start_job`'s `deadline_seconds`) may
        # already have marked this job failed with a "took too long" message while the real pipeline kept
        # running in the background (Python cannot kill a thread) - if that pipeline later finishes anyway,
        # it must NOT silently flip the job back to "done" out from under a user who was already told it
        # failed and moved on.
        if job is None or job.status != "running":
            return
        job.status = "done"
        job.step = "Done"
        db.commit()


def _mark_failed(job_id: int, error: str) -> None:
    with _db.SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return
        job.status = "failed"
        job.error = error
        db.commit()


def start_job(
    job: Job,
    slots: threading.BoundedSemaphore,
    work: Callable[[StepFn], None],
    error_message: Callable[[BaseException], str | None],
    *,
    deadline_seconds: float | None = None,
    deadline_message: str | None = None,
) -> threading.Thread:
    """Starts `work` in a daemon thread and returns immediately - the caller (the HTTP route) returns its
    202 response right after calling this, never waiting on the thread.

    `slots` must already be ACQUIRED by the caller (a quick, non-blocking `slots.acquire(blocking=False)`
    in the request handler itself, so a full slot still produces the exact same immediate 429 the old
    synchronous route gave - the brief's own "cheap and instant checks stay synchronous" rule extends to
    this one too, not just to key/ownership checks). This function takes over responsibility for releasing
    it, in the thread, once the real work finishes - so the slot is now held for as long as the work
    actually takes, not for a soft deadline that could and did lie about whether work was still running.

    `work(step)` runs the real pipeline, calling `step("...")` at each phase boundary. `error_message(exc)`
    maps a caught exception to the exact human-readable text a caller would previously have received as an
    HTTP error body - or returns `None` for an exception type nobody anticipated, which is re-raised (after
    still marking the job failed with a generic message) so it surfaces in server logs instead of being
    silently swallowed.

    `deadline_seconds`, when given, starts a second daemon thread that waits up to that long for `work` to
    finish and, if it has not, marks the job "failed" with `deadline_message` - a SANITY-CHECK WATCHDOG, not
    a real cancellation: Python cannot forcibly stop a running thread, so the real pipeline keeps running to
    completion in the background regardless (its result is then discarded by `_mark_done`/`_mark_failed`'s
    own "only touch a still-running job" guard above). This at least gives a caller a definite, honest
    answer ("took too long") instead of a job stuck at "running" forever if some inner step truly hangs.
    """
    job_id = job.id

    def _runner() -> None:
        try:
            try:
                work(lambda step: _set_step(job_id, step))
            except Exception as e:  # noqa: BLE001 - deliberately broad: this is the job's own top-level catch
                msg = error_message(e)
                if msg is None:
                    _mark_failed(job_id, "Something went wrong while building this. Try again.")
                    raise
                _mark_failed(job_id, msg)
                return
            _mark_done(job_id)
        finally:
            slots.release()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()

    if deadline_seconds:
        def _watchdog() -> None:
            thread.join(timeout=deadline_seconds)
            if thread.is_alive():
                _mark_failed(job_id, deadline_message or "This took too long and was stopped. Try again.")

        threading.Thread(target=_watchdog, daemon=True).start()

    return thread


def job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "dataset_id": job.dataset_id,
        "column": job.column_name,
        "kind": job.kind,
        "status": job.status,
        "step": job.step,
        "error": job.error,
        "result": job.result,
    }
