"""Plan and report objects. Both are plain JSON so they can live in datasets.profile["cleaning"]."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PLAN_VERSION = 1


@dataclass
class Step:
    id: str
    key: str
    column: str | None
    title: str
    description: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        return cls(
            id=str(d["id"]), key=str(d["key"]), column=d.get("column"), title=str(d.get("title", "")),
            description=str(d.get("description", "")), enabled=bool(d.get("enabled", True)),
            params=dict(d.get("params") or {}),
        )


@dataclass
class CleaningPlan:
    steps: list[Step]
    settings: dict[str, Any]
    columns: dict[str, dict[str, Any]]  # name -> {"kind", "sensitive"}
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    version: int = PLAN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "settings": self.settings, "columns": self.columns,
            "overrides": self.overrides, "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CleaningPlan":
        return cls(
            steps=[Step.from_dict(s) for s in d.get("steps", [])], settings=dict(d.get("settings") or {}),
            columns=dict(d.get("columns") or {}), overrides=dict(d.get("overrides") or {}),
            version=int(d.get("version", PLAN_VERSION)),
        )


@dataclass
class StepReport:
    id: str
    key: str
    column: str | None
    title: str
    description: str
    enabled: bool
    status: str  # applied | no_change | skipped | failed
    rows_affected: int = 0
    cells_affected: int = 0
    examples: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class CleaningReport:
    rows_in: int
    rows_out: int
    columns_in: int
    columns_out: int
    steps: list[StepReport]
    removed_rows_total: int
    removed_by_step: dict[str, int]
    removed_rows: list[dict[str, Any]]  # capped list; the total above is always exact
    removed_rows_truncated: bool
    removed_columns: list[dict[str, str]]
    excluded_columns: list[str]
    flagged_rows: int
    pii: dict[str, int]
    suppression: dict[str, Any]
    warnings: list[str]
    accounted_for: bool
    version: int = PLAN_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
