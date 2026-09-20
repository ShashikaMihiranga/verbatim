import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chart_data import (
    ContextData, CoPair, FreqData, FreqItem, MapData, OverviewData, Phrase, PhraseData, QualityData, Quote,
    QuoteData, ReportData, ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, SubTheme, ThemeNode,
    ToneSplit, TrendData, TrendSeries,
)
from app.charts import FRAMES, render
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
