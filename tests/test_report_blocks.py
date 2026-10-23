"""Tests for the ported block registry (docs/DECISIONS.md, 2026-10-24 stream, Stage 1). Covers three
things: the registry's own internal consistency (every id/slug/chart_id is sane), that each `needs()`
predicate actually distinguishes a "rich" report from a "thin" one where that's possible, and that the
handful of permanently-`False`/permanently-`True` entries stay that way for their documented reason (not
an oversight a future edit could silently break).
"""
from __future__ import annotations

from app.chart_data import (
    ContextData, CoPair, FreqData, MapData, OverviewData, PhraseData, QualityData, QuoteData, ReportData,
    ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, SubTheme, ThemeNode, ToneSplit, TrendData,
    TrendSeries,
)
from app.charts import FRAMES
from app.report_blocks import BLOCKS, BY_ID, BY_SLUG


def _empty_placeholders() -> dict:
    """The honest-empty placeholder fields every real ReportData carries when no structured column, or no
    not-yet-built pipeline's data, is available - same shape `app/findings.py:build_report_data` falls
    back to (`app/findings.py:522-541`)."""
    return dict(
        score=ScoreData(name="", bands=[]), segment=SegmentData(name="", groups=[], rows=[]),
        trend=TrendData(labels=[], series=[], sentiment=[], hover_index=0, note=""),
        cooccurrence=[], answer_map=MapData(seed=0, tip_text="", tip_note=""),
        frequency=FreqData(question="", answered=0, items=[], highlight="", footnote=""),
        phrases=PhraseData(phrases=[], highlight=""), quotes=QuoteData(quotes=[], highlight_index=0),
        context=ContextData(kind="anything else", kind_options=[], kind_hover="", framing="neutrally",
                             length="a sentence or two", columns_note=""),
    )


def thin_report() -> ReportData:
    """A report with real answers but nothing extra: one real theme (well under every "3 or more" gate),
    no sub-themes, perfectly neutral tone, no structured columns at all - every conditional `needs()`
    predicate should read False against this."""
    themes = [ThemeNode("Only theme", 80, 0.0, 80, "t1", ToneSplit(33, 34, 33))]
    return ReportData(
        question="Anything else?", total=100, answered=80, overall_sentiment=0.0, themes=themes,
        selected_theme="Only theme", hover_theme="Only theme",
        overview=OverviewData(stats=[("Responses", "100", "")], insights=[]),
        quality=QualityData(bins=[("n/a", 80)], typical_bin="n/a", typical_note="", notes=[]),
        **_empty_placeholders(),
    )


def rich_report() -> ReportData:
    """Three real themes (one with a sub-theme, one with a wide tone spread), a score column, a 3-group
    segment column (each clearing the 100-answer floor), and a 3-period trend - enough to clear every
    conditional `needs()` predicate that CAN be cleared by data this app builds today."""
    themes = [
        ThemeNode("Cost", 40, -0.30, 400, "t1", ToneSplit(60, 20, 20), children=[SubTheme("Upfront price", 20)]),
        ThemeNode("Charging", 25, 0.10, 250, "t2", ToneSplit(20, 30, 50)),
        ThemeNode("Not needed", 15, 0.0, 150, "t3", ToneSplit(33, 34, 33)),
        ThemeNode("Other", 20, 0.0, 200, "other", ToneSplit(33, 34, 33)),
    ]
    return ReportData(
        question="Why?", total=1200, answered=1000, overall_sentiment=-0.05, themes=themes,
        selected_theme="Cost", hover_theme="Charging",
        overview=OverviewData(stats=[("Responses", "1,200", "")], insights=[]),
        quality=QualityData(bins=[("1-10", 1000)], typical_bin="1-10", typical_note="", notes=[]),
        score=ScoreData("Likelihood", [ScoreBand("Low", [60, 30, 10], -0.2, 400), ScoreBand("High", [30, 40, 30], 0.2, 600)]),
        segment=SegmentData("Region", [SegmentGroup("North", 500), SegmentGroup("South", 500)],
                             [SegmentRow("Cost", 50, [55, 45])]),
        trend=TrendData(["Jan", "Feb", "Mar"], [TrendSeries("Cost", "t1", [40, 45, 50])], [-0.1, -0.05, 0.0], 0, ""),
        cooccurrence=[CoPair("Cost", "Charging", 50)], answer_map=MapData(1, "", ""),
        frequency=FreqData("", 0, [], "", ""), phrases=PhraseData([], ""),
        quotes=QuoteData([], 0), context=ContextData("reasons", [], "", "neutrally", "a few words", ""),
    )


def test_registry_has_46_blocks_with_unique_ids_and_slugs():
    assert len(BLOCKS) == 46
    assert len(BY_ID) == 46
    assert len(BY_SLUG) == 46
    for b in BLOCKS:
        assert BY_ID[b.id] is b
        assert BY_SLUG[b.slug] is b


def test_every_block_chart_id_exists_in_frames_or_is_explicitly_none():
    for b in BLOCKS:
        assert b.chart_id is None or b.chart_id in FRAMES, (b.id, b.chart_id)


def test_every_needs_predicate_runs_without_crashing_on_a_thin_and_a_rich_report():
    thin, rich = thin_report(), rich_report()
    for b in BLOCKS:
        assert isinstance(b.needs(thin), bool), b.id
        assert isinstance(b.needs(rich), bool), b.id


def test_frame_and_quality_blocks_are_always_available():
    thin = thin_report()
    assert BY_SLUG["frame"].needs(thin) is True
    assert BY_SLUG["summary"].needs(thin) is True
    assert BY_SLUG["also_checked"].needs(thin) is True
    assert BY_SLUG["quality"].needs(thin) is True


def test_theme_map_needs_three_real_themes():
    assert BY_SLUG["theme_map"].needs(thin_report()) is False  # only 1 real theme
    assert BY_SLUG["theme_map"].needs(rich_report()) is True  # Cost, Charging, Not needed (Other not counted)


def test_sentiment_sun_needs_a_real_tone_spread():
    assert BY_SLUG["sentiment_sun"].needs(thin_report()) is False  # perfectly neutral tone
    assert BY_SLUG["sentiment_sun"].needs(rich_report()) is True  # Cost's 60/20/20 split


def test_group_heatmap_needs_every_segment_group_at_the_floor():
    assert BY_SLUG["group_heatmap"].needs(thin_report()) is False  # no segment column at all
    assert BY_SLUG["group_heatmap"].needs(rich_report()) is True  # North 500, South 500


def test_score_groups_needs_a_score_column_and_three_themes():
    assert BY_SLUG["score_groups"].needs(thin_report()) is False
    assert BY_SLUG["score_groups"].needs(rich_report()) is True


def test_trend_needs_three_or_more_periods():
    assert BY_SLUG["trend"].needs(thin_report()) is False
    assert BY_SLUG["trend"].needs(rich_report()) is True


def test_theme_hierarchy_needs_real_sub_themes():
    assert BY_SLUG["theme_hierarchy"].needs(thin_report()) is False
    assert BY_SLUG["theme_hierarchy"].needs(rich_report()) is False  # rich_report has only 1 sub-theme (<3)
    richer = rich_report()
    richer.themes[0].children.append(SubTheme("Battery cost", 10))
    richer.themes[0].children.append(SubTheme("Insurance", 10))
    assert BY_SLUG["theme_hierarchy"].needs(richer) is True  # now 3 sub-themes total


def test_long_tail_and_inside_other_need_a_large_enough_other_bucket():
    assert BY_SLUG["long_tail"].needs(thin_report()) is False  # no "other" node at all
    assert BY_SLUG["long_tail"].needs(rich_report()) is True  # Other is 20% (>=15%)
    assert BY_SLUG["inside_other"].needs(rich_report()) is False  # 20% is not > 30%


def test_co_mentions_is_permanently_excluded_not_merely_unwired():
    # Unlike every other False predicate here, this one must stay False even against the richest possible
    # report - it is not a "not built yet" gap, it is a "cannot be built" one (see the block's own comment).
    assert BY_SLUG["co_mentions"].needs(rich_report()) is False
    assert BY_SLUG["co_mentions"].chart_id == "arc"


def test_tone_split_reuses_the_already_built_but_unwired_diverge_renderer():
    # Stage 4's near-free win: the data requirement is already met by any real theme, the renderer
    # (f_diverge) already exists - only the wiring into pick_chart_candidates is still missing.
    b = BY_SLUG["tone_split"]
    assert b.chart_id == "diverge"
    assert b.needs(rich_report()) is True


def test_band_bars_and_number_spread_reuse_the_already_wired_numeric_score_fallback():
    # Found while porting, not a design gap: build_numeric_data already feeds ReportData.score as a
    # fallback when a dataset has a numeric column (age, income) but no real score-scale column
    # (app/findings_structured.py:726-748) - both blocks' data AND renderer (f_byscore) already existed.
    assert BY_SLUG["band_bars"].needs(thin_report()) is False  # no score column of either kind
    assert BY_SLUG["band_bars"].needs(rich_report()) is True
    assert BY_SLUG["number_spread"].needs(rich_report()) is True
    assert BY_SLUG["band_bars"].chart_id == "byScore"
    assert BY_SLUG["number_spread"].chart_id == "byScore"


def test_group_split_bars_compare_dots_slope_change_got_real_new_renderers():
    # Chart-block stream, "reuse group" batch 3 (2026-10-24): new f_group_split_bars/f_compare_dots/
    # f_slope_change in app/charts.py, reusing existing SegmentData/TrendData - no new upstream pipeline.
    assert BY_SLUG["group_split_bars"].chart_id == "groupSplitBars"
    assert BY_SLUG["group_split_bars"].needs(rich_report()) is True  # rich_report has exactly 2 groups
    assert BY_SLUG["group_split_bars"].needs(thin_report()) is False

    assert BY_SLUG["compare_dots"].chart_id == "compareDots"
    assert BY_SLUG["compare_dots"].needs(rich_report()) is False  # rich_report has 2 groups, not 8-20
    assert BY_SLUG["compare_dots"].needs(thin_report()) is False

    assert BY_SLUG["slope_change"].chart_id == "slopeChange"
    assert BY_SLUG["slope_change"].needs(rich_report()) is True  # rich_report has 3 trend periods
    assert BY_SLUG["slope_change"].needs(thin_report()) is False


def test_top_phrases_is_real_once_phrase_data_is_populated():
    # Chart-block stream, "new pipeline" batch 1 (2026-10-24): app/text_pipeline/phrases.py extracts real
    # phrases from real answer text; this just confirms the registry's own predicate and chart_id - the
    # extraction logic itself is covered by tests/test_phrases.py.
    from app.chart_data import Phrase, PhraseData
    import dataclasses

    b = BY_SLUG["top_phrases"]
    assert b.chart_id == "phrases"
    assert b.needs(rich_report()) is False  # rich_report's phrases placeholder is empty
    with_phrases = dataclasses.replace(rich_report(), phrases=PhraseData([Phrase("home charger", 5, -0.1)], "home charger"))
    assert b.needs(with_phrases) is True


def test_context_header_is_real_once_any_question_exists():
    # Chart-block stream, "new pipeline" batch 2 (2026-10-24): app/findings.py's _build_context now
    # classifies the question for real - always available once a question/themes exist at all.
    assert BY_SLUG["context_header"].chart_id == "context"
    assert BY_SLUG["context_header"].needs(thin_report()) is True
    assert BY_SLUG["context_header"].needs(rich_report()) is True


def test_blocks_with_no_data_pipeline_yet_stay_false_even_on_the_richest_report():
    # Every one of these describes a column kind or cross-tab this app genuinely does not build today
    # (per each block's own comment in app/report_blocks.py) - confirms the registry doesn't silently
    # start claiming readiness once rich_report() happens to have unrelated real data.
    richest = rich_report()
    for slug in (
        "ranked_answers", "vs_average", "tone_by_number", "quotes", "see_more", "trend_groups",
        "trend_styled", "trend_grid", "trend_aggregated", "trend_errorbars",
        "theme_similarity", "answer_map", "ranked_list", "binned_grid", "region_map",
        "trend_sparse",
    ):
        assert BY_SLUG[slug].needs(richest) is False, slug
