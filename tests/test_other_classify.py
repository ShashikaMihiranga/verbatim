"""'"Look inside Other"' (docs/TODO.md, 2026-10-21): app/text_pipeline/other_classify.py. No real network
anywhere - FakeClaudeClient/FakeJevClient only, matching this codebase's existing test conventions."""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.text_pipeline.jev_sentiment import ChoiceAnswer, FakeJevClient, JevError
from app.text_pipeline.labeling import FakeClaudeClient
from app.text_pipeline.other_classify import (
    NONE_OF_THESE,
    build_classification_question,
    classify_other_answers,
    label_and_consolidate,
    recluster_other,
)
from app.text_pipeline.schema import Cluster, ClusterMember, ClusterResult

QUESTION = "What could we do better?"


def make_cluster(cluster_id, texts):
    members = [ClusterMember(row=100 * cluster_id + i, text=t, distance=float(i)) for i, t in enumerate(texts)]
    return Cluster(id=cluster_id, members=members, centroid=None)


def make_result(clusters, noise_texts=()):
    noise = [ClusterMember(row=900 + i, text=t, distance=None) for i, t in enumerate(noise_texts)]
    total = sum(len(c.members) for c in clusters) + len(noise)
    return ClusterResult(column="Why", clusters=clusters, noise=noise, total_answers=total)


def reply_for(cluster_ids, **overrides):
    themes = []
    for cid in cluster_ids:
        entry = {"cluster_id": cid, "label": f"Theme {cid}", "description": f"About cluster {cid}.",
                  "merge_with": [], "note": None}
        entry.update(overrides.get(cid, {}))
        themes.append(entry)
    return json.dumps({"themes": themes})


# ---------------------------------------------------------------- recluster_other


def test_recluster_other_finds_separable_groups():
    rng = np.random.default_rng(0)
    dims = 300
    centers = [rng.normal(size=dims) for _ in range(2)]
    vectors, texts, rows = [], [], []
    row = 0
    for gi, center in enumerate(centers):
        for _ in range(60):
            v = center + rng.normal(scale=0.1, size=dims)
            vectors.append((v / np.linalg.norm(v)).tolist())
            texts.append(f"group {gi} answer")
            rows.append(row)
            row += 1

    result = recluster_other(rows, texts, vectors)

    assert len(result.clusters) >= 2
    assert result.total_answers == 120


def test_recluster_other_empty_input():
    result = recluster_other([], [], [])
    assert result.clusters == [] and result.total_answers == 0


def test_recluster_other_fewer_than_floor_answers_becomes_all_noise_not_a_crash():
    """Real bug, found via this module's own first end-to-end API test: sklearn's HDBSCAN raises a hard
    ValueError ("min_samples must be at most the number of samples") rather than gracefully finding
    nothing when asked for fewer answers than its own min_samples floor - something only this entry
    point can hit, since every other cluster_answers call site is gated by pipeline.py's own
    MIN_ANSWERS_TO_CLUSTER=20 first. Must return everything as noise instead of raising."""
    rows = [1, 2, 3]
    texts = ["a", "b", "c"]
    vectors = [[0.1, 0.2], [0.3, 0.1], [0.9, 0.9]]

    result = recluster_other(rows, texts, vectors)

    assert result.clusters == []
    assert sorted(m.row for m in result.noise) == rows
    assert result.total_answers == 3


# ---------------------------------------------------------------- label_and_consolidate


def test_label_and_consolidate_labels_and_merges_same_label_clusters():
    clusters = [
        make_cluster(0, ["slow shipping", "late delivery"]),
        make_cluster(1, ["shipping took forever", "order arrived late"]),
        make_cluster(2, ["great staff", "friendly support"]),
    ]
    result = make_result(clusters)
    # 0 and 1 get the SAME label -> merged by merging.apply_merges's same-label guarantee.
    reply = json.dumps({"themes": [
        {"cluster_id": 0, "label": "Shipping delays", "description": "About shipping.", "merge_with": [], "note": None},
        {"cluster_id": 1, "label": "Shipping delays", "description": "About shipping.", "merge_with": [], "note": None},
        {"cluster_id": 2, "label": "Great staff", "description": "About staff.", "merge_with": [], "note": None},
    ]})
    client = FakeClaudeClient(reply)

    out = label_and_consolidate(result, QUESTION, client)

    assert len(out.labels) == 2  # "Shipping delays" (merged 0+1) and "great staff" cluster
    labels_by_name = {l.label: l for l in out.labels}
    assert labels_by_name["Shipping delays"].size == 4  # 2 + 2 members merged
    assert sum(len(c.members) for c in out.result.clusters) == 6


def test_label_and_consolidate_drops_synthesized_other_entry():
    clusters = [make_cluster(0, ["a", "b"])]
    result = make_result(clusters, noise_texts=["noisy one", "noisy two"])
    reply = reply_for([0])
    client = FakeClaudeClient(reply)

    out = label_and_consolidate(result, QUESTION, client)

    assert len(out.labels) == 1
    assert all(l.label != "Other" for l in out.labels)


def test_label_and_consolidate_no_real_clusters_returns_empty():
    result = ClusterResult(column="Why", clusters=[], noise=[ClusterMember(row=1, text="x", distance=None)], total_answers=1)
    client = FakeClaudeClient(reply_for([]))
    out = label_and_consolidate(result, QUESTION, client)
    assert out.labels == [] and out.result.clusters == []


# ---------------------------------------------------------------- build_classification_question


def test_build_classification_question_combines_known_and_new_plus_none_of_these():
    known = {"Cost": "Answers about price.", "Support": "Answers about staff."}
    from app.text_pipeline.other_classify import ConsolidatedCandidates
    from app.text_pipeline.schema import ThemeLabel

    candidates = ConsolidatedCandidates(
        result=make_result([make_cluster(0, ["x"])]),
        labels=[ThemeLabel(cluster_id=0, label="Shipping delays", description="About shipping.", size=1, merge_with=[], note=None)],
    )

    criteria, new_labels = build_classification_question(known, candidates)

    assert criteria == {
        "Cost": "Answers about price.",
        "Support": "Answers about staff.",
        "Shipping delays": "About shipping.",
        NONE_OF_THESE: pytest.approx(criteria[NONE_OF_THESE]),  # present with its own description
    }
    assert new_labels == {"Shipping delays": "About shipping."}


def test_build_classification_question_known_label_wins_on_collision():
    known = {"Cost": "The real known description."}
    from app.text_pipeline.other_classify import ConsolidatedCandidates
    from app.text_pipeline.schema import ThemeLabel

    candidates = ConsolidatedCandidates(
        result=make_result([make_cluster(0, ["x"])]),
        labels=[ThemeLabel(cluster_id=0, label="Cost", description="A different, new description.", size=1, merge_with=[], note=None)],
    )
    criteria, new_labels = build_classification_question(known, candidates)
    assert criteria["Cost"] == "The real known description."
    assert new_labels == {"Cost": "A different, new description."}  # still reported, caller's call what to do


# ---------------------------------------------------------------- classify_other_answers


_CRITERIA = {"Cost": "About price.", "Support": "About staff.", NONE_OF_THESE: "No clear match."}


def test_classify_other_answers_maps_every_row():
    def pick(text, question_key, instructions, criteria):
        choice = "Cost" if "price" in text else "Support"
        return ChoiceAnswer(choice=choice, confidence=0.9, probabilities={})

    client = FakeJevClient(("pos", 0.9), choice_result=pick)
    out = classify_other_answers([1, 2], ["too expensive, bad price", "staff were rude"], _CRITERIA, client)

    assert out.by_row == {1: "Cost", 2: "Support"}
    assert out.confidence_by_row == {1: 0.9, 2: 0.9}
    assert out.failed_rows == []
    assert len(client.choice_calls) == 2


def test_classify_other_answers_empty_input_makes_no_calls():
    client = FakeJevClient(("pos", 0.9))
    out = classify_other_answers([], [], _CRITERIA, client)
    assert out.by_row == {} and client.choice_calls == []


def test_classify_other_answers_a_single_row_failure_does_not_lose_the_rest():
    def pick(text, question_key, instructions, criteria):
        if text == "boom":
            raise JevError("simulated failure")
        return ChoiceAnswer(choice="Cost", confidence=0.5, probabilities={})

    client = FakeJevClient(("pos", 0.9), choice_result=pick)
    out = classify_other_answers([1, 2, 3], ["ok", "boom", "also ok"], _CRITERIA, client)

    assert out.failed_rows == [2]
    assert out.by_row == {1: "Cost", 3: "Cost"}


def test_classify_other_answers_logs_a_warning_for_a_partial_failure(caplog):
    # Fixed 2026-10-23: a failure used to be completely silent - nothing logged anywhere, and the
    # caller's own summary had nowhere to report it either, so a real problem looked identical to a
    # legitimate "nothing matched" result. This pins the partial-failure case (some rows failed, most
    # didn't) at WARNING, not ERROR - see the systemic-failure test below for the ERROR case.
    def pick(text, question_key, instructions, criteria):
        if text == "boom":
            raise JevError("simulated failure")
        return ChoiceAnswer(choice="Cost", confidence=0.5, probabilities={})

    client = FakeJevClient(("pos", 0.9), choice_result=pick)
    with caplog.at_level("WARNING", logger="verbatim.other_classify"):
        out = classify_other_answers([1, 2, 3], ["ok", "boom", "also ok"], _CRITERIA, client)

    assert out.failed_rows == [2]
    assert any(r.levelname == "WARNING" and "1/3" in r.message for r in caplog.records)
    assert not any(r.levelname == "ERROR" for r in caplog.records)


def test_classify_other_answers_logs_an_error_when_every_row_fails(caplog):
    # The systemic case this fix exists for: every single row rejected (e.g. a bad API key) - this must
    # be loud (ERROR, not WARNING), since it means the whole run's "nothing matched" result is actually
    # a total failure, not a real finding. Found live: this exact shape (known_added=0, new_themes=[])
    # on a 19,799-row Other bucket was a rejected TYPESAFE_API_KEY, not a legitimate empty result.
    def always_fails(text, question_key, instructions, criteria):
        raise JevError("simulated auth failure")

    client = FakeJevClient(("pos", 0.9), choice_result=always_fails)
    with caplog.at_level("WARNING", logger="verbatim.other_classify"):
        out = classify_other_answers([1, 2, 3], ["a", "b", "c"], _CRITERIA, client)

    assert out.failed_rows == [1, 2, 3]
    assert out.by_row == {}
    assert any(r.levelname == "ERROR" and "3/3" in r.message for r in caplog.records)


def test_classify_other_answers_can_return_none_of_these():
    client = FakeJevClient(
        ("pos", 0.9),
        choice_result=ChoiceAnswer(choice=NONE_OF_THESE, confidence=0.4, probabilities={}),
    )
    out = classify_other_answers([1], ["totally unrelated answer"], _CRITERIA, client)
    assert out.by_row[1] == NONE_OF_THESE


def test_classify_other_answers_reports_live_progress_throttled_and_complete():
    # Feeds the report's Inside Other panel real counts while Jev matches answers (docs/REPORT_UI_REWORK.md).
    def pick(text, question_key, instructions, criteria):
        return ChoiceAnswer(choice="Cost" if "price" in text else "Support", confidence=0.9, probabilities={})

    calls = []
    rows = list(range(10))
    texts = ["bad price" if r % 2 else "rude staff" for r in rows]
    client = FakeJevClient(("pos", 0.9), choice_result=pick)

    out = classify_other_answers(rows, texts, _CRITERIA, client, concurrency=1,
                                 on_progress=lambda d, t, by_row, failed: calls.append((d, t, dict(by_row))),
                                 progress_interval=3600)
    # A one-hour interval allows exactly the first report and the final, complete one.
    assert [c[0] for c in calls] == [1, 10]
    assert calls[-1][1] == 10 and calls[-1][2] == out.by_row

    every = []
    classify_other_answers(rows, texts, _CRITERIA, client, concurrency=1,
                           on_progress=lambda d, t, by_row, failed: every.append(d), progress_interval=0)
    assert every == list(range(1, 11))
