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
    cooccurrence: list[CoPair]  # theme pairs mentioned in the same answer
    answer_map: MapData
    frequency: FreqData
    phrases: PhraseData
    quotes: QuoteData
    quality: QualityData
    context: ContextData
