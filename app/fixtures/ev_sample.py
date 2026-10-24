"""EV survey sample ("Why haven't you bought an electric vehicle yet?") as a ReportData.

This is the data the 20 design charts were drawn from. render() defaults to it.
"""
import random

from ..chart_data import (
    BinCell, BinnedGridData, CategoryAvg, CategoryAvgData, ContextData, CoPair, FreqData, FreqItem,
    GroupTrendData, GroupTrendSeries, MapData, OverviewData, Phrase, PhraseData, QualityData, Quote,
    QuoteData, ReportData, ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, SubTheme,
    ThemeNode, ToneSplit, TrendData, TrendSeries,
)


def _series(a, b, noise, seed, n=12):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        base = a + (b - a) * i / (n - 1)
        jitter = 0 if i in (0, n - 1) else rnd.uniform(-noise, noise)
        out.append(base + jitter)
    return out


def _sub(*pairs):
    return [SubTheme(n, s) for n, s in pairs]


THEMES = [
    ThemeNode("Cost", 30, -0.05, 14258, "t1", ToneSplit(38, 40, 22), map_xy=(0.30, 0.35),
              children=_sub(("Upfront price", 15), ("Battery replacement cost", 7.5), ("Insurance and running costs", 7.5))),
    ThemeNode("Charging", 26, -0.20, 12357, "t2", ToneSplit(52, 33, 15), map_xy=(0.68, 0.50),
              children=_sub(("No home charger", 11.7), ("Too few public chargers", 9.1), ("Slow to charge", 5.2))),
    ThemeNode("Range and battery", 16, -0.10, 7604, "t3", ToneSplit(44, 38, 18), map_xy=(0.82, 0.25),
              children=_sub(("Range anxiety", 9.6), ("Battery life", 6.4))),
    ThemeNode("Not needed", 10, -0.02, 4753, "t4", ToneSplit(30, 45, 25), map_xy=(0.15, 0.75),
              children=_sub(("Current car is fine", 5.5), ("Barely drive", 2.5), ("Hybrid or petrol is enough", 2))),
    ThemeNode("Doubts about the technology", 8, -0.15, 3802, "t5", ToneSplit(47, 36, 17), map_xy=(0.45, 0.80),
              callout=(160, 144, ["Doubts about", "the technology", "8%"]),
              children=_sub(("Too new", 4), ("Resale value", 4))),
    ThemeNode("Availability", 5, 0.10, 2376, "t6", ToneSplit(28, 40, 32), map_xy=(0.50, 0.15),
              callout=(250, 78, ["Availability", "5%"]),
              children=_sub(("Waiting lists", 3), ("No dealers nearby", 2))),
    ThemeNode("Uncertainty", 3, 0.05, 1426, "t7", ToneSplit(25, 45, 30), map_xy=(0.28, 0.65),
              callout=(306, 40, ["Uncertainty 3%"])),
    ThemeNode("Other", 2, -0.03, 950, "other", ToneSplit(30, 40, 30),
              note="Folded in: answers too rare for a theme"),
]

_MEK = ["Cost", "Charging", "Range and battery", "Not needed", "Doubts about the technology", "Availability", "Uncertainty", "Other"]
assert [t.name for t in THEMES] == _MEK

EV = ReportData(
    question="Why haven't you bought an electric vehicle yet?",
    total=50000,
    answered=47525,
    overall_sentiment=-0.10,
    themes=THEMES,
    selected_theme="Charging",
    hover_theme="Range and battery",
    overview=OverviewData(
        stats=[("Responses", "50,000", ""), ("Answered", "95%", "(2,475 blank, n/a or don't know)"),
               ("Typical length", "8 words", ""), ("Average sentiment", "-0.10", "Negative is expected for this question"),
               ("Themes", "7", "(17 sub-themes)")],
        insights=["Cost is the largest theme at 30% of answers, led by \"Upfront price\".",
                  "Charging carries the most negative wording (-0.20 against -0.10 overall).",
                  "Age group \"65+\" mentions Not needed 2.6 times as often as the average respondent."],
    ),
    score=ScoreData("Likelihood to buy", [
        ScoreBand("Low (0-6)", [27, 25, 15, 18, 9, 2, 2, 2], -0.14, 16000),
        ScoreBand("Middle (7-8)", [33, 28, 17, 3, 7, 7, 3, 2], -0.10, 19000),
        ScoreBand("High (9-10)", [30, 24, 18, 1, 6, 14, 5, 2], -0.03, 12525),
    ]),
    segment=SegmentData(
        name="Age group",
        groups=[SegmentGroup(a, n) for a, n in [("18-24", 5100), ("25-34", 9800), ("35-44", 10600), ("45-54", 9300), ("55-64", 7200), ("65+", 5500)]],
        rows=[SegmentRow("Cost", 30, [40, 38, 32, 27, 24, 20]), SegmentRow("Charging", 26, [30, 32, 31, 27, 22, 18]),
              SegmentRow("Range and battery", 16, [13, 14, 16, 17, 19, 20]), SegmentRow("Not needed", 10, [4, 5, 8, 11, 17, 26]),
              SegmentRow("Doubts about the technology", 8, [6, 7, 8, 9, 10, 10])],
        highlight=(3, 5),
        highlight_text='Age group "65+" mentions Not needed 2.6 times as often as the average respondent.',
    ),
    trend=TrendData(
        labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        series=[TrendSeries("Cost", "t1", _series(26, 34, 1.1, 3)), TrendSeries("Charging", "t2", _series(33, 22, 1.1, 5)),
                TrendSeries("Range and battery", "t3", _series(16, 16, 0.5, 7)), TrendSeries("Not needed", "t4", _series(10, 10, 0.4, 11)),
                TrendSeries("Doubts about the technology", "t5", _series(8, 8, 0.3, 13))],
        sentiment=_series(-0.14, -0.07, 0.012, 17),
        hover_index=8,
        note="Monthly, January to December.",
    ),
    group_trend=GroupTrendData(
        group_column="Customer type",
        labels=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        series=[
            GroupTrendSeries("Business", "t1", _series(-0.05, -0.28, 0.02, 21)),
            GroupTrendSeries("Consumer", "t2", _series(-0.12, -0.10, 0.02, 23)),
            GroupTrendSeries("Fleet", "t3", _series(-0.08, -0.09, 0.02, 29)),
        ],
        note="Monthly, January to December.",
    ),
    binned_grid=BinnedGridData(
        row_name="Age", col_name="Household income",
        row_labels=["18-34", "35-49", "50-64", "65+"],
        col_labels=["Under $30k", "$30k-60k", "$60k-100k", "$100k+"],
        cells=[
            BinCell("18-34", "Under $30k", 1840, -0.22), BinCell("18-34", "$30k-60k", 2210, -0.18),
            BinCell("18-34", "$60k-100k", 1680, -0.08), BinCell("18-34", "$100k+", 920, 0.04),
            BinCell("35-49", "Under $30k", 1210, -0.19), BinCell("35-49", "$30k-60k", 2680, -0.14),
            BinCell("35-49", "$60k-100k", 2340, -0.05), BinCell("35-49", "$100k+", 1560, 0.10),
            BinCell("50-64", "Under $30k", 980, -0.16), BinCell("50-64", "$30k-60k", 1890, -0.11),
            BinCell("50-64", "$60k-100k", 1720, -0.02), BinCell("50-64", "$100k+", 1340, 0.13),
            BinCell("65+", "Under $30k", 1120, -0.10), BinCell("65+", "$30k-60k", 1450, -0.06),
            BinCell("65+", "$60k-100k", 980, 0.02), BinCell("65+", "$100k+", 610, 0.17),
        ],
    ),
    cooccurrence=[CoPair(_MEK[a], _MEK[b], c) for a, b, c in
                  [(0, 1, 1900), (1, 2, 1600), (0, 2, 1100), (0, 4, 800), (2, 4, 700), (0, 5, 400), (1, 5, 350), (1, 3, 300), (4, 6, 200), (3, 5, 150)]],
    answer_map=MapData(42, "No driveway so can't install a home charger", "Charging, negative"),
    frequency=FreqData(
        question="What is your occupation?",
        answered=47973,
        items=[FreqItem("Teacher", 9.3, 3), FreqItem("Nurse", 6.6), FreqItem("Software engineer", 4.8, 3), FreqItem("Accountant", 4.0),
               FreqItem("Sales assistant", 3.3), FreqItem("Manager", 2.9), FreqItem("Retail worker", 2.7, 3), FreqItem("Student", 2.1),
               FreqItem("Electrician", 1.9), FreqItem("Retired", 1.8)],
        highlight="Nurse",
        footnote="1,461 different answers after merging spelling and plural variants. The ten most common cover 39% of answers, and 41% of the distinct answers were given only once.",
    ),
    category_avg=CategoryAvgData(
        category_name="What is your occupation?", number_name="Household income", overall_avg=58200,
        items=[CategoryAvg("Software engineer", 94500, 2304), CategoryAvg("Manager", 81200, 1391),
               CategoryAvg("Accountant", 72600, 1919), CategoryAvg("Electrician", 61300, 912),
               CategoryAvg("Teacher", 49800, 4463), CategoryAvg("Sales assistant", 38400, 1583),
               CategoryAvg("Retail worker", 33700, 1295), CategoryAvg("Student", 19200, 1008)],
    ),
    phrases=PhraseData(
        phrases=[Phrase("worried", 4909, -0.25), Phrase("home charger", 3638, -0.16), Phrase("not enough", 3068, -0.02),
                 Phrase("public charger", 2964, -0.24), Phrase("too expensive", 2815, -0.03), Phrase("long trips", 2113, -0.02),
                 Phrase("no driveway", 1911, -0.12), Phrase("can't afford", 1455, -0.10), Phrase("range anxiety", 1200, -0.11),
                 Phrase("battery life", 1020, -0.18), Phrase("resale value", 724, 0.01), Phrase("waiting list", 720, 0.10)],
        highlight="public charger",
    ),
    quotes=QuoteData(
        quotes=[Quote("No driveway so can't install a home charger", "Charging", "negative"),
                Quote("Not enough public chargers near me", "Charging", "negative"),
                Quote("Worried about resale value", "Doubts about the technology", "negative"),
                Quote("The upfront price is too high", "Cost", "neutral"),
                Quote("I barely drive, my current car is fine", "Not needed", "neutral"),
                Quote("Still weighing it up, need more information", "Uncertainty", "neutral"),
                Quote("I'd love one, but there's a long waiting list for the models I want", "Availability", "positive")],
        highlight_index=1,
    ),
    quality=QualityData(
        bins=[("1", 1900), ("2", 3800), ("3", 5700), ("4-5", 9500), ("6-8", 11400), ("9-12", 9500), ("13-20", 4300), ("21-40", 1100), ("41+", 300)],
        typical_bin="6-8",
        typical_note="Typical length 8 words",
        notes=["2,475 blank, said nothing or n/a, or said they did not know. These are left out of the themes.",
               "12% of answers repeat an earlier answer word for word.",
               "Sentiment comes from a word-based scorer built for English. It reads wording, not intent, and can miss sarcasm."],
    ),
    context=ContextData(
        kind="reasons",
        kind_options=["reasons", "improvements", "experiences", "facts", "anything else", "opinions"],
        kind_hover="facts",
        framing="negatively",
        length="a sentence or two",
        columns_note="Also found a score column (Likelihood to buy), a date column (Survey date, grouped by month), and a segment column (Age group).",
    ),
)
