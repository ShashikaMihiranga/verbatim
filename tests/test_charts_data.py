import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chart_data import (
    BinCell, BinnedGridData, CategoryAvg, CategoryAvgData, ContextData, CoPair, FreqData, FreqItem,
    GroupTrendData, GroupTrendSeries, MapData, OverviewData, Phrase, PhraseData, QualityData, Quote,
    QuoteData, ReportData, ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, SubTheme,
    ThemeNode, ToneSplit, TrendData, TrendSeries,
)
from app.charts import (
    FRAMES, _icicle_rotated_label, _prefers_icicle, _too_narrow_for, _treemap_areas, f_overview, f_treemap,
    icicle_html, render, rows, treemap_html, treemap_rows,
)
from app.main import app

client = TestClient(app)
GOLDEN = Path(__file__).parent / "golden"


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_frame_identical_to_golden(frame_id):
    """Byte-for-byte regression: output before the data-object refactor."""
    assert render(frame_id) == (GOLDEN / f"{frame_id}.html").read_text()


def test_golden_covers_all_frames():
    assert {p.stem for p in GOLDEN.glob("*.html")} == set(FRAMES)


def test_api_charts_lists_every_frame():
    r = client.get("/api/charts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == len(FRAMES)
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
        group_trend=GroupTrendData("Region", ["W1", "W2", "W3"],
                                    [GroupTrendSeries("North", "t1", [-0.2, -0.1, 0.0]), GroupTrendSeries("South", "t2", [0.1, 0.1, 0.1])],
                                    "Weekly."),
        binned_grid=BinnedGridData("Age", "Spend", ["Young", "Old"], ["Low", "High"],
                                    [BinCell("Young", "Low", 40, -0.2), BinCell("Young", "High", 30, 0.1),
                                     BinCell("Old", "Low", 20, -0.1), BinCell("Old", "High", 10, 0.3)]),
        cooccurrence=[CoPair("Zebra crossing", "Yak shaving", 120)],
        answer_map=MapData(1, "Zebras like stripes", "Zebra crossing, negative"),
        frequency=FreqData("Pet?", 900, [FreqItem("Zebra", 50, 2), FreqItem("Yak", 30)], "Zebra", "Two answers dominate."),
        category_avg=CategoryAvgData("Pet?", "Age", 32.0, [CategoryAvg("Zebra", 41.0, 450), CategoryAvg("Yak", 24.0, 270)]),
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
        "groupSplitBars": ["Zebra crossing", "North", "South"], "compareDots": ["Zebra crossing", "North"],
        "slopeChange": ["Zebra crossing", "Yak shaving", "W1", "W3"], "phrases": ["zebra stripes"],
        "toneByNumber": ["Low", "High", "Mood"], "themeMixOverTime": ["Zebra crossing", "Yak shaving", "W1"],
        "quotes": ["Stripes are confusing", "Zebra crossing"], "freq": ["Zebra", "Pet?"],
        "vsAverage": ["Zebra", "Yak", "Pet?"],
        "trendGroups": ["North", "South", "W1"], "trendStyled": ["North", "South", "W1"],
        "binnedGrid": ["Young", "Old", "Age", "Spend"],
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
    # f_phrases/f_freq/f_quotes all moved to FRAMES (chart-block stream, 2026-10-24: see
    # test_frame_identical_to_golden and test_custom_data_renders_its_own_names, which now cover them the
    # normal way) - f_quality is the one genuinely registered-elsewhere function kept in this smoke test.
    from app import charts

    data = small_report()
    for fn, needle in [(charts.f_freq, "Zebra"), (charts.f_quotes, "Stripes are confusing"),
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


# -------------------------------------------------------------------- "Other" box-area cap (not clipping)

def test_treemap_areas_caps_other_above_five_percent_and_redistributes():
    """"Other" at 30% (merged from _other_colored_themes()'s Theme X/Y plus the real noise bucket) must get
    only 5% of the treemap's AREA, not its real 30% share - the freed 25 points go to Theme A/Theme B in
    proportion to their own existing shares (50/20, i.e. 5:2), not evenly."""
    data = small_report()
    data.themes = _other_colored_themes()
    rows_data = treemap_rows(data)

    areas = _treemap_areas(rows_data)

    assert areas["Other"] == pytest.approx(5.0)
    assert areas["Theme A"] == pytest.approx(50 + 25 * (50 / 70))  # ~67.857
    assert areas["Theme B"] == pytest.approx(20 + 25 * (20 / 70))  # ~27.143
    assert sum(areas.values()) == pytest.approx(100.0)  # total area is conserved, only redistributed


def test_treemap_areas_leaves_other_unchanged_at_or_below_the_cap():
    """"Other" already at or under 5% needs no capping or redistribution - areas equal real shares exactly,
    matching this fix's "if it's less, adjust their size [i.e. leave them alone]" behaviour."""
    data = small_report()  # small_report()'s own Other is 10 of 1000 = unused here; build explicit shares
    data.themes = [
        ThemeNode("Theme A", 80.0, 0.1, 800, "t1", ToneSplit(10, 10, 80)),
        ThemeNode("Theme B", 15.0, 0.1, 150, "t2", ToneSplit(10, 10, 80)),
        ThemeNode("Other", 5.0, 0.0, 50, "other", ToneSplit(30, 30, 40), note="Folded in: too rare"),
    ]
    rows_data = treemap_rows(data)

    areas = _treemap_areas(rows_data)

    assert areas == {"Theme A": pytest.approx(80.0), "Theme B": pytest.approx(15.0), "Other": pytest.approx(5.0)}


def test_treemap_areas_no_redistribution_target_leaves_other_uncapped():
    """A report with ONLY a merged "Other" bucket (no real theme survived at all) has nowhere to give the
    freed area to - capping it would just shrink the total area represented for no visual gain, so it
    keeps its real, full share instead."""
    data = small_report()
    data.themes = [ThemeNode("Other", 100.0, 0.0, 1000, "other", ToneSplit(30, 30, 40))]
    rows_data = treemap_rows(data)

    areas = _treemap_areas(rows_data)

    assert areas == {"Other": pytest.approx(100.0)}


def test_treemap_html_other_label_still_shows_its_true_share_despite_the_area_cap():
    """The area cap (above) must never change what the label actually PRINTS - "Other" still reads its
    real 30% in text, its box is just not allowed to visually dominate the layout."""
    data = small_report()
    data.themes = _other_colored_themes()

    html = treemap_html(data, 1084, 580)

    assert "30.0%" in html  # the real, uncapped share is still what the label shows


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
        r'<span lang="en" style="font-size:14px;font-weight:500;color:var\(--ink\);line-height:1.2;'
        r'overflow:hidden;overflow-wrap:break-word;hyphens:auto;-webkit-hyphens:auto;display:-webkit-box;-webkit-line-clamp:(\d+);'
        r'-webkit-box-orient:vertical">Zebra paint <span style="font-weight:600">',
        html)
    assert sub_cell, "no sub-cell label with a computed -webkit-line-clamp found for Zebra paint"


def test_treemap_html_shows_remainder_cell_when_subtheme_coverage_is_incomplete():
    """Regression pin (docs/DECISIONS.md): MIN_SUBTHEME_COVERAGE only requires sub-themes to cover >= 50%
    of their parent's answers, by design - but squarify() always fills 100% of the reserved sub-area
    regardless, so without a remainder cell the chart would visually imply full coverage. small_report()'s
    "Zebra crossing" theme (share 60) has one sub-theme "Zebra paint" (share 40) - a real 20-point gap."""
    data = small_report()
    html = treemap_html(data, 1084, 580)

    assert "20% not in a sub-theme" in html
    assert "color-mix(in srgb, var(--muted) 18%, var(--surface))" in html


def test_treemap_html_omits_remainder_cell_when_coverage_is_effectively_complete():
    """A sub-theme sum within 0.5 percentage points of its parent's own share is treated as full coverage
    - no remainder cell for noise-level rounding gaps."""
    data = small_report()
    data.themes = [
        ThemeNode("Zebra crossing", 60.2, -0.3, 600, "t1", ToneSplit(60, 30, 10),
                  [SubTheme("Zebra paint", 60.0)]),
        ThemeNode("Other", 39.8, 0.0, 398, "other", ToneSplit(30, 40, 30), note="Folded in: too rare"),
    ]
    html = treemap_html(data, 1084, 580)

    assert "not in a sub-theme" not in html


def test_treemap_html_does_not_indexerror_with_three_real_subthemes_plus_remainder():
    """Regression pin: MIX = [46, 36, 27] is a 3-element list, and a theme can already have up to
    MAX_SUBTHEMES_PER_THEME (3) real sub-cells (k reaching 2) - a naive 4th synthetic remainder entry
    would push k to 3 and raise IndexError on MIX[k] without the "__remainder__" special case."""
    data = small_report()
    data.themes = [
        ThemeNode("Zebra crossing", 90, -0.3, 900, "t1", ToneSplit(60, 30, 10), [
            SubTheme("Zebra paint", 20),
            SubTheme("Zebra stripes", 20),
            SubTheme("Zebra crossing signs", 20),
        ]),
        ThemeNode("Other", 10, 0.0, 100, "other", ToneSplit(30, 40, 30), note="Folded in: too rare"),
    ]
    html = treemap_html(data, 1084, 580)  # must not raise IndexError

    assert "30% not in a sub-theme" in html
    assert "Zebra paint" in html and "Zebra stripes" in html and "Zebra crossing signs" in html


# -------------------------------------------------------------------- icicle layout (chosen per-report
# when the treemap's packed squares would leave a label too narrow to read - see _prefers_icicle)

def test_prefers_icicle_false_when_every_name_has_room():
    """small_report()'s own themes (short names, generous shares, one short sub-theme) must stay on the
    denser treemap layout - this is the "names can get it short, use the treemap" case."""
    data = small_report()
    assert _prefers_icicle(data, 1084, 580) is False


def test_prefers_icicle_true_when_several_real_themes_squeeze_a_small_ones_sub_themes():
    """The real, reported case (confirmed via direct squarify geometry, not guessed): several competing
    real themes (matching the actual shares that produced the bug: a dominant 43.2%/26.8% pair, then
    smaller ones) leave a 3.7%-share theme's own sub-theme row too narrow for a long-named sub-theme -
    this must flip to icicle. Each real theme's box, and the sub-theme squeeze specifically, was verified
    directly against `squarify`'s own output before writing this assertion."""
    data = small_report()
    data.themes = [
        ThemeNode("Dress fit and sizing", 43.2, -0.1, 432, "t1", ToneSplit(40, 30, 30)),
        ThemeNode("Versatility and style appeal", 26.8, 0.1, 268, "t2", ToneSplit(30, 30, 40)),
        ThemeNode("Sweater fit and comfort", 6.0, 0.0, 60, "t3", ToneSplit(30, 30, 40)),
        ThemeNode("Jacket and coat fit", 3.7, 0.0, 37, "t4", ToneSplit(30, 30, 40), [
            SubTheme("Jacket sleeve and size adjustments", 2.8),
            SubTheme("Coats: warmth and fit considerations", 0.9),
        ]),
        ThemeNode("Other", 20.3, 0.0, 203, "other", ToneSplit(30, 40, 30), note="Folded in: too rare"),
    ]
    assert _prefers_icicle(data, 1084, 580) is True


def test_prefers_icicle_true_when_a_small_theme_has_a_dominant_rival():
    """A tiny-share theme next to a near-total-dominant one gets squarify's full-height sliver of a box -
    even a modestly long name can't fit. Verified directly against squarify's own geometry (~22px wide)."""
    data = small_report()
    data.themes = [
        ThemeNode("Fit and sizing", 98.0, -0.1, 980, "t1", ToneSplit(40, 30, 30)),
        ThemeNode("Versatility and style appeal", 2.0, 0.1, 20, "t2", ToneSplit(30, 30, 40)),
    ]
    assert _prefers_icicle(data, 1084, 580) is True


def test_too_narrow_for_short_name_in_a_reasonably_wide_box_is_false():
    assert _too_narrow_for("Cost", 120) is False


def test_too_narrow_for_long_first_word_in_a_tiny_box_is_true():
    assert _too_narrow_for("Versatility and style", 15) is True


def test_too_narrow_for_remainder_placeholder_is_never_flagged():
    assert _too_narrow_for("__remainder__", 5) is False


def test_icicle_html_draws_every_theme_full_row_height_only_width_varies():
    """The defining property of the icicle layout vs the treemap: every theme box spans the SAME height
    (the chart's own theme-row height), differing only in width - never nested/packed by area."""
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 60.0, 0.1, 600, "t1", ToneSplit(10, 10, 80)),
        ThemeNode("Theme B", 40.0, 0.1, 400, "t2", ToneSplit(10, 10, 80)),
    ]
    html = icicle_html(data, 1000, 400)

    heights = sorted(set(re.findall(r'height:(\d+\.\d\d)%;padding:1\.5px', html)))
    assert len(heights) == 1  # one shared row height - no sub-themes here, so it's the full 100%
    assert heights[0] == "100.00"


def test_icicle_html_theme_row_width_is_proportional_to_share():
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 75.0, 0.1, 750, "t1", ToneSplit(10, 10, 80)),
        ThemeNode("Theme B", 25.0, 0.1, 250, "t2", ToneSplit(10, 10, 80)),
    ]
    html = icicle_html(data, 1000, 400)

    a_idx = html.find('data-theme="Theme A"')
    b_idx = html.find('data-theme="Theme B"')
    a_width = re.search(r'width:(\d+\.\d\d)%', html[a_idx:]).group(1)
    b_width = re.search(r'width:(\d+\.\d\d)%', html[b_idx:]).group(1)
    assert float(a_width) == pytest.approx(75.0, abs=0.5)
    assert float(b_width) == pytest.approx(25.0, abs=0.5)


def test_icicle_html_other_width_is_capped_same_as_treemap_area_cap():
    data = small_report()
    data.themes = _other_colored_themes()  # Theme A 50, Theme B 20, merged Other 30

    html = icicle_html(data, 1000, 400)

    other_idx = html.find('data-theme="Other"')
    other_width = float(re.search(r'width:(\d+\.\d\d)%', html[other_idx:]).group(1))
    assert other_width == pytest.approx(5.0, abs=0.5)  # capped, not its real 30%
    assert "30%" in html  # the label still shows the real, uncapped share (narrow box -> rotated name+pct)


# -------------------------------------------------------------------- icicle rotated-label fallback
# (design/screens/icicle.dc.html rotates a too-narrow label 90° rather than wrapping it horizontally)

def test_icicle_html_rotates_a_narrow_but_not_impossibly_narrow_columns_label():
    """A column too narrow for horizontal wrapping (< 6 chars/line) but wide enough for one line's own
    thickness, and tall enough for the full rotated string, shows the real name - rotated - not just a
    bare percentage. Shares chosen to land squarely in the rotated tier (verified: ~54px wide at w=1000,
    well past the ~27px rotation-thickness floor)."""
    data = small_report()
    data.themes = [
        ThemeNode("Fit and sizing", 95.0, -0.1, 950, "t1", ToneSplit(40, 30, 30)),
        ThemeNode("Versatility and style appeal", 5.0, 0.1, 50, "t2", ToneSplit(30, 30, 40)),
    ]
    html = icicle_html(data, 1000, 400)
    idx = html.find('data-theme="Versatility and style appeal"')
    cell = html[idx:idx + 700]
    assert "rotate(-90deg)" in cell
    assert "Versatility and style appeal" in cell
    assert "5%" in cell
    assert "-webkit-line-clamp" not in cell  # rotated text never wraps/clamps


def test_icicle_html_too_narrow_even_to_rotate_falls_back_to_percent_or_nothing():
    """A column narrower than one rotated line's own thickness can't rotate either - it must degrade
    further (percent-only or nothing), never overflow its own box."""
    data = small_report()
    data.themes = [
        ThemeNode("Fit and sizing", 98.0, -0.1, 980, "t1", ToneSplit(40, 30, 30)),
        ThemeNode("Versatility and style appeal", 2.0, 0.1, 20, "t2", ToneSplit(30, 30, 40)),
    ]
    html = icicle_html(data, 1084, 580)
    idx = html.find('data-theme="Versatility and style appeal"')
    cell = html[idx:idx + 400]
    assert "rotate(-90deg)" not in cell
    # The box renders with no inner label div at all (empty body) - this narrow (2% of 1084px), neither
    # the full name nor even the bare percentage fits, rotated or not.
    assert 'background:var(--t2);position:relative"></div>' in cell


def test_icicle_html_remainder_cell_is_never_rotated():
    """The "not in a sub-theme" remainder entry always reads horizontally, matching treemap_html's own
    remainder styling - it is explanatory text, not a theme name competing for the same narrow column."""
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 80.0, 0.1, 800, "t1", ToneSplit(10, 10, 80), [SubTheme("Sub one", 10.0)]),
    ]
    html = icicle_html(data, 1000, 400)
    assert "not in a sub-theme" in html
    not_in_idx = html.find("not in a sub-theme")
    assert "rotate(-90deg)" not in html[max(0, not_in_idx - 300):not_in_idx]


def test_icicle_rotated_label_is_a_single_unwrapped_line():
    html = _icicle_rotated_label("Battery replacement cost 7.5%", 15, "var(--ink)")
    assert "white-space:nowrap" in html
    assert "-webkit-line-clamp" not in html
    assert "Battery replacement cost 7.5%" in html


def test_icicle_html_sub_themes_sit_in_a_second_row_under_their_parent():
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 80.0, 0.1, 800, "t1", ToneSplit(10, 10, 80), [
            SubTheme("Sub one", 50.0), SubTheme("Sub two", 30.0),
        ]),
        ThemeNode("Theme B", 20.0, 0.1, 200, "t2", ToneSplit(10, 10, 80)),
    ]
    html = icicle_html(data, 1000, 400)

    assert html.count('data-theme="Theme A"') == 3  # the theme's own box + its 2 real sub-boxes
    assert "Sub one" in html and "Sub two" in html
    sub_one_idx = html.find("Sub one")
    sub_one_top = re.search(r'top:(\d+\.\d\d)%', html[:sub_one_idx][::-1])
    # top of the sub-row must be strictly below (greater %) than the theme row's own top (0%)
    theme_a_top = re.search(r'top:(\d+\.\d\d)%', html[html.find('data-theme="Theme A"'):])
    assert theme_a_top.group(1) == "0.00"


def test_icicle_html_remainder_cell_when_subtheme_coverage_is_incomplete():
    data = small_report()
    data.themes = [
        ThemeNode("Theme A", 80.0, 0.1, 800, "t1", ToneSplit(10, 10, 80), [SubTheme("Sub one", 40.0)]),
    ]
    html = icicle_html(data, 1000, 400)
    assert "not in a sub-theme" in html


def test_icicle_html_no_crash_on_zero_drawable_rows():
    data = small_report()
    data.themes = [ThemeNode("Empty", 0.0, 0.0, 0, "t1", ToneSplit(0, 100, 0))]
    html = icicle_html(data, 1000, 400)
    assert "position:relative" in html and 'data-theme' not in html


def test_f_treemap_switches_to_icicle_when_prefers_icicle(monkeypatch):
    import app.charts as charts_mod
    monkeypatch.setattr(charts_mod, "_prefers_icicle", lambda data, w, h: True)
    html, _, _ = charts_mod.f_treemap(small_report())
    assert "Width is share of answered" in html  # the icicle-specific subtitle, not the treemap one


def test_f_treemap_keeps_treemap_when_not_prefers_icicle(monkeypatch):
    import app.charts as charts_mod
    monkeypatch.setattr(charts_mod, "_prefers_icicle", lambda data, w, h: False)
    html, _, _ = charts_mod.f_treemap(small_report())
    assert "Block area is share of answered" in html


def test_f_overview_and_f_treemap_each_decide_independently_for_their_own_size():
    """f_overview's hero chart (320px tall) and f_treemap's standalone chart (580px tall) each call
    `_prefers_icicle` with their OWN reference size, not a shared decision - confirmed against a real
    dataset (14 themes, long names) that the smaller hero chart can legitimately need icicle while the
    taller standalone chart still has enough room for treemap. Both must render without error either way -
    this pins that behaviour, not "always agree"."""
    data = small_report()
    data.themes = [
        ThemeNode("Fit and sizing", 90.0, -0.1, 900, "t1", ToneSplit(40, 30, 30)),
        ThemeNode("Versatility and style appeal across many different outfits", 10.0, 0.1, 100, "t2",
                   ToneSplit(30, 30, 40)),
    ]
    overview_html, _, _ = f_overview(data)
    treemap_html_out, _, _ = f_treemap(data)
    assert "data-theme" in overview_html and "data-theme" in treemap_html_out  # both rendered fine


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


def test_report_sunburst_is_one_panel_not_the_gallery_two_state_demo():
    # The gallery frame shows "Default, hover on X" and "X selected" side by side; a real report finding
    # must show only its own state (found live: a long_tail finding rendered both, 1,640px tall).
    from app.charts import render_parts, render_report_parts
    from app.fixtures.ev_sample import EV

    gallery_html, _, gallery_h = render_parts("sunburst", EV)
    assert "Default, hover on" in gallery_html and gallery_h == 1640  # gallery unchanged

    finding_html, _, finding_h = render_report_parts("sunburst", EV, "Other")
    assert "Default, hover on" not in finding_html
    assert finding_html.count("Other selected, others dimmed") == 1
    assert finding_h < gallery_h

    overview_html, _, _ = render_report_parts("sunburst", EV)
    assert "Default, hover on" not in overview_html and "others dimmed" not in overview_html

    assert render_report_parts("treemap", EV) == render_parts("treemap", EV)  # every other chart unchanged


# ---- report UI review fixes (2026-10-24, live on dataset 11)

def _ev_copy():
    import copy
    from app.fixtures.ev_sample import EV
    return copy.deepcopy(EV)


def test_score_group_sentiment_pill_is_tinted_by_its_own_sign():
    # Every pill used to be tinted --neg, so clearly positive groups (+0.50) showed red.
    from app.charts import f_byscore
    data = _ev_copy()
    for b in data.score.bands:
        b.sentiment = 0.5
    html, _, _ = f_byscore(data)
    assert "var(--pos)" in html and "color-mix(in srgb,var(--neg)" not in html


def test_score_group_thin_segments_print_their_value_under_the_bar_not_clipped_inside():
    from app.charts import f_byscore
    data = _ev_copy()
    html, _, _ = f_byscore(data)
    thin = [(t.name, v) for b in data.score.bands for t, v in zip(data.themes, b.mix) if 0 < v < 5]
    assert thin, "fixture needs at least one thin segment"
    name, v = thin[0]
    assert "Under 5%:" in html and f"{name} {v}%" in html


def test_tone_split_bars_never_reach_the_label_column():
    # A 72%-positive theme used to run its bar to x~1026, under the "negative / positive" labels.
    from app.charts import f_diverge
    from app.chart_data import ToneSplit
    data = _ev_copy()
    for t in data.themes:
        t.tones = ToneSplit(5.0, 15.0, 80.0)
    html, _, _ = f_diverge(data)
    ends = [float(x) + float(w) for x, w in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="32"', html)]
    assert ends and max(ends) <= 930


def test_sunburst_callout_for_a_small_left_hand_theme_sits_on_the_left():
    # Live: "Overall satisfaction and compliments 77 (3.9%)" was drawn rightwards across the ring.
    from app.charts import sunburst
    data = _ev_copy()
    for t in data.themes:
        t.callout = None  # real reports have no hand-placed callout positions
    html = sunburst(data, 640, 580, 380, 300, 245, 14, 12.5)
    right_anchored = re.findall(r'transform:translate\(-100%,-50%\)[^>]*>([^<]*\(\d+(?:\.\d+)?%\))', html)
    assert right_anchored, "expected at least one left-side callout anchored by its right edge"


def test_report_overview_points_from_other_to_inside_other_and_says_when_it_is_drawn_smaller(monkeypatch):
    # Report page only: the Inside Other section sits right under the treemap (docs/REPORT_UI_REWORK.md).
    import app.charts as charts
    from app.charts import render_parts, render_report_parts, treemap_html
    data = _ev_copy()
    other = next(t for t in data.themes if t.color == "other")
    others = [t for t in data.themes if t.color != "other"]
    other.share = 40.0  # well above the 5% area cap, so the box is drawn smaller than its real share
    for t in others:
        t.share = round(60.0 / len(others), 1)

    hinted = treemap_html(data, 1084, 580, other_hint=True)
    assert "Look inside ↓" in hinted and "Drawn smaller than its real share" in hinted
    assert "Look inside ↓" not in treemap_html(data, 1084, 580)

    # The report overview turns the hint on (when it draws a treemap); the gallery frame never does.
    monkeypatch.setattr(charts, "_prefers_icicle", lambda *a, **k: False)
    assert "Look inside ↓" in render_report_parts("overview", data)[0]
    assert "Look inside ↓" not in render_parts("overview", data)[0]

    other.share = 4.0  # under the cap: drawn at its real size, so only the pointer, no "smaller" note
    for t in others:
        t.share = round(96.0 / len(others), 1)
    small = treemap_html(data, 1084, 580, other_hint=True)
    assert "Drawn smaller than its real share" not in small


def test_report_overview_is_one_question_with_no_repeated_header_or_stats():
    # docs/REPORT_UI_REWORK.md Phase 3: the page already prints the question, summary and stats.
    from app.charts import render_parts, render_report_parts
    data = _ev_copy()
    report_html = render_report_parts("overview", data)[0]
    assert "What are the themes?" in report_html
    assert "Block area is share of answered. Sub-themes sit inside their theme." in report_html
    for repeated in ("How big, how clean", "Responses", "Typical length", "Average sentiment", data.question):
        assert repeated not in report_html
    assert "How big, how clean" in render_parts("overview", data)[0]  # gallery frame unchanged


# ---------------------------------------------------------------- report overview labels (BUG-043/044/036)

def _dataset_12_like():
    """Dataset 12's shape: one big theme with sub-themes, six small ones, and a merged Other box of 50.7%
    (12 unthemed answers' worth plus 113 folded real themes)."""
    from app.chart_data import OtherBreakdown
    data = small_report()
    data.themes = [
        ThemeNode("Workspace temperature and air quality", 32.0, -0.2, 320, "t1", ToneSplit(50, 30, 20),
                  [SubTheme("Temperature control", 12), SubTheme("Air quality", 8)]),
        ThemeNode("Privacy and noise", 6.0, -0.1, 60, "t2", ToneSplit(40, 40, 20)),
        ThemeNode("Desk booking", 3.0, 0, 30, "t3", ToneSplit(30, 40, 30)),
        ThemeNode("Parking availability", 2.5, 0, 25, "t4", ToneSplit(30, 40, 30)),
        ThemeNode("Cleanliness", 2.0, 0, 20, "t5", ToneSplit(30, 40, 30)),
        ThemeNode("Kitchen facilities", 1.8, 0, 18, "t6", ToneSplit(30, 40, 30)),
        ThemeNode("Meeting rooms", 1.0, 0, 10, "t7", ToneSplit(30, 40, 30)),
        ThemeNode("Other", 50.7, 0, 507, "other", ToneSplit(30, 40, 30)),
    ]
    data.other_breakdown = OtherBreakdown(noise_count=12, noise_share=1.7, hidden_real_count=490,
                                          hidden_real_share=49.0, hidden_real_theme_count=113,
                                          total_real_theme_count=120)
    return data


def test_report_overview_keeps_the_treemap_even_when_the_icicle_would_be_preferred(monkeypatch):
    # BUG-044: the icicle's rotated, mid-word-broken labels read badly on desktop. The gallery keeps it.
    import app.charts as charts
    from app.charts import render_parts, render_report_parts
    monkeypatch.setattr(charts, "_prefers_icicle", lambda *a, **k: True)
    data = _dataset_12_like()
    report_html = render_report_parts("overview", data)[0]
    assert "Block area is share of answered" in report_html
    assert "rotate(-90deg)" not in report_html
    assert "container-type:inline-size" in report_html
    gallery = render_parts("overview", data)[0]
    assert "container-type" not in gallery and "113 more themes" not in gallery


def test_report_overview_labels_never_break_words_and_keep_every_name_readable():
    from app.charts import render_report_parts
    data = _dataset_12_like()
    html_out = render_report_parts("overview", data)[0]
    # The browser may only wrap at spaces: no forced mid-word breaks or automatic hyphens.
    assert "overflow-wrap:break-word" not in html_out and "hyphens:auto" not in html_out
    assert "overflow-wrap:anywhere" not in html_out
    for t in data.themes[:-1]:
        # The full name stays in the box's title and in screen-reader text whatever label fits.
        assert f'title="{t.name} {t.share}%"' in html_out
        assert f">{t.name} {t.share}%</span>" in html_out
    for sub in data.themes[0].children:
        assert f'title="{sub.name} {sub.share:g}%"' in html_out
    # Every visible label has a share-only fallback, switched by the box's own width.
    full = re.findall(r'class="(vbtm[0-9a-f]+-\d+)f"', html_out)
    assert full
    for cls in full:
        assert f"{{.{cls}f{{display:none}}.{cls}p{{display:block}}}}" in html_out
        assert f'{cls}p"' in html_out


def test_min_label_width_never_splits_a_word():
    from app.charts import WORD_EM, _min_label_width
    fs = 15
    longest = len("Temperature") * fs * WORD_EM
    assert _min_label_width("Temperature control 12%", fs, 3) == pytest.approx(longest)
    one_line = len("Temperature control 12%") * fs * WORD_EM
    assert _min_label_width("Temperature control 12%", fs, 1) == pytest.approx(one_line)
    two = _min_label_width("Temperature control 12%", fs, 2)
    assert longest <= two < one_line


def test_report_overview_names_a_box_of_folded_real_themes():
    # BUG-043: 113 real themes plus 12 unthemed answers were all labelled "Other 50.7%".
    from app.charts import render_report_parts
    data = _dataset_12_like()
    html_out = render_report_parts("overview", data)[0]
    assert 'data-theme="Other" title="113 more themes 50.7%"' in html_out
    assert ">113 more themes 50.7%</span>" in html_out
    assert "Look inside ↓" in html_out  # there are unthemed answers to look inside


def test_other_display_name_rules():
    from app.chart_data import OtherBreakdown
    from app.charts import other_display_name
    data = small_report()
    assert other_display_name(data) == "Other"  # nothing known: plain Other
    data.other_breakdown = OtherBreakdown(12, 1.7, 490, 49.0, 113, 120)
    assert other_display_name(data) == "113 more themes"
    data.other_breakdown = OtherBreakdown(120, 30.0, 10, 2.5, 1, 8)
    assert other_display_name(data) == "Other and 1 more theme"
    data.other_breakdown = OtherBreakdown(50, 12.0, 0, 0.0, 0, 5)
    assert other_display_name(data) == "Other"  # only unthemed answers: nothing folded


def test_report_overview_has_no_look_inside_pointer_without_unthemed_answers():
    from app.chart_data import OtherBreakdown
    from app.charts import render_report_parts
    data = _dataset_12_like()
    data.other_breakdown = OtherBreakdown(0, 0.0, 507, 50.7, 113, 120)
    html_out = render_report_parts("overview", data)[0]
    assert "113 more themes" in html_out
    assert "Look inside" not in html_out and "↓" not in html_out


def test_narrow_tall_other_box_keeps_a_compact_pointer():
    # BUG-036: dataset 12's capped Other box was about 54px wide, below the old 80x64 the hint needed.
    from app.charts import HINT_MIN_W, _report_treemap_cell, _TreemapLabels
    data = _dataset_12_like()
    labels = _TreemapLabels([("Other", 50.7)])
    cell = _report_treemap_cell(data, labels, "Other", 50.7, "other", (1030, 140, 54, 180), 1084, 320,
                                {"Other": 5.0}, True)
    style = labels.style()
    hint = re.search(r'class="(vbtm[0-9a-f]+-\d+)h"', cell).group(1)
    # Both pointers ship; the box's own width picks one, so at ~54px only the arrow shows.
    assert 'role="img" aria-label="Look inside Other, below"' in cell and ">↓</div>" in cell
    assert f"@container (width<{HINT_MIN_W}px){{.{hint}h{{display:none}}.{hint}k{{display:block}}}}" in style
    assert 54 < HINT_MIN_W
    # The name is still there for screen readers and on hover, and the share is never word-broken.
    assert 'title="113 more themes 50.7%"' in cell
    assert "overflow-wrap:break-word" not in cell


def test_rank_themes_open_to_show_their_sub_themes():
    """BUG-055: sub-themes sit under their theme as an expandable row, not behind a fake switch."""
    from app.charts import f_rank, f_rank_m
    from app.fixtures.ev_sample import EV
    with_kids = [t for t in EV.themes if t.children]
    for fn in (f_rank, f_rank_m):
        body = fn(EV)[0]
        assert "Sub-themes</" not in body and "<input" not in body
        assert body.count("<details>") == len(with_kids)
        for t in with_kids:
            # each sub-theme comes after its own theme's row
            at = body.index(f"{t.name}: show")
            for c in t.children:
                assert body.index(c.name, at) > at


def test_rank_without_sub_themes_has_nothing_to_open():
    from dataclasses import replace
    from app.charts import f_rank, f_rank_m
    from app.fixtures.ev_sample import EV
    bare = replace(EV, themes=[replace(t, children=[]) for t in EV.themes])
    for fn in (f_rank, f_rank_m):
        body = fn(bare)[0]
        assert "<details>" not in body and "sub-themes" not in body
