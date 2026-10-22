"""Adaptive cleaning API (stream 5).

POST  /api/datasets/{id}/clean/plan    build the plan for this dataset and return it with a preview report
PATCH /api/datasets/{id}/clean/plan    toggle steps, edit merge tables, change a few thresholds; returns new preview
POST  /api/datasets/{id}/clean/apply   run the plan, store the cleaned copy, store the report
GET   /api/datasets/{id}/clean/report  the stored plan and report

Everything is owner-only (same `current_user` and `_own_dataset` as the upload API). The original file is
never changed; the cleaned copy is stored in Postgres (`app.models.CleanedFile`, keyed by the sha256 of its
bytes) - see app/api_upload.py's module docstring and docs/DECISIONS.md for why this moved off disk. The
plan and report live in datasets.profile["cleaning"], so no schema change was needed for those. Only one or
two cleaning jobs run at once (CLEAN_CONCURRENCY) so a public deployment cannot be tied up by a burst of
requests.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api_upload import ALLOWED_EXT, _own_dataset, current_user, scratch_file
from .cleaning import EDITABLE_PARAMS, CleaningError, CleaningPlan, apply_plan, plan_with_preview
from .cleaning.common import safe_text
from .db import get_db
from .models import CleanedFile, Dataset, UploadedFile, User
from .profiling import LoadError, load_table

router = APIRouter(prefix="/api")

_SLOTS = threading.BoundedSemaphore(max(1, int(os.environ.get("CLEAN_CONCURRENCY", "2") or 2)))
_HEX64 = re.compile(r"[0-9a-f]{64}")


# ---------------------------------------------------------------- helpers
class _Slot:
    def __enter__(self):
        if not _SLOTS.acquire(blocking=False):
            raise HTTPException(429, "Cleaning is busy with other files. Try again in a few seconds.")

    def __exit__(self, *exc):
        _SLOTS.release()


def _load_df(db: Session, ds: Dataset):
    profile = ds.profile or {}
    ext = profile.get("stored_ext")
    if not _HEX64.fullmatch(ds.file_hash or "") or ext not in ALLOWED_EXT:
        raise HTTPException(404, "The original file for this dataset is not available.")
    row = db.get(UploadedFile, ds.file_hash)
    if row is None:
        # Now only happens if data is genuinely corrupted/missing, not from a redeploy (see docs/DECISIONS.md).
        raise HTTPException(404, "The original file for this dataset is not available.")
    try:
        with scratch_file(row.content, ext) as path:
            df = load_table(path).df
    except LoadError as e:
        raise HTTPException(400, str(e)) from e
    # The raw file always reloads under its LITERAL header text (or the loader's own `Column N` fallback)
    # - a column rename made at the Check Columns step (app/api_upload.py::confirm_columns) only lives in
    # `profile["confirmed"]["renames"]`, so it must be re-applied here on every reload or cleaning would
    # silently drift back to the pre-rename names. Confirmed via grep: `load_table(` is only ever called
    # from here and from `profiling/__init__.py::profile_file` (upload time, before any rename exists) -
    # this is the one other place that needs the map.
    renames = ((profile.get("confirmed") or {}).get("renames")) or {}
    if renames:
        df = df.rename(columns=renames)
    return df


def _save(db: Session, ds: Dataset, cleaning: dict[str, Any]) -> None:
    profile = dict(ds.profile or {})
    profile["cleaning"] = cleaning
    ds.profile = profile  # a new dict, so SQLAlchemy sees the JSON change
    db.commit()


def _stored(ds: Dataset) -> dict[str, Any]:
    return dict((ds.profile or {}).get("cleaning") or {})


def _plan_response(plan: CleaningPlan, preview) -> dict[str, Any]:
    return {"plan": plan.to_dict(), "preview": preview.to_dict()}


def _run(fn):
    try:
        return fn()
    except CleaningError as e:
        raise HTTPException(422, str(e)) from e


# ---------------------------------------------------------------- request bodies
class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_group_size: int | None = Field(default=None, ge=2, le=1000)


class MergeEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from", max_length=500)
    to: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None


class StepEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(max_length=400)
    enabled: bool | None = None
    params: dict[str, Any] | None = None
    merges: list[MergeEdit] = Field(default_factory=list, max_length=1000)


class PlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[StepEdit] = Field(max_length=500)


def _clean_params(key: str, params: dict[str, Any]) -> dict[str, Any]:
    allowed = EDITABLE_PARAMS.get(key, set())
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k not in allowed:
            raise HTTPException(422, f"'{k}' cannot be changed on this step.")
        if k == "min_count":
            if isinstance(v, bool) or not isinstance(v, int) or not 2 <= v <= 1_000_000:
                raise HTTPException(422, "min_count must be a whole number of at least 2.")
        elif k == "scale":
            ok = (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in v)
                  and 0 <= v[0] < v[1] <= 100)
            if not ok:
                raise HTTPException(422, "scale must be two whole numbers, low then high, for example [1, 5].")
        elif k in ("extra_terms", "safe_words"):
            ok = (isinstance(v, list) and len(v) <= 100 and all(isinstance(x, str) and 1 <= len(x.strip()) <= 60 for x in v))
            if not ok:
                raise HTTPException(422, f"{k} must be a list of at most 100 short pieces of text.")
            v = [safe_text(x, 60).strip() for x in v]
        elif k == "day_first":
            if v is not None and not isinstance(v, bool):
                raise HTTPException(422, "day_first must be true, false or null.")
        out[k] = v
    return out


# ---------------------------------------------------------------- routes
@router.post("/datasets/{dataset_id}/clean/plan")
def build_plan(dataset_id: int, body: PlanRequest | None = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    df = _load_df(db, ds)
    settings = {"min_group_size": body.min_group_size} if body and body.min_group_size else None
    with _Slot():
        plan, preview = _run(lambda: plan_with_preview(df, ds.profile, None, settings))
    _save(db, ds, {"plan": plan.to_dict(), "created_at": datetime.now(timezone.utc).isoformat()})
    return _plan_response(plan, preview)


@router.patch("/datasets/{dataset_id}/clean/plan")
def edit_plan(dataset_id: int, body: PlanPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    stored = _stored(ds)
    if "plan" not in stored:
        raise HTTPException(409, "Build the plan first.")
    plan = CleaningPlan.from_dict(stored["plan"])
    by_id = {s.id: s for s in plan.steps}
    overrides = {k: dict(v) for k, v in plan.overrides.items()}
    for edit in body.steps:
        step = by_id.get(edit.id)
        if step is None:
            raise HTTPException(422, "That step is not in the plan.")
        ov = overrides.setdefault(step.id, {})
        if edit.enabled is not None:
            ov["enabled"] = edit.enabled
        if edit.params:
            ov["params"] = {**ov.get("params", {}), **_clean_params(step.key, edit.params)}
        if edit.merges:
            known = {e["from"] for e in step.params.get("merges", [])}
            table = ov.setdefault("merges", {})
            for m in edit.merges:
                if m.from_ not in known:
                    raise HTTPException(422, "That merge is not in the table.")
                one: dict[str, Any] = {}
                if m.to is not None:
                    to = safe_text(m.to, 200).strip()
                    if not to:
                        raise HTTPException(422, "A merge needs a non-empty target label.")
                    one["to"] = to
                if m.enabled is not None:
                    one["enabled"] = m.enabled
                table[m.from_] = {**table.get(m.from_, {}), **one}
    df = _load_df(db, ds)
    with _Slot():
        new_plan, preview = _run(lambda: plan_with_preview(df, ds.profile, overrides, plan.settings))
    _save(db, ds, {"plan": new_plan.to_dict(), "created_at": stored.get("created_at")})  # edits invalidate an old apply
    return _plan_response(new_plan, preview)


@router.post("/datasets/{dataset_id}/clean/apply")
def apply_cleaning(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    stored = _stored(ds)
    df = _load_df(db, ds)
    with _Slot():
        if "plan" in stored:
            plan = CleaningPlan.from_dict(stored["plan"])
        else:
            plan, _ = _run(lambda: plan_with_preview(df, ds.profile))
        clean, report = _run(lambda: apply_plan(df, plan))
    data = clean.to_csv(index=False).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    if db.get(CleanedFile, digest) is None:  # insert-or-reuse: dedup by hash, same as the raw-bytes store
        db.add(CleanedFile(clean_hash=digest, content=data))
        try:
            db.commit()
        except IntegrityError:  # another request stored the same bytes first; they are identical either way
            db.rollback()
    _save(db, ds, {
        "plan": plan.to_dict(), "report": report.to_dict(), "clean_hash": digest,
        "applied_at": datetime.now(timezone.utc).isoformat(), "created_at": stored.get("created_at"),
    })
    return {"dataset_id": ds.id, "clean_hash": digest, "report": report.to_dict()}


@router.get("/datasets/{dataset_id}/clean/report")
def get_report(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id)
    stored = _stored(ds)
    if "report" not in stored:
        raise HTTPException(404, "This dataset has not been cleaned yet.")
    return {"dataset_id": ds.id, "plan": stored["plan"], "report": stored["report"],
            "clean_hash": stored.get("clean_hash"), "applied_at": stored.get("applied_at")}
