"""Tests for app/text_pipeline/quotes.py (chart-block stream, 2026-10-24, batch 1, `quotes` block)."""
from __future__ import annotations

from app.text_pipeline.quotes import MAX_PER_THEME, MAX_THEMES, build_quote_data


def test_returns_none_when_nothing_real_is_given():
    assert build_quote_data([]) is None
    assert build_quote_data([("Cost", [])]) is None


def test_picks_the_most_typical_answer_by_median_length():
    # word counts: 2, 9, 6 - median is 6, so the 6-word answer itself is the closest (distance 0), picked
    # first over the 2-word (distance 4) and 9-word (distance 3) outliers.
    texts = ["Too expensive", "Way too expensive overall for what you get, really", "Pricing is way too high honestly"]
    data = build_quote_data([("Cost", texts)])
    assert data is not None
    assert data.quotes[0].text == "Pricing is way too high honestly"
    assert data.quotes[0].theme == "Cost"


def test_tone_is_a_real_lexicon_score_not_hardcoded():
    data = build_quote_data([("Cost", ["I love the low price, it is great"])])
    assert data.quotes[0].tone == "positive"
    data2 = build_quote_data([("Cost", ["I hate the high price, it is terrible"])])
    assert data2.quotes[0].tone == "negative"


def test_caps_themes_and_quotes_per_theme():
    theme_texts = [(f"Theme{i}", [f"Answer {i} one", f"Answer {i} two", f"Answer {i} three"]) for i in range(10)]
    data = build_quote_data(theme_texts)
    themes_seen = {q.theme for q in data.quotes}
    assert len(themes_seen) <= MAX_THEMES
    per_theme: dict[str, int] = {}
    for q in data.quotes:
        per_theme[q.theme] = per_theme.get(q.theme, 0) + 1
    assert all(n <= MAX_PER_THEME for n in per_theme.values())


def test_blank_and_non_string_entries_are_skipped():
    data = build_quote_data([("Cost", ["Real answer here", "", "   ", None])])  # type: ignore[list-item]
    assert data is not None
    assert all(q.text == "Real answer here" for q in data.quotes)
