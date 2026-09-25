"""Optional per-answer tone classification via Jev, an AI service from TypeSafe AI
(https://docs.typesafe.ai). This is a narrow, approved trial: Jev is used for sentiment/tone
classification ONLY, and nowhere else in this app. Nothing here is imported or called automatically -
`sentiment.score_column_with_jev` is opt-in, a caller must pass a configured client.

Shape deliberately mirrors `embeddings.py`'s `EmbeddingClient`/`VoyageEmbeddingClient`/
`FakeEmbeddingClient` split (one-method Protocol, a real network-backed implementation, a deterministic
test double that records its calls) and follows `app/auth.py:_fetch_jwks`'s precedent for calling an
external HTTPS API: plain `urllib.request`, a short timeout, a hard cap on how many response bytes are
read, no new HTTP dependency (`requests`/`httpx`) added to `requirements.txt`.

This module is intentionally small and single-purpose: a general-purpose multi-question TypeSafe client
is NOT built here, only the one "tone" question this trial covers (see docs/DECISIONS.md for why the
trial is scoped to sentiment and not column-kind detection or theme merge/split flags).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Literal, Protocol, runtime_checkable

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
JEV_TIMEOUT_SECONDS = 10
JEV_MAX_RESPONSE_BYTES = 16 * 1024  # replies are tiny (one choice + a few floats); guard against a rogue/huge body
# Roughly one order of magnitude below Jev's ~64k token context budget, using a crude chars-per-token
# proxy (~4). This is not a practical limit for a single survey answer, but the brief asks for defensive
# validation anyway rather than trusting an unbounded string into the request.
MAX_TEXT_CHARS = 200_000
PROBABILITY_SUM_TOLERANCE = 0.02  # floats from an external API; do not demand an exact 1.0

Tone = Literal["neg", "neu", "pos"]

# Jev's "negative"/"neutral"/"positive" strings mapped onto this codebase's existing tone vocabulary
# (see `AnswerScore.tone` in schema.py, and the lexicon's own buckets in sentiment.py).
_JEV_CHOICE_TO_TONE: dict[str, Tone] = {"negative": "neg", "neutral": "neu", "positive": "pos"}

_QUESTIONS = {
    "tone": {
        "type": "choice",
        "instructions": "Judge the overall tone of this survey answer.",
        "criteria": {
            "negative": "The answer expresses dissatisfaction, criticism, or a negative experience.",
            "neutral": "The answer is factual, mixed, or does not lean clearly positive or negative.",
            "positive": "The answer expresses satisfaction, praise, or a positive experience.",
        },
    },
}


class JevNotConfigured(RuntimeError):
    """Raised instead of ever making a network call when TYPESAFE_API_KEY is empty/missing. Mirrors
    `embeddings.EmbeddingNotConfigured`."""


class JevError(RuntimeError):
    """Raised for anything else that stops a Jev classification being trusted: a non-2xx HTTP status, a
    malformed or incomplete response body, a `choice` that isn't "negative"/"neutral"/"positive", a
    `probabilities` dict that doesn't sum close to 1, or a `confidence` outside 0..1. Nothing unvalidated
    ever reaches an `AnswerScore`."""


@runtime_checkable
class JevClient(Protocol):
    """Anything that can classify one answer's tone. Mirrors `EmbeddingClient`'s one-method shape."""

    def classify_tone(self, text: str) -> tuple[Tone, float]:
        ...


class HttpJevClient:
    """Real implementation, via `urllib.request` (same style as `app/auth.py:_fetch_jwks`): POST JSON,
    `Authorization: Bearer` header, ~10s timeout, response capped at `JEV_MAX_RESPONSE_BYTES`. Retries
    once on a transient network error or a 5xx status; never retries a 4xx (bad request/auth/rate-limit -
    retrying blindly on those would just repeat the same failure or make a 429 worse).

    Reads `TYPESAFE_API_KEY` from the environment; raises `JevNotConfigured` if it is unset, before ever
    touching the network.
    """

    def __init__(self, timeout: float = JEV_TIMEOUT_SECONDS, model: str = JEV_MODEL) -> None:
        api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            raise JevNotConfigured(
                "TYPESAFE_API_KEY is not set. Jev sentiment needs it; nothing was sent over the network."
            )
        self._api_key = api_key
        self.timeout = timeout
        self.model = model

    def classify_tone(self, text: str) -> tuple[Tone, float]:
        if not text or not text.strip():
            raise JevError("classify_tone called with empty text.")
        if len(text) > MAX_TEXT_CHARS:
            raise JevError(f"text too long for one Jev call ({len(text)} characters).")

        body = json.dumps({"state": text, "model": self.model, "questions": _QUESTIONS}).encode("utf-8")
        req = urllib.request.Request(
            JEV_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        last_error: Exception | None = None
        for attempt in range(2):  # one retry, transient errors / 5xx only - never on a 4xx
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read(JEV_MAX_RESPONSE_BYTES + 1)
                if len(raw) > JEV_MAX_RESPONSE_BYTES:
                    raise JevError("Jev response was larger than expected.")
                return _parse_jev_response(raw)
            except urllib.error.HTTPError as e:
                if 400 <= e.code < 500:  # bad request/auth/429 - retrying would not help
                    raise JevError(f"Jev returned HTTP {e.code}.") from e
                last_error = e
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise JevError(f"Jev request failed after a retry: HTTP {e.code}.") from e
            except JevError:
                raise
            except (urllib.error.URLError, OSError) as e:  # transient network error
                last_error = e
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise JevError(f"Jev request failed after a retry: {last_error}") from last_error
        # Unreachable: every branch above either returns or raises.
        raise JevError(f"Jev request failed: {last_error}")  # pragma: no cover


def _parse_jev_response(raw: bytes) -> tuple[Tone, float]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JevError(f"Jev response was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise JevError("Jev response was not a JSON object.")

    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise JevError('Jev response is missing an "answers" object.')
    tone_answer = answers.get("tone")
    if not isinstance(tone_answer, dict):
        raise JevError('Jev response is missing an "answers.tone" object.')

    choice = tone_answer.get("choice")
    if choice not in _JEV_CHOICE_TO_TONE:
        raise JevError(f"Jev returned an unrecognised tone choice: {choice!r}")

    confidence = tone_answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise JevError(f"Jev returned a non-numeric confidence: {confidence!r}")
    confidence = float(confidence)
    if not (0.0 <= confidence <= 1.0):
        raise JevError(f"Jev returned a confidence outside 0..1: {confidence!r}")

    probabilities = tone_answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(_JEV_CHOICE_TO_TONE):
        raise JevError(f"Jev returned malformed probabilities: {probabilities!r}")
    values: list[float] = []
    for v in probabilities.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise JevError(f"Jev returned a non-numeric probability: {probabilities!r}")
        values.append(float(v))
    total = sum(values)
    if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
        raise JevError(f"Jev's probabilities do not sum to 1 (got {total}): {probabilities!r}")

    return _JEV_CHOICE_TO_TONE[choice], confidence


class FakeJevClient:
    """Deterministic, network-free stand-in for tests. Constructed with either a fixed `(tone,
    confidence)` pair or a callable of the text that returns one; records every text it was asked to
    classify in `self.calls`. Mirrors `FakeEmbeddingClient`/`sentiment.FakeClaudeClient`."""

    def __init__(self, result: tuple[Tone, float] | Callable[[str], tuple[Tone, float]]) -> None:
        self._result = result
        self.calls: list[str] = []

    def classify_tone(self, text: str) -> tuple[Tone, float]:
        self.calls.append(text)
        if callable(self._result):
            return self._result(text)
        return self._result
