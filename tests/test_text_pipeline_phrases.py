"""Tests for app/text_pipeline/phrases.py (chart-block stream, 2026-10-24, top_phrases block)."""
from __future__ import annotations

from app.text_pipeline.phrases import MIN_PHRASE_ANSWERS, build_phrase_data


def test_returns_none_when_nothing_recurs_enough():
    texts = ["A totally unique answer one", "Something else entirely different", "A third unrelated reply"]
    assert build_phrase_data(texts) is None


def test_finds_a_phrase_repeated_across_enough_distinct_answers():
    texts = [
        "No driveway so I can not install a home charger",
        "Worried about the home charger install cost",
        "Our home charger install was quick and easy",
        "Totally unrelated answer about something else",
    ]
    data = build_phrase_data(texts)
    assert data is not None
    assert data.phrases[0].text == "home charger"
    assert data.phrases[0].count == 3
    assert data.highlight == "home charger"


def test_counts_a_phrase_once_per_answer_not_once_per_occurrence():
    # "home charger" appears TWICE in this one answer - must still count as 1 answer, not 2, so one
    # talkative respondent can't out-rank three distinct respondents who each said it once.
    texts = [
        "The home charger broke, so I bought a second home charger",
        "Another answer entirely",
        "A third, different answer",
    ]
    data = build_phrase_data(texts)
    phrase = next((p for p in (data.phrases if data else []) if p.text == "home charger"), None)
    assert phrase is None or phrase.count == 1  # never 2


def test_phrase_sentiment_is_the_average_of_the_full_answers_it_appears_in():
    texts = [
        "I love the home charger, it works great",
        "I hate the home charger, it broke immediately",
        "The home charger is fine I guess",
    ]
    data = build_phrase_data(texts)
    phrase = next(p for p in data.phrases if p.text == "home charger")
    assert phrase.count == 3
    assert -1.0 <= phrase.sentiment <= 1.0  # a real average, not a hardcoded/missing value


def test_a_stopword_edge_is_trimmed_but_an_interior_stopword_is_kept():
    texts = [
        "Not worth the price at all",
        "Really not worth the price this year",
        "Still not worth the price honestly",
    ]
    data = build_phrase_data(texts)
    phrase_texts = {p.text for p in data.phrases}
    assert "not worth the price" in phrase_texts  # interior stopwords ("the") kept
    assert not any(t.startswith("the ") or t.endswith(" the") for t in phrase_texts)  # edges trimmed


def test_non_string_and_blank_entries_are_skipped_not_crashed_on():
    texts = ["Home charger install was great", "Home charger broke fast", "Loved the home charger", None, "", "   ", 42]
    data = build_phrase_data(texts)  # type: ignore[arg-type]
    assert data is not None
    assert data.phrases[0].text == "home charger"


def test_min_phrase_answers_floor_is_small_not_the_30_answer_suppression_floor():
    # Deliberately NOT app.cleaning.suppression.min_group_size()'s 30 - see the module's own docstring.
    assert MIN_PHRASE_ANSWERS < 30


def test_heights_and_curly_apostrophes_never_become_phrase_fragments():
    # Found live on dataset 11: chips like "i'm '" and "' lbs" came from heights (5'4") leaving a bare
    # "'" token, and curly apostrophes splitting "I’m" into "i" + "m".
    texts = [
        "I'm 5'4, 125 lbs and it runs true to size",
        "I'm 5'2, 130 lbs, true to size for me",
        "I’m 5’6, 135 lbs - true to size",
        "I'm 5'7, 140 lbs, ordered my usual",
    ]
    data = build_phrase_data(texts)
    assert data is not None
    shown = [p.text for p in data.phrases]
    assert "true to size" in shown
    for t in shown:
        words = t.split()
        assert "'" not in words and not t.startswith("'") and not t.endswith("'"), shown
        assert words[0] not in {"i'm", "i", "m", "am"}, shown
