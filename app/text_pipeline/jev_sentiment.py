"""Per-answer classification via Jev, an AI service from TypeSafe AI (https://docs.typesafe.ai). Started
as a narrow, approved trial scoped to sentiment/tone only (see docs/DECISIONS.md for why that trial was
scoped away from column-kind detection and theme merge/split flags). Extended 2026-10-21 (docs/TODO.md,
"Look inside Other" feature) with a second, DYNAMIC choice-question capability: `classify_choice` takes
its `instructions`/`criteria` per call instead of a hardcoded question, used for high-volume per-answer
classification against a label set Claude decides once per run (never per-answer) - see
`app/text_pipeline/labeling.py`'s own consolidation step for where that label set comes from. Nothing
here is imported or called automatically - every caller must pass a configured client explicitly.

Shape deliberately mirrors `embeddings.py`'s `EmbeddingClient`/`VoyageEmbeddingClient`/
`FakeEmbeddingClient` split (one-method-per-capability Protocol, a real network-backed implementation, a
deterministic test double that records its calls) and follows `app/auth.py:_fetch_jwks`'s precedent for
calling an external HTTPS API: plain `urllib.request`, a short timeout, a hard cap on how many response
bytes are read, no new HTTP dependency (`requests`/`httpx`) added to `requirements.txt`.

Schema confirmed directly against TypeSafe's own docs (docs.typesafe.ai/primitives/choice, 2026-10-21)
before this extension was written, not assumed from a third-party summary: a Choice question is
`{"type": "choice", "instructions": str, "criteria": {option_name: description_or_null, ...}}` (this
module's own pre-existing `_QUESTIONS["tone"]` already matched this shape), capped at 255 options per
request, and the response carries `choice`/`confidence`/`probabilities` - exactly what `_parse_jev_response`
already validated for the fixed tone question, now generalized below.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, runtime_checkable

JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
JEV_TIMEOUT_SECONDS = 10
JEV_MAX_RESPONSE_BYTES = 16 * 1024  # replies are tiny (one choice + a few floats); guard against a rogue/huge body
# Roughly one order of magnitude below Jev's ~64k token context budget, using a crude chars-per-token
# proxy (~4). This is not a practical limit for a single survey answer, but the brief asks for defensive
# validation anyway rather than trusting an unbounded string into the request.
MAX_TEXT_CHARS = 200_000
PROBABILITY_SUM_TOLERANCE = 0.02  # floats from an external API; do not demand an exact 1.0
MAX_CRITERIA_OPTIONS = 255  # TypeSafe's own documented cap on a single Choice question's option count

Tone = Literal["neg", "neu", "pos"]


@dataclass(frozen=True)
class ChoiceAnswer:
    """One `classify_choice` result. Deliberately returns ALL THREE fields (not just the top choice,
    unlike `classify_tone`'s `(Tone, float)` pair) - a caller classifying against a dynamic label set
    (e.g. "Look inside Other"'s known-themes-plus-new-themes list) needs `probabilities` to decide its
    own no-confident-match threshold, which `_JEV_CHOICE_TO_TONE`'s fixed 3-way mapping never had to
    consider."""
    choice: str  # the selected option's key, one of the `criteria` dict's own keys - never re-mapped
    confidence: float  # 0..1
    probabilities: dict[str, float]  # one entry per `criteria` key, sums to ~1

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
    malformed or incomplete response body, a `choice` not among the question's own valid options, a
    `probabilities` dict that doesn't sum close to 1, or a `confidence` outside 0..1. Nothing unvalidated
    ever reaches an `AnswerScore` or a `Theme` row."""


@runtime_checkable
class JevClient(Protocol):
    """Anything that can classify one answer, one question at a time. `classify_tone` is the original,
    fixed question; `classify_choice` (2026-10-21) is the general case it was always a special case of -
    a caller supplies its own `instructions`/`criteria` instead of a hardcoded question."""

    def classify_tone(self, text: str) -> tuple[Tone, float]:
        ...

    def classify_choice(
        self, text: str, *, question_key: str, instructions: str, criteria: dict[str, str | None],
    ) -> ChoiceAnswer:
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
        answer = self._request_answer("tone", _QUESTIONS["tone"], text, what="classify_tone")
        choice, confidence, _probabilities = _validate_choice_answer(
            answer, valid_choices=set(_JEV_CHOICE_TO_TONE), what="tone",
        )
        return _JEV_CHOICE_TO_TONE[choice], confidence

    def classify_choice(
        self, text: str, *, question_key: str, instructions: str, criteria: dict[str, str | None],
    ) -> ChoiceAnswer:
        if not criteria:
            raise JevError("classify_choice called with no criteria (no options to choose between).")
        if len(criteria) > MAX_CRITERIA_OPTIONS:
            raise JevError(
                f"classify_choice called with {len(criteria)} options; Jev's own Choice question caps "
                f"at {MAX_CRITERIA_OPTIONS}."
            )
        spec = {"type": "choice", "instructions": instructions, "criteria": criteria}
        answer = self._request_answer(question_key, spec, text, what="classify_choice")
        choice, confidence, probabilities = _validate_choice_answer(
            answer, valid_choices=set(criteria), what=question_key,
        )
        return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=probabilities)

    def _request_answer(self, question_key: str, question_spec: dict, text: str, *, what: str) -> dict:
        """Shared HTTP mechanics for any single-question Jev call (`classify_tone`/`classify_choice`
        both build their own `question_spec` and call this): POST, retry policy, response-size guard,
        and pulling `answers[question_key]` back out - everything up to but not including validating
        THAT sub-object's own fields, which differs per question (`tone`'s fixed 3-way choice vs a
        dynamic `classify_choice` criteria set) and is handled by `_validate_choice_answer` instead."""
        if not text or not text.strip():
            raise JevError(f"{what} called with empty text.")
        if len(text) > MAX_TEXT_CHARS:
            raise JevError(f"text too long for one Jev call ({len(text)} characters).")

        body = json.dumps(
            {"state": text, "model": self.model, "questions": {question_key: question_spec}},
        ).encode("utf-8")
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
                return _parse_answer_object(raw, question_key)
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


def _parse_answer_object(raw: bytes, question_key: str) -> dict:
    """Question-agnostic half of response parsing: valid JSON, a top-level `answers` object, and that
    object's own `question_key` entry is itself an object. Returns that sub-object unvalidated beyond
    its shape - `_validate_choice_answer` below checks its actual fields, since what counts as valid
    differs per question (fixed tone choices vs a dynamic criteria set)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JevError(f"Jev response was not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise JevError("Jev response was not a JSON object.")

    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise JevError('Jev response is missing an "answers" object.')
    answer = answers.get(question_key)
    if not isinstance(answer, dict):
        raise JevError(f'Jev response is missing an "answers.{question_key}" object.')
    return answer


def _validate_choice_answer(
    answer: dict, *, valid_choices: set[str], what: str,
) -> tuple[str, float, dict[str, float]]:
    """Shared field validation for any Choice-type answer (`tone`'s fixed 3 choices, or a
    `classify_choice` caller's own dynamic set) - `choice` must be one of `valid_choices`, `confidence`
    must be a real number in 0..1, `probabilities` must have exactly `valid_choices`' own keys and sum to
    ~1. Nothing unvalidated ever reaches `classify_tone`'s `Tone` mapping or a `ChoiceAnswer`."""
    choice = answer.get("choice")
    if choice not in valid_choices:
        raise JevError(f"Jev returned an unrecognised {what} choice: {choice!r}")

    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise JevError(f"Jev returned a non-numeric confidence: {confidence!r}")
    confidence = float(confidence)
    if not (0.0 <= confidence <= 1.0):
        raise JevError(f"Jev returned a confidence outside 0..1: {confidence!r}")

    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != valid_choices:
        raise JevError(f"Jev returned malformed probabilities: {probabilities!r}")
    values: list[float] = []
    for v in probabilities.values():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise JevError(f"Jev returned a non-numeric probability: {probabilities!r}")
        values.append(float(v))
    total = sum(values)
    if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
        raise JevError(f"Jev's probabilities do not sum to 1 (got {total}): {probabilities!r}")

    return choice, confidence, {k: float(v) for k, v in probabilities.items()}


class FakeJevClient:
    """Deterministic, network-free stand-in for tests. `tone_result` is either a fixed `(tone,
    confidence)` pair or a callable of the text that returns one, for `classify_tone`. `choice_result`
    (optional) is the equivalent for `classify_choice` - either a fixed `ChoiceAnswer` or a callable of
    `(text, question_key, instructions, criteria)` that returns one; omitted, `classify_choice` picks the
    first `criteria` key with confidence 1.0, a reasonable default for tests that don't care which
    option is chosen. Records every call in `self.calls`/`self.choice_calls`. Mirrors
    `FakeEmbeddingClient`/`sentiment.FakeClaudeClient`."""

    def __init__(
        self,
        tone_result: tuple[Tone, float] | Callable[[str], tuple[Tone, float]],
        choice_result: ChoiceAnswer | Callable[[str, str, str, dict[str, str | None]], ChoiceAnswer] | None = None,
    ) -> None:
        self._tone_result = tone_result
        self._choice_result = choice_result
        self.calls: list[str] = []
        self.choice_calls: list[dict[str, Any]] = []

    def classify_tone(self, text: str) -> tuple[Tone, float]:
        self.calls.append(text)
        if callable(self._tone_result):
            return self._tone_result(text)
        return self._tone_result

    def classify_choice(
        self, text: str, *, question_key: str, instructions: str, criteria: dict[str, str | None],
    ) -> ChoiceAnswer:
        self.choice_calls.append(
            {"text": text, "question_key": question_key, "instructions": instructions, "criteria": criteria},
        )
        if self._choice_result is None:
            first = next(iter(criteria))
            return ChoiceAnswer(choice=first, confidence=1.0, probabilities={k: 1.0 if k == first else 0.0 for k in criteria})
        if callable(self._choice_result):
            return self._choice_result(text, question_key, instructions, criteria)
        return self._choice_result
