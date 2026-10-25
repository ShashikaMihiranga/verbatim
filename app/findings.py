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
  - Sub-themes ARE now populated when a theme qualifies (`Theme.sub_themes`, a second HDBSCAN pass inside
    that theme's own answers - see `app/text_pipeline/subthemes.py` for the exact eligibility rule: only
    the top handful of real themes by size, only above a minimum answer count, and only when enough
    sub-clusters survive and cover enough of the parent to not visually mislead a treemap block). Most
    themes still end up with `sub_themes == []` (too small, ranked too low, gated out, or "Other", which is
    never sub-clustered) - `theme_nodes` below reads `t.sub_themes` directly, capped and filtered, into each
    `ThemeNode.children`. This still does not change which chart SPEC.md section 4's table selects for a
    finding; see `pick_chart` below and the `CHART_BY_KIND` comment for why sunburst/icicle stay unwired.
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
    BinnedGridData, CategoryAvgData, ContextData, FreqData, GroupTrendData, MapData, OtherBreakdown,
    OverviewData, PhraseData, QualityData, QuoteData, ReportData, ScoreData, SegmentData, SubTheme,
    ThemeNode, ThemeSummary, ToneSplit, TrendData,
)
from .cleaning.suppression import min_group_size as _suppression_min_group_size
from .findings_structured import (
    SCORE_SPREAD_SOLID,
    SEGMENT_SKEW_RATIO_SOLID,
    TREND_SHIFT_SOLID,
    StructuredContext,
    score_correlation_candidates,
    segment_skew_candidates,
    trend_shift_candidates,
)
from .models import Dataset, Finding, Report, Theme
from .report_blocks import max_tone_spread, sub_theme_total
from .text_pipeline import AnthropicClaudeClient, ClaudeClient
from .text_pipeline import LabelingClaudeNotConfigured as FindingsClaudeNotConfigured
from .text_pipeline.labeling import OTHER_LABEL, kind_payload
from .text_pipeline.phrases import build_phrase_data
from .text_pipeline.quotes import build_quote_data

__all__ = [
    "Candidate", "FindingsClaudeNotConfigured", "FindingsError", "NoThemesForColumn", "FakeClaudeClient",
    "build_report_data", "candidate_findings", "label_confidence", "pick_chart", "write_headline",
    "build_findings", "default_claude_client", "theme_nodes", "question_for",
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

# SPEC.md section 4's table, two rows with a real skip condition (chart-block stream, 2026-10-24,
# Stage 3 - these were previously documented as "out-of-scope follow-up work", now wired for real):
#   "Sunburst: ...Skip when fewer than 3 sub-themes in total, use treemap."
#   "Sentiment sunburst or Marimekko: ...Skip when sentiment spread under 0.05" (fallback: Diverge, "Reasons
#   with neutral or positive framing" - same priority tier, SPEC's own documented alternate for this case).
# `pick_chart` below checks both real thresholds via `app.report_blocks.sub_theme_total`/`max_tone_spread`
# against the finding's own `ReportData` - no `report_data` (legacy/direct calls) falls back to each kind's
# table-documented default (treemap/sentsun), same as this module's behavior before this stage.
SUB_THEME_SUNBURST_MIN = 3  # SPEC.md section 4's own "fewer than 3 sub-themes in total" wording
TONE_SPREAD_SENTSUN_MIN = 0.05  # SPEC.md section 4's own "sentiment spread under 0.05" wording

# Stage 4 (chart-block stream, 2026-10-24): a `trend_shift` finding's own gate ladder - more specific/
# richer alternates checked first, `trend` (CHART_BY_KIND's table default) is the final fallback.
# `theme_mix_over_time`'s own threshold, matching its registry `needs()` (app/report_blocks.py b44)
# exactly: 3 or more real themes (the same "theme exists at all" shape `sub_theme_total`/`max_tone_spread`
# above already reuse `report_data.themes` for). `trend_small_multiples`/`trend_sparse` are the ladder's
# two higher-priority rungs (SPEC's own "more than 4 themes would tangle" / "some periods are missing"
# cases) - not wired here yet: `trend_small_multiples` has no renderer yet, `trend_sparse` has neither a
# renderer nor the per-period answer-count data `TrendData` would need to detect a gap at all (see
# `docs/DECISIONS.md`'s Stage 4 entry and the plan file for the follow-up that adds both rungs).
THEME_MIX_OVER_TIME_MIN_THEMES = 3

CHART_BY_KIND = {
    "tone_contrast": "sentsun",  # table: "Sentiment sunburst or Marimekko", priority 4 - the TABLE-DEFAULT
                                 # chart; pick_chart below swaps this for "diverge" when real tone spread is
                                 # under TONE_SPREAD_SENTSUN_MIN (SPEC's own documented skip + fallback)
    "dominant_theme": "rank",  # table: "Rank", priority 3 - the richest single view we have for "this
                               # theme clearly leads" (shows share, count and sentiment tint together)
    "long_tail": "treemap",  # table: "Treemap", priority 2, replaces sunburst - block area makes an
                             # oversized "Other" block legible at a glance; pick_chart below swaps this for
                             # "sunburst" when real sub-theme count reaches SUB_THEME_SUNBURST_MIN
    "segment_skew": "heatmap",  # table: "Heatmap", priority 5 - matches SPEC.md section 4's row exactly
    "score_correlation": "byScore",  # table's own analogue is "Sankey" (priority 5), explicitly out of
                                      # scope this pass (no Sankey renderer exists/is tested yet) - `byScore`
                                      # is used instead: its renderer already exists, is tested, and matches
                                      # the mockup's visual style for "a number that moves with score". A
                                      # deliberate, documented SPEC.md deviation - see docs/DECISIONS.md.
    "trend_shift": "trend",  # table: "Trend", priority 6 - the TABLE-DEFAULT chart; pick_chart below swaps
                             # this for "themeMixOverTime" once real themes reach THEME_MIX_OVER_TIME_MIN_THEMES
}
PRIORITY_BY_KIND = {
    "long_tail": 2, "dominant_theme": 3, "tone_contrast": 4, "segment_skew": 5, "score_correlation": 5,
    "trend_shift": 6,
}


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


def theme_nodes(
    themes: list[Theme], total_answered: int, filter_rows: set[int] | None = None,
) -> list[ThemeNode]:
    """Converts stored `Theme` rows into colour-assigned `ThemeNode`s: real themes largest-first get
    "t1".."t7" tokens via `_theme_color` (only the first 7 real themes get their own node - see below),
    "Other" (if present) always goes last with the "other" token. `children` is built straight from
    `t.sub_themes` (see `app.models.Theme.sub_themes` and `app/text_pipeline/subthemes.py`) - `[]` for a
    `Theme` that was not split (most of them - see the module docstring's eligibility summary) or has no
    `sub_themes` at all (`None`, e.g. a row written before this stream), exactly as before.

    No signature change needed for real sub-themes to reach a caller: every one of this function's callers
    already hands it live `Theme` ORM rows, so reading `t.sub_themes` here is enough - see the plan's
    Context section for why (`build_report_data`, `app.api_themes.themes_chart`,
    `app.api_report._structured_context_for` and `app.findings_structured.score_correlation_candidates`
    all get real children for free, with zero interface changes).

    Extracted so this exact colour-assignment logic exists in exactly one place, reused by both
    `build_report_data` below (via its own local `_node` partial application) and
    `app.api_themes.themes_chart` (the lightweight "one chart, not a wall of cards" endpoint for the
    Themes screen, which needs the same `Theme` rows -> `ThemeNode`s conversion but has no `Dataset`/
    `cleaning_report`/`ReportData` context to call the full `build_report_data` with).

    A dataset with more than 7 real themes used to give every theme beyond the 7th its own `ThemeNode`,
    just with `_theme_color`'s same "other" fallback colour as the genuine noise cluster - several
    differently-named nodes all rendering as one indistinguishable grey blob in every chart, some too thin
    for a wedge label at all (confirmed on a real hotel-reviews dataset with 25+ real themes). Real themes
    beyond the top 7 (`overflow_real`) are now folded into the SAME single node as the noise cluster via
    `_merge_into_other` below, so every consumer - charts and the score/segment/trend cross-tab engine
    alike - sees at most 8 nodes total (7 real + 1 merged "Other"), never more than one node sharing the
    "other" colour."""
    real = [t for t in themes if t.label != OTHER_LABEL]
    other = next((t for t in themes if t.label == OTHER_LABEL), None)

    def _eff_size(t: Theme) -> int:
        # Filters feature (SPEC.md section 5): under a filter, "size" means "rows that are both in this
        # theme AND pass the filter" - never the stored, dataset-wide `t.size`. A theme that's largest
        # overall can legitimately rank lower (or vanish) once a filter is active; that's correct, not a
        # bug. Byte-identical to `t.size` when no filter is active.
        if filter_rows is None:
            return t.size
        return len(set(t.answer_refs or []) & filter_rows)

    ranked_real = sorted(real, key=_eff_size, reverse=True)
    kept_real, overflow_real = ranked_real[:7], ranked_real[7:]

    def _children(t: Theme) -> list[SubTheme]:
        # Capped to MAX_SUBTHEMES_PER_THEME (3) at the clustering step already (subthemes.py), but this is
        # a second, independent guard here too (plan decision 7): `app.charts.py`'s treemap `MIX` list is a
        # hardcoded 3-element list (a 4th sub-theme would raise `IndexError` there), and a sub-theme whose
        # SHARE (not stored size) rounds to 0.0% on a very large dataset would crash squarify's divide-by-
        # zero - so the `share > 0` filter is applied to the COMPUTED share below, after rounding, not to
        # the stored `size` (which is always > 0 for anything that was actually kept and stored).
        #
        # Filters feature: a sub-theme's own size has no per-row record to intersect against `filter_rows`
        # (only the parent `Theme.answer_refs` does) - rather than inventing a new approximation, sub-
        # themes are simply dropped while a filter is active (documented scope cut, see the Filters plan).
        if filter_rows is not None:
            return []
        children: list[SubTheme] = []
        for s in (t.sub_themes or [])[:3]:
            share = round(s["size"] / total_answered * 100, 1) if total_answered else 0.0
            if share > 0:
                children.append(SubTheme(name=s["label"], share=share))
        return children

    def _node(t: Theme, color: str) -> ThemeNode:
        refs = sorted(set(t.answer_refs or []) & filter_rows) if filter_rows is not None \
            else sorted(t.answer_refs or [])
        count = len(refs) if filter_rows is not None else t.size
        share = round(count / total_answered * 100, 1) if total_answered else 0.0
        tone = t.tone or {}
        # chart-block stream, 2026-10-24, batch 3 (theme_similarity): real for any theme built since the
        # map_x/map_y columns landed (a 2D PCA projection of the theme's own real HDBSCAN cluster centroid,
        # computed once at build time - see app/api_themes.py's _write_theme_rows). None/None for "Other"
        # and for any theme built before this stream - map_xy already means "None scatters the theme"
        # (this field's own docstring), so an old row just renders exactly as it always did.
        map_xy = (t.map_x, t.map_y) if t.map_x is not None and t.map_y is not None else None
        return ThemeNode(
            name=t.label, share=share, sentiment=t.sentiment if t.sentiment is not None else 0.0,
            count=count, color=color,
            tones=ToneSplit(neg=tone.get("neg", 0.0), neu=tone.get("neu", 100.0), pos=tone.get("pos", 0.0)),
            children=_children(t), map_xy=map_xy,
            answer_refs=refs, theme_id=t.id,
        )

    def _merge_into_other(overflow: list[Theme], other: Theme | None) -> ThemeNode:
        """Combines every real theme ranked 8th+ plus the genuine noise cluster (whichever of the two are
        present) into ONE node, colour "other" - see the module-level note above for why. `answer_refs` is
        the union of every folded theme's own `answer_refs`, so downstream cross-tab counts
        (`app.findings_structured.build_score_data` et al.) still count every merged answer correctly.
        `theme_id` stays a real id (not None) when exactly one theme is being folded - the common case of
        a dataset with <=7 real themes and just the noise cluster, byte-identical to this function's
        pre-merge behaviour.

        Filters feature: when `filter_rows` is active, every merged theme's `answer_refs` is first
        intersected with `filter_rows`, and `total_count`/sentiment/tone are all recomputed from those
        filtered refs rather than the stored `t.size` - so the folded "Other" node's numbers stay
        consistent with every other (filtered) node."""
        merged = overflow + ([other] if other is not None else [])
        # Keyed by position, not `t.id` - unpersisted `Theme` rows (e.g. in tests) all have `id is None`,
        # which would collide as dict keys and silently drop every merged theme but the last.
        if filter_rows is not None:
            merged_refs = [sorted(set(t.answer_refs or []) & filter_rows) for t in merged]
            sizes = [len(refs) for refs in merged_refs]
        else:
            merged_refs = [sorted(t.answer_refs or []) for t in merged]
            sizes = [t.size for t in merged]
        total_count = sum(sizes)
        share = round(total_count / total_answered * 100, 1) if total_answered else 0.0
        sentiment = sum((t.sentiment or 0.0) * s for t, s in zip(merged, sizes)) / total_count \
            if total_count else 0.0
        tone_totals = {"neg": 0.0, "neu": 0.0, "pos": 0.0}
        for t, s in zip(merged, sizes):
            tone = t.tone or {}
            for k in tone_totals:
                tone_totals[k] += tone.get(k, 0.0) * s
        tones = ToneSplit(
            neg=round(tone_totals["neg"] / total_count, 1) if total_count else 0.0,
            neu=round(tone_totals["neu"] / total_count, 1) if total_count else 100.0,
            pos=round(tone_totals["pos"] / total_count, 1) if total_count else 0.0,
        )
        answer_refs = sorted({r for refs in merged_refs for r in refs})
        theme_id = merged[0].id if len(merged) == 1 else None

        if overflow:
            folded_names = ", ".join(t.label for t in overflow)
            note = (f"Folded in: {folded_names}, plus answers too rare, unclear or distinct to group "
                    "into a theme.") if other is not None else f"Folded in: {folded_names}."
        elif other is not None:
            note = f"Folded in: {other.description}" if other.description else \
                "Folded in: answers too rare, unclear or distinct to group into a theme."
        else:
            note = ""

        return ThemeNode(
            name=OTHER_LABEL, share=share, sentiment=round(sentiment, 3), count=total_count, color="other",
            tones=tones, note=note, answer_refs=answer_refs, theme_id=theme_id,
        )

    nodes = [_node(t, _theme_color(i)) for i, t in enumerate(kept_real)]
    if overflow_real or other is not None:
        nodes.append(_merge_into_other(overflow_real, other))
    return nodes


def other_breakdown(
    themes: list[Theme], total_answered: int, filter_rows: set[int] | None = None,
) -> tuple[OtherBreakdown | None, list[ThemeSummary]]:
    """Companion to `theme_nodes` for the report's "Other" exploration section (docs/TODO.md, 2026-10-21
    Phase 1) - same ranking, same `_eff_size`/filter handling, but exposes what `_merge_into_other`
    folds away: the noise-vs-hidden-real-themes split inside "Other", and the full, UNCAPPED list of
    every real theme (not just the top 7 a `ThemeNode` can get its own colour for).

    Deliberately a separate function, not a `theme_nodes` return-shape change: `theme_nodes` is reused
    by the capped treemap AND the score/segment/trend cross-tab engine
    (`app.findings_structured.build_score_data` et al.), all of which depend on its existing "at most 8
    nodes" contract - changing that shape would ripple into every one of those callers. This function
    touches none of them; it only reads the same `Theme` rows a second time.

    Returns `(None, all_themes)` when there is nothing genuinely in "Other" to explain (no noise cluster
    and no real theme ranked 8th+) - the common case for most datasets, and the signal the report page
    uses to skip the callout entirely rather than showing an empty/zero breakdown."""
    real = [t for t in themes if t.label != OTHER_LABEL]
    other = next((t for t in themes if t.label == OTHER_LABEL), None)

    def _eff_size(t: Theme) -> int:
        if filter_rows is None:
            return t.size
        return len(set(t.answer_refs or []) & filter_rows)

    ranked_real = sorted(real, key=_eff_size, reverse=True)
    all_themes = [
        ThemeSummary(
            name=t.label,
            share=round(_eff_size(t) / total_answered * 100, 1) if total_answered else 0.0,
            count=_eff_size(t),
            sentiment=round(t.sentiment or 0.0, 3),
        )
        for t in ranked_real
    ]

    hidden = ranked_real[7:]
    hidden_count = sum(_eff_size(t) for t in hidden)
    noise_count = _eff_size(other) if other is not None else 0
    if total_answered <= 0 or (hidden_count == 0 and noise_count == 0):
        return None, all_themes

    return OtherBreakdown(
        noise_count=noise_count,
        noise_share=round(noise_count / total_answered * 100, 1),
        hidden_real_count=hidden_count,
        hidden_real_share=round(hidden_count / total_answered * 100, 1),
        hidden_real_theme_count=len(hidden),
        total_real_theme_count=len(ranked_real),
    ), all_themes


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
    answer_texts: list[str] | None = None,
    quote_theme_texts: list[tuple[str, list[str]]] | None = None,
    answer_positions: dict[int, tuple[float, float]] | None = None,
    structured: StructuredContext | None = None,
    filter_rows: set[int] | None = None,
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
    `context` (honest generic defaults - see module docstring).

    `structured` is an optional `app.findings_structured.StructuredContext` (built by
    `app.findings_structured.build_structured_context`): when given and it has real score/segment/trend
    data, that data fills `score`/`segment`/`trend` below; otherwise (the default, `None`) they stay
    today's empty/neutral placeholders - only their shape needs to be valid so `ReportData` constructs at
    all. `cooccurrence` is always an empty placeholder regardless (only `f_arc` reads it, out of scope
    here). `pick_chart` does not yet select a chart kind that reads `score`/`segment`/`trend` (that is a
    separate, later stream), so populating them here has no visible effect on `build_findings`'s own output
    until that wiring lands.
    `answer_map` is still a placeholder - no similarity-embedding pipeline exists upstream yet.

    `phrases` is real (chart-block stream, 2026-10-24) when `answer_texts` is given - the actual cleaned
    answer strings, same "this function only has Theme rows, a caller with the dataframe already loaded
    passes the real thing through" shape as `answer_lengths` above. `app.text_pipeline.phrases.build_phrase_data`
    does the extraction (pure code, no network - see that module's own docstring). Without `answer_texts`,
    `phrases` stays the honest empty placeholder it always was.

    `quotes` is real when `quote_theme_texts` is given - each real theme's own most-typical answer(s), via
    `app.text_pipeline.quotes.build_quote_data`. `frequency` is real whenever `structured` resolved a real
    `short_text` candidate column (`app.findings_structured.build_frequency_data`, a short-answer
    column's own frequency table - distinct from the main open-ended column's theme clustering).
    `category_avg` is real whenever `structured` resolved a real short_text-category-by-number-average
    pairing (`app.findings_structured.build_category_avg_data`, chart-block stream batch 2).

    `filter_rows` (Filters feature, SPEC.md section 5) restricts `themes`/`score`/`segment`/`trend` to the
    given row-index set; `total_rows`/`quality`/`answer_lengths` stay dataset-wide regardless (they
    describe the whole upload, not a themed subset - a deliberate scope boundary, not an oversight). Theme
    counts/shares/ranking need the FILTERED total to compute correct shares, but that total is itself only
    known after filtering - so `theme_nodes` runs twice when a filter is active: once to learn the filtered
    total, once more (now that it's known) to produce correctly-shared nodes. No second code path, no
    change to the unfiltered call below.
    """
    if filter_rows is None:
        total_answered = _total_answered(themes)
        overall = _overall_sentiment(themes, total_answered)
        nodes = theme_nodes(themes, total_answered)
    else:
        nodes = theme_nodes(themes, total_answered=1, filter_rows=filter_rows)  # pass 1: learn the total
        total_answered = sum(n.count for n in nodes)
        nodes = theme_nodes(themes, total_answered, filter_rows=filter_rows)  # pass 2: correct shares
        # Same count-weighted-average-of-the-aggregate approximation `_overall_sentiment` uses, just over
        # the filtered nodes' counts (no per-row sentiment exists to recompute exactly - see
        # findings_structured.py's module-level sentiment-approximation note).
        overall = sum(n.sentiment * n.count for n in nodes) / total_answered if total_answered else 0.0

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

    score = structured.score if structured and structured.score else ScoreData(name="", bands=[])
    segment = structured.segment if structured and structured.segment else SegmentData(name="", groups=[], rows=[])
    trend = structured.trend if structured and structured.trend else TrendData(
        labels=[], series=[], sentiment=[], hover_index=0, note="",
    )
    # Every theme row passed here belongs to the one report column (callers query by column), so the
    # first row's column name is the report's - used to look up the user's saved question-type correction.
    column = themes[0].column_name if themes else None
    context = _build_context(question, overall, answer_lengths, score, segment, trend, structured,
                             kind_override=stored_question_kind(dataset, column))

    return ReportData(
        question=question, total=total_rows, answered=total_answered, overall_sentiment=round(overall, 3),
        themes=nodes, selected_theme=selected_theme, hover_theme=hover_theme,
        overview=overview,
        score=score,
        segment=segment,
        trend=trend,
        group_trend=structured.group_trend if structured and structured.group_trend else GroupTrendData(group_column="", labels=[], series=[], note=""),
        binned_grid=structured.binned_grid if structured and structured.binned_grid else BinnedGridData(row_name="", col_name="", row_labels=[], col_labels=[], cells=[]),
        cooccurrence=[],
        answer_map=_build_answer_map(nodes, answer_positions, getattr(dataset, "id", None) or 0, quote_theme_texts),
        frequency=structured.frequency if structured and structured.frequency else FreqData(question="", answered=0, items=[], highlight="", footnote=""),
        category_avg=structured.category_avg if structured and structured.category_avg else CategoryAvgData(category_name="", number_name="", overall_avg=0.0, items=[]),
        phrases=(build_phrase_data(answer_texts) if answer_texts else None) or PhraseData(phrases=[], highlight=""),
        theme_scores=structured.theme_scores if structured else None,
        quotes=(build_quote_data(quote_theme_texts) if quote_theme_texts else None) or QuoteData(quotes=[], highlight_index=0),
        quality=quality,
        context=context,
    )


def _build_overview(nodes: list[ThemeNode], overall: float, total_rows: int, total_answered: int,
                     answer_lengths: list[int] | None) -> OverviewData:
    pct_answered = round(total_answered / total_rows * 100) if total_rows else 0
    blank = max(0, total_rows - total_answered)
    real_nodes = [n for n in nodes if n.color != "other"]
    sub_theme_count = sum(len(n.children) for n in real_nodes)

    stats = [
        ("Responses", f"{total_rows:,}", ""),
        ("Answered", f"{pct_answered}%", f"({blank:,} blank, n/a or excluded)" if blank else ""),
        ("Themes", str(len(real_nodes)),
         f"({sub_theme_count} sub-themes)" if sub_theme_count else "(no sub-themes)"),
        ("Average sentiment", f"{overall:+.2f}", ""),
    ]
    if answer_lengths:
        # Headline the real median, with the most common length band as context. It used to headline the
        # band ("41+ words") and then contradict it underneath ("Typical length 57 words").
        _, typical_bin, _ = _length_bins(answer_lengths)
        median = round(statistics.median(answer_lengths))
        stats.insert(2, ("Typical length", f"{median} words", f"median; most answers {typical_bin} words"))

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


# ---------------------------------------------------------------- context_header (chart-block stream,
# 2026-10-24: ContextData used to be permanently honest-placeholder defaults - "anything else"/"neutrally"/
# "a sentence or two" regardless of the real question or data, per the module's own earlier docstring. The
# "kind" guess below is a deliberately CHEAP heuristic, not a Claude call: this block's own stated purpose
# (HANDOFF.md's "needs" text) is "shown after upload, so the user can correct what Verbatim understood" - a
# quick first guess the user is expected to fix, not a rigorous classification worth a network call or a
# new failure mode for. "framing"/"length" need no guessing at all - they are real numbers this function
# already computed (overall_sentiment, answer_lengths), just restated in words.

# Checked in this order (first match wins) - "why"/"reason" is the strongest, least ambiguous signal, so
# it goes first; "anything else" is the honest fallback when nothing matches, never a forced guess.
_KIND_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("reasons", ("why", "reason")),
    ("improvements", ("improve", "better", "suggest", "change")),
    ("experiences", ("experience", "describe", "tell us about", "happened")),
    ("opinions", ("think", "opinion", "feel about", "believe", "agree")),
    ("facts", ("what is", "what are", "how many", "how much", "list")),
]


QUESTION_KINDS = ["reasons", "improvements", "experiences", "facts", "opinions", "anything else"]


def stored_question_kind(dataset: Any, column: str | None) -> str | None:
    """The user's own correction of the question type for this dataset + column, if they made one
    (saved by `app/api_context.py` under `profile["question_kinds"][column]`). Overrides the keyword
    guess everywhere the guess is shown."""
    if not column:
        return None
    kinds = (getattr(dataset, "profile", None) or {}).get("question_kinds") or {}
    kind = kinds.get(column)
    return kind if kind in QUESTION_KINDS else None


def question_kind_for(dataset: Any, column: str) -> str:
    """What the question asks for, as used when naming themes and writing findings: the user's
    correction, else Verbatim's keyword guess."""
    return stored_question_kind(dataset, column) or _classify_question_kind(question_for(dataset, column))


def built_question_kind(dataset: Any, column: str, stored: str | None) -> str:
    """The kind a build used. Builds before 2026-10-25 sent none; they count as the guess, so only a
    user's correction marks them out of date."""
    return stored if stored in QUESTION_KINDS else _classify_question_kind(question_for(dataset, column))


def _classify_question_kind(question: str) -> str:
    q = question.lower()
    for kind, needles in _KIND_PATTERNS:
        if any(n in q for n in needles):
            return kind
    return "anything else"


def _build_context(
    question: str, overall: float, answer_lengths: list[int] | None,
    score: "ScoreData", segment: "SegmentData", trend: "TrendData",
    structured: "StructuredContext | None", kind_override: str | None = None,
) -> ContextData:
    guessed = _classify_question_kind(question)
    kind = kind_override or guessed
    framing = "positively" if overall >= 0.05 else "negatively" if overall <= -0.05 else "neutrally"
    if answer_lengths:
        median = statistics.median(answer_lengths)
        length = "a word or two" if median < 4 else "a sentence or two" if median < 25 else "a paragraph or more"
    else:
        length = "a sentence or two"  # honest fallback: no real answer-length data to go by
    # TrendData has no column-name field of its own (unlike ScoreData/SegmentData's `.name`) - the real
    # name lives on `structured.trend_column_name` instead.
    trend_name = structured.trend_column_name if structured else ""
    present = [n for n, has in (
        (score.name, bool(score.bands)), (segment.name, bool(segment.groups)), (trend_name, bool(trend.labels)),
    ) if has and n]
    columns_note = (
        f"{', '.join(present)} also cross-cut this report." if present
        else "No score, segment or date column was found to cross-cut this report."
    )
    return ContextData(
        kind=kind, kind_options=list(QUESTION_KINDS),
        kind_hover=kind, framing=framing, length=length, columns_note=columns_note,
        guessed_kind=guessed, corrected=kind != guessed,
    )


def _build_answer_map(
    nodes: list[ThemeNode], answer_positions: dict[int, tuple[float, float]] | None, seed: int,
    quote_theme_texts: list[tuple[str, list[str]]] | None,
) -> MapData:
    """`answer_map` (chart-block stream, 2026-10-24, batch 4): groups the real sampled positions
    (`app.api_themes._sample_answer_positions`, stored on `Column.answer_positions`) by which REAL theme
    each sampled row belongs to - "Other" excluded, same reasoning `quotes`' own theme grouping already
    documents (a point inside "Other" would misleadingly imply it belongs to one real idea). `tip_text`/
    `tip_note` reuse whichever real text `quote_theme_texts` already picked out (no new per-row text
    plumbing needed for one cosmetic tooltip example) - honest placeholders when neither is available."""
    points_by_theme: dict[str, list[tuple[float, float]]] = {}
    if answer_positions:
        for node in nodes:
            if node.color == "other":
                continue
            pts = [answer_positions[r] for r in node.answer_refs if r in answer_positions]
            if pts:
                points_by_theme[node.name] = pts
    tip_text, tip_note = "", ""
    if quote_theme_texts:
        name, texts = quote_theme_texts[0]
        if texts:
            tip_text, tip_note = texts[0], name
    return MapData(seed=seed, tip_text=tip_text, tip_note=tip_note, points_by_theme=points_by_theme)


# ==================================================================== 2. candidate_findings

def candidate_findings(
    themes: list[Theme], min_group_size: int | None = None, structured: StructuredContext | None = None,
) -> list[Candidate]:
    """Computes candidate findings from stored `Theme` rows (SPEC.md section 9.3).

    Five kinds total now - see the module docstring's history for why only two existed before this stream:
      - **tone contrast**: a theme whose sentiment differs notably (either direction) from the dataset's
        overall (answer-count-weighted) sentiment.
      - **dominant/rare theme**: the largest real theme, if it clearly leads (a "clear #1"), or the
        "Other"/long-tail group, if it is unusually large (a data-quality signal as much as a finding).
      - **segment skew** (`structured.segment`, SPEC 9.3 "a theme raised more by one group"), **score
        correlation** (`structured.score`, "a number that moves with sentiment or score") and **trend
        shift** (`structured.trend`, "a trend over time") - each only computed when `structured` is given
        and has real data for that column; see `app/findings_structured.py`'s own B3 section for their
        gate/solid thresholds and scoring.

    Every candidate must clear `min_group_size` (defaults to `app.cleaning.suppression.min_group_size()`,
    this codebase's existing convention for "too small a group to report on" - reused rather than a second
    constant) before it is even considered, and must additionally clear a kind-specific effect-size gate
    (`TONE_GAP_MIN`/`DOMINANT_SHARE_MIN`+`DOMINANT_MARGIN_MIN`/`LONGTAIL_SHARE_MIN`, or the new kinds' own
    gates in `app/findings_structured.py`) to become a Candidate at all. `score`'s shape differs by kind,
    on purpose: `tone_contrast` blends its -1..+1 effect size with a diminishing size bonus, while
    `dominant_theme`/`long_tail` score on a bare percentage point with no bonus at all - the 3 new kinds
    match `dominant_theme`/`long_tail`'s bare-percentage-point shape exactly (not `tone_contrast`'s), so
    those 4 kinds compete on the same scale in one ranked pool; `tone_contrast`'s own pre-existing mismatch
    with the other 4 is left as documented, known debt, not fixed here - see docs/DECISIONS.md.

    `structured=None` (the default, and passing it explicitly) is byte-identical to today's behaviour: no
    new candidates are computed, existing callers are unaffected.

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

    # --- score/segment/date-driven kinds (B3): appended to the SAME pool above, not a parallel mechanism -
    # only computed for whichever of structured.segment/.score/.trend actually has real data.
    if structured is not None:
        if structured.segment is not None:
            candidates.extend(segment_skew_candidates(structured.segment, themes, floor))
        if structured.score is not None:
            candidates.extend(score_correlation_candidates(structured.score, themes, floor))
        if structured.trend is not None:
            candidates.extend(trend_shift_candidates(
                structured.trend, themes, floor, structured.trend_column_name,
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:MAX_CANDIDATES]


# ==================================================================== 3. label_confidence

def label_confidence(candidate: Candidate) -> str:
    """"Solid" or "Tentative" (SPEC.md section 9.3/6). A simple, documented threshold on group size
    (`SOLID_COUNT_MULTIPLIER` times the suppression floor) AND a kind-specific effect-size threshold -
    both are named constants (the 3 newest ones in `app/findings_structured.py`, imported above), easy to
    retune; SPEC.md gives no exact numbers for this, only "label uncertain ones Tentative".

    `candidate.count` already carries the exact answer count each new kind's own "Solid" rule (in
    `app/findings_structured.py`'s B3 section) needs checked against the floor - the group's `n` for
    `segment_skew`, the smaller of the two extreme bands' `answers` for `score_correlation`, the theme's
    own `size` for `trend_shift` - so the group-size check above already applies correctly to all 5 kinds
    without any kind-specific branching for it."""
    floor = _suppression_min_group_size()
    if candidate.count < floor * SOLID_COUNT_MULTIPLIER:
        return "tentative"
    if candidate.kind == "tone_contrast":
        return "solid" if abs(candidate.numbers["gap"]) >= TONE_GAP_SOLID else "tentative"
    if candidate.kind == "dominant_theme":
        return "solid" if candidate.numbers["share_pct"] >= DOMINANT_SHARE_SOLID else "tentative"
    if candidate.kind == "long_tail":
        return "solid" if candidate.numbers["share_pct"] >= LONGTAIL_SHARE_SOLID else "tentative"
    if candidate.kind == "segment_skew":
        ratio = candidate.numbers["ratio"]
        return "solid" if (ratio >= SEGMENT_SKEW_RATIO_SOLID or ratio <= 1 / SEGMENT_SKEW_RATIO_SOLID) else "tentative"
    if candidate.kind == "score_correlation":
        return "solid" if candidate.numbers["spread_pct"] >= SCORE_SPREAD_SOLID else "tentative"
    if candidate.kind == "trend_shift":
        return "solid" if abs(candidate.numbers["change_pct"]) >= TREND_SHIFT_SOLID else "tentative"
    return "tentative"  # pragma: no cover - defensive: every real kind is handled above


# ==================================================================== 4. pick_chart

def pick_chart(candidate: Candidate, report_data: "ReportData | None" = None) -> str:
    """Maps a finding kind to one of this stream's wired-up chart ids, per SPEC.md section 4's priority
    table - `CHART_BY_KIND` for the simple one-kind-one-chart cases, plus real skip-condition swaps this
    stream wires for real (Stage 3, then Stage 4):

    - `long_tail` renders `sunburst` instead of the table-default `treemap` once real sub-themes reach
      `SUB_THEME_SUNBURST_MIN` (SPEC's own "skip when fewer than 3 sub-themes, use treemap" - applied the
      other way around: treemap is the one-time default, sunburst is what SPEC actually wants once there
      is enough sub-theme detail to justify an extra ring).
    - `tone_contrast` renders `diverge` instead of the table-default `sentsun` once real tone spread drops
      under `TONE_SPREAD_SENTSUN_MIN` (SPEC's own "sentiment spread under 0.05" skip condition - sentsun's
      inner/outer ring split has nothing to show when every theme reads about the same, so this swaps to
      Diverge, SPEC's own documented alternate for "reasons with neutral or positive framing", rather than
      rendering a flat, uninformative sun).
    - `trend_shift` renders `themeMixOverTime` instead of the table-default `trend` once a real report has
      `THEME_MIX_OVER_TIME_MIN_THEMES` or more real themes (matching `theme_mix_over_time`'s own registry
      `needs()`, `app/report_blocks.py` b44 - a single combined line chart undersells a trend with several
      real themes moving; the stacked-share view shows the whole mix shifting, not just one line). This is
      rung 3 of Stage 4's planned gate ladder (`trend_sparse` > `trend_small_multiples` >
      `theme_mix_over_time` > `trend`) - the top two rungs are follow-up work, not wired yet (see
      `docs/DECISIONS.md`'s Stage 4 entry for why).

    `report_data` is `None` for a caller with no `ReportData` yet available (kept optional, not required,
    so a direct/legacy call site still gets each kind's table-documented default) - every real call site in
    `build_findings` below passes the real one, since it is already computed before `pick_chart` is ever
    called there."""
    chart = CHART_BY_KIND[candidate.kind]
    if report_data is None:
        return chart
    if candidate.kind == "long_tail" and sub_theme_total(report_data) >= SUB_THEME_SUNBURST_MIN:
        return "sunburst"
    if candidate.kind == "tone_contrast" and max_tone_spread(report_data) < TONE_SPREAD_SENTSUN_MIN:
        return "diverge"
    if candidate.kind == "trend_shift":
        real_theme_count = sum(1 for t in report_data.themes if t.color != "other")
        if real_theme_count >= THEME_MIX_OVER_TIME_MIN_THEMES:
            return "themeMixOverTime"
    return chart


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
# Added when the question type is known: "the most common reason", not "the most common topic".
HEADLINE_KIND_SYSTEM = (
    ' If you are given "question_asks_for", the question asks people for that kind of answer (e.g. '
    '"reasons", "improvements", "facts"): describe the themes as that kind of thing.'
)


def _build_headline_prompt(candidates: list[Candidate], question: str, question_kind: str | None = None) -> str:
    payload = {
        "survey_question": question,
        **kind_payload(question_kind),
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


def write_headline(candidates: list[Candidate], client: ClaudeClient, question: str,
                   question_kind: str | None = None) -> dict[str, str]:
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
    prompt = _build_headline_prompt(candidates, question, question_kind)
    raw = client.complete(HEADLINE_SYSTEM + HEADLINE_KIND_SYSTEM if kind_payload(question_kind) else HEADLINE_SYSTEM, prompt)
    return _parse_headlines(raw, expected_ids)


# ==================================================================== 6. build_findings

def question_for(dataset: Dataset, column: str) -> str:
    """Same question-resolution order `app/api_themes.py`'s `build_themes` route already uses. Public
    (no leading underscore) because `app.api_themes.themes_chart` reuses it too, for the same "confirmed
    question, else profiled question, else the raw column name" fallback - not re-derived a second time."""
    confirmed = (dataset.profile or {}).get("confirmed") or {}
    question = (confirmed.get("question") or "").strip()
    if question:
        return question
    return ((dataset.profile or {}).get("question") or {}).get("text") or column


def themes_signature(themes: list[Theme]) -> list[list]:
    """What the findings were written from: each theme's id, size and label. A report whose stored
    signature differs from the live themes is stale - Look inside Other, for one, grows known themes and
    adds new ones without deleting any, so checking for findings about deleted themes alone misses it."""
    return sorted([t.id, t.size, t.label] for t in themes)


def build_findings(
    dataset: Dataset,
    column: str,
    db_session: Session,
    claude_client: ClaudeClient,
    cleaning_report: Any = None,
    answer_lengths: list[int] | None = None,
    answer_texts: list[str] | None = None,
    quote_theme_texts: list[tuple[str, list[str]]] | None = None,
    answer_positions: dict[int, tuple[float, float]] | None = None,
    min_group_size: int | None = None,
    structured: StructuredContext | None = None,
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

    `structured` is an optional `app.findings_structured.StructuredContext` (see `build_report_data`'s own
    docstring): when given, it is threaded into both `candidate_findings` (the 3 new score/segment/date
    finding kinds) and `build_report_data` (the `byScore`/`heatmap`/`trend` chart data), from the SAME
    `StructuredContext` instance - never rebuilt twice for one report.

    Raises `NoThemesForColumn` if no themes are stored yet for this dataset + column.
    """
    themes = list(db_session.scalars(
        select(Theme).where(Theme.dataset_id == dataset.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    if not themes:
        raise NoThemesForColumn(f"No stored themes for dataset {dataset.id}, column {column!r}. Build themes first.")

    question = question_for(dataset, column)
    kind = question_kind_for(dataset, column)
    candidates = candidate_findings(themes, min_group_size=min_group_size, structured=structured)
    sentences = write_headline(candidates, claude_client, question, kind)
    report_data = build_report_data(
        dataset, themes, cleaning_report, question, answer_lengths=answer_lengths,
        answer_texts=answer_texts, quote_theme_texts=quote_theme_texts,
        answer_positions=answer_positions, structured=structured,
    )

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
            chart_type=pick_chart(cand, report_data), confidence=label_confidence(cand),
            data={**cand.numbers, "column": column, "kind": cand.kind},
        ))
    db_session.add_all(new_findings)
    db_session.flush()  # assigns Finding.id before it is referenced in blocks below

    blocks: list[dict[str, Any]] = [{"kind": "overview", "chart_id": "overview", "priority": 1, "finding_id": None}]
    # "context" (chart-block stream, 2026-10-24, wiring batch A): always-on, not a competing finding - the
    # question-kind classification is real and available whenever there is a question at all
    # (app.report_blocks.BY_SLUG["context_header"].needs), so it is shown unconditionally right after the
    # overview, same chapter position ("1") the design itself gives it.
    if report_data.context.kind:
        blocks.append({"kind": "context", "chart_id": "context", "priority": 1, "finding_id": None})
    for cand, finding in zip(ordered, new_findings):
        blocks.append({
            "kind": "finding", "chart_id": pick_chart(cand, report_data), "priority": PRIORITY_BY_KIND[cand.kind],
            "finding_id": finding.id,
        })
    # "quotes"/"phrases" (wiring batch A): also always-on, shown after the competing findings but before
    # the quality footer - matching the design's own chapter 6 position for both (app.report_blocks.BLOCKS'
    # b16/b47). Each needs its own real upstream data (quote_theme_texts/answer_texts) to have anything to
    # show - app/api_report.py already computes both for every real report, so this is never empty by
    # construction once a report has any themes at all; still checked here rather than assumed, since a
    # caller with neither wired (e.g. a test building report_data directly) must not get an empty chart.
    if report_data.quotes.quotes:
        blocks.append({"kind": "quotes", "chart_id": "quotes", "priority": 7, "finding_id": None})
    if report_data.phrases.phrases:
        blocks.append({"kind": "phrases", "chart_id": "phrases", "priority": 7, "finding_id": None})
    blocks.append({"kind": "quality", "chart_id": "quality", "priority": 9, "finding_id": None})

    report = Report(dataset_id=dataset.id, content={
        "column": column, "question": question, "blocks": blocks,
        "also_checked_nothing_notable": len(candidates) == 0,
        "themes_signature": themes_signature(themes),
        "question_kind": kind,
    })
    db_session.add(report)
    db_session.commit()
    return report
