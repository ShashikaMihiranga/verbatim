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
from app.chart_data import SubTheme
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
    other_breakdown,
    pick_chart,
    theme_nodes,
    write_headline,
)
from app.models import Dataset, Finding, Report, Theme

QUESTION = "Why haven't you bought an electric vehicle yet?"


# ---------------------------------------------------------------- fixture builders

def make_theme(tid, label, size, sentiment, tone=None, column_name="Why", dataset_id=1, description=None,
               sub_themes=None, answer_refs=None):
    t = Theme(
        dataset_id=dataset_id, column_name=column_name, label=label, description=description,
        size=size, sentiment=sentiment, tone=tone or {"neg": 34.0, "neu": 33.0, "pos": 33.0},
        answer_refs=answer_refs if answer_refs is not None else [],
        sub_themes=sub_themes,
    )
    t.id = tid  # unpersisted rows: assign a stable fake id so Candidate.id stays unique across kinds/tests
    return t


def make_sub_theme(label, size, sentiment=0.0, tone=None):
    """One `Theme.sub_themes` JSON entry, same shape `app.api_themes._write_theme_rows` stores - see
    `app.models.Theme.sub_themes`'s own comment for the exact keys."""
    return {
        "label": label, "description": f"About {label}.", "size": size, "sentiment": sentiment,
        "tone": tone or {"neg": 34.0, "neu": 33.0, "pos": 33.0}, "answer_refs": list(range(size)),
    }


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
    `pick_chart` never selects sunburst/icicle for any finding kind - real sub-themes existing now
    (app/findings.py's module docstring) does not by itself change this, since wiring that table row's own
    threshold check into `pick_chart` is separate, explicitly out-of-scope follow-up work (see
    CHART_BY_KIND's own comment) - so a "theme breakdown" finding (long_tail) must still use the table's
    documented fallback (treemap), never sunburst, regardless of how many sub-themes exist."""
    tone = Candidate("tone_contrast", "x", 1, "X", count=1, score=1.0, numbers={})
    dominant = Candidate("dominant_theme", "x", 1, "X", count=1, score=1.0, numbers={})
    long_tail = Candidate("long_tail", "x", 1, "X", count=1, score=1.0, numbers={})
    assert pick_chart(tone) == "sentsun"
    assert pick_chart(dominant) == "rank"
    assert pick_chart(long_tail) == "treemap"
    assert pick_chart(long_tail) != "sunburst"


# ==================================================================== theme_nodes (real sub-theme wiring)

def test_theme_nodes_backward_compat_no_sub_themes_yields_empty_children():
    """Pin: a `Theme` with no `sub_themes` at all (`None`, e.g. every row this app wrote before this
    stream, or any theme that was never split) still yields `children == []`, exactly as before."""
    themes = [make_theme(1, "Cost", 100, -0.1), make_theme(2, "Other", 20, 0.0)]
    nodes = theme_nodes(themes, total_answered=120)
    assert all(n.children == [] for n in nodes)


def test_theme_nodes_populates_children_from_stored_sub_themes():
    sub_themes = [
        make_sub_theme("Price too high", size=40, sentiment=-0.3),
        make_sub_theme("Hidden fees", size=20, sentiment=-0.1),
    ]
    themes = [
        make_theme(1, "Cost", 100, -0.2, sub_themes=sub_themes),
        make_theme(2, "Other", 20, 0.0),
    ]
    nodes = theme_nodes(themes, total_answered=200)
    cost_node = next(n for n in nodes if n.name == "Cost")
    assert cost_node.children == [
        SubTheme(name="Price too high", share=20.0),  # 40/200
        SubTheme(name="Hidden fees", share=10.0),  # 20/200
    ]
    # "Other" is never sub-clustered (see app/text_pipeline/subthemes.py) and this fixture never gave it
    # any sub_themes anyway - children stays empty for it.
    other_node = next(n for n in nodes if n.name == "Other")
    assert other_node.children == []


def test_theme_nodes_caps_children_at_three():
    sub_themes = [make_sub_theme(f"Sub {i}", size=10) for i in range(4)]  # a 4th sub-theme entry, stored
    themes = [make_theme(1, "Cost", 100, -0.1, sub_themes=sub_themes)]
    nodes = theme_nodes(themes, total_answered=100)
    assert len(nodes[0].children) == 3
    assert [c.name for c in nodes[0].children] == ["Sub 0", "Sub 1", "Sub 2"]  # 4th silently dropped, not crashed on


def test_theme_nodes_drops_sub_themes_whose_share_rounds_to_zero():
    """A sub-theme's stored `size` is always > 0, but its computed SHARE (of the whole column's answers,
    not the parent's) can still round to 0.0 on a large enough dataset - app.charts.py's treemap divides by
    a sub-theme's share via squarify, so this must be filtered, not merely tolerated."""
    sub_themes = [
        make_sub_theme("Real sub-theme", size=5_000),
        make_sub_theme("Rounds to zero", size=1),  # 1 / 2_000_000 * 100 rounds to 0.0
    ]
    themes = [make_theme(1, "Cost", 5_001, -0.1, sub_themes=sub_themes)]
    nodes = theme_nodes(themes, total_answered=2_000_000)
    assert [c.name for c in nodes[0].children] == ["Real sub-theme"]


# ==================================================================== theme_nodes (rank-8+ / Other merge)

def test_theme_nodes_real_node_carries_its_own_answer_refs_and_theme_id():
    themes = [make_theme(1, "Cost", 100, -0.1, answer_refs=[3, 1, 2])]
    nodes = theme_nodes(themes, total_answered=100)
    assert nodes[0].answer_refs == [1, 2, 3]  # sorted
    assert nodes[0].theme_id == 1


def test_theme_nodes_up_to_seven_real_themes_each_keep_their_own_node():
    """<=7 real themes (the common case): unchanged from before this fix - each real theme gets its own
    node/colour, and a lone "Other" node's theme_id stays a real id (not None), byte-compatible with the
    pre-merge behaviour."""
    themes = [make_theme(i, f"T{i}", 100 - i, 0.0, answer_refs=[i]) for i in range(1, 8)]
    other = make_theme(8, "Other", 10, 0.0, answer_refs=[100])
    nodes = theme_nodes(themes + [other], total_answered=710)
    assert [n.name for n in nodes] == ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "Other"]
    assert [n.color for n in nodes] == ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "other"]
    assert nodes[-1].theme_id == 8  # only the noise cluster folded in - a real, single id, not None
    assert nodes[-1].answer_refs == [100]


def test_theme_nodes_merges_rank_eight_plus_real_themes_with_other_into_one_node():
    """The bug this fixes: a dataset with >7 real themes used to give ranks 8+ their own nodes, each
    sharing the same "other" colour as the genuine noise cluster - several indistinguishable grey nodes.
    Now every one of them, plus the noise cluster, becomes exactly ONE merged node."""
    kept = [make_theme(i, f"T{i}", 100 - i, 0.1 * i, answer_refs=[i]) for i in range(1, 8)]  # ranks 1-7
    overflow = [
        make_theme(8, "Fabric quality", 20, -0.4, answer_refs=[80, 81]),
        make_theme(9, "Delivery speed", 15, 0.2, answer_refs=[90]),
    ]
    other = make_theme(10, "Other", 10, 0.0, answer_refs=[100, 101])
    nodes = theme_nodes(kept + overflow + [other], total_answered=200)

    assert [n.name for n in nodes] == ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "Other"]
    assert [n.color for n in nodes] == ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "other"]
    merged = nodes[-1]
    assert merged.count == 20 + 15 + 10  # 45
    assert merged.share == pytest.approx(22.5)  # 45/200
    assert merged.answer_refs == [80, 81, 90, 100, 101]
    assert merged.theme_id is None  # 3 themes folded together - no single Theme row represents this
    assert merged.sentiment == pytest.approx((-0.4 * 20 + 0.2 * 15 + 0.0 * 10) / 45, abs=1e-3)
    assert "Fabric quality" in merged.note and "Delivery speed" in merged.note


def test_theme_nodes_merge_note_preserves_noise_only_wording_when_no_overflow():
    """Pin: when there's no real rank-8+ overflow (<=7 real themes), the merged node's note text stays
    byte-identical to the pre-merge behaviour - only genuinely folding in extra real themes changes it."""
    themes = [make_theme(1, "Cost", 100, 0.0)]
    other = make_theme(2, "Other", 20, 0.0, description="Answers about unrelated topics.")
    nodes = theme_nodes(themes + [other], total_answered=120)
    assert nodes[-1].note == "Folded in: Answers about unrelated topics."

    other_no_desc = make_theme(2, "Other", 20, 0.0, description=None)
    nodes2 = theme_nodes(themes + [other_no_desc], total_answered=120)
    assert nodes2[-1].note == "Folded in: answers too rare, unclear or distinct to group into a theme."


def test_theme_nodes_merges_overflow_even_with_no_noise_cluster_present():
    """A dataset can have >7 real themes and no noise cluster at all (nothing was too rare/unclear) - the
    overflow must still merge into one node, not be silently dropped."""
    kept = [make_theme(i, f"T{i}", 100 - i, 0.0, answer_refs=[i]) for i in range(1, 8)]
    overflow = [make_theme(8, "Extra", 5, 0.0, answer_refs=[80])]
    nodes = theme_nodes(kept + overflow, total_answered=700)
    assert nodes[-1].name == "Other"
    assert nodes[-1].count == 5
    assert nodes[-1].theme_id == 8  # exactly one theme folded in - still a real single id
    assert nodes[-1].note == "Folded in: Extra."


# ==================================================================== other_breakdown (docs/TODO.md, 2026-10-21 Phase 1)

def test_other_breakdown_none_when_seven_or_fewer_real_themes_and_no_noise():
    """The common case: nothing is genuinely hidden in "Other" - no breakdown to show, but the full
    ranked theme list is still returned."""
    themes = [make_theme(i, f"T{i}", 100 - i, 0.0, answer_refs=[i]) for i in range(1, 6)]
    breakdown, all_themes = other_breakdown(themes, total_answered=500)
    assert breakdown is None
    assert [t.name for t in all_themes] == ["T1", "T2", "T3", "T4", "T5"]


def test_other_breakdown_present_for_noise_only_even_with_seven_or_fewer_real_themes():
    """A noise cluster alone (no rank-8+ overflow) still gets a breakdown - "this really is just varied
    content, not hidden themes" is itself useful information, not a no-op case."""
    themes = [make_theme(1, "Cost", 100, 0.0, answer_refs=list(range(100)))]
    other = make_theme(2, "Other", 20, 0.0, answer_refs=list(range(100, 120)))
    breakdown, _ = other_breakdown(themes + [other], total_answered=120)
    assert breakdown is not None
    assert breakdown.noise_count == 20
    assert breakdown.hidden_real_count == 0
    assert breakdown.hidden_real_theme_count == 0


def test_other_breakdown_splits_noise_from_hidden_real_themes():
    kept = [make_theme(i, f"T{i}", 100, 0.0, answer_refs=list(range(i * 100, i * 100 + 100))) for i in range(1, 8)]
    hidden = [
        make_theme(8, "Fabric quality", 20, -0.4, answer_refs=[800, 801]),
        make_theme(9, "Delivery speed", 15, 0.2, answer_refs=[900]),
    ]
    other = make_theme(10, "Other", 10, 0.0, answer_refs=[1000, 1001])
    total = 7 * 100 + 20 + 15 + 10  # 745
    breakdown, all_themes = other_breakdown(kept + hidden + [other], total_answered=total)

    assert breakdown is not None
    assert breakdown.noise_count == 10
    assert breakdown.noise_share == pytest.approx(round(10 / total * 100, 1))
    assert breakdown.hidden_real_count == 35  # 20 + 15
    assert breakdown.hidden_real_share == pytest.approx(round(35 / total * 100, 1))
    assert breakdown.hidden_real_theme_count == 2
    assert breakdown.total_real_theme_count == 9  # 7 kept + 2 hidden

    # all_themes is the FULL, uncapped, ranked list - all 9 real themes, "Other" itself excluded
    assert [t.name for t in all_themes] == ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "Fabric quality", "Delivery speed"]
    assert all_themes[-1].count == 15
    assert all_themes[-1].share == pytest.approx(round(15 / total * 100, 1))


def test_other_breakdown_hidden_real_themes_with_no_noise_cluster_present():
    kept = [make_theme(i, f"T{i}", 100, 0.0, answer_refs=[i]) for i in range(1, 8)]
    hidden = [make_theme(8, "Extra", 5, 0.0, answer_refs=[80])]
    breakdown, _ = other_breakdown(kept + hidden, total_answered=705)
    assert breakdown is not None
    assert breakdown.noise_count == 0
    assert breakdown.hidden_real_count == 5
    assert breakdown.hidden_real_theme_count == 1


def test_other_breakdown_respects_filter_rows():
    kept = [make_theme(i, f"T{i}", 100, 0.0, answer_refs=list(range(i * 100, i * 100 + 100))) for i in range(1, 8)]
    hidden = make_theme(8, "Extra", 50, 0.0, answer_refs=list(range(800, 850)))
    # Filter keeps only 10 of "Extra"'s 50 rows.
    filter_rows = {r for t in kept for r in (t.answer_refs or [])} | set(range(800, 810))
    breakdown, all_themes = other_breakdown(kept + [hidden], total_answered=710, filter_rows=filter_rows)
    assert breakdown is not None
    assert breakdown.hidden_real_count == 10  # not 50 - filtered
    assert all_themes[-1].count == 10


# ==================================================================== theme_nodes with filter_rows (Filters feature)

def test_theme_nodes_filter_rows_recomputes_count_and_share():
    themes = [
        make_theme(1, "Cost", 100, 0.2, answer_refs=list(range(0, 100))),
        make_theme(2, "Speed", 50, -0.1, answer_refs=list(range(100, 150))),
    ]
    # Filter keeps all 100 "Cost" rows but only 10 of "Speed"'s 50 rows.
    filter_rows = set(range(0, 100)) | set(range(100, 110))
    nodes = theme_nodes(themes, total_answered=110, filter_rows=filter_rows)

    by_name = {n.name: n for n in nodes}
    assert by_name["Cost"].count == 100
    assert by_name["Speed"].count == 10
    assert by_name["Speed"].answer_refs == list(range(100, 110))
    assert by_name["Cost"].share == pytest.approx(round(100 / 110 * 100, 1))
    assert by_name["Speed"].share == pytest.approx(round(10 / 110 * 100, 1))


def test_theme_nodes_filter_rows_can_change_ranking():
    """A theme that's largest overall can rank lower once a filter removes most of its rows - this is
    correct behaviour, not a bug (SPEC.md: filtering recomputes "theme counts")."""
    themes = [
        make_theme(1, "BigOverall", 100, 0.0, answer_refs=list(range(0, 100))),
        make_theme(2, "SmallOverall", 20, 0.0, answer_refs=list(range(100, 120))),
    ]
    # Filter keeps only 2 of BigOverall's rows but all 20 of SmallOverall's.
    filter_rows = set(range(0, 2)) | set(range(100, 120))

    unfiltered = theme_nodes(themes, total_answered=120)
    assert [n.name for n in unfiltered] == ["BigOverall", "SmallOverall"]

    filtered = theme_nodes(themes, total_answered=22, filter_rows=filter_rows)
    assert [n.name for n in filtered] == ["SmallOverall", "BigOverall"]
    assert filtered[0].count == 20
    assert filtered[1].count == 2


def test_theme_nodes_filter_rows_drops_sub_themes():
    sub = [make_sub_theme("Fit", 30, 0.1)]
    themes = [make_theme(1, "Cost", 100, 0.0, answer_refs=list(range(100)), sub_themes=sub)]
    unfiltered = theme_nodes(themes, total_answered=100)
    assert unfiltered[0].children  # sanity: sub-themes populate without a filter

    filtered = theme_nodes(themes, total_answered=100, filter_rows=set(range(50)))
    assert filtered[0].children == []  # documented scope cut: sub-themes drop under a filter


def test_theme_nodes_filter_rows_none_is_byte_identical_to_omitting_it():
    themes = [make_theme(i, f"T{i}", 100 - i, 0.1 * i, answer_refs=[i]) for i in range(1, 10)]
    omitted = theme_nodes(themes, total_answered=500)
    explicit_none = theme_nodes(themes, total_answered=500, filter_rows=None)
    assert omitted == explicit_none


def test_theme_nodes_filter_rows_merges_overflow_consistently():
    """The "Other" merge path under a filter: every folded theme's answer_refs/count/sentiment/tone are
    recomputed from the filtered intersection, not the stored t.size. Kept themes each get 10 answer_refs,
    all inside the filter, so their effective size (10) stays well above the overflow pair's (<=2) and
    ranking is unaffected by the filter - isolating this test to the merge-arithmetic behaviour alone."""
    kept = [
        make_theme(i, f"T{i}", 100 - i, 0.0, answer_refs=list(range(i * 10, i * 10 + 10)))
        for i in range(1, 8)
    ]
    overflow = [
        make_theme(8, "Fabric quality", 20, -0.4, answer_refs=[80, 81, 82, 83]),
        make_theme(9, "Delivery speed", 15, 0.2, answer_refs=[90, 91]),
    ]
    other = make_theme(10, "Other", 10, 0.0, answer_refs=[100, 101])
    all_themes = kept + overflow + [other]
    kept_rows = {r for t in kept for r in t.answer_refs}
    # Filter keeps all of kept's refs, half of Fabric quality's, none of Delivery speed's, both of Other's.
    filter_rows = kept_rows | {80, 81} | {100, 101}

    nodes = theme_nodes(all_themes, total_answered=10, filter_rows=filter_rows)
    assert [n.name for n in nodes[:7]] == [f"T{i}" for i in range(1, 8)]  # ranking unaffected, as designed
    merged = nodes[-1]
    assert merged.name == "Other"
    assert merged.count == 2 + 0 + 2  # 4
    assert merged.answer_refs == [80, 81, 100, 101]
    assert merged.sentiment == pytest.approx((-0.4 * 2 + 0.2 * 0 + 0.0 * 2) / 4, abs=1e-3)


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
    # None of dominant_and_longtail_themes()'s fixture Themes set `sub_themes`, so every ThemeNode still
    # has empty children - real sub-theme wiring (see theme_nodes tests below) is additive, not a change
    # in behaviour for a Theme that was never split.
    assert all(t.children == [] for t in data.themes)

    for frame_id in ("overview", "treemap", "rank", "sentsun", "quality"):
        html = render(frame_id, data)
        assert html.startswith("<!doctype html>")
        if frame_id == "sentsun":
            assert "<svg" in html  # genuine polar geometry - still SVG, see docs/DECISIONS.md
        if frame_id == "treemap":
            assert "<svg" not in html  # rewritten to fluid HTML/CSS - see docs/DECISIONS.md
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


# ==================================================================== context (chart-block stream, 2026-10-24)

def test_context_kind_is_classified_from_the_real_question_text():
    dataset = SimpleNamespace(row_count=100)
    data = build_report_data(dataset, dominant_and_longtail_themes(), {}, QUESTION)
    assert data.context.kind == "reasons"  # QUESTION starts "Why haven't you..."
    assert data.context.kind_hover == "reasons"  # no second guess invented


def test_context_kind_falls_back_to_anything_else_when_nothing_matches():
    dataset = SimpleNamespace(row_count=100)
    data = build_report_data(dataset, dominant_and_longtail_themes(), {}, "Any other comments?")
    assert data.context.kind == "anything else"


@pytest.mark.parametrize("question,expected", [
    ("What improvements would you suggest?", "improvements"),
    ("Describe your experience with support.", "experiences"),
    ("What do you think about the new design?", "opinions"),
    ("What is your job title?", "facts"),
])
def test_context_kind_covers_every_real_option(question, expected):
    dataset = SimpleNamespace(row_count=100)
    data = build_report_data(dataset, dominant_and_longtail_themes(), {}, question)
    assert data.context.kind == expected


def test_context_framing_reflects_real_overall_sentiment_not_a_fixed_default():
    dataset = SimpleNamespace(row_count=100)
    data = build_report_data(dataset, dominant_and_longtail_themes(), {}, QUESTION)
    # dominant_and_longtail_themes() carries real negative sentiment themes - see its own fixture.
    assert data.context.framing == "negatively"
    assert data.context.framing == ("positively" if data.overall_sentiment >= 0.05 else
                                     "negatively" if data.overall_sentiment <= -0.05 else "neutrally")


def test_context_length_reflects_real_median_answer_length():
    dataset = SimpleNamespace(row_count=100)
    short = build_report_data(dataset, dominant_and_longtail_themes(), {}, QUESTION, answer_lengths=[2, 3, 2, 3])
    long_ = build_report_data(dataset, dominant_and_longtail_themes(), {}, QUESTION, answer_lengths=[40, 50, 60])
    assert short.context.length == "a word or two"
    assert long_.context.length == "a paragraph or more"


def test_context_columns_note_reflects_real_structured_columns_present():
    dataset = SimpleNamespace(row_count=100)
    no_structured = build_report_data(dataset, dominant_and_longtail_themes(), {}, QUESTION)
    assert "No score, segment or date" in no_structured.context.columns_note


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
