"""Sentiment scoring for individual answers (SPEC.md section 2, "Sentiment" row: "Lexicon in code, all
answers. Claude spot-checks about 100 samples to report scorer agreement").

This runs independently of theme clustering (`clustering.py`, `pipeline.py`) - it scores each answer on
its own, not a group of answers - though it shares the same masked-text input, via
`app.cleaning.payload.model_safe_column` (the only door text leaves through).

Two halves:
  - `score_text` / `score_column` / `tone_split`: pure code, no network, no model calls, ever. This is
    what runs for every answer in production.
  - `spot_check`: an OPTIONAL Claude call that judges a representative sample and reports how often it
    agrees with the lexicon, for a quality report. Never required for scoring to work; lazy-imports
    `anthropic` and needs `ANTHROPIC_API_KEY`, following the same pattern as `app/profiling/claude_hook.py`.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from ..cleaning.models import CleaningPlan
from ..cleaning.payload import model_safe_column
from ..chart_data import ToneSplit
from .schema import AnswerScore

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_DISAGREEMENTS_SHOWN = 20  # SpotCheckReport.disagreements is for display, never the full raw sample

# ---------------------------------------------------------------------------------------------------------
# Lexicon
#
# A hand-built list of a few hundred common English words, grouped by strength so a word's weight reflects
# how strongly it usually reads as positive/negative in a survey answer, not just its direction. Deliberately
# NOT a heavy third-party sentiment package (the brief's own preference: no new native/compiled dependency
# for a job a focused word list can do). See docs/DECISIONS.md for this lexicon's honest coverage and limits.
#
# Weight bands: strong = +/-1.0 (unambiguous, high-conviction wording), moderate = +/-0.6 (everyday praise/
# complaint vocabulary), mild = +/-0.3 (lukewarm wording - "fine", "okay", "meh" - real signal, but weaker
# than someone reaching for "amazing" or "terrible").
# ---------------------------------------------------------------------------------------------------------

_STRONG_POS = [
    "excellent", "amazing", "fantastic", "outstanding", "wonderful", "perfect", "love", "loved", "loving",
    "incredible", "superb", "brilliant", "exceptional", "phenomenal", "awesome", "best", "delighted",
    "thrilled", "impressed", "flawless", "recommend", "recommended", "exceeded", "delightful",
]
_MODERATE_POS = [
    "good", "great", "nice", "happy", "satisfied", "satisfying", "helpful", "friendly", "easy", "fast",
    "quick", "reliable", "valuable", "worth", "value", "efficient", "professional", "clean", "comfortable",
    "convenient", "affordable", "responsive", "polite", "courteous", "smooth", "pleasant", "enjoyable",
    "effective", "useful", "solid", "consistent", "knowledgeable", "attentive", "supportive", "clear",
    "simple", "accurate", "timely", "secure", "trustworthy", "generous", "fair", "improved", "improvement",
    "upgrade", "upgraded", "succeed", "success", "successful", "praise", "praised", "kind", "caring",
    "welcoming", "smooth", "seamless", "intuitive", "generous", "prompt", "speedy", "durable", "sturdy",
    "tasty", "delicious", "fresh", "cheerful", "grateful", "appreciate", "appreciated", "enjoy", "enjoyed",
]
_MILD_POS = [
    "fine", "okay", "ok", "decent", "reasonable", "adequate", "acceptable", "average", "alright",
    "sufficient", "satisfactory", "tolerable", "fair", "passable",
]

_STRONG_NEG = [
    "terrible", "awful", "horrible", "worst", "hate", "hated", "hating", "disgusting", "useless", "scam",
    "fraud", "ripoff", "unacceptable", "disaster", "nightmare", "furious", "outraged", "appalling",
    "atrocious", "pathetic", "garbage", "worthless", "avoid", "disgraceful", "unbearable", "despise",
]
_MODERATE_NEG = [
    "bad", "poor", "slow", "expensive", "confusing", "disappointed", "disappointing", "frustrating",
    "frustrated", "annoying", "annoyed", "difficult", "problem", "problems", "issue", "issues", "complaint",
    "complaints", "delay", "delayed", "delays", "rude", "unhelpful", "unresponsive", "unreliable", "faulty",
    "defective", "damaged", "overpriced", "costly", "pricey", "misleading", "dishonest", "incompetent",
    "lazy", "messy", "dirty", "uncomfortable", "inconvenient", "complicated", "confused", "angry", "upset",
    "unhappy", "dissatisfied", "waste", "wasted", "lacking", "lacks", "missing", "fail", "failed",
    "failure", "broken", "glitchy", "buggy", "crash", "crashes", "crashed", "stuck", "laggy", "unfair",
    "cancel", "cancelled", "refund", "complain", "complained", "worse", "hostile", "condescending",
    "dismissive", "ignored", "ignoring", "overcharged", "understaffed", "chaotic", "unorganized",
    "disorganized", "unprofessional", "stressful", "painful", "regret", "regretted", "unfriendly",
]
_MILD_NEG = [
    "meh", "bland", "boring", "mediocre", "forgettable", "underwhelming", "unimpressed", "subpar",
    "middling", "stale", "clunky", "dated", "cramped", "noisy",
]

SENTIMENT_WEIGHTS: dict[str, float] = {}
for _word in _STRONG_POS:
    SENTIMENT_WEIGHTS[_word] = 1.0
for _word in _MODERATE_POS:
    SENTIMENT_WEIGHTS[_word] = 0.6
for _word in _MILD_POS:
    SENTIMENT_WEIGHTS[_word] = 0.3
for _word in _STRONG_NEG:
    SENTIMENT_WEIGHTS[_word] = -1.0
for _word in _MODERATE_NEG:
    SENTIMENT_WEIGHTS[_word] = -0.6
for _word in _MILD_NEG:
    SENTIMENT_WEIGHTS[_word] = -0.3

# Negation flips the polarity of the next sentiment-bearing word within a short window. Both the
# apostrophe and no-apostrophe spellings are listed because survey text often drops apostrophes.
NEGATIONS: set[str] = {
    "not", "no", "never", "cannot", "cant", "can't", "dont", "don't", "doesnt", "doesn't", "didnt",
    "didn't", "isnt", "isn't", "wasnt", "wasn't", "werent", "weren't", "arent", "aren't", "wont", "won't",
    "wouldnt", "wouldn't", "shouldnt", "shouldn't", "couldnt", "couldn't", "without", "hardly", "barely",
    "neither", "nor", "nobody", "nothing", "none", "lack", "lacking",
}
NEGATION_WINDOW = 3  # how many following tokens a negation can still flip

# Intensifiers scale the weight of the next sentiment word; >1 amplifies, <1 softens ("somewhat good").
INTENSIFIERS: dict[str, float] = {
    "very": 1.5, "extremely": 1.8, "incredibly": 1.7, "really": 1.3, "so": 1.3, "super": 1.4,
    "highly": 1.4, "absolutely": 1.6, "totally": 1.3, "completely": 1.4, "utterly": 1.5, "quite": 1.2,
    "particularly": 1.2, "especially": 1.2, "truly": 1.3, "genuinely": 1.2,
    "somewhat": 0.6, "slightly": 0.5, "fairly": 0.8, "rather": 0.8, "kinda": 0.6, "kind": 0.7,
}
INTENSIFIER_WINDOW = 2

_TOKEN_RE = re.compile(r"[a-z']+")

# Tone thresholds. `score_text` averages the weight of every matched sentiment word (not diluted by
# sentence length), so a single mild word already lands at +/-0.3 and a single moderate word at +/-0.6.
# The neutral band only needs to catch scores near zero: genuine cancellation (roughly equal positive and
# negative wording in the same answer) or a heavily-softened word (e.g. "slightly good" = 0.3 * 0.5 =
# 0.15). 0.15 sits below that softened-mild-word floor and well below an unmodified mild word (0.3), so:
#   - any answer with a single recognised sentiment word (even mild) clears the band and gets a tone,
#   - only near-zero net scores land in "neu",
#   - "no sentiment words matched at all" scores exactly 0.0, which is also inside the band, so
#     "no signal" and "neutral" naturally end up the same bucket.
NEG_THRESHOLD = -0.15
POS_THRESHOLD = 0.15


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def score_text(text: str) -> tuple[float, Literal["neg", "neu", "pos"]]:
    """Lexicon-score one string. Pure function, no I/O. Returns (polarity in [-1, 1], tone bucket)."""
    tokens = _tokenize(text)
    contributions: list[float] = []
    mult = 1.0
    mult_left = 0
    negate_left = 0

    for tok in tokens:
        if tok in NEGATIONS:
            negate_left = NEGATION_WINDOW
            if mult_left > 0:
                mult_left -= 1
                if mult_left == 0:
                    mult = 1.0
            continue
        if tok in INTENSIFIERS:
            mult = INTENSIFIERS[tok]
            mult_left = INTENSIFIER_WINDOW
            if negate_left > 0:
                negate_left -= 1
            continue
        weight = SENTIMENT_WEIGHTS.get(tok)
        if weight is not None:
            w = weight * mult
            if negate_left > 0:
                w = -w
            contributions.append(w)
            mult, mult_left, negate_left = 1.0, 0, 0
            continue
        # a plain, unrecognised word still consumes one step of any open negation/intensifier window
        if negate_left > 0:
            negate_left -= 1
        if mult_left > 0:
            mult_left -= 1
            if mult_left == 0:
                mult = 1.0

    if not contributions:
        polarity = 0.0
    else:
        polarity = sum(contributions) / len(contributions)
    polarity = max(-1.0, min(1.0, polarity))

    if polarity <= NEG_THRESHOLD:
        tone: Literal["neg", "neu", "pos"] = "neg"
    elif polarity >= POS_THRESHOLD:
        tone = "pos"
    else:
        tone = "neu"
    return polarity, tone


def score_column(clean_df: pd.DataFrame, plan: CleaningPlan, column: str) -> list[AnswerScore | None]:
    """Score every row of `column`, in original row order, via `model_safe_column` (the only door text
    leaves through). A row with no answer (missing/NaN, or masked down to an empty string - both mean
    "nothing to score") comes back as None; a score is never invented for it.
    """
    masked = model_safe_column(clean_df, plan, column)  # same order/length as clean_df; None for blank/NaN
    out: list[AnswerScore | None] = []
    for row_index, text in zip(clean_df.index, masked):
        if not text or not text.strip():  # None, "", or whitespace-only - all "no answer" for scoring
            out.append(None)
            continue
        polarity, tone = score_text(text)
        out.append(AnswerScore(row=int(row_index), text=text, polarity=polarity, tone=tone))
    return out


def _round_percentages_to_100(counts: dict[str, int], total: int) -> dict[str, float]:
    """Largest-remainder rounding: each share rounds to the nearest whole percent, and any leftover point(s)
    from that rounding go to the categories with the largest fractional part, so the three shares always
    sum to exactly 100 (never 99 or 101 from independently-rounded floats)."""
    raw = {k: (v / total) * 100 for k, v in counts.items()}
    floors = {k: math.floor(v) for k, v in raw.items()}
    remainder = 100 - sum(floors.values())
    order = sorted(raw.keys(), key=lambda k: raw[k] - floors[k], reverse=True)
    result = dict(floors)
    for k in order[:remainder]:
        result[k] += 1
    return {k: float(v) for k, v in result.items()}


def tone_split(scores: list[AnswerScore]) -> ToneSplit:
    """Aggregate scored answers into a `ToneSplit` (see `app/chart_data.py`: neg/neu/pos percentages of
    answered responses), so this can plug straight into the charts with no translation. Percentages always
    sum to exactly 100.

    With zero scored answers there is nothing to report; by convention that is 100% neutral (not 0/0/0,
    which would break the "always sums to 100" invariant) - callers with no data should treat that as
    "insufficient data" upstream rather than reading it as a real finding.
    """
    total = len(scores)
    if total == 0:
        return ToneSplit(neg=0.0, neu=100.0, pos=0.0)
    counts = {"neg": 0, "neu": 0, "pos": 0}
    for s in scores:
        counts[s.tone] += 1
    pct = _round_percentages_to_100(counts, total)
    return ToneSplit(neg=pct["neg"], neu=pct["neu"], pos=pct["pos"])


# ---------------------------------------------------------------------------------------------------------
# Optional Claude spot-check. Same lazy-import / "raise before any network call" pattern as
# app/profiling/claude_hook.py and app/text_pipeline/embeddings.py's VoyageEmbeddingClient.
# ---------------------------------------------------------------------------------------------------------

ClaudeClient = Any  # anything shaped like anthropic.Anthropic() - `.messages.create(...)`; see FakeClaudeClient

SYSTEM_PROMPT = (
    "You judge the overall tone of short survey answers. For each answer, decide whether it reads as "
    'negative, neutral, or positive. Reply with JSON only: {"results": [{"index": int, "tone": "neg" | '
    '"neu" | "pos"}, ...]}, exactly one entry per answer given, using its index. Never invent answers, '
    "never add commentary outside the JSON."
)


class ClaudeNotConfigured(RuntimeError):
    """Raised instead of ever making a network call with no API key (and no client passed in for tests)."""


class SpotCheckParseError(RuntimeError):
    """Raised when Claude's reply cannot be trusted as a valid, complete tone judgement."""


@dataclass
class SpotCheckReport:
    sample_size: int  # how many answers were actually sampled and judged (<= the requested sample_size)
    agreement_pct: float  # % of sampled answers where the lexicon's bucket matches Claude's
    pairs: list[dict[str, Any]]  # every sampled {row, text, lexicon_tone, claude_tone}, for inspection
    disagreements: list[dict[str, Any]] = field(default_factory=list)  # capped subset of `pairs`, for display


class FakeClaudeClient:
    """Deterministic, network-free stand-in for tests. Takes a fixed reply string (or a callable that
    builds one from the sent messages), same shape as the real client: `.messages.create(...)` returning
    an object with `.content[i].text`. Mirrors `app/profiling/claude_hook.py`'s test fake."""

    def __init__(self, reply: str | Any) -> None:
        self._reply = reply
        self.calls: list[dict[str, Any]] = []

    class _Msg:
        def __init__(self, text: str) -> None:
            self.content = [type("Block", (), {"text": text})()]

    def _create(self, **kwargs: Any) -> "FakeClaudeClient._Msg":
        self.calls.append(kwargs)
        reply = self._reply(kwargs) if callable(self._reply) else self._reply
        return FakeClaudeClient._Msg(reply)

    @property
    def messages(self) -> Any:
        return type("Messages", (), {"create": staticmethod(self._create)})()


def _representative_sample(scores: list[AnswerScore], sample_size: int) -> list[AnswerScore]:
    """Pick up to `sample_size` answers spread across the tone buckets present in `scores`, not just the
    first N rows - a lexicon can be systematically wrong on one bucket, and taking the first N would miss
    that if the data happens to be sorted or clustered by tone. Allocates the sample across buckets by
    their share of the data (largest-remainder, same helper as `tone_split`), then, within each bucket,
    takes evenly-spaced answers across that bucket's rows rather than its first few.
    """
    if sample_size <= 0 or not scores:
        return []
    buckets: dict[str, list[AnswerScore]] = {"neg": [], "neu": [], "pos": []}
    for s in scores:
        buckets[s.tone].append(s)
    present = {tone: items for tone, items in buckets.items() if items}
    if not present:
        return []

    n = min(sample_size, len(scores))
    counts = {tone: len(items) for tone, items in present.items()}
    quotas = _round_percentages_to_100(counts, len(scores))  # reuse: proportions of the whole dataset
    # Turn the (0-100) proportional shares into integer sample counts that sum to exactly n, again by
    # largest remainder, then guarantee every present bucket gets at least one pick if there is room.
    raw_alloc = {tone: quotas[tone] / 100 * n for tone in present}
    alloc = {tone: math.floor(v) for tone, v in raw_alloc.items()}
    remaining = n - sum(alloc.values())
    order = sorted(present.keys(), key=lambda t: raw_alloc[t] - alloc[t], reverse=True)
    for tone in order[:remaining]:
        alloc[tone] += 1
    for tone in present:
        if alloc[tone] == 0 and n >= len(present):
            alloc[tone] = 1  # every present bucket represented when there is room for one each
    # Trim back down to n if the "at least one" guarantee pushed the total over.
    while sum(alloc.values()) > n:
        biggest = max(alloc, key=lambda t: alloc[t])
        alloc[biggest] -= 1
    for tone in present:
        alloc[tone] = min(alloc[tone], len(present[tone]))

    sample: list[AnswerScore] = []
    for tone, items in present.items():
        k = alloc.get(tone, 0)
        if k <= 0:
            continue
        length = len(items)
        if k >= length:
            picks = items
        else:
            picks = [items[round(i * (length - 1) / (k - 1))] if k > 1 else items[0] for i in range(k)]
            # de-duplicate positions from the rounding above while keeping order
            seen_ids: set[int] = set()
            deduped = []
            for p in picks:
                if id(p) not in seen_ids:
                    seen_ids.add(id(p))
                    deduped.append(p)
            picks = deduped
        sample.extend(picks)
    return sample[:n]


def _parse_spot_check_json(text: str, expected_indexes: set[int]) -> dict[int, str]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise SpotCheckParseError("Claude's reply did not contain a JSON object.")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise SpotCheckParseError(f"Claude's reply was not valid JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SpotCheckParseError('Claude\'s reply is missing a "results" list.')

    out: dict[int, str] = {}
    for item in data["results"]:
        if not isinstance(item, dict):
            raise SpotCheckParseError("Every item in \"results\" must be an object.")
        idx = item.get("index")
        tone = item.get("tone")
        if not isinstance(idx, int) or tone not in ("neg", "neu", "pos"):
            raise SpotCheckParseError(f"Malformed result entry: {item!r}")
        out[idx] = tone
    missing = expected_indexes - out.keys()
    if missing:
        raise SpotCheckParseError(f"Claude's reply is missing tone judgements for indexes {sorted(missing)}.")
    return out


def spot_check(scores: list[AnswerScore], client: ClaudeClient = None, sample_size: int = 100) -> SpotCheckReport:
    """Ask Claude to independently judge tone for a representative sample of already-lexicon-scored
    answers, and report how often the two agree (SPEC.md: "Claude spot-checks about 100 samples to report
    scorer agreement"). One batched call. Never required for `score_column`/`tone_split` to work.

    Raises `ClaudeNotConfigured` if `client` is None and `ANTHROPIC_API_KEY` is not set (or the `anthropic`
    package is missing) - checked before any network call. Raises `SpotCheckParseError` on a malformed or
    incomplete reply, rather than silently returning a wrong or partial report.
    """
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ClaudeNotConfigured(
                "ANTHROPIC_API_KEY is not set. The spot-check needs it; nothing was sent over the network."
            )
        try:
            import anthropic  # lazy import: only needed when this function is actually used
        except ImportError as e:  # pragma: no cover - exercised only when the package is missing
            raise ClaudeNotConfigured(
                "The 'anthropic' package is not installed. Add it to the environment before spot-checking."
            ) from e
        client = anthropic.Anthropic()

    sample = _representative_sample(scores, sample_size)
    if not sample:
        return SpotCheckReport(sample_size=0, agreement_pct=0.0, pairs=[], disagreements=[])

    payload = [{"index": i, "text": s.text} for i, s in enumerate(sample)]
    msg = client.messages.create(
        model=os.environ.get("VERBATIM_CLAUDE_MODEL", DEFAULT_MODEL),
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps({"answers": payload})}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content)
    judged = _parse_spot_check_json(text, {p["index"] for p in payload})

    pairs: list[dict[str, Any]] = []
    matches = 0
    for i, s in enumerate(sample):
        claude_tone = judged[i]
        agree = claude_tone == s.tone
        matches += int(agree)
        pairs.append({
            "row": s.row, "text": s.text, "lexicon_tone": s.tone, "claude_tone": claude_tone, "agree": agree,
        })
    agreement_pct = (matches / len(sample)) * 100
    disagreements = [p for p in pairs if not p["agree"]][:MAX_DISAGREEMENTS_SHOWN]
    return SpotCheckReport(
        sample_size=len(sample), agreement_pct=agreement_pct, pairs=pairs, disagreements=disagreements,
    )
