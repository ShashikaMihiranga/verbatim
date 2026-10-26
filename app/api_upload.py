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
from .models import Column, Dataset, DatasetCollaborator, Project, UploadedFile, User
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


# Sharing/roles (SPEC.md section 5; docs/TODO.md, fixed 2026-10-22): owner > editor > viewer. The owner
# always has every role implicitly (`Dataset.project.user_id`, unchanged); a `DatasetCollaborator` row
# grants exactly one of the other two roles to a second signed-in `User`.
ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


def _dataset_role(db: Session, user: User, ds: Dataset) -> str | None:
    """The caller's own role on `ds` - `"owner"`, `"editor"`, `"viewer"`, or `None` if they have no access
    at all. Never raises; `_own_dataset` below is what turns `None` into a 404."""
    if ds.project.user_id == user.id:
        return "owner"
    collab = db.scalar(
        select(DatasetCollaborator).where(DatasetCollaborator.dataset_id == ds.id, DatasetCollaborator.user_id == user.id)
    )
    return collab.role if collab is not None else None


def _own_dataset(db: Session, user: User, dataset_id: int, min_role: str = "viewer") -> Dataset:
    """Every data route's one ownership choke point (`app/api_cleaning.py`, `app/api_jobs.py`,
    `app/api_report.py`, `app/api_themes.py`, `app/api_projects.py` all call this, never a second check of
    their own) - extended for sharing/roles rather than replaced, so every existing call site keeps
    working unchanged at its default `min_role="viewer"` (today's exact behaviour before this feature:
    only the owner ever had any access at all, and every existing caller WAS effectively requiring full
    access, so this default is a deliberate, documented widening - callers that mutate data must now pass
    `min_role="editor"` explicitly, and the one truly destructive route, `delete_dataset`, passes
    `min_role="owner"`). Still returns a generic 404 (not 403) for "doesn't exist", "not yours", and "yours
    but your role isn't high enough" alike - deliberately not revealing which, same as before this
    feature."""
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found.")
    role = _dataset_role(db, user, ds)
    if role is None or ROLE_RANK[role] < ROLE_RANK[min_role]:
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
    """Drop the raw bytes unless any dataset (any user's) still points at them: the row is shared by hash."""
    if db.scalar(select(Dataset.id).where(Dataset.file_hash == digest).limit(1)) is not None:
        return
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
    position: int
    name: str = Field(max_length=255)
    kind: Literal["open_text", "short_text", "score", "date", "segment", "numeric", "yes_no", "id_or_junk"]
    off: bool = False  # switched off for reports the user shares


class ConfirmBody(BaseModel):
    columns: list[ColumnChoice] = Field(max_length=300)
    question: str | None = Field(default=None, max_length=500)
    # docs/TODO.md (fixed 2026-10-22): lets a user override which `open_text`-kind column becomes the
    # report's subject, when more than one exists - previously there was no field anywhere for this,
    # `Themes.tsx`'s `pickOpenTextColumn` always decided automatically with no way to overrule it. `None`
    # (the default) keeps today's fully-automatic behaviour unchanged.
    primary_open_text: str | None = Field(default=None, max_length=255)


@router.patch("/datasets/{dataset_id}/columns")
def confirm_columns(dataset_id: int, body: ConfirmBody, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Matches submitted columns to profiled columns by POSITION, not by name - this is what lets a
    submitted `name` that differs from the profiled one mean "rename this column" instead of "unknown
    column" (docs/TODO.md, 2026-10-21 headerless-column feature). A rename is recorded in
    `profile["confirmed"]["renames"]` (original literal header -> final name); `app/api_cleaning.py`'s
    `_load_df` applies that same map every time it reloads the raw file, so cleaning/themes/reports all
    see the final name consistently - see that function's own comment for why this is the one other place
    that needs it."""
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    profile = dict(ds.profile or {})
    guessed_by_pos = {c["position"]: c for c in profile.get("columns", [])}
    chosen_by_pos = {c.position: c for c in body.columns}
    unknown = sorted(set(chosen_by_pos) - set(guessed_by_pos))
    if unknown:
        raise HTTPException(422, f"Unknown column position(s): {', '.join(str(p) for p in unknown[:5])}")
    missing = sorted(set(guessed_by_pos) - set(chosen_by_pos))
    if missing:
        raise HTTPException(422, f"Missing column position(s): {', '.join(str(p) for p in missing[:5])}")

    # `guessed_by_pos[pos]["name"]` is `profile["columns"]`'s CURRENT name - on a second confirm (before
    # cleaning/themes are built, the one supported re-confirm case), that's already a renamed name, not
    # the literal raw-file header. Chain through any prior rename so every lookup below resolves to the
    # TRUE literal header (what `_load_df` always reloads the raw file under), regardless of how many
    # times confirm has been called. Captured into `true_original_by_pos` UP FRONT, before anything
    # mutates `profile["columns"]` in place below - `guessed_by_pos`'s dicts are the SAME objects as
    # `profile["columns"]`'s (not copies), so reading `g["name"]` after that mutation would silently see
    # the already-renamed value instead of the original.
    prior_renames = ((profile.get("confirmed") or {}).get("renames")) or {}
    original_by_current_name = {v: k for k, v in prior_renames.items()}
    true_original_by_pos = {pos: original_by_current_name.get(g["name"], g["name"]) for pos, g in guessed_by_pos.items()}

    renames = {
        true_original_by_pos[pos]: chosen_by_pos[pos].name
        for pos, g in guessed_by_pos.items()
        if chosen_by_pos[pos].name != g["name"]
    }

    question = (body.question or "").strip() or None

    primary_open_text = (body.primary_open_text or "").strip() or None
    if primary_open_text is not None:
        chosen_names = {c.name for c in chosen_by_pos.values()}
        if primary_open_text not in chosen_names:
            raise HTTPException(422, "primary_open_text must be one of the submitted columns.")
        chosen_kind = next(c.kind for c in chosen_by_pos.values() if c.name == primary_open_text)
        if chosen_kind != "open_text":
            raise HTTPException(422, "primary_open_text must be a column confirmed as open_text.")

    profile["confirmed"] = {
        "columns": {c.name: {"kind": c.kind, "off": c.off} for c in chosen_by_pos.values()},
        "renames": renames,  # original literal header -> final (possibly user-renamed) name
        "question": question,
        "primary_open_text": primary_open_text,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    for col in profile.get("columns", []):
        col["name"] = chosen_by_pos[col["position"]].name
    ds.profile = profile  # new dict object so SQLAlchemy sees the JSON change

    for old in db.scalars(select(Column).where(Column.dataset_id == ds.id)).all():
        db.delete(old)
    for pos, g in guessed_by_pos.items():
        c = chosen_by_pos[pos]
        db.add(Column(
            dataset_id=ds.id, name=c.name, position=pos, kind=c.kind,
            stats={"off": c.off, "unit": g.get("unit"), "sensitive": g["sensitive"], "guessed_kind": g["kind"],
                   "distinct": g["distinct"], "missing": g["missing"], "original_name": true_original_by_pos[pos]},
        ))
    db.commit()
    return _view(ds)


__all__ = ["router", "current_user", "KINDS"]
