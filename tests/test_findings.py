"""Findings engine (stream 7): app/findings.py. FakeClaudeClient only, no network - see
test_zero_network_is_ever_attempted below for an explicit socket-block guard, matching the network-free
guarantee already verified elsewhere in this repo (tests/test_jev_sentiment.py, test_text_pipeline_labeling.py).
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.charts import render
from app.db import Base
from app.findings import (
    Candidate,
    FakeClaudeClient,
    FindingsClaudeNotConfigured,
    FindingsError,
    NoThemesForColumn,
    build_findings,
    build_report_data,
    candidate_findings,
    default_claude_client,
    label_confidence,
    pick_chart,
    write_headline,
)
from app.models import Dataset, Finding, Report, Theme

QUESTION = "Why haven't you bought an electric vehicle yet?"


# ---------------------------------------------------------------- fixture builders

def make_theme(tid, label, size, sentiment, tone=None, column_name="Why", dataset_id=1, description=None):
    t = Theme(
        dataset_id=dataset_id, column_name=column_name, label=label, description=description,
        size=size, sentiment=sentiment, tone=tone or {"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=[],
    )
    t.id = tid  # unpersisted rows: assign a stable fake id so Candidate.id stays unique across kinds/tests
    return t


def tone_contrast_themes():
    """Two themes clear the tone-contrast gate (Charging very negative, NotNeeded positive); the rest sit
    close to the (weighted) overall sentiment and neither theme count is a clear #1 nor is Other oversized."""
    return [
        make_theme(1, "Cost", 300, -0.05),
        make_theme(2, "Charging", 260, -0.30),
        make_theme(3, "Range", 160, -0.05),
        make_theme(4, "Not needed", 100, 0.25),
        make_theme(5, "Doubts", 80, -0.05),
        make_theme(6, "Availability", 50, -0.05),
        make_theme(7, "Other", 50, -0.03),
    ]


def dominant_and_longtail_themes():
    """One theme clearly dominates (60% share, 45-point lead) and "Other" sits right at the long-tail
    gate (15%); every theme shares the same sentiment, so no tone-contrast candidate should appear."""
    return [
        make_theme(1, "Cost", 600, -0.05),
        make_theme(2, "Charging", 150, -0.05),
        make_theme(3, "Range", 100, -0.05),
        make_theme(4, "Other", 150, -0.05),
    ]


def six_tone_contrast_themes():
    """Six themes all clear the tone-contrast gate (to prove the 5-candidate cap and score ordering);
    sentiments are symmetric so the dataset's overall sentiment is exactly 0."""
    return [
        make_theme(1, "T1", 100, -0.5),
        make_theme(2, "T2", 100, -0.4),
        make_theme(3, "T3", 100, -0.3),
        make_theme(4, "T4", 100, 0.3),
        make_theme(5, "T5", 100, 0.4),
        make_theme(6, "T6", 100, 0.5),
        make_theme(7, "Other", 50, 0.0),
    ]


def nothing_notable_themes():
    """Nothing clears any gate: sentiments are identical, shares are close, Other is small."""
    return [
        make_theme(1, "A", 200, -0.05),
        make_theme(2, "B", 180, -0.05),
        make_theme(3, "C", 170, -0.05),
        make_theme(4, "Other", 50, -0.05),
    ]


# ==================================================================== candidate_findings

def test_tone_contrast_candidates_found_scored_and_ordered():
    candidates = candidate_findings(tone_contrast_themes())
    kinds_and_names = [(c.kind, c.theme_name) for c in candidates]
    assert kinds_and_names == [("tone_contrast", "Not needed"), ("tone_contrast", "Charging")]
    # "Not needed"'s gap (+0.334) is bigger than Charging's (-0.216), so it scores and ranks first
    assert candidates[0].score > candidates[1].score
    for c in candidates:
        assert abs(c.numbers["gap"]) >= 0.08
        assert c.numbers["overall_sentiment"] == pytest.approx(-0.084, abs=1e-3)


def test_dominant_theme_and_long_tail_candidates():
    candidates = candidate_findings(dominant_and_longtail_themes())
    by_kind = {c.kind: c for c in candidates}
    assert set(by_kind) == {"dominant_theme", "long_tail"}
    dom = by_kind["dominant_theme"]
    assert dom.theme_name == "Cost"
    assert dom.numbers["share_pct"] == pytest.approx(60.0)
    assert dom.numbers["margin_pct"] == pytest.approx(45.0)
    tail = by_kind["long_tail"]
    assert tail.theme_name == "Other"
    assert tail.numbers["share_pct"] == pytest.approx(15.0)
    # dominant's much bigger margin outranks the long tail's share
    assert dom.score > tail.score


def test_candidates_capped_at_five_and_weakest_tie_dropped():
    candidates = candidate_findings(six_tone_contrast_themes())
    assert len(candidates) == 5  # 6 qualify, capped at MAX_CANDIDATES
    names = [c.theme_name for c in candidates]
    assert "T4" not in names  # T3 and T4 tie on |gap|=0.3; T3 was listed first and wins the stable sort
    assert "T3" in names
    assert names == ["T1", "T6", "T2", "T5", "T3"]


def test_nothing_notable_returns_no_candidates():
    """SPEC.md section 5's "also checked, nothing notable" case: the engine must be able to say nothing,
    not force a weak candidate in just to have something to show."""
    assert candidate_findings(nothing_notable_themes()) == []


def test_small_groups_are_discarded_before_scoring():
    # An enormous sentiment gap on a tiny group must not become a tone-contrast candidate - "Big" still
    # legitimately qualifies as a dominant-theme candidate (90% share), which is the correct, unrelated
    # behaviour this test is not about.
    themes = [
        make_theme(1, "Big", 500, -0.05),
        make_theme(2, "Tiny", 5, -0.90),
        make_theme(3, "Other", 50, -0.05),
    ]
    candidates = candidate_findings(themes, min_group_size=30)
    assert all(c.theme_name != "Tiny" for c in candidates)
    assert [c.kind for c in candidates] == ["dominant_theme"]


# ==================================================================== label_confidence

def test_label_confidence_thresholds():
    solid_tone = Candidate("tone_contrast", "x", 1, "X", count=100, score=1.0, numbers={"gap": -0.2, "share_pct": 10})
    assert label_confidence(solid_tone) == "solid"

    weak_gap = Candidate("tone_contrast", "x", 1, "X", count=100, score=1.0, numbers={"gap": -0.09, "share_pct": 10})
    assert label_confidence(weak_gap) == "tentative"  # count is fine, but the gap is below TONE_GAP_SOLID

    small_group = Candidate("tone_contrast", "x", 1, "X", count=40, score=1.0, numbers={"gap": -0.5, "share_pct": 10})
    assert label_confidence(small_group) == "tentative"  # gap is huge, but count is below the solid floor

    solid_dom = Candidate("dominant_theme", "x", 1, "X", count=200, score=1.0, numbers={"share_pct": 40})
    assert label_confidence(solid_dom) == "solid"
    tentative_dom = Candidate("dominant_theme", "x", 1, "X", count=200, score=1.0, numbers={"share_pct": 26})
    assert label_confidence(tentative_dom) == "tentative"

    solid_tail = Candidate("long_tail", "x", 1, "X", count=200, score=1.0, numbers={"share_pct": 30})
    assert label_confidence(solid_tail) == "solid"
    tentative_tail = Candidate("long_tail", "x", 1, "X", count=200, score=1.0, numbers={"share_pct": 16})
    assert label_confidence(tentative_tail) == "tentative"


# ==================================================================== pick_chart

def test_pick_chart_mapping_and_the_sunburst_to_treemap_fallback():
    """SPEC.md section 4's table: "Sunburst: ...Skip when fewer than 3 sub-themes in total, use treemap."
    Every ReportData this engine builds has zero sub-themes (see app/findings.py's module docstring), so
    a "theme breakdown" finding (long_tail) must use the table's own stated fallback (treemap), never
    sunburst - this test pins that down explicitly rather than leaving it implicit."""
    tone = Candidate("tone_contrast", "x", 1, "X", count=1, score=1.0, numbers={})
    dominant = Candidate("dominant_theme", "x", 1, "X", count=1, score=1.0, numbers={})
    long_tail = Candidate("long_tail", "x", 1, "X", count=1, score=1.0, numbers={})
    assert pick_chart(tone) == "sentsun"
    assert pick_chart(dominant) == "rank"
    assert pick_chart(long_tail) == "treemap"
    assert pick_chart(long_tail) != "sunburst"


# ==================================================================== build_report_data + render() smoke test

def test_build_report_data_renders_through_real_charts_module():
    """The single most important test: proves the ReportData this engine builds is actually consumable by
    app/charts.py's existing render(), not just internally self-consistent."""
    dataset = SimpleNamespace(row_count=1000)
    cleaning_report = {
        "rows_in": 1000, "rows_out": 950, "removed_by_step": {"blank_non_answers:Why": 30, "collapse_duplicate_answers": 20},
        "pii": {"email": 4, "phone": 1},
    }
    data = build_report_data(dataset, dominant_and_longtail_themes(), cleaning_report, QUESTION)

    assert [t.name for t in data.themes] == ["Cost", "Charging", "Range", "Other"]
    assert data.themes[-1].color == "other"
    assert data.themes[0].color == "t1" and data.themes[1].color == "t2"
    assert all(t.children == [] for t in data.themes)  # sub-theme wiring is out of scope

    for frame_id in ("overview", "treemap", "rank", "sentsun", "quality"):
        html = render(frame_id, data)
        assert html.startswith("<!doctype html>")
        if frame_id in ("treemap", "sentsun"):
            assert "<svg" in html
        if frame_id in ("treemap", "rank", "sentsun"):
            assert "Cost" in html and "Charging" in html  # real theme data reached the renderer


def test_build_report_data_quality_notes_reflect_real_cleaning_counts():
    dataset = SimpleNamespace(row_count=1000)
    cleaning_report = {"removed_by_step": {"blank_non_answers:Why": 12}, "pii": {"email": 3}}
    data = build_report_data(dataset, dominant_and_longtail_themes(), cleaning_report, QUESTION)
    assert "12" in data.quality.notes[0]
    assert "3" in data.quality.notes[1]
    assert data.quality.typical_bin == "n/a"  # no answer_lengths passed: honest placeholder, not invented


def test_build_report_data_answer_lengths_produce_a_real_histogram():
    dataset = SimpleNamespace(row_count=100)
    lengths = [3] * 10 + [7] * 30 + [15] * 5
    data = build_report_data(dataset, dominant_and_longtail_themes(), {}, QUESTION, answer_lengths=lengths)
    assert data.quality.typical_bin == "6-8"
    assert dict(data.quality.bins)["6-8"] == 30


# ==================================================================== write_headline

def reply_stub(prompt: str) -> str:
    sent = json.loads(prompt)["findings"]
    return json.dumps({"headlines": [{"id": f["id"], "sentence": f"Stub sentence about {f['theme']}."} for f in sent]})


def test_write_headline_batches_in_one_call_and_returns_every_id():
    candidates = candidate_findings(tone_contrast_themes())
    client = FakeClaudeClient(reply_stub)

    sentences = write_headline(candidates, client, QUESTION)

    assert len(client.calls) == 1  # one call, not one per candidate
    assert set(sentences) == {c.id for c in candidates}
    assert QUESTION in client.calls[0]["prompt"]
    sent_payload = json.loads(client.calls[0]["prompt"])
    # only computed numbers travel to Claude - never raw answer text
    for finding in sent_payload["findings"]:
        assert set(finding) <= {"id", "kind", "theme", "share_pct", "count", "sentiment", "overall_sentiment",
                                 "gap", "runner_up_share_pct", "margin_pct"}


def test_write_headline_makes_no_call_when_there_are_no_candidates():
    client = FakeClaudeClient("should never be used")
    assert write_headline([], client, QUESTION) == {}
    assert client.calls == []


def test_write_headline_raises_cleanly_on_malformed_reply():
    candidates = candidate_findings(tone_contrast_themes())
    client = FakeClaudeClient("not json at all, sorry")
    with pytest.raises(FindingsError) as exc_info:
        write_headline(candidates, client, QUESTION)
    assert exc_info.value.raw_response == "not json at all, sorry"


def test_write_headline_raises_when_a_candidate_is_missing_from_the_reply():
    candidates = candidate_findings(tone_contrast_themes())
    only_first = json.dumps({"headlines": [{"id": candidates[0].id, "sentence": "Fine."}]})
    client = FakeClaudeClient(only_first)
    with pytest.raises(FindingsError):
        write_headline(candidates, client, QUESTION)


def test_write_headline_raises_on_empty_sentence():
    candidates = candidate_findings(tone_contrast_themes())
    bad = json.dumps({"headlines": [{"id": c.id, "sentence": "   "} for c in candidates]})
    client = FakeClaudeClient(bad)
    with pytest.raises(FindingsError):
        write_headline(candidates, client, QUESTION)


# ==================================================================== zero network

class _NoSockets:
    def __enter__(self):
        self._orig = socket.socket

        def _blocked(*a, **k):
            raise AssertionError("a real socket was opened - network access is not allowed here")

        socket.socket = _blocked
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig


def test_zero_network_is_ever_attempted(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with _NoSockets():
        # the real client path: no key configured, must fail before ever opening a socket
        with pytest.raises(FindingsClaudeNotConfigured):
            default_claude_client()
        # the fake-client path used by every other test in this file: also never touches a socket
        candidates = candidate_findings(tone_contrast_themes())
        sentences = write_headline(candidates, FakeClaudeClient(reply_stub), QUESTION)
        assert len(sentences) == len(candidates)


# ==================================================================== build_findings (end to end)

@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s


def seed_dataset_and_themes(s, themes):
    ds = Dataset(project_id=1, filename="survey.csv", file_hash="0" * 64, row_count=1000,
                 profile={"confirmed": {"question": QUESTION}})
    s.add(ds)
    s.flush()
    for t in themes:
        t.id = None  # let the DB assign real primary keys this time
        t.dataset_id = ds.id
        s.add(t)
    s.commit()
    return ds


def test_build_findings_writes_findings_and_report(session):
    ds = seed_dataset_and_themes(session, dominant_and_longtail_themes())
    client = FakeClaudeClient(reply_stub)

    report = build_findings(ds, "Why", session, client, cleaning_report={"pii": {}, "removed_by_step": {}})

    findings = session.scalars(select(Finding).where(Finding.dataset_id == ds.id)).all()
    assert {f.chart_type for f in findings} == {"rank", "treemap"}
    assert all(f.confidence in ("solid", "tentative") for f in findings)
    assert all(f.data["column"] == "Why" for f in findings)
    assert all(f.sentence.startswith("Stub sentence about") for f in findings)

    stored = session.get(Report, report.id)
    blocks = stored.content["blocks"]
    assert blocks[0] == {"kind": "overview", "chart_id": "overview", "priority": 1, "finding_id": None}
    assert blocks[-1] == {"kind": "quality", "chart_id": "quality", "priority": 9, "finding_id": None}
    finding_blocks = blocks[1:-1]
    assert [b["priority"] for b in finding_blocks] == sorted(b["priority"] for b in finding_blocks)
    assert stored.content["also_checked_nothing_notable"] is False


def test_build_findings_rebuild_replaces_prior_findings_and_report(session):
    ds = seed_dataset_and_themes(session, dominant_and_longtail_themes())
    client = FakeClaudeClient(reply_stub)

    build_findings(ds, "Why", session, client, cleaning_report={})
    build_findings(ds, "Why", session, client, cleaning_report={})

    findings = session.scalars(select(Finding).where(Finding.dataset_id == ds.id)).all()
    reports = session.scalars(select(Report).where(Report.dataset_id == ds.id)).all()
    assert len(findings) == 2  # dominant_theme + long_tail, not doubled by the rebuild
    assert len(reports) == 1  # the old report was replaced, not appended to


def test_build_findings_nothing_notable_still_writes_a_report_with_only_overview_and_quality(session):
    ds = seed_dataset_and_themes(session, nothing_notable_themes())
    client = FakeClaudeClient("should never be called")

    report = build_findings(ds, "Why", session, client, cleaning_report={})

    assert client.calls == []  # no candidates -> zero Claude calls
    assert session.scalars(select(Finding).where(Finding.dataset_id == ds.id)).all() == []
    blocks = session.get(Report, report.id).content["blocks"]
    assert [b["kind"] for b in blocks] == ["overview", "quality"]
    assert session.get(Report, report.id).content["also_checked_nothing_notable"] is True


def test_build_findings_raises_without_stored_themes(session):
    ds = Dataset(project_id=1, filename="survey.csv", file_hash="1" * 64, row_count=100, profile={})
    session.add(ds)
    session.commit()
    with pytest.raises(NoThemesForColumn):
        build_findings(ds, "Why", session, FakeClaudeClient("unused"))
