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


def test_pool_covers_every_theme_not_only_the_four_largest():
    from app.text_pipeline.quotes import build_quote_pool
    theme_texts = [(f"Theme{i}", [f"Answer {i} one", f"Answer {i} two"]) for i in range(7)]
    assert {q["theme"] for q in build_quote_pool(theme_texts)} == {f"Theme{i}" for i in range(7)}


def test_pool_ranks_each_tab():
    from app.text_pipeline.quotes import build_quote_pool
    texts = ["I love it, great and lovely", "It is fine", "I hate it, terrible and awful", "It is bad"]
    pool = build_quote_pool([("Cost", texts)])
    first = {view: next(q["text"] for q in pool if q["ranks"].get(view) == 0) for view in ("negative", "positive")}
    assert first == {"negative": "I hate it, terrible and awful", "positive": "I love it, great and lovely"}
    assert all(q["score"] < 0 for q in pool if "negative" in q["ranks"])
    assert sum("random" in q["ranks"] for q in pool) == 4
    assert len({q["text"] for q in pool}) == len(pool)  # one answer in several tabs is listed once


def test_pool_is_masked_and_the_same_on_every_load():
    from app.text_pipeline.quotes import build_quote_pool
    texts = [f"answer {i} email me at jo@example.com" for i in range(30)]
    pool = build_quote_pool([("Support", texts)])
    assert not any("jo@example.com" in q["text"] for q in pool)
    assert pool == build_quote_pool([("Support", texts)])
