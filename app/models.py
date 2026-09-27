from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
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
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SigninVariantLog(Base):
    __tablename__ = "signin_variant_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    variant: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = _created()
