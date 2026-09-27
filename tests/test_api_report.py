"""Stream 8: the dynamic-report API. Fake Claude client only, no real network anywhere - see
test_zero_network_is_ever_attempted below (mirrors tests/test_findings.py's own socket-blocking guard).

Themes are seeded directly into the test database (mirroring tests/test_findings.py's
`seed_dataset_and_themes`, not the real embed/cluster pipeline) so candidate sizes/sentiments can be chosen
precisely and honestly against app/findings.py's own documented thresholds - `candidate_findings`'s
`min_group_size`/gate constants - rather than hoping a fake bag-of-words embedding client happens to
cluster a certain way. This module never touches app/findings.py's own thresholds; it only picks inputs
that are known (by reading them) to clear or miss those thresholds.
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api_report import _SLOTS
from app.api_themes import get_claude_client
from app.api_upload import current_user
from app.db import Base, get_db
from app.main import app
from app.models import Finding, Report, Theme
from app.text_pipeline.labeling import FakeClaudeClient

Q = "What could we do better?"


# ---------------------------------------------------------------- fixture data

def _reliability_phrase(i: int) -> str:
    return f"Reliability complaint number {i}: the battery drains fast and it overheats constantly, very annoying."


def _support_phrase(i: int) -> str:
    return f"Support praise number {i}: the staff were friendly and helpful, checkout felt welcoming."


def survey_df(n_reliability: int = 60, n_support: int = 20) -> pd.DataFrame:
    """Distinct text per row (each carries a running number) so cleaning's blank/duplicate steps never
    drop a row - this fixture needs stable, predictable row positions to match `Theme.answer_refs` against."""
    text = [_reliability_phrase(i) for i in range(n_reliability)] + [_support_phrase(i) for i in range(n_support)]
    return pd.DataFrame({"Respondent ID": range(1, len(text) + 1), Q: text}).astype(object)


def _fake_claude_reply(prompt: str) -> str:
    """Handles BOTH prompt shapes `get_claude_client` is reused for: theme labelling
    (`app.text_pipeline.labeling.label_clusters`, {"clusters": [...]}) and headline writing
    (`app.findings.write_headline`, {"findings": [...]}) - this router shares one Claude-client provider
    with app/api_themes.py, so a test overriding it must speak both."""
    payload = json.loads(prompt)
    if "clusters" in payload:
        themes = [
            {"cluster_id": c["cluster_id"], "label": f"Theme {c['cluster_id']}",
             "description": f"About cluster {c['cluster_id']}.", "merge_with": [], "note": None}
            for c in payload["clusters"]
        ]
        return json.dumps({"themes": themes})
    if "findings" in payload:
        sent = payload["findings"]
        return json.dumps({
            "headlines": [{"id": f["id"], "sentence": f"Stub sentence about {f['theme']}."} for f in sent]
        })
    raise AssertionError(f"unexpected prompt shape sent to the fake Claude client: {prompt}")


def install_fake_claude():
    app.dependency_overrides[get_claude_client] = lambda: FakeClaudeClient(_fake_claude_reply)


# ---------------------------------------------------------------- fixtures (mirrors tests/test_api_themes.py)

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield SimpleNamespace(client=TestClient(app), Session=Session, uploads=tmp_path / "uploads")
    app.dependency_overrides.clear()


def as_user(uid):
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uid)


def make_users(env, *clerk_ids):
    from app.models import User
    ids = []
    with env.Session() as s:
        for c in clerk_ids:
            u = User(clerk_id=c)
            s.add(u)
            s.commit()
            ids.append(u.id)
    return ids


def upload_csv(env, df, name="survey.csv"):
    data = df.to_csv(index=False).encode("utf-8")
    r = env.client.post("/api/upload", files={"file": (name, data, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def clean_and_apply(env, did):
    r = env.client.post(f"/api/datasets/{did}/clean/plan")
    assert r.status_code == 200, r.text
    r3 = env.client.post(f"/api/datasets/{did}/clean/apply")
    assert r3.status_code == 200, r3.text
    return r3.json()


def seed_themes(env, did, specs: list[dict]):
    with env.Session() as s:
        for spec in specs:
            s.add(Theme(dataset_id=did, column_name=Q, **spec))
        s.commit()


# Two themes that clear both `candidate_findings`' size floor (min_group_size, default 30) and their
# kind-specific effect-size gates: Reliability (60 answers, share 75%, clear #1 -> dominant_theme;
# sentiment -0.30) and Support (20 answers, sentiment +0.30). Weighted overall sentiment is -0.15, so both
# themes clear TONE_GAP_MIN (0.08); Reliability's own gap (0.15) sits just under TONE_GAP_SOLID (0.16) so
# it stays "Tentative" even though its count clears the Solid count floor - only the dominant_theme finding
# (share 75% >= DOMINANT_SHARE_SOLID 35%) should come out "Solid". Checked against the real thresholds in
# app/findings.py, not guessed.
def notable_theme_specs() -> list[dict]:
    return [
        dict(label="Reliability", description="Battery and overheating complaints.", size=60, sentiment=-0.30,
             tone={"neg": 70.0, "neu": 20.0, "pos": 10.0}, answer_refs=list(range(0, 60))),
        dict(label="Support", description="Praise for staff and checkout.", size=20, sentiment=0.30,
             tone={"neg": 10.0, "neu": 20.0, "pos": 70.0}, answer_refs=list(range(60, 80))),
    ]


# Nothing clears any gate: near-identical sentiment, no theme anywhere near a "clear #1", every group
# smaller than min_group_size (30) so candidate_findings discards them before scoring even starts (see
# app/findings.py:candidate_findings - "must clear min_group_size... before it is even considered").
def nothing_notable_theme_specs() -> list[dict]:
    return [
        dict(label="A", description="First group.", size=10, sentiment=-0.05,
             tone={"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=list(range(0, 10))),
        dict(label="B", description="Second group.", size=9, sentiment=-0.05,
             tone={"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=list(range(10, 19))),
        dict(label="C", description="Third group.", size=8, sentiment=-0.05,
             tone={"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=list(range(19, 27))),
    ]


# ---------------------------------------------------------------- build-then-get round trip (the important one)

def test_build_then_get_round_trip_renders_real_chart_html_with_real_theme_names(env):
    install_fake_claude()
    did = upload_csv(env, survey_df())
    applied = clean_and_apply(env, did)
    assert applied["report"]["rows_out"] == 80  # no rows silently dropped - answer_refs below assume this
    seed_themes(env, did, notable_theme_specs())

    built = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert built.status_code == 200, built.text
    body = built.json()

    assert body["dataset_id"] == did and body["column"] == Q
    assert body["also_checked_nothing_notable"] is False
    assert "Reliability" not in body["summary"]  # the summary is plain arithmetic, not theme names
    assert "theme" in body["summary"] and "tone" in body["summary"]

    kinds = [b["kind"] for b in body["blocks"]]
    assert kinds[0] == "overview" and kinds[-1] == "quality"
    assert "finding" in kinds  # at least one real finding block, not just overview/quality

    finding_blocks = [b for b in body["blocks"] if b["kind"] == "finding"]
    assert len(finding_blocks) >= 1
    all_html = " ".join(b["chart_html"] for b in body["blocks"])
    assert "Reliability" in all_html and "Support" in all_html  # real theme names reached a real chart

    for b in finding_blocks:
        assert b["finding"] is not None
        assert b["finding"]["sentence"].startswith("Stub sentence about")
        assert b["finding"]["confidence"] in ("solid", "tentative")
        assert b["finding"]["theme_id"] is not None
        assert "<!doctype html>" in b["chart_html"].lower()
        assert b["chart_title"]  # a human title from app.charts.TITLES, not the bare chart_id

    solid = {b["finding"]["sentence"] for b in finding_blocks if b["finding"]["confidence"] == "solid"}
    assert solid, "the dominant Reliability finding (75% share) should be Solid"

    # GET returns the same shape, re-rendered fresh rather than replaying stored HTML
    got = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
    assert got.status_code == 200, got.text
    got_body = got.json()
    assert got_body["question"] == body["question"]
    assert {b["kind"] for b in got_body["blocks"]} == {b["kind"] for b in body["blocks"]}
    assert [b["finding"]["sentence"] for b in got_body["blocks"] if b["finding"]] == \
           [b["finding"]["sentence"] for b in body["blocks"] if b["finding"]]

    # "See answers" reuses app/api_themes.py's existing endpoint - not duplicated here.
    a_theme_id = finding_blocks[0]["finding"]["theme_id"]
    answers = env.client.get(f"/api/datasets/{did}/themes/{a_theme_id}/answers")
    assert answers.status_code == 200, answers.text
    assert answers.json()["answers"]


# ---------------------------------------------------------------- also-checked-nothing-notable

def test_nothing_notable_writes_overview_and_quality_only(env):
    install_fake_claude()
    did = upload_csv(env, survey_df(n_reliability=15, n_support=12))
    clean_and_apply(env, did)
    seed_themes(env, did, nothing_notable_theme_specs())

    built = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["also_checked_nothing_notable"] is True
    assert [b["kind"] for b in body["blocks"]] == ["overview", "quality"]
    assert all(b["finding"] is None for b in body["blocks"])

    got = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
    assert got.status_code == 200, got.text
    assert got.json()["also_checked_nothing_notable"] is True


# ---------------------------------------------------------------- rebuild replaces, not duplicates

def test_rebuild_replaces_prior_report_not_duplicates(env):
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())

    first = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert first.status_code == 200, first.text
    second = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert second.status_code == 200, second.text

    with env.Session() as s:
        reports = s.scalars(select(Report).where(Report.dataset_id == did)).all()
        findings = s.scalars(select(Finding).where(Finding.dataset_id == did)).all()
    assert len(reports) == 1
    finding_kinds = sorted(f.data["kind"] for f in findings)
    assert finding_kinds == sorted({"dominant_theme", "tone_contrast", "tone_contrast"})


# ---------------------------------------------------------------- errors

def test_no_themes_yet_returns_422(env):
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert r.status_code == 422, r.text
    assert "themes" in r.json()["detail"].lower()


def test_missing_claude_key_returns_503(env):
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())

    r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert r.status_code == 503, r.text
    assert "claude" in r.json()["detail"].lower()
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_get_before_any_report_says_which_prior_step_is_missing(env):
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)

    # no themes at all yet: distinct message from "no report yet"
    no_themes = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
    assert no_themes.status_code == 404
    assert "themes" in no_themes.json()["detail"].lower()

    # themes exist, but the report was never built
    seed_themes(env, did, notable_theme_specs())
    no_report = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
    assert no_report.status_code == 404
    assert "report" in no_report.json()["detail"].lower()
    assert no_report.json()["detail"] != no_themes.json()["detail"]


def test_concurrency_cap_returns_429(env):
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())

    assert _SLOTS.acquire(blocking=False)  # simulate a job already running (default cap is 2)
    try:
        assert _SLOTS.acquire(blocking=False)  # exhaust both slots
        try:
            r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
            assert r.status_code == 429, r.text
        finally:
            _SLOTS.release()
    finally:
        _SLOTS.release()


# ---------------------------------------------------------------- ownership isolation

def test_ownership_isolation(env):
    install_fake_claude()
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())
    built = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert built.status_code == 200, built.text

    as_user(uid2)
    assert env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).status_code == 404


# ---------------------------------------------------------------- no real network

class _NoSockets:
    """Mirrors tests/test_findings.py's own socket-blocking guard, adapted for the API layer: unlike that
    module (which calls app.findings functions directly), this file drives requests through FastAPI's
    TestClient, whose ASGI event-loop plumbing opens its own local AF_UNIX socketpairs for every request -
    nothing to do with network access. Only AF_INET/AF_INET6 (real network families) are blocked here."""

    def __enter__(self):
        self._orig = socket.socket

        def _guarded(family=socket.AF_INET, *a, **k):
            if family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("a real network socket was opened - network access is not allowed here")
            return self._orig(family, *a, **k)

        socket.socket = _guarded
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig


def test_zero_network_is_ever_attempted(env):
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())

    with _NoSockets():
        r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
        assert r.status_code == 200, r.text
        g = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
        assert g.status_code == 200, g.text
