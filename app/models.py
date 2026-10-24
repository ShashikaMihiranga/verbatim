from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    clerk_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = _created()


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="project")


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    row_count: Mapped[int | None] = mapped_column(Integer)
    profile: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()
    project: Mapped[Project] = relationship(back_populates="datasets")


class Column(Base):
    __tablename__ = "columns"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer)
    # text | number | category | date | id | ignore
    kind: Mapped[str] = mapped_column(String(32))
    stats: Mapped[dict | None] = mapped_column(JSON)
    # A bounded SAMPLE of real per-answer 0..1 positions for the answer_map block (chart-block stream,
    # 2026-10-24, batch 4), {"row_index_as_str": [x, y]} - a dict, not a 2D array, because only a subset
    # of rows is ever sampled (see app/api_themes.py's own comment on why) and a dict keeps each point
    # attached to its real row index rather than an implicit position. Kept on `Column`, not `Theme`: a
    # position describes the ANSWER's own semantic location, independent of which theme it currently
    # belongs to (unlike `Theme.map_x/map_y`, which is a property of the theme's own cluster). `None`
    # (the default, and every column built before this stream) means no real positions exist yet.
    answer_positions: Mapped[dict | None] = mapped_column(JSON)


class Theme(Base):
    __tablename__ = "themes"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    column_id: Mapped[int | None] = mapped_column(ForeignKey("columns.id", ondelete="SET NULL"))
    # the open-text column name this theme was built from. Kept as a plain string (not just `column_id`)
    # so themes can be listed/filtered/replaced without depending on a matching `columns` row existing -
    # see app/api_themes.py and docs/DECISIONS.md (2026-09-25 entry).
    column_name: Mapped[str | None] = mapped_column(String(255), index=True)
    label: Mapped[str] = mapped_column(String(255))
    # one plain sentence describing what the answers in this theme have in common (Claude's read, or the
    # locally-synthesized "Other" description - see app/text_pipeline/labeling.py:ThemeLabel.description)
    description: Mapped[str | None] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, default=0)
    sentiment: Mapped[float | None] = mapped_column()  # aggregate polarity, mean of this theme's AnswerScores
    # neg/neu/pos percentage split for this theme's answers (app.chart_data.ToneSplit shape), stored as
    # {"neg": float, "neu": float, "pos": float}; see app/api_themes.py and docs/DECISIONS.md.
    tone: Mapped[dict | None] = mapped_column(JSON)
    # row indexes of real answers behind this theme
    answer_refs: Mapped[list | None] = mapped_column(JSON)
    # up to 3 sub-themes (second HDBSCAN pass inside this theme's own answers - see
    # app/text_pipeline/subthemes.py), largest first. Each entry:
    # {"label": str, "description": str, "size": int, "sentiment": float,
    #  "tone": {"neg": float, "neu": float, "pos": float}, "answer_refs": list[int]}.
    # [] when this theme was not split (below the size floor, capped out at t1..t7, coverage/count
    # gates not met, or labeling failed) or is "Other" (never sub-clustered).
    sub_themes: Mapped[list | None] = mapped_column(JSON)
    # 0..1 position on the theme-similarity map (chart-block stream, 2026-10-24, batch 3: theme_similarity
    # block) - a 2D PCA projection of this theme's real cluster centroid (already computed by HDBSCAN at
    # build time, see app/text_pipeline/clustering.py's `store_centers="centroid"` - no extra embedding
    # call, no new network cost). Both None for "Other" (noise has no single centroid to project) and for
    # any theme built before this stream (an old row simply has nothing to show on this one chart, same
    # "honest gap, not an invented position" contract every other not-yet-backfilled field in this app
    # already follows - see ThemeNode.map_xy's own docstring in app/chart_data.py).
    map_x: Mapped[float | None] = mapped_column()
    map_y: Mapped[float | None] = mapped_column()


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    theme_id: Mapped[int | None] = mapped_column(ForeignKey("themes.id", ondelete="SET NULL"))
    sentence: Mapped[str] = mapped_column(Text)
    chart_type: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(16), default="tentative")  # solid | tentative
    data: Mapped[dict | None] = mapped_column(JSON)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    content: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()


class UploadedFile(Base):
    """The raw bytes of an uploaded spreadsheet, content-addressed by sha256 (see app/api_upload.py).

    Postgres, not disk: Railway's container filesystem does not survive a redeploy, and its attached
    volume path is not reliably writable by this app's non-root user either - see docs/DECISIONS.md.
    Pure blob store, deduplicated by hash exactly the way the old `UPLOAD_DIR/<hash><ext>` disk path was -
    only the storage backend changed, not the addressing scheme. A row here is independent of any one
    `Dataset`/user: the same bytes uploaded by two different users share one row.
    """
    __tablename__ = "uploaded_files"
    file_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created()


class CleanedFile(Base):
    """The cleaned CSV bytes produced by `app/api_cleaning.py:apply_cleaning`, content-addressed by sha256
    of those bytes - the same addressing `UPLOAD_DIR/<hash>.clean.csv` used on disk, now in Postgres. See
    `UploadedFile`'s docstring for why disk storage was dropped."""
    __tablename__ = "cleaned_files"
    clean_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created()


class Job(Base):
    """A background build (themes or report) that runs in a daemon thread, not inside the request that
    started it (see app/jobs.py and docs/DECISIONS.md, "async build jobs"). One row per build attempt for
    a dataset+column+kind - a fresh build replaces the prior job row the same way `Theme` rows are already
    replaced on rebuild, so `GET .../jobs/latest` always has at most one row to find.
    """
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    column_name: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "themes" | "report"
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    # short plain-English phase, e.g. "Turning answers into vectors" - never jargon, never a raw percentage
    step: Mapped[str] = mapped_column(String(255), default="Starting")
    # the exact human-readable message a caller would previously have received as an HTTP error body -
    # never a raw traceback (see app/jobs.py:_error_message_for)
    error: Mapped[str | None] = mapped_column(Text)
    # Small, job-kind-specific summary written once a job finishes successfully (docs/TODO.md, 2026-10-21
    # Stage 3: "Look inside Other"'s own Known/New/Still-in-Other results panel needs real numbers, not a
    # second query reconstructing them after the fact). `None` for every job kind that has nothing to
    # summarize (themes, report) - this column is optional on purpose, not every job needs one.
    result: Mapped[dict | None] = mapped_column(JSON)
    # Live counts while a job runs ("Look inside Other": answers matched so far per known/new theme), so the
    # report can show real progress rather than a simulated count-up. None for jobs that don't report any.
    progress: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SigninVariantLog(Base):
    __tablename__ = "signin_variant_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    variant: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = _created()


class DatasetCollaborator(Base):
    """Sharing/roles (SPEC.md section 5; docs/TODO.md, fixed 2026-10-22): a signed-in `User` other than
    the dataset's own owner, with an "editor" or "viewer" role on that dataset. The owner is never a row
    here - ownership stays implicit via the existing `Dataset.project.user_id` path (`app/api_upload.py`'s
    `_own_dataset`, now role-aware - see that function's own docstring), unchanged by this feature. Added
    via an accepted invite link (`app/api_sharing.py`), never directly - there is no way to add a
    collaborator by email/account lookup: Clerk auth here is JWT-verification only (no Clerk secret key,
    no user directory API - confirmed via `app/auth.py`), so this app has no way to resolve "the person
    with this email" to a `User` row before they have signed in at least once themselves."""
    __tablename__ = "dataset_collaborators"
    __table_args__ = (UniqueConstraint("dataset_id", "user_id", name="uq_dataset_collaborator"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "editor" | "viewer"
    created_at: Mapped[datetime] = _created()


class DatasetInviteLink(Base):
    """An owner-created link that grants "editor" access to WHOEVER signs in and visits it
    (`app/api_sharing.py`'s accept route) - the realistic stand-in for "invite a teammate by email" given
    the Clerk-JWT-only constraint `DatasetCollaborator`'s own docstring explains. Reusable (not single-use)
    unless the owner revokes it; no expiry field - an editor invite is meant to stay valid until revoked,
    unlike a read-only share link below, which SPEC.md explicitly asks to support an optional expiry."""
    __tablename__ = "dataset_invite_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = _created()


class DatasetShareLink(Base):
    """A read-only, no-sign-in-required share-by-link (SPEC.md section 5), with an optional expiry. Grants
    "viewer" access ONLY, resolved via a token-gated public route (`app/api_sharing.py`'s `GET
    /api/share/{token}/...`), never through the normal authenticated dataset routes - those stay
    `current_user`-gated regardless of a valid share token, so a share link can never see more than the
    specific read-only views that public route set exposes (notably: no verbatim-answer route exists on
    that path at all - see `app/api_sharing.py`'s own module docstring for why that is the real
    "hide verbatims for external audiences" mechanism, not a redaction toggle)."""
    __tablename__ = "dataset_share_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    column_name: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
