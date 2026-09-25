"""Stream 6: sentiment scoring (lexicon + optional Claude spot-check). No network, ever."""
import json

import numpy as np
import pandas as pd
import pytest

from app.cleaning import plan_cleaning
from app.chart_data import ToneSplit
from app.text_pipeline import (
    AnswerScore,
    ClaudeNotConfigured,
    FakeClaudeClient,
    SpotCheckParseError,
    score_column,
    score_text,
    spot_check,
    tone_split,
)


def profile_for(df, kinds, sensitive=()):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": c in sensitive}
                        for c in df.columns]}


# ---------------------------------------------------------------- score_text (pure lexicon)

POSITIVE_SENTENCES = [
    "This was an excellent experience, the staff were amazing and so helpful.",
    "Great value for money, I love the product and would recommend it to everyone.",
    "Fantastic service, fast delivery, and a wonderful team to deal with.",
]
NEGATIVE_SENTENCES = [
    "This was a terrible experience, the staff were rude and unhelpful.",
    "Awful product, way overpriced and it broke after a week, total waste of money.",
    "Horrible service, slow delivery, and the support team was dismissive.",
]


@pytest.mark.parametrize("text", POSITIVE_SENTENCES)
def test_score_text_obviously_positive(text):
    polarity, tone = score_text(text)
    assert tone == "pos"
    assert polarity > 0.15


@pytest.mark.parametrize("text", NEGATIVE_SENTENCES)
def test_score_text_obviously_negative(text):
    polarity, tone = score_text(text)
    assert tone == "neg"
    assert polarity < -0.15


def test_score_text_negation_flips_polarity():
    good_polarity, good_tone = score_text("The service was good.")
    not_good_polarity, not_good_tone = score_text("The service was not good.")
    assert good_tone == "pos"
    assert not_good_tone == "neg"
    assert not_good_polarity < 0
    assert not_good_polarity < good_polarity

    bad_polarity, bad_tone = score_text("The food was bad.")
    not_bad_polarity, not_bad_tone = score_text("The food was not bad.")
    assert bad_tone == "neg"
    assert not_bad_polarity >= 0  # "not bad" must score non-negative
    assert not_bad_tone != "neg"
    assert not_bad_polarity > bad_polarity


def test_score_text_no_sentiment_words_is_neutral():
    polarity, tone = score_text("The order arrived on Tuesday from the warehouse.")
    assert tone == "neu"
    assert polarity == 0.0


def test_score_text_intensifier_amplifies():
    plain, _ = score_text("The staff were good.")
    intensified, _ = score_text("The staff were extremely good.")
    assert intensified > plain


def test_score_text_polarity_always_bounded():
    for text in POSITIVE_SENTENCES + NEGATIVE_SENTENCES + ["", "no words here at all"]:
        polarity, _ = score_text(text)
        assert -1.0 <= polarity <= 1.0


# ---------------------------------------------------------------- score_column

def test_score_column_blank_and_nan_rows_come_back_none():
    df = pd.DataFrame(
        {"Why": ["Excellent service, loved it.", np.nan, "", "Terrible, awful experience.", "   "]},
        index=[0, 1, 3, 4, 7],
    ).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))
    scores = score_column(df, plan, "Why")

    assert len(scores) == 5
    assert scores[0] is not None and scores[0].tone == "pos"
    assert scores[1] is None  # NaN
    assert scores[2] is None  # empty string - nothing to score
    assert scores[3] is not None and scores[3].tone == "neg"
    assert scores[4] is None  # whitespace-only - nothing to score
    # row is carried through from the original (non-contiguous) dataframe index, never renumbered
    assert scores[0].row == 0
    assert scores[3].row == 4


def test_score_column_never_invents_a_score_for_blank_rows():
    df = pd.DataFrame({"Why": [np.nan, np.nan, ""]}).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))
    scores = score_column(df, plan, "Why")
    assert scores == [None, None, None]


# ---------------------------------------------------------------- tone_split

def _scores(tones):
    return [AnswerScore(row=i, text=f"answer {i}", polarity=0.0, tone=t) for i, t in enumerate(tones)]


def test_tone_split_sums_to_100_all_positive():
    ts = tone_split(_scores(["pos"] * 7))
    assert isinstance(ts, ToneSplit)
    assert ts.neg + ts.neu + ts.pos == 100
    assert ts.pos == 100 and ts.neg == 0 and ts.neu == 0


def test_tone_split_sums_to_100_all_neutral():
    ts = tone_split(_scores(["neu"] * 5))
    assert ts.neg + ts.neu + ts.pos == 100
    assert ts.neu == 100


def test_tone_split_sums_to_100_empty():
    ts = tone_split([])
    assert ts.neg + ts.neu + ts.pos == 100
    assert ts.neu == 100  # convention: no data reads as 100% neutral, not 0/0/0


@pytest.mark.parametrize("tones", [
    ["neg"] * 3 + ["neu"] * 4 + ["pos"] * 2,   # 9, uneven thirds
    ["neg"] * 1 + ["pos"] * 2,                  # 3, no neutral at all
    ["neg"] * 11 + ["neu"] * 11 + ["pos"] * 11,  # 33, divides evenly-ish
    ["pos"],                                     # 1
    ["neg"] * 97 + ["neu"] * 1 + ["pos"] * 2,   # skewed, common rounding edge case
])
def test_tone_split_sums_to_exactly_100_various_distributions(tones):
    ts = tone_split(_scores(tones))
    assert ts.neg + ts.neu + ts.pos == 100
    for v in (ts.neg, ts.neu, ts.pos):
        assert 0 <= v <= 100


# ---------------------------------------------------------------- spot_check

def _mixed_scores():
    return (
        [AnswerScore(row=i, text=f"negative answer {i}", polarity=-0.5, tone="neg") for i in range(0, 10)]
        + [AnswerScore(row=i, text=f"neutral answer {i}", polarity=0.0, tone="neu") for i in range(10, 20)]
        + [AnswerScore(row=i, text=f"positive answer {i}", polarity=0.6, tone="pos") for i in range(20, 30)]
    )


def _agreeing_reply(kwargs):
    sent = json.loads(kwargs["messages"][0]["content"])
    results = []
    for item in sent["answers"]:
        # agree with whatever the lexicon said, using the text to figure out which one it was
        if "negative" in item["text"]:
            tone = "neg"
        elif "positive" in item["text"]:
            tone = "pos"
        else:
            tone = "neu"
        results.append({"index": item["index"], "tone": tone})
    return json.dumps({"results": results})


def test_spot_check_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ClaudeNotConfigured):
        spot_check(_mixed_scores(), client=None, sample_size=10)


def test_spot_check_one_batched_call_and_respects_sample_size():
    client = FakeClaudeClient(_agreeing_reply)
    report = spot_check(_mixed_scores(), client=client, sample_size=12)
    assert len(client.calls) == 1
    assert report.sample_size == 12
    assert report.agreement_pct == 100.0
    assert len(report.pairs) == 12
    assert report.disagreements == []


def test_spot_check_sample_has_representative_spread_across_buckets():
    client = FakeClaudeClient(_agreeing_reply)
    report = spot_check(_mixed_scores(), client=client, sample_size=9)
    tones_seen = {p["lexicon_tone"] for p in report.pairs}
    assert len(tones_seen) > 1  # not just the first N rows, which would all be "neg"


def test_spot_check_reports_disagreements():
    def disagree_on_positive(kwargs):
        sent = json.loads(kwargs["messages"][0]["content"])
        results = []
        for item in sent["answers"]:
            if "positive" in item["text"]:
                tone = "neg"  # deliberately wrong, to exercise disagreement reporting
            elif "negative" in item["text"]:
                tone = "neg"
            else:
                tone = "neu"
            results.append({"index": item["index"], "tone": tone})
        return json.dumps({"results": results})

    client = FakeClaudeClient(disagree_on_positive)
    report = spot_check(_mixed_scores(), client=client, sample_size=30)
    assert report.agreement_pct < 100.0
    assert len(report.disagreements) > 0
    assert all(d["lexicon_tone"] != d["claude_tone"] for d in report.disagreements)
    assert len(report.disagreements) <= 20


def test_spot_check_raises_cleanly_on_malformed_json():
    client = FakeClaudeClient("not json at all")
    with pytest.raises(SpotCheckParseError):
        spot_check(_mixed_scores(), client=client, sample_size=5)


def test_spot_check_raises_cleanly_on_incomplete_results():
    # only ever answers for index 0, however many answers are sent
    client = FakeClaudeClient(json.dumps({"results": [{"index": 0, "tone": "neg"}]}))
    with pytest.raises(SpotCheckParseError):
        spot_check(_mixed_scores(), client=client, sample_size=5)


def test_spot_check_raises_cleanly_on_bad_tone_value():
    def bad_tone_reply(kwargs):
        sent = json.loads(kwargs["messages"][0]["content"])
        results = [{"index": item["index"], "tone": "very_negative"} for item in sent["answers"]]
        return json.dumps({"results": results})

    client = FakeClaudeClient(bad_tone_reply)
    with pytest.raises(SpotCheckParseError):
        spot_check(_mixed_scores(), client=client, sample_size=5)
