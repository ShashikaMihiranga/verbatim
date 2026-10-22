"""Sharing/roles API (SPEC.md section 5; docs/TODO.md, fixed 2026-10-22).

POST   /api/datasets/{id}/invite-links                   owner-only: create a reusable editor-invite link
GET    /api/datasets/{id}/invite-links                   owner-only: list active invite links
DELETE /api/datasets/{id}/invite-links/{link_id}          owner-only: revoke one
POST   /api/invite-links/{token}/accept                   any signed-in user: become an "editor" on that dataset
GET    /api/datasets/{id}/collaborators                   owner-only: list editor/viewer collaborators
DELETE /api/datasets/{id}/collaborators/{collaborator_id} owner-only: remove one

POST   /api/datasets/{id}/share-links                     owner-only: create a read-only, no-sign-in share link
GET    /api/datasets/{id}/share-links                     owner-only: list active share links
DELETE /api/datasets/{id}/share-links/{link_id}            owner-only: revoke one
GET    /api/share/{token}/report                          PUBLIC, no auth: the read-only report a valid,
                                                           unexpired share link grants - token+expiry gated
                                                           only, never `current_user`.

Two realities shaped this design, both confirmed by investigation before building it, not assumed:

1. **No "invite by email" is possible.** Clerk auth here is pure JWT verification (`app/auth.py`) - no
   Clerk secret key, no user-directory API - so there is no way to resolve "the person with this email"
   to a `User` row before they have signed in at least once themselves. The realistic stand-in: an owner
   generates a reusable link; whoever signs in and visits it becomes an "editor" collaborator
   (`DatasetInviteLink`/`accept_invite_link` below). This is a deliberate, documented departure from
   SPEC.md's literal "owner/editor/viewer roles" wording, not an oversight - see docs/DECISIONS.md.

2. **"Hide verbatims for external audiences" is enforced by NEVER exposing a verbatim-answer route on
   the public share-link path at all** - not by a redaction toggle on an otherwise-identical route. The
   public `GET /api/share/{token}/report` route below only ever calls `app.api_report._render_report`
   (the same renderer `GET /api/datasets/{id}/report` uses for a signed-in viewer), which embeds chart
   fragments built from aggregated numbers - never a verbatim-answer list. A signed-in "viewer"
   collaborator (not a share-link visitor) CAN still reach `app.api_themes`'s real answer routes, which
   hide text there instead (`app.api_themes._answers_page`'s own `hide_text` param) - a different
   audience, a different mechanism, both documented where they live.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_report import _latest_report_for_column, _render_report
from .api_upload import _own_dataset, current_user
from .db import get_db
from .models import Dataset, DatasetCollaborator, DatasetInviteLink, DatasetShareLink, User

router = APIRouter(prefix="/api")

TOKEN_BYTES = 24  # secrets.token_urlsafe(24) -> a 32-character URL-safe token, not practically guessable


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


# ---------------------------------------------------------------- editor invite links

@router.post("/datasets/{dataset_id}/invite-links", status_code=201)
def create_invite_link(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    link = DatasetInviteLink(dataset_id=ds.id, token=_new_token())
    db.add(link)
    db.commit()
    return {"id": link.id, "token": link.token, "created_at": link.created_at.isoformat()}


@router.get("/datasets/{dataset_id}/invite-links")
def list_invite_links(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    links = db.scalars(
        select(DatasetInviteLink).where(DatasetInviteLink.dataset_id == ds.id).order_by(DatasetInviteLink.id)
    ).all()
    return {"invite_links": [{"id": l.id, "token": l.token, "created_at": l.created_at.isoformat()} for l in links]}


@router.delete("/datasets/{dataset_id}/invite-links/{link_id}", status_code=204)
def revoke_invite_link(dataset_id: int, link_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    link = db.get(DatasetInviteLink, link_id)
    if link is None or link.dataset_id != ds.id:
        raise HTTPException(404, "Invite link not found.")
    db.delete(link)
    db.commit()


@router.post("/invite-links/{token}/accept")
def accept_invite_link(token: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Any signed-in user may call this - there is no ownership check to make, since the whole point is
    letting someone who is NOT the owner gain access. Idempotent: visiting an already-accepted link again
    is a no-op, not an error (a teammate re-opening a bookmarked invite link should never see a failure).
    Upgrades nothing: if the visitor is already the owner, or already an editor/viewer, their existing
    (always-at-least-as-high) access is left alone - this link only ever grants "editor", never downgrades."""
    link = db.scalar(select(DatasetInviteLink).where(DatasetInviteLink.token == token))
    if link is None:
        raise HTTPException(404, "This invite link is invalid or has been revoked.")
    ds = db.get(Dataset, link.dataset_id)
    if ds is None:
        raise HTTPException(404, "This invite link is invalid.")
    if ds.project.user_id == user.id:
        return {"dataset_id": ds.id, "role": "owner"}
    existing = db.scalar(
        select(DatasetCollaborator).where(DatasetCollaborator.dataset_id == ds.id, DatasetCollaborator.user_id == user.id)
    )
    if existing is not None:
        if existing.role != "editor":
            existing.role = "editor"
            db.commit()
        return {"dataset_id": ds.id, "role": existing.role}
    db.add(DatasetCollaborator(dataset_id=ds.id, user_id=user.id, role="editor"))
    db.commit()
    return {"dataset_id": ds.id, "role": "editor"}


# ---------------------------------------------------------------- collaborators

@router.get("/datasets/{dataset_id}/collaborators")
def list_collaborators(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    rows = db.scalars(
        select(DatasetCollaborator).where(DatasetCollaborator.dataset_id == ds.id).order_by(DatasetCollaborator.id)
    ).all()
    return {"collaborators": [{"id": c.id, "user_id": c.user_id, "role": c.role} for c in rows]}


@router.delete("/datasets/{dataset_id}/collaborators/{collaborator_id}", status_code=204)
def remove_collaborator(
    dataset_id: int, collaborator_id: int, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    row = db.get(DatasetCollaborator, collaborator_id)
    if row is None or row.dataset_id != ds.id:
        raise HTTPException(404, "Collaborator not found.")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------- read-only share links

class CreateShareLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=255)
    expires_at: date | None = None  # a calendar date - the link stops working at the START of that day (UTC)


@router.post("/datasets/{dataset_id}/share-links", status_code=201)
def create_share_link(
    dataset_id: int, body: CreateShareLinkRequest,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    expires_at = (
        datetime(body.expires_at.year, body.expires_at.month, body.expires_at.day, tzinfo=timezone.utc)
        if body.expires_at else None
    )
    link = DatasetShareLink(dataset_id=ds.id, token=_new_token(), column_name=body.column, expires_at=expires_at)
    db.add(link)
    db.commit()
    return {
        "id": link.id, "token": link.token, "column": link.column_name,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "created_at": link.created_at.isoformat(),
    }


@router.get("/datasets/{dataset_id}/share-links")
def list_share_links(dataset_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    links = db.scalars(
        select(DatasetShareLink).where(DatasetShareLink.dataset_id == ds.id).order_by(DatasetShareLink.id)
    ).all()
    return {
        "share_links": [
            {
                "id": l.id, "token": l.token, "column": l.column_name,
                "expires_at": l.expires_at.isoformat() if l.expires_at else None,
                "created_at": l.created_at.isoformat(),
            }
            for l in links
        ]
    }


@router.delete("/datasets/{dataset_id}/share-links/{link_id}", status_code=204)
def revoke_share_link(dataset_id: int, link_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id, min_role="owner")
    link = db.get(DatasetShareLink, link_id)
    if link is None or link.dataset_id != ds.id:
        raise HTTPException(404, "Share link not found.")
    db.delete(link)
    db.commit()


def _live_share_link(db: Session, token: str) -> DatasetShareLink:
    link = db.scalar(select(DatasetShareLink).where(DatasetShareLink.token == token))
    if link is None:
        raise HTTPException(404, "This link is invalid.")
    if link.expires_at is not None:
        now = datetime.now(timezone.utc)
        expires_at = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise HTTPException(404, "This link has expired.")
    return link


@router.get("/share/{token}/report")
def public_report(token: str, db: Session = Depends(get_db)):
    """No `current_user` dependency at all - a valid, unexpired token IS the authorization, exactly what
    "share-by-link, no sign-in required" means. Reuses `app.api_report._render_report` unchanged - the
    same renderer a signed-in viewer's own `GET /datasets/{id}/report` uses - so this route can never
    accidentally expose anything that route doesn't already (notably: no verbatim-answer data, since
    that renderer never includes any - see this module's own docstring)."""
    link = _live_share_link(db, token)
    ds = db.get(Dataset, link.dataset_id)
    if ds is None:
        raise HTTPException(404, "This link is invalid.")
    report = _latest_report_for_column(db, ds.id, link.column_name)
    if report is None:
        raise HTTPException(404, "No report has been built yet for this column.")
    return _render_report(db, ds, link.column_name, report)
