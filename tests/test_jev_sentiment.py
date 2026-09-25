"""Optional Jev (TypeSafe AI) sentiment trial: `app/text_pipeline/jev_sentiment.py` and
`sentiment.score_column_with_jev`. NO real network anywhere - `HttpJevClient`'s one exercised test
monkeypatches `urllib.request.urlopen` itself, never opens a real socket."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import numpy as np
import pandas as pd
import pytest

from app.cleaning import plan_cleaning
from app.text_pipeline import AnswerScore, score_column, score_column_with_jev, score_text
from app.text_pipeline.jev_sentiment import (
    FakeJevClient,
    HttpJevClient,
    JevError,
    JevNotConfigured,
)


def profile_for(df, kinds, sensitive=()):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": c in sensitive}
                        for c in df.columns]}


def _df_and_plan(values, index=None):
    df = pd.DataFrame({"Why": values}, index=index).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))
    return df, plan


# ---------------------------------------------------------------- FakeJevClient round-trip

def test_score_column_with_jev_round_trips_fixed_result():
    df, plan = _df_and_plan(["Loved the service.", "It was fine.", "Awful, would not return."])
    client = FakeJevClient(("pos", 0.9))
    scores = score_column_with_jev(df, plan, "Why", client)

    assert len(scores) == 3
    assert client.calls == ["Loved the service.", "It was fine.", "Awful, would not return."]
    for s in scores:
        assert s is not None
        assert s.tone == "pos"
        assert s.polarity == pytest.approx(0.9)


def test_score_column_with_jev_uses_callable_result_per_text():
    def by_text(text: str):
        if "great" in text:
            return ("pos", 0.8)
        if "terrible" in text:
            return ("neg", 0.7)
        return ("neu", 0.5)

    df, plan = _df_and_plan(["This was great", "This was terrible", "This was ordinary"])
    client = FakeJevClient(by_text)
    scores = score_column_with_jev(df, plan, "Why", client)

    assert [s.tone for s in scores] == ["pos", "neg", "neu"]
    assert scores[0].polarity == pytest.approx(0.8)
    assert scores[1].polarity == pytest.approx(-0.7)
    assert scores[2].polarity == pytest.approx(0.0)  # neutral is never scaled by confidence


# ---------------------------------------------------------------- blank / NaN rows

def test_score_column_with_jev_blank_and_nan_rows_come_back_none():
    df, plan = _df_and_plan(
        ["Loved it", np.nan, "", "Terrible", "   "],
        index=[0, 1, 3, 4, 7],
    )
    client = FakeJevClient(("pos", 0.6))
    scores = score_column_with_jev(df, plan, "Why", client)

    assert len(scores) == 5
    assert scores[0] is not None
    assert scores[1] is None  # NaN
    assert scores[2] is None  # empty string
    assert scores[3] is not None
    assert scores[4] is None  # whitespace-only
    # blank rows never reach the client
    assert client.calls == ["Loved it", "Terrible"]
    # row index carried through from the original (non-contiguous) dataframe index
    assert scores[0].row == 0
    assert scores[3].row == 4


def test_score_column_with_jev_never_invents_a_score_for_blank_rows():
    df, plan = _df_and_plan([np.nan, np.nan, ""])
    client = FakeJevClient(("neu", 0.5))
    scores = score_column_with_jev(df, plan, "Why", client)
    assert scores == [None, None, None]
    assert client.calls == []


# ---------------------------------------------------------------- lexicon path untouched

def test_lexicon_score_column_still_works_unchanged():
    """Proves the existing free lexicon path is completely unaffected by the Jev addition."""
    df, plan = _df_and_plan(
        ["Excellent service, loved it.", np.nan, "", "Terrible, awful experience.", "   "],
        index=[0, 1, 3, 4, 7],
    )
    scores = score_column(df, plan, "Why")

    assert len(scores) == 5
    assert scores[0] is not None and scores[0].tone == "pos"
    assert scores[1] is None
    assert scores[2] is None
    assert scores[3] is not None and scores[3].tone == "neg"
    assert scores[4] is None
    # same polarity/tone score_text would give directly - the lexicon math itself is untouched
    expected_polarity, expected_tone = score_text("Excellent service, loved it.")
    assert scores[0].polarity == expected_polarity
    assert scores[0].tone == expected_tone


# ---------------------------------------------------------------- max_answers cap / fallback

def test_max_answers_caps_jev_calls_and_falls_back_to_lexicon():
    texts = ["Great stuff", "Amazing work", "Terrible service", "Awful experience", "It was fine"]
    df, plan = _df_and_plan(texts)
    client = FakeJevClient(("pos", 0.99))  # deliberately different from what the lexicon would say
    scores = score_column_with_jev(df, plan, "Why", client, max_answers=2)

    assert len(scores) == 5
    # only the first 2 non-empty rows went to Jev
    assert client.calls == ["Great stuff", "Amazing work"]
    assert scores[0].polarity == pytest.approx(0.99) and scores[0].tone == "pos"
    assert scores[1].polarity == pytest.approx(0.99) and scores[1].tone == "pos"
    # the rest fell back to the free lexicon, not Jev, and not dropped
    for i, text in enumerate(texts[2:], start=2):
        expected_polarity, expected_tone = score_text(text)
        assert scores[i] is not None
        assert scores[i].polarity == expected_polarity
        assert scores[i].tone == expected_tone


def test_max_answers_none_sends_every_row_to_jev():
    texts = ["a good one", "another good one", "a third good one"]
    df, plan = _df_and_plan(texts)
    client = FakeJevClient(("pos", 0.5))
    scores = score_column_with_jev(df, plan, "Why", client, max_answers=None)
    assert len(client.calls) == 3
    assert all(s.polarity == pytest.approx(0.5) for s in scores)


def test_max_answers_only_counts_non_empty_rows_toward_the_cap():
    df, plan = _df_and_plan(["first", np.nan, "second", "", "third", "fourth"])
    client = FakeJevClient(("neu", 0.4))
    scores = score_column_with_jev(df, plan, "Why", client, max_answers=2)
    # blanks don't consume the cap; exactly the first two non-empty answers go to Jev
    assert client.calls == ["first", "second"]
    non_empty = [s for s in scores if s is not None]
    assert len(non_empty) == 4  # first, second, third, fourth - all still scored, just by two methods


def test_max_answers_larger_than_row_count_sends_everything_to_jev():
    df, plan = _df_and_plan(["only one row"])
    client = FakeJevClient(("pos", 0.7))
    scores = score_column_with_jev(df, plan, "Why", client, max_answers=100)
    assert client.calls == ["only one row"]
    assert scores[0].polarity == pytest.approx(0.7)


# ---------------------------------------------------------------- JevNotConfigured (no network attempted)

def test_http_jev_client_raises_not_configured_without_api_key(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def fail_if_called(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("urlopen must not be called when TYPESAFE_API_KEY is unset")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_called)
    with pytest.raises(JevNotConfigured):
        HttpJevClient()


# ---------------------------------------------------------------- HttpJevClient request/response, mocked urlopen

class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, n=-1):
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok_body(choice="positive", confidence=0.82, probabilities=None):
    if probabilities is None:
        probabilities = {"negative": 0.05, "neutral": 0.13, "positive": 0.82}
    return json.dumps({
        "model": "jev-1.13.0",
        "answers": {"tone": {
            "type": "choice", "choice": choice, "probabilities": probabilities, "confidence": confidence,
        }},
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }).encode("utf-8")


def test_http_jev_client_builds_request_and_parses_valid_response(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout
        return _FakeHttpResponse(_ok_body())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = HttpJevClient()
    tone, confidence = client.classify_tone("Great product, very happy.")

    assert tone == "pos"
    assert confidence == pytest.approx(0.82)
    assert captured["url"] == "https://api.typesafe.ai/v1/systemone"
    assert captured["method"] == "POST"
    assert captured["headers"]["authorization"] == "Bearer test-key-123"
    assert captured["body"]["state"] == "Great product, very happy."
    assert captured["body"]["model"] == "jev-latest"
    assert set(captured["body"]["questions"]["tone"]["criteria"]) == {"negative", "neutral", "positive"}


_EVEN_PROBS = {"negative": 1 / 3, "neutral": 1 / 3, "positive": 1 / 3}


@pytest.mark.parametrize("choice,tone", [("negative", "neg"), ("neutral", "neu"), ("positive", "pos")])
def test_http_jev_client_maps_every_valid_choice(monkeypatch, choice, tone):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(
            _ok_body(choice=choice, confidence=0.5, probabilities=_EVEN_PROBS)
        ),
    )
    result_tone, confidence = HttpJevClient().classify_tone("some text")
    assert result_tone == tone
    assert confidence == pytest.approx(0.5)


def test_http_jev_client_raises_on_bad_choice(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(_ok_body(choice="mixed")),
    )
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")


def test_http_jev_client_raises_on_bad_probabilities_sum(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    bad_probs = {"negative": 0.1, "neutral": 0.1, "positive": 0.1}  # sums to 0.3, not 1
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(_ok_body(probabilities=bad_probs)),
    )
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")


def test_http_jev_client_raises_on_missing_probability_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    bad_probs = {"negative": 0.5, "positive": 0.5}  # missing "neutral"
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(_ok_body(probabilities=bad_probs)),
    )
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.5, "high", None])
def test_http_jev_client_raises_on_bad_confidence(monkeypatch, bad_confidence):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(_ok_body(confidence=bad_confidence)),
    )
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")


def test_http_jev_client_raises_on_malformed_json(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(b"not json at all"),
    )
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")


def test_http_jev_client_raises_on_missing_answers_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHttpResponse(json.dumps({"model": "jev-1.13.0"}).encode("utf-8")),
    )
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")


def test_http_jev_client_does_not_retry_on_4xx(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")
    assert calls["n"] == 1  # never retried on a 4xx


def test_http_jev_client_retries_once_on_transient_error_then_succeeds(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    calls = {"n": 0}

    def flaky_then_ok(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("connection reset")
        return _FakeHttpResponse(_ok_body())

    monkeypatch.setattr(urllib.request, "urlopen", flaky_then_ok)
    monkeypatch.setattr("app.text_pipeline.jev_sentiment.time.sleep", lambda *_: None)
    tone, confidence = HttpJevClient().classify_tone("some text")
    assert calls["n"] == 2
    assert tone == "pos"


def test_http_jev_client_raises_after_exhausting_retry_on_persistent_transient_error(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    calls = {"n": 0}

    def always_fails(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.URLError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", always_fails)
    monkeypatch.setattr("app.text_pipeline.jev_sentiment.time.sleep", lambda *_: None)
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")
    assert calls["n"] == 2  # one original attempt + one retry, then it gives up


def test_http_jev_client_response_size_cap(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key-123")
    huge = b" " * (16 * 1024 + 1)  # one byte over JEV_MAX_RESPONSE_BYTES

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeHttpResponse(huge))
    with pytest.raises(JevError):
        HttpJevClient().classify_tone("some text")
