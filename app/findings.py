"""Findings engine (stream 7): SPEC.md's own build-order step 2 ("chart-selection rules"), not step 3
(score/segment/date/filters cross-analysis - explicitly out of scope here, see docs/DECISIONS.md).

Turns stored `Theme` rows (`app.models.Theme`, built by `app/api_themes.py`) into:
  1. a `ReportData` (`app.chart_data`) real chart renderers already understand - `build_report_data`;
  2. a small, scored set of "findings" worth telling as a report block - `candidate_findings`;
  3. a "Solid"/"Tentative" badge per finding - `label_confidence`;
  4. a chart id per finding, honouring SPEC.md section 4's priority table - `pick_chart`;
  5. one plain headline sentence per finding, in ONE batched Claude call, numbers only - `write_headline`;
  6. `Finding`/`Report` rows for one dataset + column - `build_findings`.

Deliberately narrow first pass (SPEC.md section 9.3's finding kinds need score/segment/date data this
stream does not have yet):
  - Only two finding kinds are computed: **tone contrast** (a theme's sentiment differs notably from the
    dataset's overall sentiment) and **dominant/rare theme** (a theme is unusually large, i.e. a clear
    #1, or "Other"/the long tail is unusually large - a data-quality signal as much as a finding).
    SPEC 9.3's other three kinds ("a theme raised more by one group than by the rest", "a number that
    moves with sentiment or score", "a trend over time") all need segment/score/date columns, which are
    SPEC.md build-order step 3 and out of scope here.
  - Sub-themes are never populated (`ThemeNode.children` is always `[]`): the `Theme` table has no
    sub-theme rows yet, so every ReportData this module builds has zero sub-themes. This is not
    cosmetic - it changes which chart SPEC.md section 4's table says to use; see `pick_chart` below.
  - `ContextData` (question kind/framing/length) falls back to honest, generic defaults: nothing
    upstream (`app/profiling/claude_hook.py`) infers those fields yet, only column kind/unit and the
    question text itself.

No network in this module directly: it takes an already-built `ClaudeClient` (same one-method Protocol
`app/text_pipeline/labeling.py` defines - see `default_claude_client` below for the real implementation,
reused rather than reinvented) and never touches the database except through the `Session` it is given.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .chart_data import (
    ContextData, FreqData, MapData, OverviewData, PhraseData, QualityData, QuoteData, ReportData,
    ScoreData, SegmentData, ThemeNode, ToneSplit, TrendData,
)
from .cleaning.suppression import min_group_size as _suppression_min_group_size
from .models import Dataset, Finding, Report, Theme
from .text_pipeline import AnthropicClaudeClient, ClaudeClient
from .text_pipeline import LabelingClaudeNotConfigured as FindingsClaudeNotConfigured
from .text_pipeline.labeling import OTHER_LABEL

__all__ = [
    "Candidate", "FindingsClaudeNotConfigured", "FindingsError", "NoThemesForColumn", "FakeClaudeClient",
    "build_report_data", "candidate_findings", "label_confidence", "pick_chart", "write_headline",
    "build_findings", "default_claude_client",
]

# ---------------------------------------------------------------- tunable thresholds (documented, easy to retune)

# Tone contrast: |theme sentiment - overall sentiment|.
TONE_GAP_MIN = 0.08  # minimum gap to raise a tone-contrast candidate at all
TONE_GAP_SOLID = 0.16  # gap needed (with the group-size floor below) to call it "Solid"

# Dominant theme: the largest real (non-"Other") theme.
DOMINANT_SHARE_MIN = 25.0  # % share needed to be considered a "clear #1" at all
DOMINANT_MARGIN_MIN = 10.0  # ...and must lead the second-largest theme by at least this many share points
DOMINANT_SHARE_SOLID = 35.0  # share needed (with the group-size floor) to call it "Solid"

# Long tail: the "Other" theme.
LONGTAIL_SHARE_MIN = 15.0  # % share needed to be worth flagging as a long-tail finding at all
LONGTAIL_SHARE_SOLID = 25.0  # share needed to call it "Solid"

# Applies to every kind: "Solid" additionally needs at least this many times the group-size floor
# (app.cleaning.suppression.min_group_size(), default 30) - e.g. 2x the default = 60 answers. Below the
# floor itself a candidate is discarded outright (never becomes a Candidate at all, see candidate_findings).
SOLID_COUNT_MULTIPLIER = 2

MAX_CANDIDATES = 5  # SPEC.md section 5: "keep the top 3 to 5" - this is a cap, never a floor (see below)

# ---------------------------------------------------------------- chart selection (SPEC.md section 4)

# SPEC.md section 4's table: "Sunburst: Open-ended text and 2 or more themes... Skip when fewer than 3
# sub-themes in total, use treemap." Every ReportData this module builds has zero sub-themes (see module
# docstring), which is always "fewer than 3" - so the sunburst row's own stated skip condition is always
# met here, and its documented replacement (treemap) is what this module actually uses. Not a workaround:
# it is the table's own fallback rule, applied honestly rather than rendering a sunburst with no outer
# ring. See docs/DECISIONS.md.
CHART_BY_KIND = {
    "tone_contrast": "sentsun",  # table: "Sentiment sunburst or Marimekko", priority 4 - unaffected by the
                                 # sub-theme gap (its own skip condition is about sentiment spread, not sub-themes)
    "dominant_theme": "rank",  # table: "Rank", priority 3 - the richest single view we have for "this
                               # theme clearly leads" (shows share, count and sentiment tint together)
    "long_tail": "treemap",  # table: "Treemap", priority 2, replaces sunburst - block area makes an
                             # oversized "Other" block legible at a glance
}
PRIORITY_BY_KIND = {"long_tail": 2, "dominant_theme": 3, "tone_contrast": 4}


@dataclass
class Candidate:
    """One candidate finding, scored and ready for `label_confidence`/`pick_chart`/`write_headline`."""

    kind: str  # "tone_contrast" | "dominant_theme" | "long_tail"
    id: str  # stable id, e.g. "tone_contrast:17" ("<kind>:<theme.id>") - unique even when the same
             # theme yields more than one candidate kind, and used as the Claude batch's join key
    theme_id: int | None
    theme_name: str
    count: int  # answers behind this finding (its group size)
    score: float  # ranking score blending effect size and group size (see candidate_findings)
    numbers: dict[str, Any] = field(default_factory=dict)  # exactly what is sent to Claude / stored on Finding.data


class FindingsError(RuntimeError):
    """Claude's headline reply could not be trusted. Carries the raw reply text (mirrors
    `app.text_pipeline.labeling.LabelingError`) so a caller can log or inspect it."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class NoThemesForColumn(RuntimeError):
    """Raised by `build_findings` when no `Theme` rows exist yet for this dataset + column. Build themes
    first (`POST /api/datasets/{id}/themes/build`, see `app/api_themes.py`)."""


class FakeClaudeClient:
    """Deterministic, network-free stand-in for tests. Same one-method shape as
    `app.text_pipeline.labeling.FakeClaudeClient` - this module defines its own copy rather than
    importing that one, matching this repo's existing precedent of one small Fake per stream (see
    `app/text_pipeline/__init__.py`'s "Known duplication" note, which already flags this as accepted,
    documented tech debt rather than an oversight). `reply` is the literal string to return every time,
    or a callable `(prompt) -> str` for tests that need the reply to depend on what was sent."""

    def __init__(self, reply: str | Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append({"system": system, "prompt": prompt})
        return self.reply(prompt) if callable(self.reply) else self.reply


def default_claude_client() -> ClaudeClient:
    """Builds the real Claude client for headline-writing. Reuses `app.text_pipeline.labeling`'s
    `AnthropicClaudeClient` exactly (same `ANTHROPIC_API_KEY`, same small model, same lazy `anthropic`
    import) rather than a second real-client implementation - this module invents no new Claude-calling
    convention. Raises `FindingsClaudeNotConfigured` (re-exported from
    `app.text_pipeline.LabelingClaudeNotConfigured` - see the module docstring's naming note below)
    before ever touching the network if no key is set.

    Naming choice (the brief asked this to be called out explicitly): this module reuses
    `LabelingClaudeNotConfigured` under the alias `FindingsClaudeNotConfigured`, rather than defining a
    third distinct-but-identically-shaped exception class. `app/text_pipeline/__init__.py` already flags
    that `labeling.py` and `sentiment.py` each independently invented their own `ClaudeNotConfigured`
    class and calls that "known duplication" that "a future pass should consolidate" - adding a third
    would deepen exactly that debt instead of following the brief's instruction to reuse this codebase's
    existing patterns. Since `app/api_themes.py`'s `get_claude_client()` dependency already knows how to
    catch `LabelingClaudeNotConfigured` and turn it into a clean 503, a sibling API-layer route that wants
    findings-building over HTTP can reuse that exact provider for this module too - no new DI wiring
    needed for the "no key configured" case.
    """
    return AnthropicClaudeClient()


# ---------------------------------------------------------------- shared numbers (kept in sync between
# candidate_findings and build_report_data so a Finding's numbers and the chart's overall_sentiment/share
# never quietly disagree)

def _total_answered(themes: list[Theme]) -> int:
    return sum(t.size for t in themes)


def _overall_sentiment(themes: list[Theme], total: int) -> float:
    if total <= 0:
        return 0.0
    return sum((t.sentiment or 0.0) * t.size for t in themes) / total


def _theme_color(rank_index: int) -> str:
    """"t1".."t7" in size order (rank_index 0 = largest), "other" for anything beyond - charts.py's CSS
    only defines seven distinct theme tokens plus "other", so a dataset with more than seven real themes
    (unusual - clustering's adaptive min cluster size keeps counts modest) falls back to reusing the
    "other" token for the overflow rather than inventing an eighth colour. Documented, not silent."""
    tokens = [f"t{i}" for i in range(1, 8)]
    return tokens[rank_index] if rank_index < len(tokens) else "other"


# ---------------------------------------------------------------- answer-length histogram (optional -
# see build_report_data's docstring: this module is not handed the cleaned dataframe, only Theme rows, so
# a real histogram needs the caller to pass pre-computed word counts; without them we say so honestly.)

_LENGTH_BUCKETS: list[tuple[int, int | None, str]] = [
    (1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4-5"), (6, 8, "6-8"),
    (9, 12, "9-12"), (13, 20, "13-20"), (21, 40, "21-40"), (41, None, "41+"),
]


def _length_bins(lengths: list[int]) -> tuple[list[tuple[str, int]], str, str]:
    counts = {label: 0 for _, _, label in _LENGTH_BUCKETS}
    for n in lengths:
        for lo, hi, label in _LENGTH_BUCKETS:
            if n >= lo and (hi is None or n <= hi):
                counts[label] += 1
                break
    bins = [(label, counts[label]) for _, _, label in _LENGTH_BUCKETS]
    typical_label = max(bins, key=lambda b: b[1])[0] if bins else "n/a"
    median = round(statistics.median(lengths)) if lengths else 0
    return bins, typical_label, f"Typical length {median} words"


# ---------------------------------------------------------------- cleaning-report field access (accepts
# either the stored dict - CleaningReport.to_dict(), what api_cleaning.py actually persists - or a
# CleaningReport instance directly)

def _cr(report: Any, key: str, default: Any) -> Any:
    if report is None:
        return default
    if isinstance(report, dict):
        return report.get(key, default)
    return getattr(report, key, default)


# ==================================================================== 1. build_report_data

def build_report_data(
    dataset: Dataset,
    themes: list[Theme],
    cleaning_report: Any,
    question: str,
    *,
    answer_lengths: list[int] | None = None,
) -> ReportData:
    """Converts stored `Theme` rows for one dataset + column into the `ReportData` shape
    `app/charts.py`'s renderers already understand.

    `cleaning_report` is either the dict `api_cleaning.py` persists (`CleaningReport.to_dict()`, found at
    `dataset.profile["cleaning"]["report"]`) or a `CleaningReport` instance - both read the same way here.

    `answer_lengths` is an optional list of per-answer word counts. This function is only handed `Theme`
    rows, not the cleaned dataframe, so it cannot cheaply compute a real answer-length histogram itself;
    a caller that already has the cleaned text loaded (as `app/api_themes.py`'s route does, to build
    themes in the first place) can pass the word counts through here for a real histogram. Without them,
    `quality.bins`/`typical_bin` say so honestly rather than inventing numbers - see `_build_quality`.

    Populates: `overview` (stats/insights computed here in code from the numbers below - never asked of
    Claude, per SPEC.md section 2's rule that headline generation gets numbers only, applied the same way
    to this block), `themes` (real themes largest-first, "Other" last, colours "t1".."t7" then "other",
    `children=[]` always - see module docstring), `quality` (from `cleaning_report`'s real counts),
    `context` (honest generic defaults - see module docstring). `score`/`segment`/`trend`/`cooccurrence`
    are empty/neutral placeholders: SPEC.md build-order step 3 (score/segment/date columns) is out of
    scope for this stream, and `pick_chart` never selects a chart that would read them, so their content
    never reaches a report - only their shape needs to be valid so `ReportData` constructs at all.
    `answer_map`/`frequency`/`phrases`/`quotes` are placeholders for the same reason: none of this
    stream's chosen chart ids (`overview`, `treemap`/`rank`/`sentsun`, `quality`) read them.
    """
    real = [t for t in themes if t.label != OTHER_LABEL]
    other = next((t for t in themes if t.label == OTHER_LABEL), None)
    ranked_real = sorted(real, key=lambda t: t.size, reverse=True)
    total_answered = _total_answered(themes)
    overall = _overall_sentiment(themes, total_answered)

    def _node(t: Theme, color: str, note: str = "") -> ThemeNode:
        share = round(t.size / total_answered * 100, 1) if total_answered else 0.0
        tone = t.tone or {}
        return ThemeNode(
            name=t.label, share=share, sentiment=t.sentiment if t.sentiment is not None else 0.0,
            count=t.size, color=color,
            tones=ToneSplit(neg=tone.get("neg", 0.0), neu=tone.get("neu", 100.0), pos=tone.get("pos", 0.0)),
            children=[],  # sub-theme wiring is out of scope for this stream - see module docstring
            note=note,
        )

    nodes = [_node(t, _theme_color(i)) for i, t in enumerate(ranked_real)]
    if other is not None:
        note = f"Folded in: {other.description}" if other.description else \
            "Folded in: answers too rare, unclear or distinct to group into a theme."
        nodes.append(_node(other, "other", note=note))

    selected_theme = nodes[0].name if nodes else ""
    hover_theme = nodes[1].name if len(nodes) > 1 else selected_theme
    total_rows = dataset.row_count if dataset.row_count else total_answered

    overview = _build_overview(nodes, overall, total_rows, total_answered, answer_lengths)
    # The report page this feeds always shows its own real, Claude-written "What stands out" list built
    # from actual findings (app/api_report.py's response, rendered by Report.tsx above the overview chart)
    # - clearing this chart's own copy here stops it printing a second, redundant "What stands out" heading
    # right below the page's real one. app/charts.py's f_overview only shows that heading when insights is
    # non-empty, so this cleanly removes the whole duplicate section rather than leaving an empty one.
    overview.insights = []
    quality = _build_quality(cleaning_report, total_rows, total_answered, answer_lengths)
    context = ContextData(
        kind="anything else",
        kind_options=["reasons", "improvements", "experiences", "facts", "opinions", "anything else"],
        kind_hover="reasons", framing="neutrally", length="a sentence or two",
        columns_note="Score, segment and date cross-cuts are not wired into this report yet.",
    )

    return ReportData(
        question=question, total=total_rows, answered=total_answered, overall_sentiment=round(overall, 3),
        themes=nodes, selected_theme=selected_theme, hover_theme=hover_theme,
        overview=overview,
        score=ScoreData(name="", bands=[]),
        segment=SegmentData(name="", groups=[], rows=[]),
        trend=TrendData(labels=[], series=[], sentiment=[], hover_index=0, note=""),
        cooccurrence=[],
        answer_map=MapData(seed=0, tip_text="", tip_note=""),
        frequency=FreqData(question="", answered=0, items=[], highlight="", footnote=""),
        phrases=PhraseData(phrases=[], highlight=""),
        quotes=QuoteData(quotes=[], highlight_index=0),
        quality=quality,
        context=context,
    )


def _build_overview(nodes: list[ThemeNode], overall: float, total_rows: int, total_answered: int,
                     answer_lengths: list[int] | None) -> OverviewData:
    pct_answered = round(total_answered / total_rows * 100) if total_rows else 0
    blank = max(0, total_rows - total_answered)
    real_nodes = [n for n in nodes if n.color != "other"]

    stats = [
        ("Responses", f"{total_rows:,}", ""),
        ("Answered", f"{pct_answered}%", f"({blank:,} blank, n/a or excluded)" if blank else ""),
        ("Themes", str(len(real_nodes)), "(no sub-themes yet)"),
        ("Average sentiment", f"{overall:+.2f}", ""),
    ]
    if answer_lengths:
        _, typical_bin, typical_note = _length_bins(answer_lengths)
        stats.insert(2, ("Typical length", f"{typical_bin} words", typical_note))

    insights: list[str] = []
    if nodes:
        insights.append(f"{nodes[0].name} is the largest theme at {nodes[0].share:g}% of answers.")
    if real_nodes:
        tone_lead = max(real_nodes, key=lambda n: abs(n.sentiment - overall))
        if abs(tone_lead.sentiment - overall) >= TONE_GAP_MIN:
            direction = "negative" if tone_lead.sentiment < overall else "positive"
            insights.append(
                f"{tone_lead.name} carries the most {direction} wording "
                f"({tone_lead.sentiment:+.2f} against {overall:+.2f} overall)."
            )
    if len(insights) < 2:
        other_node = next((n for n in nodes if n.color == "other"), None)
        if other_node is not None and other_node.share >= LONGTAIL_SHARE_MIN:
            insights.append(
                f"{other_node.name} is unusually large at {other_node.share:g}% of answers, worth a closer look."
            )
    return OverviewData(stats=stats, insights=insights[:2])


def _build_quality(cleaning_report: Any, total_rows: int, total_answered: int,
                    answer_lengths: list[int] | None) -> QualityData:
    removed_by_step = _cr(cleaning_report, "removed_by_step", {}) or {}
    pii = _cr(cleaning_report, "pii", {}) or {}
    blanks = sum(v for k, v in removed_by_step.items() if "blank" in k)
    dups = sum(v for k, v in removed_by_step.items() if "duplicate" in k)
    total_pii = sum(pii.values()) if isinstance(pii, dict) else 0

    notes = [
        (f"{blanks:,} rows were blank, said nothing, or answered n/a; {dups:,} were exact or near-duplicate "
         "answers. Both are left out of the themes.") if (blanks or dups)
        else "No blank or duplicate rows were flagged by cleaning.",
        (f"{total_pii:,} likely name, address or phone mentions were masked before any text reached a model.")
        if total_pii else "No personal information (names, addresses, phone numbers) was found to mask.",
        "Sentiment comes from a word-based scorer built for English. It reads wording, not intent, and can "
        "miss sarcasm. Scorer-to-sample-label agreement is not tracked by this report yet.",
    ]
    if answer_lengths:
        bins, typical_bin, typical_note = _length_bins(answer_lengths)
    else:
        bins = [("n/a", max(total_answered, 1))]
        typical_bin = "n/a"
        typical_note = "Answer length was not computed for this report."
    return QualityData(bins=bins, typical_bin=typical_bin, typical_note=typical_note, notes=notes)


# ==================================================================== 2. candidate_findings

def candidate_findings(themes: list[Theme], min_group_size: int | None = None) -> list[Candidate]:
    """Computes candidate findings from stored `Theme` rows (SPEC.md section 9.3).

    Deliberately narrow first pass - see the module docstring for why only these two kinds exist yet:
      - **tone contrast**: a theme whose sentiment differs notably (either direction) from the dataset's
        overall (answer-count-weighted) sentiment.
      - **dominant/rare theme**: the largest real theme, if it clearly leads (a "clear #1"), or the
        "Other"/long-tail group, if it is unusually large (a data-quality signal as much as a finding).

    Every candidate must clear `min_group_size` (defaults to `app.cleaning.suppression.min_group_size()`,
    this codebase's existing convention for "too small a group to report on" - reused rather than a second
    constant) before it is even considered, and must additionally clear a kind-specific effect-size gate
    (`TONE_GAP_MIN`/`DOMINANT_SHARE_MIN`+`DOMINANT_MARGIN_MIN`/`LONGTAIL_SHARE_MIN`) to become a Candidate
    at all. Each candidate's `score` blends effect size (the dominant factor) with a diminishing bonus for
    larger groups, so two similarly-sized effects rank the one backed by more answers higher.

    Returns the top `MAX_CANDIDATES` (5) by score - a CAP, never a floor: SPEC.md section 5 also describes
    an "also checked, nothing notable" case, so this can legitimately return `[]` when nothing clears the
    gates, and returns fewer than 3 rather than padding with weak candidates just to hit a minimum.
    """
    floor = min_group_size if min_group_size is not None else _suppression_min_group_size()
    real = [t for t in themes if t.label != OTHER_LABEL]
    other = next((t for t in themes if t.label == OTHER_LABEL), None)
    total = _total_answered(themes)
    if total <= 0 or not real:
        return []
    overall = _overall_sentiment(themes, total)

    candidates: list[Candidate] = []

    # --- tone contrast
    for t in real:
        if t.size < floor:
            continue
        sentiment = t.sentiment if t.sentiment is not None else 0.0
        gap = sentiment - overall
        if abs(gap) < TONE_GAP_MIN:
            continue
        share = round(t.size / total * 100, 1)
        score = abs(gap) * (1 + min(1.0, t.size / (5 * floor)))
        candidates.append(Candidate(
            kind="tone_contrast", id=f"tone_contrast:{t.id}", theme_id=t.id, theme_name=t.label,
            count=t.size, score=score,
            numbers={
                "theme": t.label, "share_pct": share, "count": t.size,
                "sentiment": round(sentiment, 3), "overall_sentiment": round(overall, 3), "gap": round(gap, 3),
            },
        ))

    # --- dominant theme (the largest real theme, if it clearly leads)
    ranked = sorted(real, key=lambda t: t.size, reverse=True)
    if ranked and ranked[0].size >= floor:
        top = ranked[0]
        top_share = round(top.size / total * 100, 1)
        second_share = round(ranked[1].size / total * 100, 1) if len(ranked) > 1 else 0.0
        margin = round(top_share - second_share, 1)
        if top_share >= DOMINANT_SHARE_MIN and margin >= DOMINANT_MARGIN_MIN:
            candidates.append(Candidate(
                kind="dominant_theme", id=f"dominant_theme:{top.id}", theme_id=top.id, theme_name=top.label,
                count=top.size, score=margin,
                numbers={
                    "theme": top.label, "share_pct": top_share, "count": top.size,
                    "runner_up_share_pct": second_share, "margin_pct": margin,
                },
            ))

    # --- long tail ("Other" unusually large - a data-quality signal, not just a finding)
    if other is not None and other.size >= floor:
        share = round(other.size / total * 100, 1)
        if share >= LONGTAIL_SHARE_MIN:
            candidates.append(Candidate(
                kind="long_tail", id=f"long_tail:{other.id}", theme_id=other.id, theme_name=other.label,
                count=other.size, score=share,
                numbers={"theme": other.label, "share_pct": share, "count": other.size},
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:MAX_CANDIDATES]


# ==================================================================== 3. label_confidence

def label_confidence(candidate: Candidate) -> str:
    """"Solid" or "Tentative" (SPEC.md section 9.3/6). A simple, documented threshold on group size
    (`SOLID_COUNT_MULTIPLIER` times the suppression floor) AND a kind-specific effect-size threshold -
    both are named constants at the top of this module, easy to retune; SPEC.md gives no exact numbers
    for this, only "label uncertain ones Tentative"."""
    floor = _suppression_min_group_size()
    if candidate.count < floor * SOLID_COUNT_MULTIPLIER:
        return "tentative"
    if candidate.kind == "tone_contrast":
        return "solid" if abs(candidate.numbers["gap"]) >= TONE_GAP_SOLID else "tentative"
    if candidate.kind == "dominant_theme":
        return "solid" if candidate.numbers["share_pct"] >= DOMINANT_SHARE_SOLID else "tentative"
    if candidate.kind == "long_tail":
        return "solid" if candidate.numbers["share_pct"] >= LONGTAIL_SHARE_SOLID else "tentative"
    return "tentative"  # pragma: no cover - defensive: every real kind is handled above


# ==================================================================== 4. pick_chart

def pick_chart(candidate: Candidate) -> str:
    """Maps a finding kind to one of this stream's small set of wired-up chart ids
    (`overview`, `treemap`, `rank`, `sentsun`, `quality`), per SPEC.md section 4's priority table - see
    `CHART_BY_KIND`'s comments for the fallback reasoning (sunburst's own stated skip condition, "fewer
    than 3 sub-themes in total, use treemap", is always met while sub-themes are unpopulated)."""
    return CHART_BY_KIND[candidate.kind]


# ==================================================================== 5. write_headline

HEADLINE_SYSTEM = (
    "You write one plain sentence per survey finding, for a report a non-expert will read. You are given "
    "the survey question and, for each finding, its computed numbers only - never raw survey answers. "
    'Reply with JSON only, no prose before or after it: {"headlines": [{"id": str, "sentence": str}, ...]}. '
    "Include exactly one entry per id you were given, using that same id. Each sentence: says what stands "
    "out in plain words, uses relative wording ('about twice as often', 'the most negative') rather than "
    "exact statistical jargon or p-values, never claims a cause, and is a single sentence with no line "
    "breaks. Never invent, guess, or state any number that was not given to you."
)


def _build_headline_prompt(candidates: list[Candidate], question: str) -> str:
    payload = {
        "survey_question": question,
        "findings": [{"id": c.id, "kind": c.kind, **c.numbers} for c in candidates],
    }
    return json.dumps(payload)


def _extract_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise FindingsError("Claude's reply did not contain any JSON.", text)
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise FindingsError(f"Claude's reply was not valid JSON: {e}", text) from e


def _parse_headlines(text: str, expected_ids: set[str]) -> dict[str, str]:
    """Strictly validates the parsed reply against `expected_ids` (the candidate ids we actually sent) -
    mirrors `app.text_pipeline.labeling._parse_response` exactly: never trusts a field it has not checked
    the type of, raises `FindingsError` (with the raw text) on any structural problem, requires exactly
    one usable entry per expected id, and silently ignores entries for ids we never sent."""
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise FindingsError("Claude's reply was not a JSON object.", text)
    headlines = data.get("headlines")
    if not isinstance(headlines, list):
        raise FindingsError("Claude's reply had no 'headlines' list.", text)

    by_id: dict[str, str] = {}
    for item in headlines:
        if not isinstance(item, dict):
            raise FindingsError("Claude's reply had a non-object entry in 'headlines'.", text)
        cid = item.get("id")
        if not isinstance(cid, str) or not cid:
            raise FindingsError(f"Claude's reply had a headline with a missing/invalid id: {item!r}", text)
        if cid not in expected_ids:
            continue  # a hallucinated/unknown id does not fail the whole batch on its own
        sentence = item.get("sentence")
        if not isinstance(sentence, str) or not sentence.strip():
            raise FindingsError(f"Claude's reply had no usable sentence for id {cid!r}.", text)
        by_id[cid] = sentence.strip()[:300]

    missing = expected_ids - by_id.keys()
    if missing:
        raise FindingsError(f"Claude's reply was missing headline(s) for id(s) {sorted(missing)}.", text)
    return by_id


def write_headline(candidates: list[Candidate], client: ClaudeClient, question: str) -> dict[str, str]:
    """Writes one plain sentence per candidate finding, in ONE batched Claude call - never one call per
    candidate (this codebase's existing convention, SPEC.md section 2's "Headline sentences" row and
    `app.text_pipeline.labeling.label_clusters`'s own "one batched call for all clusters" precedent).
    Named `write_headline` (singular) to match this brief's numbered item, but - exactly like
    `label_clusters` - it must take every kept candidate at once to honour that convention, so its actual
    signature takes the list of kept candidates, not one.

    Claude is given ONLY the computed numbers per candidate (`Candidate.numbers` - theme name, share,
    sentiment/gap, count; never raw answer text) plus the survey question, matching SPEC.md's rule that
    headline generation is cheap and low-risk precisely because it never sees samples.

    Returns `{candidate.id: sentence}`. Returns `{}` and makes NO call at all when `candidates` is empty -
    this is how "also checked, nothing notable" (SPEC.md section 5) reaches the report at zero network cost.

    Raises `FindingsError` (carrying the raw reply) if the reply cannot be trusted as headlines.
    """
    if not candidates:
        return {}
    expected_ids = {c.id for c in candidates}
    prompt = _build_headline_prompt(candidates, question)
    raw = client.complete(HEADLINE_SYSTEM, prompt)
    return _parse_headlines(raw, expected_ids)


# ==================================================================== 6. build_findings

def _question_for(dataset: Dataset, column: str) -> str:
    """Same question-resolution order `app/api_themes.py`'s `build_themes` route already uses."""
    confirmed = (dataset.profile or {}).get("confirmed") or {}
    question = (confirmed.get("question") or "").strip()
    if question:
        return question
    return ((dataset.profile or {}).get("question") or {}).get("text") or column


def build_findings(
    dataset: Dataset,
    column: str,
    db_session: Session,
    claude_client: ClaudeClient,
    cleaning_report: Any = None,
    answer_lengths: list[int] | None = None,
    min_group_size: int | None = None,
) -> Report:
    """Orchestrates 1-5 for one dataset + open-text column: loads its stored `Theme` rows, computes and
    scores candidates, writes headlines (one batched Claude call), builds the `ReportData`, and persists
    `Finding` rows (one per kept candidate) plus one `Report` row for the ordered block list.

    Replaces any existing report for this dataset + column (mirrors `app/api_themes.py`'s theme-rebuild
    pattern: old rows are only deleted after every step above has already succeeded, so a failure here
    leaves a prior report/findings untouched). Neither `Finding` nor `Report` has a `column` field
    (checked - see docs/DECISIONS.md for why no migration was added for this): `column` is instead stored
    inside `Finding.data`/`Report.content`, which already exist for exactly this purpose ("the specific
    numbers behind that finding") and is used here as the correlation key for "this dataset's report for
    this column" on rebuild.

    Render-vs-store-HTML: `Report.content` stores each block's `chart_id`/`finding_id`/`priority`, NOT
    rendered HTML. `app/charts.py`'s `render()` is fast, pure-Python and makes no network call, so
    re-rendering from the stored `Theme`/`Finding` rows on every read is cheap and - unlike cached HTML -
    can never go stale after a theme rename/merge/split (SPEC.md section 5's "editing a theme... updates
    the whole report"). A caller that wants to render a block calls
    `render(block["chart_id"], build_report_data(dataset, themes, cleaning_report, question))`.

    Raises `NoThemesForColumn` if no themes are stored yet for this dataset + column.
    """
    themes = list(db_session.scalars(
        select(Theme).where(Theme.dataset_id == dataset.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    if not themes:
        raise NoThemesForColumn(f"No stored themes for dataset {dataset.id}, column {column!r}. Build themes first.")

    question = _question_for(dataset, column)
    candidates = candidate_findings(themes, min_group_size=min_group_size)
    sentences = write_headline(candidates, claude_client, question)
    report_data = build_report_data(dataset, themes, cleaning_report, question, answer_lengths=answer_lengths)

    # Replace prior findings/report for this dataset + column - see the column-correlation note above.
    for old_finding in db_session.scalars(select(Finding).where(Finding.dataset_id == dataset.id)).all():
        if isinstance(old_finding.data, dict) and old_finding.data.get("column") == column:
            db_session.delete(old_finding)
    for old_report in db_session.scalars(select(Report).where(Report.dataset_id == dataset.id)).all():
        if isinstance(old_report.content, dict) and old_report.content.get("column") == column:
            db_session.delete(old_report)

    ordered = sorted(candidates, key=lambda c: (PRIORITY_BY_KIND[c.kind], -c.score))
    new_findings: list[Finding] = []
    for cand in ordered:
        new_findings.append(Finding(
            dataset_id=dataset.id, theme_id=cand.theme_id, sentence=sentences[cand.id],
            chart_type=pick_chart(cand), confidence=label_confidence(cand),
            data={**cand.numbers, "column": column, "kind": cand.kind},
        ))
    db_session.add_all(new_findings)
    db_session.flush()  # assigns Finding.id before it is referenced in blocks below

    blocks: list[dict[str, Any]] = [{"kind": "overview", "chart_id": "overview", "priority": 1, "finding_id": None}]
    for cand, finding in zip(ordered, new_findings):
        blocks.append({
            "kind": "finding", "chart_id": pick_chart(cand), "priority": PRIORITY_BY_KIND[cand.kind],
            "finding_id": finding.id,
        })
    blocks.append({"kind": "quality", "chart_id": "quality", "priority": 9, "finding_id": None})

    report = Report(dataset_id=dataset.id, content={
        "column": column, "question": question, "blocks": blocks,
        "also_checked_nothing_notable": len(candidates) == 0,
    })
    db_session.add(report)
    db_session.commit()
    return report
