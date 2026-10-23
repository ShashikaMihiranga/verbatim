"""The report's full block registry (docs/DECISIONS.md, 2026-10-24 stream): every chart/block this app's
own design system (`verbatim-visual-system/HANDOFF.md` section 3, `generator/gen_blocklib.py`'s `BL`
table) has designed for the dynamic report, ported here as real, testable data instead of a design-only
markdown table. This is Stage 1 of that stream's plan - data + a real `needs(report_data) -> bool`
predicate per block, no selection/scoring logic yet (that is `score_block`/`select_blocks`, Stage 2 -
app/findings.py's `pick_chart`/`candidate_findings`/`build_findings` keep running exactly as before until
that stage lands).

Every block id/slug/chapter/example sentence below is copied verbatim from `gen_blocklib.py`'s `BL` list
(the design's own stated source of truth, HANDOFF.md section 8: "these Python files, not the `.dc.html`
outputs, are the canonical structured data"). The "needs" column there is prose; `needs()` here is the
same requirement made runnable against this app's real `ReportData` (app/chart_data.py) - not a new
design decision, a translation of one already made.

`chart_id` is NOT in the design's own `BL` table (the design implies a chart from each block's own name/
slug, drawn by hand per block in the `.dc.html` boards) - it is this port's own addition, naming which
`app/charts.py:FRAMES` renderer (if any exists yet) actually draws this block, so later stages have a real
dispatch target instead of another prose column to re-interpret. `None` means no renderer exists yet
(a later stage's job, or - for `co_mentions` - never will).

Several blocks' prose "needs" describe a data shape this app does not build yet (a second-column
frequency table, real similarity-map coordinates, phrase extraction, geographic data, per-period answer
counts, numeric-column binning). Their `needs()` is `lambda data: False` with a comment naming the exact
missing pipeline - an honest "not yet wired" marker a later stage closes, never a silent gap. One block
(`co_mentions`, the arc/co-occurrence chart) is `False` for a different reason: this pipeline's clustering
is a hard partition (one theme per answer by construction), so there is no real co-occurrence signal to
compute regardless of future work - see DECISIONS 2026-10-21, confirmed again in this stream's own plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .chart_data import ReportData

OTHER_COLOR = "other"


def _real_themes(data: ReportData) -> list:
    """`ReportData.themes` nodes use the `"other"` colour token for the one merged bucket (noise plus any
    real theme past the top 7) - same convention `app/charts.py`'s own `rows()`/`treemap_rows` and
    `app/findings.py`'s `_theme_color` already use. "Real themes" excludes that one merged node, matching
    what `candidate_findings`'s own `real = [t for t in themes if t.label != OTHER_LABEL]` means for a
    `Theme` row - the `ThemeNode` equivalent."""
    return [t for t in data.themes if t.color != OTHER_COLOR]


def _other_node(data: ReportData):
    return next((t for t in data.themes if t.color == OTHER_COLOR), None)


def _sub_theme_total(data: ReportData) -> int:
    return sum(len(t.children) for t in data.themes)


def _max_tone_spread(data: ReportData) -> float:
    """Widest negative/positive split on any one real theme, 0..1 - the same shape of signal `tone_contrast`
    candidates gate on (`app/findings.py:TONE_GAP_MIN`), reused here as a data-availability check, not a
    second copy of that scoring logic."""
    spreads = [abs(t.tones.pos - t.tones.neg) / 100 for t in _real_themes(data)]
    return max(spreads, default=0.0)


Needs = Callable[[ReportData], bool]


@dataclass(frozen=True)
class Block:
    id: str  # design id, e.g. "b03" - stable across renames, matches gen_blocklib.py's BL table exactly
    slug: str  # short name, e.g. "theme_map" - used as a dict key elsewhere
    chapter: str  # "1".."7", gen_blocklib.py's CH chapter table
    name: str  # display name, e.g. "Theme map"
    chart_id: str | None  # app/charts.py:FRAMES key this block renders with, or None - see module docstring
    example: str  # example headline sentence, verbatim from the design
    needs_text: str  # the design's own prose "needs" column, kept for the "left_out" reason surface
    needs: Needs  # the same requirement, made runnable against a real ReportData


# `needs_text`/`example` are copied verbatim from `gen_blocklib.py`'s `BL` table
# (generator/gen_blocklib.py:20-66). Order matches that table's own id order (b01, b03..b47 - there is no
# b02 in the source).
BLOCKS: list[Block] = [
    Block(
        "b01", "frame", "1", "Title and columns used", None,
        "The question is the title. Chips show every column the report used.",
        "Any file.",
        lambda data: True,
    ),
    Block(
        "b03", "theme_map", "2", "Theme map", "treemap",
        "Cost and Charging make up more than half of the reasons.",
        "Open-ended text with 3 or more themes. Treemap when sub-themes are many, sunburst when they are few.",
        lambda data: len(_real_themes(data)) >= 3,
    ),
    Block(
        "b04", "ranked_answers", "2", "Ranked answers", None,
        "Teacher and Nurse are the most common jobs, at nearly one answer in six.",
        "Short factual answers, merged for spelling and plurals.",
        # Needs a second, SHORT-ANSWER column's own frequency table (ReportData.frequency/FreqData) - that
        # column is never populated for real data today (app/chart_data.py's own placeholder comment);
        # this is a genuinely separate pipeline from the open-text themes list, not a missing wiring step.
        lambda data: False,
    ),
    Block(
        "b05", "summary", "2", "Summary numbers and one bar", "overview",
        "12,480 answers fell into 5 clear themes, and the mood is mostly negative.",
        "Any text column.",
        lambda data: data.answered > 0,
    ),
    Block(
        "b06", "long_tail", "2", "Long tail", None,
        "41% of the distinct answers were given only once.",
        "Short answers with many one-off variants.",
        # Approximated from the merged "other" node's share (the same signal `long_tail`'s own candidate
        # gate in app/findings.py reads from the stored Theme rows) - ReportData has no distinct-answer
        # count of its own to check the design's literal wording against. No dedicated renderer: this is
        # a footnote stat (FreqData.footnote), not its own chart, in both the design and this app today.
        lambda data: (n := _other_node(data)) is not None and n.share >= 15,
    ),
    Block(
        "b07", "inside_other", "2", "Inside Other", None,
        "Most answers sit in Other, so the themes are only part of the story.",
        "Other holding more than 30% of answers.",
        # Real in this app as a bespoke section (LookInsideOther.tsx/app/api_themes.py's look_inside_other),
        # not a render_parts/FRAMES chart - no chart_id to give it here.
        lambda data: (n := _other_node(data)) is not None and n.share > 30,
    ),
    Block(
        "b08", "rank_by_tone", "3", "Rank, tinted by tone", "rank",
        "Delivery speed is the first thing to fix, and it sounds the most negative.",
        "An improvements or barriers question.",
        # The design's "an improvements/barriers question" clause describes QUESTION INTENT, which this
        # app has no real classifier for yet (ReportData.context is always honest placeholder defaults -
        # see chart_data.py and CLAUDE.md task 5, "question context" not built). Only the DATA-SHAPE half
        # of this block's requirement (real themes exist to rank) is checked here.
        lambda data: len(_real_themes(data)) >= 1,
    ),
    Block(
        "b09", "sentiment_sun", "3", "Sentiment sun", "sentsun",
        "Delivery speed carries the most negative wording, -0.31 against -0.19 overall.",
        "Framing that is not neutral, or a tone spread above 0.05.",
        lambda data: _max_tone_spread(data) > 0.05,
    ),
    Block(
        "b10", "group_heatmap", "4", "Themes by group", "heatmap",
        'Age group "65+" mentions Not needed 2.6 times as often as the average respondent.',
        "A group column (age, plan, region) with at least 100 answers per group.",
        lambda data: bool(data.segment.groups) and all(g.n >= 100 for g in data.segment.groups),
    ),
    Block(
        "b11", "band_bars", "4", "Bars by number band", "byScore",
        "Lower-income households name Cost more. Higher-income households name Charging more.",
        "A number column (income, age) banded into groups.",
        # Found while building this (not a Stage 1 oversight corrected later): `build_numeric_data`
        # (app/findings_structured.py:472-487) is NOT an orphaned, unwired function - it already feeds
        # `StructuredContext.score`/`ReportData.score` as the fallback used when a dataset has a numeric
        # column (age, income) but no real score-scale column (app/findings_structured.py:726-748), and
        # is explicitly documented there as "rendered via the same f_byscore chart score-kind columns
        # already use - no new chart type needed." So this block's data AND renderer already exist; the
        # only gap was this registry not knowing it yet. `ReportData` has no field distinguishing "score"
        # from "numeric fallback" though (both just populate `data.score`), so this predicate is honestly
        # identical to score_groups' (b12) at this data shape - a real, documented limit, not a new bug.
        lambda data: bool(data.score.bands),
    ),
    Block(
        "b12", "score_groups", "4", "Score groups", "byScore",
        "People less likely to buy talk far more about Not needed.",
        "A score column (0-10 or 1-5) and 3 or more themes.",
        lambda data: bool(data.score.bands) and len(_real_themes(data)) >= 3,
    ),
    Block(
        "b13", "vs_average", "4", "Compared with average", None,
        "Software engineers and managers earn well above average.",
        "A number column plus short-text categories.",
        # Same missing short-answer-column pipeline as b04/ranked_answers.
        lambda data: False,
    ),
    Block(
        "b14", "tone_by_number", "4", "Tone by number band", None,
        "The more customers spend, the more negative they sound.",
        "A number column and sentiment scores.",
        # No number-column-by-sentiment cross-tab exists in ReportData today (ScoreData is explicitly a
        # 0-10/1-5 SCORE column, not an arbitrary number column like spend or age).
        lambda data: False,
    ),
    Block(
        "b15", "trend", "5", "Over time", "trend",
        "Cost is rising through the year while Charging is fading.",
        "A date column with 3 or more periods and 30 or more answers per period.",
        # The per-period >=30-answers floor is already enforced upstream, as a data-survival gate, before
        # TrendData is ever populated (app/findings_structured.py's trend cross-tab builder) - so "labels
        # exist at all" is already an honest proxy for "every period that exists cleared the floor."
        lambda data: bool(data.trend.labels) and len(data.trend.labels) >= 3,
    ),
    Block(
        "b16", "quotes", "6", "Quotes", None,
        "Deliveries keep arriving a day late.",
        "Open-ended text.",
        # Real verbatim quotes DO exist in this app (the "See answers" drill-down, a separate endpoint -
        # app/api_themes.py's theme_answers), just never through ReportData.quotes, which stays an honest
        # empty placeholder (chart_data.py's own comment). Not wired to THIS registry's data model yet.
        lambda data: False,
    ),
    Block(
        "b17", "also_checked", "7", "Also checked", None,
        "Also checked, nothing notable: Sex, Region.",
        "Any column that was used but showed nothing.",
        # This is always computed and shown today (Report.tsx's "Also checked, nothing notable" line,
        # app/api_report.py's also_checked_nothing_notable) - genuinely always available, not conditional
        # on report_data's own shape.
        lambda data: True,
    ),
    Block(
        "b18", "quality", "7", "Trust and data quality", "quality",
        "95% answered, and answers run about eight words.",
        "Always, last.",
        lambda data: True,
    ),
    Block(
        "b19", "see_more", "7", "See more charts", None,
        "A closed area that holds extra charts, so the main report stays short.",
        "Charts that did not make the cut.",
        # Needs a real notion of "left out charts," which only exists once select_blocks (Stage 2) produces
        # a real left_out list to hold something.
        lambda data: False,
    ),
    Block(
        "b20", "trend_groups", "5", "Over time, by group", None,
        "Business customers are getting more negative while the others hold steady.",
        "A date column and a group column with 2 to 5 groups of 100 or more answers each.",
        # TrendData has per-THEME series, not per-GROUP series - this needs a trend-by-segment cross-tab
        # this app does not build yet.
        lambda data: False,
    ),
    Block(
        "b21", "trend_band", "5", "Over time, with its range", "trend",
        "Average sentiment is steady, and the range around it is narrow.",
        "A date column and sentiment scores, with 30 or more answers per period.",
        # TrendData.sentiment is already a real per-period list, already rendered by f_trend - this
        # block's data requirement is already fully met wherever b15/trend's own is.
        lambda data: bool(data.trend.labels) and len(data.trend.labels) >= 3,
    ),
    Block(
        "b22", "trend_styled", "5", "Over time, by dash and marker", None,
        "The same group lines, told apart by dash and marker, so they still read in greyscale.",
        "As Over time by group, for print, PDF export or colour-blind readers.",
        # A print/accessibility variant of trend_groups (b20) - same missing per-group trend data.
        lambda data: False,
    ),
    Block(
        "b23", "trend_small_multiples", "5", "Over time, one panel per theme", None,
        "Cost and Charging move. The other four stay flat.",
        "A date column and more than 4 themes, where one chart would tangle.",
        lambda data: bool(data.trend.labels) and len(data.trend.labels) >= 3 and len(_real_themes(data)) > 4,
    ),
    Block(
        "b24", "trend_grid", "5", "Over time, themes by group", None,
        "Cost rises for Business customers only.",
        "A date column, a group column and 2 or 3 leading themes.",
        # Needs trend-by-segment AND by-theme at once - same missing cross-tab as b20, one dimension further.
        lambda data: False,
    ),
    Block(
        "b25", "trend_aggregated", "5", "Over time, daily to weekly", None,
        "Cost is climbing, once the daily swings are averaged out.",
        "A date column with many answers per day or per week.",
        # Needs the RAW per-day period granularity before any aggregation choice - TrendData only ever
        # carries the already-aggregated periods a prior step chose.
        lambda data: False,
    ),
    Block(
        "b26", "trend_errorbars", "5", "Over time, with error bars", None,
        "Sentiment improved wave on wave, and the gains are bigger than the uncertainty.",
        "A date or wave column with 3 to 6 periods.",
        # Needs a real uncertainty/variance figure per period - not computed anywhere today (only a point
        # sentiment average per period exists).
        lambda data: False,
    ),
    Block(
        "b27", "context_header", "1", "Context header", None,
        "This looks like a reasons question, answered negatively, in a sentence or two.",
        "Any file. Shown after upload, so the user can correct what Verbatim understood.",
        # ContextData is always honest placeholder defaults - no real question-kind classifier exists yet
        # (CLAUDE.md task 5, "question context" explicitly not built). chart_id would be "context", but
        # that frame is gallery-only (never fed real data) until this predicate can ever be True.
        lambda data: False,
    ),
    Block(
        "b28", "theme_hierarchy", "2", "Themes and sub-themes, sunburst", "sunburst",
        "Cost splits into upfront price, battery cost and insurance.",
        "Themes with 3 or more sub-themes in total. Desktop.",
        lambda data: _sub_theme_total(data) >= 3,
    ),
    Block(
        "b29", "theme_hierarchy_compact", "2", "Themes and sub-themes, icicle", "icicle",
        "Themes on a top row, with their sub-themes beneath.",
        "As the sunburst, on phones or when the sunburst has too many arcs.",
        lambda data: _sub_theme_total(data) >= 3,
    ),
    Block(
        "b30", "theme_similarity", "2", "Theme similarity map", "bubbles",
        "Cost and Not needed are talked about in similar words.",
        "3 or more themes, and no answer map.",
        # ThemeNode.map_xy is never populated for real data (chart_data.py's own comment: "None scatters
        # the theme") - no similarity-embedding step exists upstream.
        lambda data: False,
    ),
    Block(
        "b31", "answer_map", "2", "Answer map", "map",
        "Charging answers form two separate clusters.",
        "More than 500 answers.",
        # MapData is always placeholder (seed=0, no real tip text) - no 2D answer-embedding pipeline exists.
        lambda data: False,
    ),
    Block(
        "b32", "ranked_list", "2", "Ranked list", None,
        "The most common answers, after merging spelling variants.",
        "Short factual answers.",
        lambda data: False,  # same missing frequency pipeline as b04
    ),
    Block(
        "b33", "tone_split", "3", "Tone split by theme", "diverge",
        "Delivery speed is 56% negative, Pricing 40%.",
        "Any text column with sentiment scores.",
        # Data requirement is trivially met wherever any real theme exists - every ThemeNode already
        # carries real tones. The renderer (f_diverge, already built, currently unwired to any finding) is
        # Stage 4 work; this predicate only says the DATA is ready.
        lambda data: len(_real_themes(data)) >= 1,
    ),
    Block(
        "b34", "tone_mekko", "3", "Share and tone together, Marimekko", "mekko",
        "Delivery speed is the widest column and the most negative.",
        "3 or more themes, and non-neutral framing or a wide tone spread.",
        lambda data: len(_real_themes(data)) >= 3 and _max_tone_spread(data) > 0.05,
    ),
    Block(
        "b35", "co_mentions", "3", "Themes mentioned together, arc", "arc",
        "Cost and Charging are often raised in the same answer.",
        "4 or more themes, with co-mentions above 5% of answers.",
        # Permanently excluded, not merely unwired: this pipeline's clustering is a hard partition (one
        # theme per answer by construction - app/text_pipeline), so ReportData.cooccurrence has no real
        # signal to compute from, now or later. See DECISIONS 2026-10-21 and this stream's own plan.
        lambda data: False,
    ),
    Block(
        "b36", "theme_flow", "4", "Score group to theme to tone, Sankey", "sankey",
        "Most low scorers talk about Not needed, and sound negative.",
        "A score or group column and 3 or more themes.",
        lambda data: (bool(data.score.bands) or bool(data.segment.groups)) and len(_real_themes(data)) >= 3,
    ),
    Block(
        "b37", "score_mix", "4", "What each score group talks about", "byScore",
        "Low scorers give Not needed three times the share that high scorers do.",
        "A score column and 3 or more themes.",
        lambda data: bool(data.score.bands) and len(_real_themes(data)) >= 3,
    ),
    Block(
        "b38", "number_spread", "4", "How a number is spread", "byScore",
        "Half of respondents are aged 35 to 54, and few are under 25.",
        "A number column such as age, income or spend.",
        # Same already-wired numeric/byScore data as b11/band_bars - see that block's own comment.
        lambda data: bool(data.score.bands),
    ),
    Block(
        "b39", "group_split_bars", "4", "Two groups side by side", "groupSplitBars",
        "Women name Charging more. Men name Cost more.",
        "A two-value column such as sex or yes/no.",
        lambda data: len(data.segment.groups) == 2,
    ),
    Block(
        "b40", "compare_dots", "4", "Many groups, little space", "compareDots",
        "North is 41% against 26% overall. London is 18%.",
        "A group column with 8 to 20 values.",
        lambda data: 8 <= len(data.segment.groups) <= 20,
    ),
    Block(
        "b41", "binned_grid", "4", "Two numbers together", None,
        "Higher spenders are far less likely to sound neutral.",
        "Two number columns, or a number and a score.",
        # Needs two independent numeric columns cross-tabbed - not built (ScoreData is one score column only).
        lambda data: False,
    ),
    Block(
        "b42", "region_map", "4", "Where answers come from", None,
        "Delivery complaints cluster in the north.",
        "A region or location column.",
        # Needs real geographic data this app has no column-kind for today, and a real choropleth renderer
        # (not the same chart as b31/answer_map's similarity scatter) - same "pipeline doesn't exist yet"
        # class as answer_map, not a permanent exclusion like co_mentions.
        lambda data: False,
    ),
    Block(
        "b43", "trend_share_tone", "5", "Theme share and tone by month", "trend",
        "Cost is rising through the year while the mood around it falls.",
        "A date column, 3 or more periods, and 30 or more answers per period.",
        lambda data: bool(data.trend.labels) and len(data.trend.labels) >= 3,
    ),
    Block(
        "b44", "theme_mix_over_time", "5", "Theme mix over time", None,
        "Charging fell from 33% to 22% of answers while Cost grew.",
        "A date column with 3 or more periods and 3 or more themes.",
        lambda data: bool(data.trend.labels) and len(data.trend.labels) >= 3 and len(_real_themes(data)) >= 3,
    ),
    Block(
        "b45", "trend_sparse", "5", "Over time, when data has gaps", None,
        "Only 5 of 12 months have enough answers to show.",
        "A date column where some periods have under 30 answers.",
        # Needs a real per-period answer COUNT to detect "under 30" - TrendData carries share/sentiment per
        # period, never a count, so a gap can't be detected from this shape today.
        lambda data: False,
    ),
    Block(
        "b46", "slope_change", "5", "First against last", "slopeChange",
        "Cost: 26% in January, 34% in December.",
        "Two periods, or the first and last of many.",
        lambda data: bool(data.trend.labels) and len(data.trend.labels) >= 2,
    ),
    Block(
        "b47", "top_phrases", "6", "Recurring phrases", "phrases",
        '"No home charger" is the phrase that comes up most, and it sounds negative.',
        "Open-ended text.",
        # Real (chart-block stream, 2026-10-24): app/text_pipeline/phrases.py extracts real recurring
        # phrases from real answer text, threaded through build_report_data's new answer_texts param.
        # Renderer is f_phrases - an explicit, approved exception to CLAUDE.md's "no word cloud" rule
        # (user decision, 2026-10-24, recorded in CLAUDE.md itself).
        lambda data: bool(data.phrases.phrases),
    ),
]

BY_ID: dict[str, Block] = {b.id: b for b in BLOCKS}
BY_SLUG: dict[str, Block] = {b.slug: b for b in BLOCKS}
