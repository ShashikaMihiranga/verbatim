import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chart_data import (
    ContextData, CoPair, FreqData, FreqItem, MapData, OverviewData, Phrase, PhraseData, QualityData, Quote,
    QuoteData, ReportData, ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, SubTheme, ThemeNode,
    ToneSplit, TrendData, TrendSeries,
)
from app.charts import FRAMES, render, rows, treemap_rows, treemap_svg
from app.main import app

client = TestClient(app)
GOLDEN = Path(__file__).parent / "golden"


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_frame_identical_to_golden(frame_id):
    """Byte-for-byte regression: output before the data-object refactor."""
    assert render(frame_id) == (GOLDEN / f"{frame_id}.html").read_text()


def test_golden_covers_all_frames():
    assert {p.stem for p in GOLDEN.glob("*.html")} == set(FRAMES)


def test_api_charts_lists_20():
    r = client.get("/api/charts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 20
    assert {i["id"] for i in items} == set(FRAMES)
    assert all(i["title"] for i in items)


def test_api_chart_sunburst():
    r = client.get("/api/charts/sunburst")
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == "sunburst" and j["width"] == 1180 and j["height"] == 1640
    assert "<svg" in j["html"]
    assert hashlib.sha256(j["html"].encode()).hexdigest() == hashlib.sha256(render("sunburst").encode()).hexdigest()


def test_api_chart_unknown_404():
    assert client.get("/api/charts/nope").status_code == 404


def small_report() -> ReportData:
    themes = [
        ThemeNode("Zebra crossing", 60, -0.30, 600, "t1", ToneSplit(60, 30, 10), [SubTheme("Zebra paint", 40)], map_xy=(0.3, 0.4)),
        ThemeNode("Yak shaving", 30, 0.20, 300, "t2", ToneSplit(10, 30, 60), map_xy=(0.7, 0.6)),
        ThemeNode("Other", 10, 0.0, 100, "other", ToneSplit(30, 40, 30), note="Folded in: too rare"),
    ]
    return ReportData(
        question="Why do zebras cross?", total=1200, answered=1000, overall_sentiment=-0.05, themes=themes,
        selected_theme="Yak shaving", hover_theme="Zebra crossing",
        overview=OverviewData([("Responses", "1,200", "")], ["Zebra crossing is the largest theme."]),
        score=ScoreData("Mood", [ScoreBand("Low", [60, 30, 10], -0.2, 400), ScoreBand("High", [50, 40, 10], 0.1, 600)]),
        segment=SegmentData("Region", [SegmentGroup("North", 500), SegmentGroup("South", 500)],
                            [SegmentRow("Zebra crossing", 60, [70, 50]), SegmentRow("Yak shaving", 30, [20, 40])],
                            highlight=(0, 0), highlight_text="North mentions Zebra crossing often."),
        trend=TrendData(["W1", "W2", "W3"], [TrendSeries("Zebra crossing", "t1", [55, 60, 65]), TrendSeries("Yak shaving", "t2", [35, 30, 25])],
                        [-0.1, -0.05, 0.0], 1, "Weekly."),
        cooccurrence=[CoPair("Zebra crossing", "Yak shaving", 120)],
        answer_map=MapData(1, "Zebras like stripes", "Zebra crossing, negative"),
        frequency=FreqData("Pet?", 900, [FreqItem("Zebra", 50, 2), FreqItem("Yak", 30)], "Zebra", "Two answers dominate."),
        phrases=PhraseData([Phrase("zebra stripes", 80, -0.2), Phrase("yak wool", 40, 0.1)], "zebra stripes"),
        quotes=QuoteData([Quote("Stripes are confusing", "Zebra crossing", "negative"), Quote("Yaks are fun", "Yak shaving", "positive")], 0),
        quality=QualityData([("1", 10), ("2-3", 40), ("4+", 20)], "2-3", "Typical length 3 words", ["a", "b", "c"]),
        context=ContextData("reasons", ["reasons", "facts"], "facts", "neutrally", "a few words", "Found nothing else."),
    )


def test_custom_data_renders_its_own_names():
    data = small_report()
    for frame_id, needles in {
        "sunburst": ["Zebra crossing", "Zebra paint"], "rank": ["Zebra crossing", "Yak shaving", "-0.05"],
        "treemap": ["Zebra crossing"], "diverge": ["Yak shaving"], "byScore": ["Mood"], "heatmap": ["region", "North"],
        "trend": ["W2"], "arc": ["Yak shaving"], "map": ["Zebras like stripes"],
    }.items():
        html = render(frame_id, data)
        for n in needles:
            assert n in html, (frame_id, n)
        assert "Electric" not in html and "Charging" not in html and "Cost" not in html


def test_custom_data_renders_every_frame():
    data = small_report()
    for frame_id in FRAMES:
        assert render(frame_id, data).startswith("<!doctype html>")


def test_unregistered_frames_take_data_too():
    from app import charts

    data = small_report()
    for fn, needle in [(charts.f_freq, "Zebra"), (charts.f_phrases, "zebra stripes"), (charts.f_quotes, "Stripes are confusing"),
                       (charts.f_quality, "Typical length 3 words")]:
        assert needle in fn(data)[0]


def test_esc_escapes_quotes():
    """esc() must be safe inside a double-quoted HTML attribute, not just inside text content - see
    treemap_svg's `data-theme="{esc(name)}"` below, and docs/DECISIONS.md's stored-XSS fix entry."""
    from app.charts import esc

    assert esc('a"b') == "a&quot;b"
    assert esc("a'b") == "a&#x27;b"


def test_treemap_theme_name_with_quote_cannot_break_out_of_data_theme_attribute():
    """A theme name is a label Claude writes from raw, attacker-influenced survey-answer text
    (app/text_pipeline/labeling.py) - it must never be trusted to contain no double quote. Regression test
    for the stored-XSS fix: a `"` in a theme name used to terminate the `data-theme="..."` attribute early,
    letting the rest of the name inject a new HTML attribute (e.g. an event handler) into the fragment that
    frontend/src/ThemeChart.tsx renders via dangerouslySetInnerHTML."""
    from app.chart_data import ToneSplit
    from app.charts import treemap_svg

    data = small_report()
    data.themes = [ThemeNode('Evil" onmouseover="alert(1)', 100, 0.0, 100, "t1", ToneSplit(0, 100, 0))]
    html = treemap_svg(data, 400, 300)

    assert 'data-theme="Evil&quot; onmouseover=&quot;alert(1)">' in html
    assert 'onmouseover="alert(1)"' not in html


def _other_colored_themes():
    """3 themes coloured "other": two real 8th+-ranked themes (distinct names, no note) plus the genuine
    noise bucket literally named "Other" with a `.note` set - the collision treemap_rows must resolve.
    Shares are floats (not ints) so their sum keeps the round(x, 1) decimal - matching how real theme
    shares (computed as round(t.size / total_answered * 100, 1) in app/findings.py) actually arrive."""
    return [
        ThemeNode("Theme A", 50.0, 0.5, 500, "t1", ToneSplit(10, 10, 80)),
        ThemeNode("Theme B", 20.0, 0.1, 200, "t2", ToneSplit(20, 30, 50)),
        ThemeNode("Theme X", 10.0, 0.2, 100, "other", ToneSplit(10, 10, 80)),
        ThemeNode("Theme Y", 5.0, -0.1, 50, "other", ToneSplit(30, 30, 40)),
        ThemeNode("Other", 15.0, -0.3, 150, "other", ToneSplit(50, 30, 20), note="Folded in: too rare"),
    ]


def test_treemap_rows_merges_all_other_colored_themes_into_one():
    data = small_report()
    data.themes = _other_colored_themes()

    merged = treemap_rows(data)

    assert len(merged) == 3  # Theme A, Theme B, one merged Other
    other_row = next(r for r in merged if r[4] == "other")
    assert other_row[0] == "Other"  # keeps the genuine bucket's name, not a synthesized one
    assert other_row[1] == 30.0  # share: 10 + 5 + 15
    assert other_row[3] == 300  # count: 100 + 50 + 150
    assert other_row[2] == pytest.approx(-0.1)  # count-weighted sentiment: (0.2*100 - 0.1*50 - 0.3*150) / 300


def test_treemap_svg_draws_exactly_one_other_group_for_merged_themes():
    data = small_report()
    data.themes = _other_colored_themes()

    html = treemap_svg(data, 1084, 580)

    assert html.count('data-theme="Other"') == 1
    assert 'data-theme="Theme X"' not in html
    assert 'data-theme="Theme Y"' not in html
    assert "30.0%" in html  # merged share rendered in the label


def test_treemap_rows_noop_with_zero_other_colored_themes():
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 60, 0.1, 600, "t1", ToneSplit(10, 10, 80)),
        ThemeNode("Theme B", 40, 0.2, 400, "t2", ToneSplit(10, 10, 80)),
    ]
    assert treemap_rows(data) == rows(data)


def test_treemap_rows_noop_with_exactly_one_other_colored_theme():
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 60, 0.1, 600, "t1", ToneSplit(10, 10, 80)),
        ThemeNode("Other", 40, 0.2, 400, "other", ToneSplit(10, 10, 80), note="Folded in: too rare"),
    ]
    assert treemap_rows(data) == rows(data)


def test_treemap_svg_label_never_overflows_cell_height():
    """Regression pin for the label-overflow bug: a narrow/short canvas with a very long theme name must
    not draw label text below the rect's own bottom edge - either the label fits and draws in full, or
    nothing is drawn for that cell at all."""
    data = small_report()
    data.themes = [
        ThemeNode("Tiny", 1, 0.0, 1, "t1", ToneSplit(0, 100, 0)),
        ThemeNode("A Very Long Theme Name That Will Not Fit In A Small Cell At All", 4, 0.0, 4, "t2", ToneSplit(0, 100, 0)),
        ThemeNode("Other", 95, 0.0, 95, "other", ToneSplit(0, 100, 0), note="Folded in: too rare"),
    ]

    html = treemap_svg(data, 300, 60)
    assert "<text" in html  # sanity: the fix isn't just suppressing every label, the big cell still gets one

    for group in re.findall(r'<g data-theme="[^"]*">(.*?)</g>', html, re.S):
        rx, ry, rw, rh = (float(v) for v in re.search(
            r'<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="(-?[\d.]+)" height="(-?[\d.]+)"', group).groups())
        for tx, ty in re.findall(r'<text x="(-?[\d.]+)" y="(-?[\d.]+)"', group):
            assert float(ty) <= ry + rh + 1  # +1: sub-pixel rounding tolerance, not a real overflow allowance
