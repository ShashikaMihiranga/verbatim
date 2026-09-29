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
from app.charts import FRAMES, render, rows, treemap_html, treemap_rows
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

    data = small_report()
    data.themes = [ThemeNode('Evil" onmouseover="alert(1)', 100, 0.0, 100, "t1", ToneSplit(0, 100, 0))]
    html = treemap_html(data, 400, 300)

    assert 'data-theme="Evil&quot; onmouseover=&quot;alert(1)" style=' in html
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


def test_treemap_html_draws_exactly_one_other_box_for_merged_themes():
    data = small_report()
    data.themes = _other_colored_themes()

    html = treemap_html(data, 1084, 580)

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


def test_treemap_html_label_never_overflows_its_cell():
    """Regression pin for the fluid-layout rewrite (docs/DECISIONS.md): treemap_html has no fixed pixel
    coordinates to check for overflow any more (every box's position/size is now a % of the whole, and
    each cell's own label sits inside an `overflow:hidden` box) - the old pixel-math check this test used
    to do is now a structural CSS guarantee instead of something computed per render, so this test asserts
    the structure that guarantee depends on: no <svg, every [data-theme] cell's position/size are all %,
    every label declares a positive-integer -webkit-line-clamp (computed from the cell's own known
    height, not a fixed cap - see docs/DECISIONS.md's follow-up entry) plus overflow-wrap:break-word, and
    every cell that draws a label is overflow:hidden so a too-long label can never bleed into a sibling
    cell."""
    data = small_report()
    data.themes = [
        ThemeNode("Tiny", 1, 0.0, 1, "t1", ToneSplit(0, 100, 0)),
        ThemeNode("A Very Long Theme Name That Will Not Fit In A Small Cell At All", 4, 0.0, 4, "t2", ToneSplit(0, 100, 0)),
        ThemeNode("Other", 95, 0.0, 95, "other", ToneSplit(0, 100, 0), note="Folded in: too rare"),
    ]

    html = treemap_html(data, 300, 60)
    assert "<svg" not in html

    cells = re.findall(r'<div data-theme="[^"]*" style="([^"]+)">', html)
    assert len(cells) == 3
    for style in cells:
        for prop in ("left", "top", "width", "height"):
            m = re.search(rf'{prop}:([^;]+);', style)
            assert m and m.group(1).endswith("%"), f"{prop} in {style!r} is not a %"

    clamps = [int(v) for v in re.findall(r'-webkit-line-clamp:(\d+);', html)]
    assert len(clamps) == 3
    assert all(c >= 1 for c in clamps)
    assert html.count("overflow-wrap:break-word") == 3
    assert "overflow:hidden" in html


def test_treemap_html_sub_cell_label_line_count_is_derived_from_its_own_height():
    """Regression pin for a follow-up fluid-layout fix (docs/DECISIONS.md): sub-theme cells used to
    always render name+pct combined with no fallback and no way to show more of a long name in a tall
    cell; now their -webkit-line-clamp is computed from the sub-cell's own known height, same mechanism
    as the parent cell, instead of a container-query full/short toggle. small_report()'s "Zebra crossing"
    theme has a real sub-theme (SubTheme("Zebra paint", 40)) in its fixture data."""
    data = small_report()
    html = treemap_html(data, 1084, 580)

    sub_cell = re.search(
        r'<span style="font-size:14px;font-weight:500;color:var\(--ink\);line-height:1.2;'
        r'overflow:hidden;overflow-wrap:break-word;display:-webkit-box;-webkit-line-clamp:(\d+);'
        r'-webkit-box-orient:vertical">Zebra paint <span style="font-weight:600">',
        html)
    assert sub_cell, "no sub-cell label with a computed -webkit-line-clamp found for Zebra paint"
    assert int(sub_cell.group(1)) >= 1


def test_rank_bar_width_is_percent_not_fixed_pixels():
    """Regression pin for the fluid-layout rewrite (docs/DECISIONS.md): a rank row's share bar must
    genuinely reflow with its own row's width, not stay pinned to a px number computed against the old
    fixed 1180px design - so its width is always a CSS %, never a bare px number."""
    html = render("rank")
    bar_widths = re.findall(r'<div style="flex:1;min-width:0"><div style="width:([^;"]+);', html)
    assert len(bar_widths) >= 1
    for w in bar_widths:
        assert w.endswith("%"), f"bar width {w!r} is not a percentage"


def test_byscore_bar_is_fluid_with_container_query_label_swap():
    """Regression pin: byScore's segmented bar row must genuinely reflow (no literal width:700px), and
    the old server-side "does the name fit" guess must be replaced by a real CSS container query so the
    decision is made at the segment's actual final width, not an assumed design width."""
    html = render("byScore")
    assert "width:700px" not in html
    assert "@container" in html


def test_trend_labels_sit_outside_the_svg_within_bounds():
    """Regression pin for the fluid-layout rewrite (docs/DECISIONS.md): f_trend's SVG now draws shapes
    only (gridlines/polylines/dots, genuinely benefits from scaling as one proportional unit) - every
    text label was moved to a sibling HTML div positioned by % of the chart's own width/height, so its
    font-size stays literal instead of being subject to the SVG's own viewBox scaling. Geometry invariant
    (not exact pixels, since the whole point is these percentages are resolution-independent): every
    label's computed left/top % stays within [0, 100] across a few different synthetic trend shapes."""
    from app.charts import f_trend
    from app.chart_data import TrendData, TrendSeries

    # NP=1 (a single time bucket) hits a pre-existing, unrelated division-by-zero in f_trend's own dx
    # calculation (unchanged by this rewrite) - not exercised here since it was never reachable behavior.
    # Values stay within the chart's own fixed 0-40% y-axis scale (its gridlines are hardcoded to
    # 0/10/20/30/40, a pre-existing characteristic of this design, unchanged by this rewrite) - a value
    # outside that range would draw above/below the plot area by design, in both the old SVG version and
    # this one, so isn't a useful input for testing THIS rewrite's own position-percentage invariant.
    base = small_report()
    for labels, series, sentiment, hover in [
        (["W1", "W2", "W3"], [TrendSeries("Zebra crossing", "t1", [15, 20, 25]), TrendSeries("Yak shaving", "t2", [35, 30, 25])], [-0.1, -0.05, 0.0], 1),
        (["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
         [TrendSeries("A Very Long Theme Name Indeed", "t1", [0, 5, 10, 15, 20, 40])], [-0.2, -0.15, -0.1, -0.05, 0.0, 0.0], 5),
    ]:
        data = base
        data.trend = TrendData(labels, series, sentiment, hover, "Note.")
        html, w, h = f_trend(data)
        assert "<svg" in html
        assert "<text" not in html
        lefts = [float(v.rstrip("%")) for v in re.findall(r'left:(-?[\d.]+)%', html)]
        tops = [float(v.rstrip("%")) for v in re.findall(r'top:(-?[\d.]+)%', html)]
        assert lefts and tops
        for v in lefts + tops:
            assert -5 <= v <= 105, f"label position {v}% is wildly out of bounds"  # small allowance: axis labels sit just outside the plot area by design (e.g. x0-10)


def test_sentsun_labels_sit_outside_the_svg_within_bounds():
    """Regression pin for the fluid-layout rewrite (docs/DECISIONS.md): f_sentsun's SVG now draws wedge
    shapes only (genuine polar/arc geometry - the one case that truly can't be plain CSS boxes) - every
    label (arc_label()'s in-ring text, the center count) is a sibling HTML div positioned by % + rotate,
    same reasoning as f_trend's rewrite. Geometry invariant, not exact pixels: every label's computed
    left/top % stays within bounds across a few different synthetic theme/tone shapes."""
    from app.charts import f_sentsun

    data = small_report()
    for themes in [
        [ThemeNode("Zebra crossing", 60, -0.3, 600, "t1", ToneSplit(60, 30, 10)),
         ThemeNode("Yak shaving", 40, 0.2, 400, "t2", ToneSplit(10, 30, 60))],
        [ThemeNode("A", 1, 0.0, 10, "t1", ToneSplit(33, 34, 33)),
         ThemeNode("A Very Long Theme Name That Barely Fits Anywhere", 98, 0.0, 980, "t2", ToneSplit(0, 0, 100)),
         ThemeNode("Other", 1, 0.0, 10, "other", ToneSplit(100, 0, 0), note="Folded in: too rare")],
    ]:
        data.themes = themes
        html, w, h = f_sentsun(data)
        assert "<svg" in html
        assert "<text" not in html
        lefts = [float(v) for v in re.findall(r'left:(-?[\d.]+)%', html)]
        tops = [float(v) for v in re.findall(r'top:(-?[\d.]+)%', html)]
        assert lefts and tops
        for v in lefts + tops:
            assert -5 <= v <= 105, f"label position {v}% is wildly out of bounds"


def test_quality_histogram_is_css_bars_not_svg():
    """Regression pin: the quality histogram was an SVG (axis-aligned rects, no curved geometry - no
    reason to keep SVG once byScore proved the CSS-flex-bar pattern works). Bar heights are a % of their
    fixed-height track so the chart genuinely reflows in width."""
    html = render("quality")
    assert "<svg" not in html
    bar_heights = re.findall(r'<div style="width:100%;height:([^;"]+);border-radius:3px 3px 0 0', html)
    assert len(bar_heights) >= 1
    for h in bar_heights:
        assert h.endswith("%"), f"bar height {h!r} is not a percentage"


def test_heatmap_first_column_is_not_a_bare_pixel_width():
    """Regression pin: the heatmap's row-label column must be a range (minmax/clamp), not a literal
    250px, so it can use extra width on a wide screen instead of staying pinned to the old design."""
    html = render("heatmap")
    m = re.search(r'grid-template-columns:([^;"]+);', html)
    assert m, "no grid-template-columns found in heatmap output"
    first_col = m.group(1).split(" ")[0]
    assert first_col.startswith("minmax(") or first_col.startswith("clamp("), \
        f"heatmap's first column {first_col!r} is a bare fixed width"
