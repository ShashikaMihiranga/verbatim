"""Typed data objects that every chart in app/charts.py renders from.

Shares are percentages of answered responses (0-100). Sentiment is on a -1..+1 scale.
Colour fields are CSS token names ("t1".."t7", "other"), never hex values.
"""
from dataclasses import dataclass, field
from typing import NamedTuple, Optional


class ToneSplit(NamedTuple):
    neg: float  # % of the theme's answers with negative wording
    neu: float  # % neutral
    pos: float  # % positive


@dataclass
class SubTheme:
    name: str  # sub-theme label
    share: float  # % of all answered (not of the parent theme)


@dataclass
class ThemeNode:
    name: str  # theme label
    share: float  # % of answered responses
    sentiment: float  # average sentiment of the theme's answers
    count: int  # number of answers in the theme
    color: str  # theme colour token: "t1".."t7" or "other"
    tones: ToneSplit  # negative / neutral / positive split of this theme
    children: list[SubTheme] = field(default_factory=list)  # sub-themes (first 3 get distinct tints)
    map_xy: Optional[tuple[float, float]] = None  # 0..1 position on the similarity map; None scatters the theme
    callout: Optional[tuple[float, float, list[str]]] = None  # sunburst label for a thin wedge: (x, y, lines)
    note: str = ""  # explanation shown next to a folded-in "Other" theme
    answer_refs: list[int] = field(default_factory=list)  # cleaned-dataframe row indices behind this node
    theme_id: Optional[int] = None  # the single Theme.id this node came from; None for a merged bucket


@dataclass
class ThemeSummary:
    """One row of the report's "see all themes" list (docs/TODO.md, 2026-10-21 Phase 1) - every real
    theme, not just the top 7 `ThemeNode`s a chart can render its own colour for. Deliberately a
    separate, smaller shape from `ThemeNode`: this never needs a colour token, children, or map/callout
    positioning - it only ever feeds a plain ranked list, tone-coloured by `sentiment`, not identity."""
    name: str  # theme label
    share: float  # % of answered responses
    count: int  # number of answers in the theme
    sentiment: float  # average sentiment, -1..+1


@dataclass
class OtherBreakdown:
    """What the report's "Other" bucket is actually made of, for the >=30%-Other callout (docs/TODO.md,
    2026-10-21 Phase 1). `ThemeNode`'s own merged "Other" node already combines these two numbers into
    one count/share for charting; this is the same split BEFORE that merge, so the report can say
    honestly how much is genuinely unclassifiable vs. real themes the treemap simply has no room to
    show. `None` (not an instance with all-zero fields) when there is nothing to report - no genuine
    noise and no real theme ranked 8th or beyond, the common case for most datasets."""
    noise_count: int  # answers HDBSCAN itself could not place in any cluster
    noise_share: float  # % of answered responses
    hidden_real_count: int  # answers in real themes ranked 8th+ (not shown as their own ThemeNode)
    hidden_real_share: float  # % of answered responses
    hidden_real_theme_count: int  # number of DISTINCT real themes ranked 8th+
    total_real_theme_count: int  # total distinct real themes found (7 shown + hidden_real_theme_count)


@dataclass
class ScoreBand:
    label: str  # band label, e.g. "Low (0-6)"
    mix: list[float]  # % of the band's answers per theme, in ReportData.themes order
    sentiment: float  # average sentiment inside the band
    answers: int  # answers in the band


@dataclass
class ScoreData:
    name: str  # score column name, e.g. "Likelihood to buy"
    bands: list[ScoreBand]  # score groups, low to high


@dataclass
class SegmentGroup:
    label: str  # group label, e.g. "65+"
    n: int  # respondents in the group


@dataclass
class SegmentRow:
    theme: str  # theme name (should match a ThemeNode)
    overall: float  # theme's overall share, %
    values: list[float]  # theme share inside each group, in SegmentData.groups order


@dataclass
class SegmentData:
    name: str  # segment column name, e.g. "Age group"
    groups: list[SegmentGroup]  # column headers
    rows: list[SegmentRow]  # heatmap rows (usually the largest themes)
    highlight: Optional[tuple[int, int]] = None  # (row index, group index) of the hovered cell
    highlight_text: str = ""  # tooltip text for the hovered cell


@dataclass
class TrendSeries:
    theme: str  # theme name
    color: str  # theme colour token
    values: list[float]  # share (%) per period


@dataclass
class TrendData:
    labels: list[str]  # period labels, e.g. months
    series: list[TrendSeries]  # theme share lines
    sentiment: list[float]  # average sentiment per period
    hover_index: int  # period highlighted by the crosshair
    note: str  # subtitle, e.g. "Monthly, January to December."


@dataclass
class GroupTrendSeries:
    group: str  # segment group label, e.g. "Business"
    color: str  # theme-style colour token ("t1".."t7"), assigned by rank - groups have no colour of their own
    values: list[float]  # average sentiment per period, -1..1


@dataclass
class GroupTrendData:
    """`trend_groups`/`trend_styled` (docs/DECISIONS.md, 2026-10-24 chart-block stream, batch 2):
    "Business customers are getting more negative while the others hold steady" - one SENTIMENT line per
    segment GROUP over time, not one SHARE line per theme (`TrendData` above). A deliberately separate
    shape, not a relabeled `TrendData`: the two axes (what a line represents, what its value means) are
    both different, and groups need an assigned colour `ThemeNode` already carries for themes."""
    group_column: str  # the segment column's own name, e.g. "Customer type"
    labels: list[str]  # period labels, same bands TrendData.labels would use for the same date column
    series: list[GroupTrendSeries]
    note: str  # subtitle, e.g. "Monthly, January to December."


@dataclass
class CoPair:
    a: str  # theme name
    b: str  # theme name
    count: int  # answers mentioning both themes


@dataclass
class MapData:
    seed: int  # random seed for dot scatter (keeps the map stable between renders)
    tip_text: str  # example answer shown in the map tooltip
    tip_note: str  # small line under the tooltip text


@dataclass
class FreqItem:
    label: str  # answer text after merging variants
    pct: float  # % of answered
    merged: int = 0  # number of spellings merged into this label (0 = none)


@dataclass
class FreqData:
    question: str  # short-answer question this list comes from (a different column from the main question)
    answered: int  # answers to that question
    items: list[FreqItem]  # most common answers, descending
    highlight: str  # label of the highlighted row
    footnote: str  # summary sentence under the list


@dataclass
class CategoryAvg:
    label: str  # category label, e.g. "Software engineer"
    avg: float  # that category's own average of the number column
    n: int  # answers in this category


@dataclass
class CategoryAvgData:
    """A number column's average, split by a short-text category column - the `vs_average` block
    (docs/DECISIONS.md, 2026-10-24 chart-block stream): "Software engineers and managers earn well above
    average." Distinct from `ScoreData`: that is a NUMBER column banded into ranges, cross-tabbed against
    THEMES; this is a CATEGORY column's groups, each compared against the number column's own overall
    average - the two axes are swapped, so it is its own shape, not a relabeled ScoreData."""
    category_name: str  # the short-text column's own name, e.g. "Job title"
    number_name: str  # the number column's own name, e.g. "Income"
    overall_avg: float  # the number column's real average across every answered row, not just these categories
    items: list[CategoryAvg]  # categories, largest-average first


@dataclass
class Phrase:
    text: str  # phrase
    count: int  # occurrences
    sentiment: float  # average sentiment of answers containing it


@dataclass
class PhraseData:
    phrases: list[Phrase]  # recurring phrases, most frequent first
    highlight: str  # phrase drawn with a ring


@dataclass
class Quote:
    text: str  # verbatim answer
    theme: str  # theme name
    tone: str  # "negative", "neutral" or "positive"


@dataclass
class QuoteData:
    quotes: list[Quote]  # answers to list
    highlight_index: int  # row drawn as hovered


@dataclass
class QualityData:
    bins: list[tuple[str, int]]  # histogram of answer length: (words label, answers)
    typical_bin: str  # label of the bin holding the typical length
    typical_note: str  # caption over that bin, e.g. "Typical length 8 words"
    notes: list[str]  # three data-quality sentences


@dataclass
class ContextData:
    kind: str  # what the question asks for, e.g. "reasons"
    kind_options: list[str]  # alternatives in the dropdown
    kind_hover: str  # dropdown option drawn as hovered
    framing: str  # e.g. "negatively"
    length: str  # e.g. "a sentence or two"
    columns_note: str  # sentence about the other columns found


@dataclass
class OverviewData:
    stats: list[tuple[str, str, str]]  # (label, big value, small note)
    insights: list[str]  # "What stands out" sentences


@dataclass
class ReportData:
    question: str  # the open-ended question text
    total: int  # rows in the upload
    answered: int  # rows with a usable answer
    overall_sentiment: float  # average sentiment across all answers
    themes: list[ThemeNode]  # themes, largest first ("Other" last)
    selected_theme: str  # theme drawn as selected in demo frames
    hover_theme: str  # theme drawn as hovered in demo frames
    overview: OverviewData
    score: ScoreData
    segment: SegmentData
    trend: TrendData
    group_trend: GroupTrendData
    cooccurrence: list[CoPair]  # theme pairs mentioned in the same answer
    answer_map: MapData
    frequency: FreqData
    category_avg: CategoryAvgData
    phrases: PhraseData
    quotes: QuoteData
    quality: QualityData
    context: ContextData
