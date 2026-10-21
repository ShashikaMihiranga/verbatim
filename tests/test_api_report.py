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
import threading
from threading import Event
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import app.db as db_module
from app.api_report import _SLOTS
from app.api_themes import get_claude_client
from app.api_upload import current_user
from app.db import Base, get_db
from app.main import app
from app.models import Finding, Report, Theme
from app.text_pipeline.labeling import FakeClaudeClient
from tests.job_test_support import BlockingClient, wait_for_job

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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    # A real file-backed SQLite database, not `sqlite://` (in-memory) with a single shared `StaticPool`
    # connection - see tests/test_api_themes.py's own `env` fixture for why: async build jobs now run real
    # pipeline work on a background thread while the main test thread keeps polling, and a shared in-memory
    # connection object serialises that badly (observed directly as sporadic corruption under the full
    # suite). `NullPool` gives every session its own real connection to the same file.
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    # The background job thread `POST .../report/build` now starts does not go through FastAPI's DI (it is
    # not a request) - it opens its own session via `app.db.SessionLocal()` at call time (see app/jobs.py).
    # Point that same module attribute at this test's own engine.
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    yield SimpleNamespace(client=TestClient(app), Session=Session)
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


def start_report_job(env, did, column=Q) -> int:
    """Starts a report build and returns its job id WITHOUT waiting - for tests that need to observe an
    intermediate state before the (fake) pipeline is allowed to finish."""
    r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": column})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running" and body["job_id"]
    return body["job_id"]


def build_report_job(env, did, column=Q, timeout=5.0) -> dict:
    """Starts a report build through the real async route and waits for it to finish, returning the final
    job body - the report-side equivalent of tests/test_api_themes.py's `build_themes_job`."""
    job_id = start_report_job(env, did, column)
    return wait_for_job(env.client, did, job_id, timeout=timeout)


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

    job = build_report_job(env, did)
    assert job["status"] == "done", job
    assert job["error"] is None

    built = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
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
        # chart_html is now a raw body FRAGMENT (app.charts.render_parts's shape), meant to be embedded
        # directly into the report page's own DOM - never a full standalone document any more.
        assert "<!doctype html>" not in b["chart_html"].lower()
        assert "<html" not in b["chart_html"].lower()
        assert isinstance(b["chart_width"], int) and b["chart_width"] > 0
        assert isinstance(b["chart_height"], int) and b["chart_height"] > 0
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


# ---------------------------------------------------------------- "Other" exploration (docs/TODO.md, 2026-10-21 Phase 1)

def test_get_report_other_breakdown_none_with_two_ordinary_themes(env):
    """The common case (<=7 real themes, no noise cluster): nothing to explain, but all_themes still
    lists every real theme."""
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())
    job = build_report_job(env, did)
    assert job["status"] == "done", job

    body = env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).json()
    assert body["other_breakdown"] is None
    assert [t["name"] for t in body["all_themes"]] == ["Reliability", "Support"]
    assert body["all_themes"][0]["count"] == 60
    assert body["all_themes"][1]["count"] == 20


def test_get_report_other_breakdown_splits_noise_from_hidden_real_themes(env):
    """A dataset with more than 7 real themes plus a noise cluster: other_breakdown separates the two,
    and all_themes lists every real theme, not just the 7 the treemap can show."""
    install_fake_claude()
    did = upload_csv(env, survey_df(n_reliability=100, n_support=100))
    clean_and_apply(env, did)
    specs = [
        dict(label=f"T{i}", description=f"Theme {i}.", size=10, sentiment=0.0,
             tone={"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=list(range(i * 10, i * 10 + 10)))
        for i in range(8)  # 8 real themes - one more than the treemap's 7-colour cap
    ]
    specs.append(dict(label="Other", description="Unrelated answers.", size=120, sentiment=0.0,
                       tone={"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=list(range(80, 200))))
    seed_themes(env, did, specs)
    job = build_report_job(env, did)
    assert job["status"] == "done", job

    body = env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).json()
    breakdown = body["other_breakdown"]
    assert breakdown is not None
    assert breakdown["noise_count"] == 120
    assert breakdown["hidden_real_count"] == 10  # T7, the 8th real theme, ranked last of the 8
    assert breakdown["hidden_real_theme_count"] == 1
    assert breakdown["total_real_theme_count"] == 8

    assert len(body["all_themes"]) == 8  # every real theme, "Other" itself excluded
    assert "Other" not in [t["name"] for t in body["all_themes"]]


# ---------------------------------------------------------------- also-checked-nothing-notable

def test_nothing_notable_writes_overview_and_quality_only(env):
    install_fake_claude()
    did = upload_csv(env, survey_df(n_reliability=15, n_support=12))
    clean_and_apply(env, did)
    seed_themes(env, did, nothing_notable_theme_specs())

    job = build_report_job(env, did)
    assert job["status"] == "done", job
    built = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
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

    first = build_report_job(env, did)
    assert first["status"] == "done", first
    second = build_report_job(env, did)
    assert second["status"] == "done", second
    assert second["id"] != first["id"]  # a fresh build replaces the prior Job row too, not just Report/Finding rows

    with env.Session() as s:
        reports = s.scalars(select(Report).where(Report.dataset_id == did)).all()
        findings = s.scalars(select(Finding).where(Finding.dataset_id == did)).all()
    assert len(reports) == 1
    finding_kinds = sorted(f.data["kind"] for f in findings)
    assert finding_kinds == sorted({"dominant_theme", "tone_contrast", "tone_contrast"})


# ---------------------------------------------------------------- filters (segment / score band / date range)

def survey_df_with_rating(n_reliability: int = 60, n_support: int = 20) -> pd.DataFrame:
    """`survey_df()` plus a "Rating" column on an observable 0-10 scale, evenly spread across
    `band_score`'s Low (0-6)/Middle (7-8)/High (9-10) bands, so a confirmed "score" kind survives both the
    cleaning pipeline's own scale detection and (with `MIN_GROUP_SIZE` lowered) build_score_data's
    suppression floor."""
    df = survey_df(n_reliability, n_support)
    n = len(df)
    df["Rating"] = [[0, 7, 10][i % 3] for i in range(n)]  # includes 0 so scale detection locks to (0, 10)
    return df


def setup_filterable_report(env, monkeypatch, timeout=5.0) -> int:
    """Uploads `survey_df_with_rating()`, confirms "Rating" as a score column, cleans, seeds
    `notable_theme_specs()` (Reliability rows 0-59, Support rows 60-79 - matches this fixture's row
    positions exactly), and builds the report. Lowers `MIN_GROUP_SIZE` to 5 so each ~27-row score band
    clears the suppression floor without needing a much larger fixture."""
    monkeypatch.setenv("MIN_GROUP_SIZE", "5")
    install_fake_claude()
    did = upload_csv(env, survey_df_with_rating())
    profile = env.client.get(f"/api/datasets/{did}/profile").json()["profile"]
    cols = [{"position": c["position"], "name": c["name"], "kind": c["kind"], "off": False} for c in profile["columns"]]
    for c in cols:
        if c["name"] == "Rating":
            c["kind"] = "score"
    r = env.client.patch(f"/api/datasets/{did}/columns", json={"columns": cols})
    assert r.status_code == 200, r.text
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())
    job = build_report_job(env, did, timeout=timeout)
    assert job["status"] == "done", job
    return did


def test_get_report_filter_options_present_for_a_confirmed_score_column(env, monkeypatch):
    did = setup_filterable_report(env, monkeypatch)
    body = env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).json()

    assert body["filter_options"]["score_band"] is not None
    assert body["filter_options"]["score_band"]["column"] == "Rating"
    assert set(body["filter_options"]["score_band"]["bands"]) == {"Low (0-6)", "Middle (7-8)", "High (9-10)"}
    assert body["filter_options"]["segment"] is None  # no segment column confirmed in this fixture
    assert body["filter_options"]["date_range"] is None
    assert body["filters_applied"] == {
        "segment": None, "score_band": None, "date_from": None, "date_to": None,
    }


def test_get_report_score_band_filter_changes_chart_html(env, monkeypatch):
    did = setup_filterable_report(env, monkeypatch)
    unfiltered = env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).json()
    filtered = env.client.get(
        f"/api/datasets/{did}/report", params={"column": Q, "score_band": "Low (0-6)"},
    ).json()

    assert filtered["filters_applied"]["score_band"] == "Low (0-6)"
    unfiltered_html = " ".join(b["chart_html"] for b in unfiltered["blocks"])
    filtered_html = " ".join(b["chart_html"] for b in filtered["blocks"])
    assert unfiltered_html != filtered_html  # narrowing to one band visibly changes the rendered charts


def test_get_report_unknown_filter_value_degrades_gracefully_not_an_error(env, monkeypatch):
    """Filtering by a segment group when no segment column was ever confirmed must yield a real (empty)
    result, not a 500 or a silent fall-back to unfiltered."""
    did = setup_filterable_report(env, monkeypatch)
    r = env.client.get(
        f"/api/datasets/{did}/report", params={"column": Q, "segment": "NotARealGroup"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["filters_applied"]["segment"] == "NotARealGroup"


def test_get_report_bad_date_format_is_422(env, monkeypatch):
    did = setup_filterable_report(env, monkeypatch)
    r = env.client.get(
        f"/api/datasets/{did}/report", params={"column": Q, "date_from": "not-a-date"},
    )
    assert r.status_code == 422, r.text
    assert "date_from" in r.json()["detail"]


def test_get_report_no_filter_params_is_unchanged_from_before_filters_existed(env, monkeypatch):
    """Regression guard: a request with no filter query params must produce the exact same
    dataset_id/column/summary/blocks/columns_used as before this feature existed - only the two new
    additive keys (filter_options/filters_applied) are new."""
    did = setup_filterable_report(env, monkeypatch)
    first = env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).json()
    second = env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).json()
    for key in ("dataset_id", "column", "question", "summary", "also_checked_nothing_notable",
                "blocks", "columns_used"):
        assert first[key] == second[key]


# ---------------------------------------------------------------- errors

def test_no_themes_yet_surfaces_as_job_error_not_a_synchronous_422(env):
    """`NoThemesForColumn` can only be known once `build_findings` actually runs (it queries stored `Theme`
    rows), so - like `TooFewAnswers` on the themes side - it now surfaces as `job.error`, not a synchronous
    422; the build route still accepts the request (202) and starts a job."""
    install_fake_claude()
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)

    job = build_report_job(env, did)
    assert job["status"] == "failed", job
    assert "themes" in job["error"].lower()


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
    job = build_report_job(env, did)
    assert job["status"] == "done", job

    as_user(uid2)
    assert env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/report", params={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/jobs/{job['id']}").status_code == 404
    assert env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "report"}).status_code == 404


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
        # The guard stays active for the whole build-then-poll-then-get sequence, not just the POST: the
        # real pipeline work now runs on a background thread that keeps going after the request returns,
        # and `socket.socket` is patched process-wide (not per-thread), so a socket opened from that thread
        # while this `with` block is still open would still be caught.
        job = build_report_job(env, did)
        assert job["status"] == "done", job
        g = env.client.get(f"/api/datasets/{did}/report", params={"column": Q})
        assert g.status_code == 200, g.text


# ---------------------------------------------------------------- async job behaviour (this stream)

def test_job_step_changes_while_running_then_reaches_done(env):
    """The core ask of this stream: a poller sees a real intermediate `job.step` before the job reaches
    "done" - `BlockingClient` pauses the fake Claude client's `complete` method (the one real network-
    shaped call `build_findings` makes, for `write_headline`) on a `threading.Event` this test controls."""
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())

    blocking = BlockingClient(FakeClaudeClient(_fake_claude_reply), "complete")
    app.dependency_overrides[get_claude_client] = lambda: blocking

    job_id = start_report_job(env, did)

    assert blocking.reached.wait(timeout=5), "the pipeline never reached the headline-writing call"
    mid = env.client.get(f"/api/datasets/{did}/jobs/{job_id}")
    assert mid.status_code == 200, mid.text
    mid_body = mid.json()
    assert mid_body["status"] == "running"
    assert mid_body["step"] == "Deciding what's worth telling"
    assert mid_body["error"] is None

    blocking.released.set()
    final = wait_for_job(env.client, did, job_id, timeout=5)
    assert final["status"] == "done", final
    assert final["step"] == "Done"


def test_latest_job_lookup_lets_a_reloaded_page_resume_watching(env):
    """`GET .../jobs/latest` is what a reloaded page uses to find a build it did not itself start - see
    tests/test_api_themes.py's identical test for the fuller rationale; this is the report-side version,
    checked mid-run (not just after the fact) using the same blocking-Claude-client trick."""
    did = upload_csv(env, survey_df())
    clean_and_apply(env, did)
    seed_themes(env, did, notable_theme_specs())

    nothing_yet = env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "report"})
    assert nothing_yet.status_code == 404

    blocking = BlockingClient(FakeClaudeClient(_fake_claude_reply), "complete")
    app.dependency_overrides[get_claude_client] = lambda: blocking
    job_id = start_report_job(env, did)
    assert blocking.reached.wait(timeout=5)

    latest = env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "report"})
    assert latest.status_code == 200, latest.text
    assert latest.json()["id"] == job_id
    assert latest.json()["status"] == "running"
    # a different kind for the same dataset+column must not match
    assert env.client.get(
        f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "themes"}
    ).status_code == 404

    blocking.released.set()
    final = wait_for_job(env.client, did, job_id, timeout=5)
    assert final["status"] == "done", final
    latest_done = env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "report"})
    assert latest_done.json()["id"] == job_id
    assert latest_done.json()["status"] == "done"


class _TwoWayBlock:
    """Like `tests.job_test_support.BlockingClient`, but only releases its callers once (at least) TWO
    concurrent calls have arrived - needed to prove `REPORT_CONCURRENCY`'s default cap of 2 is genuinely
    exhausted by two real (blocked) jobs at once, not just simulated by holding the semaphore directly."""

    def __init__(self, inner, method_name: str) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self.both_reached = Event()
        self.released = Event()

        def _blocking(*args, **kwargs):
            with self._lock:
                self._count += 1
                if self._count >= 2:
                    self.both_reached.set()
            ok = self.released.wait(timeout=10)
            if not ok:
                raise AssertionError(f"_TwoWayBlock.{method_name} was never released by the test")
            return getattr(inner, method_name)(*args, **kwargs)

        setattr(self, method_name, _blocking)


def test_concurrency_cap_holds_while_jobs_are_genuinely_running(env):
    """Unlike `test_concurrency_cap_returns_429` above (which simulates busy slots by acquiring `_SLOTS`
    directly, with no real work happening), this drives two REAL background jobs that are genuinely still
    running (both blocked on a fake Claude client) to exhaust `REPORT_CONCURRENCY`'s default cap of 2, shows
    a third build attempt is still rejected (429) while they hold both slots, then that both still complete
    normally once released."""
    blocking = _TwoWayBlock(FakeClaudeClient(_fake_claude_reply), "complete")
    app.dependency_overrides[get_claude_client] = lambda: blocking

    # Distinct content per upload (not just a different `name`): `POST /api/upload` dedupes by content hash
    # per user, so three byte-identical files would silently reuse the same one `Dataset` row - each call
    # below varies `n_support` so the three uploads are genuinely different datasets.
    did1 = upload_csv(env, survey_df(n_support=20), name="a.csv")
    clean_and_apply(env, did1)
    seed_themes(env, did1, notable_theme_specs())

    did2 = upload_csv(env, survey_df(n_support=21), name="b.csv")
    clean_and_apply(env, did2)
    seed_themes(env, did2, notable_theme_specs())

    job1_id = start_report_job(env, did1)
    job2_id = start_report_job(env, did2)
    assert blocking.both_reached.wait(timeout=5), "both jobs never reached the blocking call at the same time"

    did3 = upload_csv(env, survey_df(n_support=22), name="c.csv")
    clean_and_apply(env, did3)
    seed_themes(env, did3, notable_theme_specs())
    r3 = env.client.post(f"/api/datasets/{did3}/report/build", json={"column": Q})
    assert r3.status_code == 429, r3.text

    blocking.released.set()
    final1 = wait_for_job(env.client, did1, job1_id, timeout=5)
    final2 = wait_for_job(env.client, did2, job2_id, timeout=5)
    assert final1["status"] == "done", final1
    assert final2["status"] == "done", final2
