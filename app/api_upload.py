"""Upload and column-profiling API (stream 4).

POST  /api/upload                      multipart .csv/.xlsx/.xls -> dataset + profile
GET   /api/datasets/{id}/profile       profile plus the user's confirmed choices
PATCH /api/datasets/{id}/columns       save confirmed kinds, switch-offs and the question

Settings are read from the environment on each request:
  UPLOAD_DIR      where files are stored (default ~/.verbatim/uploads, outside the repo)
  MAX_UPLOAD_MB   size limit in megabytes (default 50)
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import authenticate
from .db import get_db
from .models import Column, Dataset, Project, User
from .profiling import KINDS, LoadError, profile_file
from .profiling.claude_hook import collect_samples, refine_profile

router = APIRouter(prefix="/api")

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
CHUNK = 1024 * 1024


def upload_dir() -> Path:
    return Path(os.environ.get("UPLOAD_DIR") or Path.home() / ".verbatim" / "uploads").expanduser()


def max_upload_bytes() -> int:
    try:
        return int(float(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024)
    except ValueError:
        return 50 * 1024 * 1024


# ---------------------------------------------------------------- auth
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in user, from a verified Clerk session token (see app/auth.py).

    The shared dev user exists only when ENV=dev and ALLOW_DEV_USER=true. In production every data
    endpoint answers 401 without a valid token.
    """
    return authenticate(request, db)[0]


def _project(db: Session, user: User) -> Project:
    project = db.scalar(select(Project).where(Project.user_id == user.id).order_by(Project.id))
    if project is None:
        project = Project(user_id=user.id, name="My project")
        db.add(project)
        db.commit()
    return project


# ---------------------------------------------------------------- helpers
def safe_filename(raw: str | None, ext: str) -> str:
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    if len(name) > 200:
        name = name[:200 - len(ext)] + ext
    return name or f"upload{ext}"


def _own_dataset(db: Session, user: User, dataset_id: int) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None or ds.project.user_id != user.id:
        raise HTTPException(404, "Dataset not found.")
    return ds


def _view(ds: Dataset, reused: bool | None = None) -> dict:
    profile = dict(ds.profile or {})
    out = {
        "id": ds.id,
        "filename": ds.filename,
        "row_count": ds.row_count,
        "confirmed": "confirmed" in profile,
        "profile": profile,
    }
    if reused is not None:
        out["reused"] = reused
    return out


# ---------------------------------------------------------------- routes
@router.post("/upload")
def upload(file: UploadFile, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    limit = max_upload_bytes()
    ext = Path((file.filename or "").replace("\\", "/")).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Only .csv, .xlsx and .xls files can be uploaded.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + CHUNK:
        raise HTTPException(413, f"That file is too large. The limit is {limit // (1024 * 1024)} MB.")

    dest_dir = upload_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".tmp-{uuid.uuid4().hex}"  # server-generated, never from user input
    sha, size = hashlib.sha256(), 0
    try:
        with tmp.open("wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"That file is too large. The limit is {limit // (1024 * 1024)} MB.")
                sha.update(chunk)
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty.")
        digest = sha.hexdigest()
        final = dest_dir / f"{digest}{ext}"  # name comes from the hash only: no path traversal possible
        os.replace(tmp, final)
    finally:
        tmp.unlink(missing_ok=True)

    project = _project(db, user)
    existing = db.scalar(
        select(Dataset).join(Project).where(Project.user_id == user.id, Dataset.file_hash == digest)
    )
    if existing is not None:
        return _view(existing, reused=True)

    try:
        profile, loaded = profile_file(final)
    except LoadError as e:
        final.unlink(missing_ok=True)
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # a malformed file must never become a 500
        final.unlink(missing_ok=True)
        raise HTTPException(400, "We could not read that file. Check it opens in Excel and try again.") from e

    profile = refine_profile(profile, collect_samples(loaded.df, profile))  # no-op without ANTHROPIC_API_KEY
    profile["stored_ext"] = ext
    ds = Dataset(
        project_id=project.id,
        filename=safe_filename(file.filename, ext),
        file_hash=digest,
        row_count=profile["row_count"],
        profile=profile,
    )
    db.add(ds)
    db.commit()
    return _view(ds, reused=False)


@router.get("/datasets/{dataset_id}/profile")
def get_profile(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _view(_own_dataset(db, user, dataset_id))


class ColumnChoice(BaseModel):
    name: str = Field(max_length=255)
    kind: Literal["open_text", "short_text", "score", "date", "segment", "numeric", "yes_no", "id_or_junk"]
    off: bool = False  # switched off for reports the user shares


class ConfirmBody(BaseModel):
    columns: list[ColumnChoice] = Field(max_length=300)
    question: str | None = Field(default=None, max_length=500)


@router.patch("/datasets/{dataset_id}/columns")
def confirm_columns(dataset_id: int, body: ConfirmBody, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id)
    profile = dict(ds.profile or {})
    guessed = {c["name"]: c for c in profile.get("columns", [])}
    chosen = {c.name: c for c in body.columns}
    unknown = sorted(set(chosen) - set(guessed))
    if unknown:
        raise HTTPException(422, f"Unknown column(s): {', '.join(unknown[:5])}")
    missing = sorted(set(guessed) - set(chosen))
    if missing:
        raise HTTPException(422, f"Missing column(s): {', '.join(missing[:5])}")

    question = (body.question or "").strip() or None
    profile["confirmed"] = {
        "columns": {n: {"kind": c.kind, "off": c.off} for n, c in chosen.items()},
        "question": question,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    ds.profile = profile  # new dict object so SQLAlchemy sees the JSON change

    for old in db.scalars(select(Column).where(Column.dataset_id == ds.id)).all():
        db.delete(old)
    for name, g in guessed.items():
        c = chosen[name]
        db.add(Column(
            dataset_id=ds.id, name=name, position=g["position"], kind=c.kind,
            stats={"off": c.off, "unit": g.get("unit"), "sensitive": g["sensitive"], "guessed_kind": g["kind"],
                   "distinct": g["distinct"], "missing": g["missing"]},
        ))
    db.commit()
    return _view(ds)


__all__ = ["router", "current_user", "KINDS"]
