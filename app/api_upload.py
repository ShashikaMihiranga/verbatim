"""Upload and column-profiling API (stream 4).

POST  /api/upload                      multipart .csv/.xlsx/.xls -> dataset + profile
GET   /api/datasets/{id}/profile       profile plus the user's confirmed choices
PATCH /api/datasets/{id}/columns       save confirmed kinds, switch-offs and the question

Settings are read from the environment on each request:
  MAX_UPLOAD_MB   size limit in megabytes (default 50)

File bytes live in Postgres (`app.models.UploadedFile`), not on disk: Railway's container filesystem does
not survive a redeploy, and its attached volume path turned out not to be reliably writable by this app's
non-root user either - see docs/DECISIONS.md (dated entry) for the diagnosis. `scratch_file` below still
writes a short-lived copy under the OS temp directory (`/tmp`), but only because `profiling/loader.py`'s
openpyxl/xlrd-backed readers need a real filesystem path, not because anything is meant to persist there -
it is deleted immediately after use and every container can always write to `/tmp` (no volume, no
permissions to fight).
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import authenticate
from .db import get_db
from .models import Column, Dataset, Project, UploadedFile, User
from .profiling import KINDS, LoadError, profile_file
from .profiling.claude_hook import collect_samples, refine_profile

router = APIRouter(prefix="/api")

ALLOWED_EXT = {".csv", ".xlsx", ".xls"}
CHUNK = 1024 * 1024


def max_upload_bytes() -> int:
    try:
        return int(float(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024)
    except ValueError:
        return 50 * 1024 * 1024


@contextlib.contextmanager
def scratch_file(data: bytes, suffix: str) -> Iterator[Path]:
    """A short-lived file under the OS temp directory holding `data`, deleted on exit.

    Scratch space for a library that needs a real path (openpyxl/xlrd/pandas via `profiling.load_table`),
    not persistent storage - nothing here needs a volume or special permissions, every container can always
    write to `/tmp`. Shared by app/api_upload.py and app/api_cleaning.py so this pattern exists in one place.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.close()
        yield Path(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


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


def _store_uploaded_bytes(db: Session, digest: str, data: bytes) -> None:
    """Insert-or-reuse: the dedup point for raw bytes (separate from, and in addition to, the `Dataset`
    dedup-by-hash below, which is per-user; this one is global and content-addressed, exactly like the old
    `UPLOAD_DIR/<hash><ext>` disk path was)."""
    if db.get(UploadedFile, digest) is not None:
        return
    db.add(UploadedFile(file_hash=digest, content=data))
    try:
        db.commit()
    except IntegrityError:  # another request stored the same bytes first; they are identical either way
        db.rollback()


def _discard_uploaded_bytes(db: Session, digest: str) -> None:
    row = db.get(UploadedFile, digest)
    if row is not None:
        db.delete(row)
        db.commit()


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

    sha, size = hashlib.sha256(), 0
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)  # /tmp scratch space only, never persisted
    tmp_path = Path(tmp.name)
    try:
        try:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"That file is too large. The limit is {limit // (1024 * 1024)} MB.")
                sha.update(chunk)
                tmp.write(chunk)
        finally:
            tmp.close()
        if size == 0:
            raise HTTPException(400, "The file is empty.")
        digest = sha.hexdigest()

        _store_uploaded_bytes(db, digest, tmp_path.read_bytes())

        project = _project(db, user)
        existing = db.scalar(
            select(Dataset).join(Project).where(Project.user_id == user.id, Dataset.file_hash == digest)
        )
        if existing is not None:
            return _view(existing, reused=True)

        try:
            profile, loaded = profile_file(tmp_path)
        except LoadError as e:
            _discard_uploaded_bytes(db, digest)
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # a malformed file must never become a 500
            _discard_uploaded_bytes(db, digest)
            raise HTTPException(400, "We could not read that file. Check it opens in Excel and try again.") from e
    finally:
        tmp_path.unlink(missing_ok=True)

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
