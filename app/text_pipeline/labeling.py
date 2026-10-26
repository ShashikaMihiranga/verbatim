"""Labelling clusters with Claude (SPEC.md section 2, "Theme labels" row: "About 15 to 25
representative answers per cluster... One batched call for all clusters. Ask for a label, a one-line
description, and merge and split suggestions.").

Design mirrors two existing modules rather than inventing a third shape:
  - `embeddings.py`'s `EmbeddingClient` Protocol / real client / `FakeEmbeddingClient` split -
    `ClaudeClient` here is a one-method Protocol, `AnthropicClaudeClient` is the real (lazy-imported
    `anthropic`, env-key-gated) implementation, `FakeClaudeClient` is the network-free test double.
  - `app/profiling/claude_hook.py`'s call shape - one call, `system` plus a single JSON user message,
    the reply parsed as JSON text, samples only (never the whole dataset), a "JSON only" instruction.

Counts are never asked of Claude: `ThemeLabel.size` always comes from `len(cluster.members)` (or
`len(result.noise)` for "Other"), computed here, in code, and copied over - a model claiming a
different size in its reply is ignored. The noise/"Other" group (SPEC.md: "answers too rare for a
theme... folded in automatically") never goes to Claude at all; this module synthesizes its
`ThemeLabel` locally.

Every sample text handed to Claude already came through `app.cleaning.payload.model_safe_column`
upstream (see `pipeline.embed_and_cluster`, which is what produces the `ClusterResult` this module
takes) - this module never re-masks and never logs a sample's text anywhere.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

from .schema import Cluster, ClusterResult, ThemeLabel

log = logging.getLogger("verbatim.labeling")
_T = TypeVar("_T")

DEFAULT_MODEL = "claude-sonnet-5"  # one tier up from claude-haiku-4-5: this is one batched call per
# build regardless of dataset size (never per-row), so the extra cost buys better naming/merging
# judgement where it matters most - see docs/DECISIONS.md's dated entry for why this was raised.
#
# 16000, not 4096 (2026-10-21, confirmed bug on a real devapp build - see docs/DECISIONS.md): the whole
# dataset's themes are labelled in ONE reply (never per-cluster), and JSON-heavy output tokenizes far
# less efficiently than prose (~2.5-3 chars/token here, not ~4) - a dataset with enough distinct themes
# reliably ran the reply past 4096 tokens, truncating it mid-JSON. Both the original call AND its one
# retry (`_retry_on_labeling_error`) failed at nearly the same character offset in the response, which is
# the signal that this was a hard budget ceiling, not the occasional malformed/dropped-cluster reply that
# retry already exists for. Billing is per token actually generated, not per `max_tokens` ceiling, so a
# generous budget costs nothing on the (overwhelming majority of) builds that never need it.
MAX_TOKENS = 16000
DEFAULT_SAMPLES_PER_CLUSTER = 20  # SPEC.md: "About 15 to 25 representative answers per cluster"
DEFAULT_SAMPLES_PER_SUBCLUSTER = 12  # a sub-cluster is already a slice of one theme; fewer samples suffice

OTHER_LABEL = "Other"
OTHER_DESCRIPTION = "Answers that were too rare, unclear, or distinct to group into a theme."
OTHER_CLUSTER_ID = -1  # matches HDBSCAN's own noise label; never a real Cluster.id (those start at 0)

SYSTEM = (
    "You help summarise open-ended survey answers that an automatic algorithm has already grouped into "
    "clusters. You are given the survey question and, for each cluster, a handful of representative "
    "answers (already stripped of anything sensitive). "
    "Before naming anything, decide on ONE consistent kind of thing every theme in this batch should "
    "describe, and name every theme along that same axis. In most feedback/review contexts, the useful "
    "axis is the FEEDBACK ASPECT being discussed (e.g. cost, ease of use, fit, durability, customer "
    "service, delivery speed) - not the product, feature, or entity a sample happens to mention. A "
    "specific product or entity named in the answers (e.g. a garment type, a product line, a store "
    "location) is usually already captured elsewhere as its own category and does not need to be "
    "rediscovered as a theme; if several clusters differ only in WHICH entity is mentioned but describe "
    "the same underlying aspect (e.g. one cluster is about dress fit, another about pants fit), treat "
    "that as the SAME theme, not different ones. Stay precise about what counts as the same aspect, "
    "though: fit, fabric quality, durability, value for money, and style are each their OWN aspect even "
    "when a single review mentions several together, and should stay as SEPARATE themes - only combine "
    "two clusters when someone summarising both in one sentence would genuinely say the same thing about "
    "them, not merely because they are about the same product category or often come up side by side. "
    "The one exception: if the survey question is itself fundamentally asking people to name or choose "
    "among entities (e.g. \"which feature do you want next\", \"which product did you buy\"), then "
    "naming those entities IS the right axis - use your judgement on which case this is, and apply it "
    "consistently across every theme in this batch. "
    "Reply with JSON only, no prose before or after "
    'it: {"themes": [{"cluster_id": int, "label": str, "description": str, "merge_with": [int, ...], '
    '"note": str or null}, ...]}. Include exactly one entry per cluster id you were given, using that '
    "same id. "
    '"label" is a few words naming the theme, along the single axis you chose above. "description" is '
    "one plain sentence, in language a non-expert would understand, saying what the answers in that "
    'cluster have in common. "merge_with" lists the ids of OTHER clusters you were given that describe '
    "the SAME feedback aspect as this one, even if they surface through different entities, products, or "
    'wording in the sample text (e.g. a cluster about dress fit and a cluster about pants fit both '
    'belong under one "fit and sizing" theme) - use [] if none do. Do NOT merge clusters that describe '
    "genuinely different aspects just because they are related or often mentioned together (fit and "
    'fabric quality are different aspects, not the same one, even in the same review). "note" is one '
    "short sentence flagging anything else worth a human's attention - most often that a cluster "
    "actually contains two distinct sub-themes and might be split - or null if there is nothing to add. "
    "You are not told how many answers are in any cluster and must never guess, invent, or state a "
    "count, percentage, or share for any cluster in your reply."
)

# Appended to SYSTEM only for "Look inside Other" (docs/BUGS.md BUG-048): its candidates come from the
# answers the normal build could not place, which is where non-answers collect, and a candidate cluster of
# them used to become a theme ("No comment provided", "Survey not applicable or irrelevant"). A per-cluster
# flag lets code drop them structurally instead of guessing from the label's wording.
NON_ANSWER_SYSTEM = (
    ' Also give every entry a "non_answer" field, true or false. It is true only when the cluster\'s '
    "answers do not answer the survey question at all: placeholders or refusals (\"no comment\", \"n/a\", "
    "\"nothing to add\", \"none\"), saying the question does not apply to them, or only pointing elsewhere "
    "(\"see above\", \"as I said before\"). It is false for any cluster with real content, even if that "
    "content is short, vague, general, or a complaint about the survey itself."
)

# Appended to SYSTEM only for "Look inside Other" when the column already has themes (user decision,
# 2026-10-25): a new group that is really a narrower part of an existing theme becomes a sub-theme inside
# it ("Delivery delays" under "Shipping") instead of a new main theme beside it.
PARENT_SYSTEM = (
    ' You are also given "existing_themes", the themes already found for this question. Give every entry '
    'a "parent_theme" field: the exact label of ONE existing theme when this cluster is a narrower, more '
    "specific part of it (someone reading that theme's description would expect these answers inside it), "
    "or null when the cluster is a topic of its own. Do not pick a parent only because the topics are "
    "related or mentioned together, and never invent a label that is not in the list."
)

SUB_SYSTEM = (
    "You help summarise open-ended survey answers that an automatic algorithm has already grouped into "
    "sub-clusters WITHIN a larger parent theme. You are given the survey question and, for each "
    "sub-cluster, the parent theme it belongs to (its own label and description) and a handful of "
    "representative answers from just that sub-cluster (already stripped of anything sensitive). Reply "
    'with JSON only, no prose before or after it: {"themes": [{"cluster_id": int, "label": str, '
    '"description": str, "merge_with": [int, ...], "note": str or null}, ...]}. Include exactly one '
    "entry per cluster id you were given, using that same id. "
    '"label" is a few words naming what specifically distinguishes this sub-group from its sibling '
    "sub-clusters under the SAME parent theme - never just repeat the parent theme's own label or "
    'description; say what makes this particular slice of the parent theme different. "description" is '
    "one plain sentence, in language a non-expert would understand, saying what the answers in this "
    "sub-cluster have in common, again focused on what sets it apart from its siblings under the same "
    'parent, not on what it shares with the parent theme as a whole. "merge_with" lists the ids of OTHER '
    "sub-clusters you were given that represent the same underlying sub-theme as this one, even if they "
    "surface through different entities or wording in the sample text - use [] if none do, but ONLY "
    "consider merging sub-clusters that share the same parent theme (each entry's own parent_theme "
    'tells you which); never suggest merging sub-clusters that belong to different parents. "note" is '
    "one short sentence flagging anything else worth a human's attention, or null "
    "if there is nothing to add. You are not told how many answers are in any sub-cluster and must "
    "never guess, invent, or state a count, percentage, or share for any sub-cluster in your reply."
)


class ClaudeNotConfigured(RuntimeError):
    """Raised instead of ever making a network call with no API key. Mirrors
    `embeddings.EmbeddingNotConfigured`."""


class LabelingError(RuntimeError):
    """Claude's reply could not be trusted as theme labels. Carries the raw reply text (already
    masked-safe, since it only ever echoes what we sent) so a caller can log or inspect it - but no
    field from a response that raised this ever reaches the database layer."""

    def __init__(self, message: str, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@runtime_checkable
class ClaudeClient(Protocol):
    """Anything that can turn one labelling prompt into Claude's raw text reply. One method, like
    `embeddings.EmbeddingClient.embed` - callers never see the underlying SDK shape. `max_tokens`
    defaults to `MAX_TOKENS` so every existing caller (`findings.py`'s own separate `FakeClaudeClient`
    included) keeps working unchanged; `label_clusters`/`label_sub_clusters` below are the only callers
    that ever pass a different value."""

    def complete(self, system: str, prompt: str, *, max_tokens: int = MAX_TOKENS) -> str:
        ...


class AnthropicClaudeClient:
    """Real Claude client. Lazy-imports `anthropic` (not a hard requirement - see
    `app/profiling/claude_hook.py`), reads `ANTHROPIC_API_KEY` from the environment and raises
    `ClaudeNotConfigured` before ever touching the network if it is unset. Model defaults to
    `DEFAULT_MODEL` above, override with `VERBATIM_CLAUDE_MODEL` (the same env var `claude_hook.py` and
    `sentiment.py` use - one model for every optional Claude step unless told otherwise)."""

    def __init__(self, model: str | None = None) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ClaudeNotConfigured(
                "ANTHROPIC_API_KEY is not set. Theme labelling needs it; nothing was sent over the network."
            )
        try:
            import anthropic  # lazy import: only needed when this class is actually used
        except ImportError as e:  # pragma: no cover - exercised only when the package is missing
            raise ClaudeNotConfigured(
                "The 'anthropic' package is not installed. Add it to the environment before labelling."
            ) from e
        self._client = anthropic.Anthropic(timeout=300.0, max_retries=2)  # big label replies take minutes
        self.model = model or os.environ.get("VERBATIM_CLAUDE_MODEL", DEFAULT_MODEL)

    def complete(self, system: str, prompt: str, *, max_tokens: int = MAX_TOKENS) -> str:
        # thinking explicitly disabled: this is a structured-JSON-only task (the system prompt already
        # spells out exact rules), never open-ended reasoning, and newer models' adaptive thinking competes
        # with the actual reply for the same max_tokens budget - confirmed directly against the real API
        # (claude-sonnet-5 upgrade, docs/DECISIONS.md's dated entry): a real labeling prompt spent its
        # entire 4096-token budget on an (unrequested) thinking block and returned NO text at all,
        # surfacing as "Claude's reply did not contain any JSON" - not a formatting problem, a budget one.
        #
        # Streamed, not a plain blocking `.create()` call (2026-10-21, confirmed bug - see
        # docs/DECISIONS.md): the Anthropic SDK itself refuses a non-streaming call whose `max_tokens` is
        # large enough that generation COULD plausibly run past 10 minutes - `ValueError: Streaming is
        # required for operations that may take longer than 10 minutes`. This only started firing once
        # `_max_tokens_for` began asking for a genuinely large budget on theme-rich datasets; this call
        # site is still synchronous from its caller's point of view (it blocks until the full reply is
        # in, same as before) - `stream=True` here only changes how the SDK transports the response, not
        # this method's blocking behaviour, so nothing upstream needed to change.
        with self._client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "disabled"},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
        return "".join(getattr(block, "text", "") for block in msg.content)


class FakeClaudeClient:
    """Deterministic, network-free stand-in for tests. `reply` is either the literal string to return
    every time, or a callable `(prompt) -> str` for tests that need the reply to depend on what was
    sent (e.g. echoing back exactly the cluster ids given). Every call is recorded in `self.calls` so
    tests can assert on batching (one call for every cluster, not one per cluster)."""

    def __init__(self, reply: str | Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, prompt: str, *, max_tokens: int = MAX_TOKENS) -> str:
        self.calls.append({"system": system, "prompt": prompt, "max_tokens": max_tokens})
        return self.reply(prompt) if callable(self.reply) else self.reply


TOKENS_PER_CLUSTER = 300  # generous per-entry allowance (cluster_id, label, description, merge_with,
# note, JSON punctuation) - see `_max_tokens_for`'s own docstring for why this exists.
MAX_TOKENS_CEILING = 48000  # far under Sonnet 5's real 128K sync-API output limit; a backstop against an
# unreasonably large request (cost/latency), not a value any normal dataset should ever reach.


def _max_tokens_for(n_clusters: int) -> int:
    """Scales the labelling reply's token budget up for datasets with a lot of distinct clusters,
    instead of one flat `MAX_TOKENS` for every size (same "adaptive, not a fixed constant" shape as
    `app.api_themes._themes_deadline_for`). Confirmed bug, 2026-10-21 (see docs/DECISIONS.md): a flat
    4096, then a flat 16000, both truncated the SAME reply mid-JSON on a real 75,000-row/theme-rich
    devapp dataset - twice, at nearly the same character offset both times, which is the signature of a
    hard ceiling being hit consistently, not an occasional malformed reply. `MAX_TOKENS` (the module
    floor) covers everything up to a normal theme count for free; past that, `TOKENS_PER_CLUSTER`
    generously accounts for one JSON theme entry (cluster_id, label, description, merge_with, note, and
    punctuation), clamped at `MAX_TOKENS_CEILING` as a sanity backstop."""
    return min(MAX_TOKENS_CEILING, max(MAX_TOKENS, n_clusters * TOKENS_PER_CLUSTER))


def _representative_texts(cluster: Cluster, n: int) -> list[str]:
    """Up to `n` sample texts, closest to the cluster's centroid first (a `None` distance, which only
    happens if the centroid could not be computed, sorts last) - a cheap, deterministic stand-in for
    "representative" that needs no extra call."""
    members = sorted(cluster.members, key=lambda m: (m.distance is None, m.distance))
    return [m.text for m in members[:n]]


# What the question asks for (the report's "This question asks for ..." choice, `app.findings.QUESTION_KINDS`).
# Sent as `question_asks_for` only when it says something; "anything else" adds nothing.
QUESTION_KIND_SYSTEM = (
    ' If you are given "question_asks_for", the survey question asks people for that kind of answer '
    '(e.g. "reasons", "improvements", "facts"): name every theme as that kind of thing, e.g. a reason '
    "people give, an improvement they ask for, or a fact they report."
)


def kind_payload(question_kind: str | None) -> dict[str, str]:
    return {"question_asks_for": question_kind} if question_kind and question_kind != "anything else" else {}


def _build_prompt(
    clusters: list[Cluster], question: str, samples_per_cluster: int,
    existing_themes: dict[str, str | None] | None = None, question_kind: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "survey_question": question,
        **kind_payload(question_kind),
        "clusters": [
            {"cluster_id": cluster.id, "sample_answers": _representative_texts(cluster, samples_per_cluster)}
            for cluster in clusters
        ],
    }
    if existing_themes:
        payload["existing_themes"] = [
            {"label": label, "description": description or ""} for label, description in existing_themes.items()
        ]
    return json.dumps(payload)


def _extract_json(text: str) -> Any:
    """Parse `text` as JSON, falling back to pulling out the first `{...}` span for a model that wraps
    its reply in prose or a code fence despite the "JSON only" instruction (same tolerance as
    `claude_hook.py`'s `_parse_json`)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise LabelingError("Claude's reply did not contain any JSON.", text)
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise LabelingError(f"Claude's reply was not valid JSON: {e}", text) from e


def _parse_response(
    text: str, expected_ids: set[int], parent_names: set[str] | None = None,
) -> dict[int, dict[str, Any]]:
    """Strictly validate the parsed reply against `expected_ids` (the cluster ids we actually sent).
    Never trusts a field it has not checked the type of; raises `LabelingError` (with the raw text) on
    any structural problem rather than letting a malformed value reach a caller."""
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise LabelingError("Claude's reply was not a JSON object.", text)
    themes = data.get("themes")
    if not isinstance(themes, list):
        raise LabelingError("Claude's reply had no 'themes' list.", text)

    by_id: dict[int, dict[str, Any]] = {}
    for item in themes:
        if not isinstance(item, dict):
            raise LabelingError("Claude's reply had a non-object entry in 'themes'.", text)

        cluster_id = item.get("cluster_id")
        if not isinstance(cluster_id, int) or isinstance(cluster_id, bool):
            raise LabelingError(f"Claude's reply had a theme with a missing/invalid cluster_id.", text)
        if cluster_id not in expected_ids:
            # Ignore themes for ids we never sent (e.g. a hallucinated id, or "Other") rather than
            # failing the whole batch over one bad entry - we still require every real id below.
            continue

        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            raise LabelingError(f"Claude's reply had no usable label for cluster {cluster_id}.", text)

        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            raise LabelingError(f"Claude's reply had no usable description for cluster {cluster_id}.", text)

        merge_with = item.get("merge_with", [])
        if not isinstance(merge_with, list) or not all(
            isinstance(m, int) and not isinstance(m, bool) for m in merge_with
        ):
            raise LabelingError(f"Claude's reply had an invalid merge_with for cluster {cluster_id}.", text)

        note = item.get("note")
        if note is not None and not isinstance(note, str):
            raise LabelingError(f"Claude's reply had an invalid note for cluster {cluster_id}.", text)

        non_answer = item.get("non_answer", False)  # only asked for with NON_ANSWER_SYSTEM; absent = False
        if not isinstance(non_answer, bool):
            raise LabelingError(f"Claude's reply had an invalid non_answer for cluster {cluster_id}.", text)

        # Only asked for with PARENT_SYSTEM. A name that is not an existing theme is ignored (the cluster
        # stays a topic of its own) rather than failing the batch over one loose reply.
        parent = item.get("parent_theme")
        parent = parent.strip() if isinstance(parent, str) else None
        if parent_names is None or parent not in parent_names:
            parent = None

        by_id[cluster_id] = {
            "label": label.strip()[:120],
            "description": description.strip()[:400],
            # Only ids we actually sent, and never the cluster's own id, survive into the result.
            "merge_with": sorted({m for m in merge_with if m in expected_ids and m != cluster_id}),
            "note": note.strip()[:240] if isinstance(note, str) and note.strip() else None,
            "non_answer": non_answer,
            "parent_theme": parent,
        }

    missing = expected_ids - by_id.keys()
    if missing:
        raise LabelingError(f"Claude's reply was missing theme(s) for cluster id(s) {sorted(missing)}.", text)
    return by_id


def _other_theme_label(result: ClusterResult) -> ThemeLabel:
    """Synthesized locally - the noise/"Other" group never goes to Claude (SPEC.md: "Other: answers too
    rare for a theme"; folded in automatically)."""
    return ThemeLabel(
        cluster_id=OTHER_CLUSTER_ID,
        label=OTHER_LABEL,
        description=OTHER_DESCRIPTION,
        size=len(result.noise),
        merge_with=[],
        note=None,
    )


def label_clusters(
    result: ClusterResult,
    question: str,
    client: ClaudeClient,
    samples_per_cluster: int = DEFAULT_SAMPLES_PER_CLUSTER,
    *,
    flag_non_answers: bool = False,
    existing_themes: dict[str, str | None] | None = None,
    question_kind: str | None = None,
) -> list[ThemeLabel]:
    """Label every cluster in `result.clusters` with one batched call to `client` (SPEC.md: "One
    batched call for all clusters" - never one call per cluster), plus a locally-synthesized "Other"
    entry when `result.noise` is non-empty. `question` gives Claude the survey question for context;
    it is never asked to count anything - every `ThemeLabel.size` comes from `len(cluster.members)`
    (or `len(result.noise)`), set by this function, never by the model.

    Returns `[]` if there are no clusters and no noise (nothing to label); otherwise makes exactly one
    `client.complete(...)` call when there are clusters, regardless of how many.

    Raises `LabelingError` (carrying the raw reply) if the reply cannot be trusted as theme labels -
    not valid JSON, missing an entry for a cluster id it was given, or a field of the wrong type.

    `flag_non_answers=True` (Look inside Other) also asks for `NON_ANSWER_SYSTEM`'s per-cluster flag,
    returned as `ThemeLabel.non_answer`. `existing_themes` (label -> description, Look inside Other) also
    asks for `PARENT_SYSTEM`'s per-cluster parent, returned as `ThemeLabel.parent_theme`.
    """
    labels: list[ThemeLabel] = []

    if result.clusters:
        expected_ids = {cluster.id for cluster in result.clusters}
        prompt = _build_prompt(result.clusters, question, samples_per_cluster, existing_themes, question_kind)
        max_tokens = _max_tokens_for(len(result.clusters))
        log.info("Theme labeling: %d clusters, max_tokens=%d", len(result.clusters), max_tokens)
        system = SYSTEM + NON_ANSWER_SYSTEM if flag_non_answers else SYSTEM
        if existing_themes:
            system += PARENT_SYSTEM
        if kind_payload(question_kind):
            system += QUESTION_KIND_SYSTEM
        raw_response = client.complete(system, prompt, max_tokens=max_tokens)
        parsed = _parse_response(raw_response, expected_ids, set(existing_themes) if existing_themes else None)
        for cluster in result.clusters:
            item = parsed[cluster.id]
            labels.append(
                ThemeLabel(
                    cluster_id=cluster.id,
                    label=item["label"],
                    description=item["description"],
                    size=len(cluster.members),
                    merge_with=item["merge_with"],
                    note=item["note"],
                    non_answer=flag_non_answers and item["non_answer"],
                    parent_theme=item["parent_theme"],
                )
            )

    if result.noise:
        labels.append(_other_theme_label(result))

    return labels


LABELING_RETRY_ATTEMPTS = 2  # the original call plus one retry


def _retry_on_labeling_error(call: Callable[[], _T], *, what: str) -> _T:
    """Shared retry shape for `label_clusters`/`label_sub_clusters`: a `LabelingError` - already known to
    be a real, occasionally-occurring failure shape (Claude's reply drops a cluster, or comes back
    malformed), not something a caller should treat as a hard, non-recoverable failure after just one
    attempt - gets one retry (a fresh `client.complete()` call, same prompt) before being raised for real.
    Reproduced live on the real deployed dataset: a manual "Try again" click (i.e. a whole new build)
    succeeded immediately on the very next attempt, which is exactly the signal that a same-build retry of
    just this one call, not the whole embed+cluster+label pipeline, should already fix most occurrences -
    see docs/TODO.md's "Claude's cluster-labeling reply occasionally drops a cluster" entry.

    Any other exception type (a real network/auth error, for instance) is not retried here - it propagates
    immediately, same as before this existed."""
    last_error: LabelingError | None = None
    for attempt in range(1, LABELING_RETRY_ATTEMPTS + 1):
        try:
            return call()
        except LabelingError as e:
            last_error = e
            if attempt < LABELING_RETRY_ATTEMPTS:
                log.warning("%s failed (attempt %d/%d), retrying: %s", what, attempt, LABELING_RETRY_ATTEMPTS, e)
    assert last_error is not None  # LABELING_RETRY_ATTEMPTS >= 1, so the loop always either returns or sets this
    raise last_error


def label_clusters_with_retry(
    result: ClusterResult,
    question: str,
    client: ClaudeClient,
    samples_per_cluster: int = DEFAULT_SAMPLES_PER_CLUSTER,
    *,
    flag_non_answers: bool = False,
    existing_themes: dict[str, str | None] | None = None,
    question_kind: str | None = None,
) -> list[ThemeLabel]:
    """`label_clusters`, retried once on `LabelingError` before giving up - see
    `_retry_on_labeling_error`'s own docstring for why. This is the one real top-level theme labeling
    call whose failure kills the whole build (unlike `label_sub_clusters`, which already degrades to "no
    sub-themes" rather than failing the build - see `app/api_themes.py::_work`), so it is the call this
    retry matters most for."""
    return _retry_on_labeling_error(
        lambda: label_clusters(result, question, client, samples_per_cluster, flag_non_answers=flag_non_answers,
                               existing_themes=existing_themes, question_kind=question_kind),
        what="Theme labeling",
    )


def label_sub_clusters_with_retry(
    sub_clusters: dict[int, list[Cluster]],
    parent_labels: dict[int, ThemeLabel],
    question: str,
    client: ClaudeClient,
    samples_per_cluster: int = DEFAULT_SAMPLES_PER_SUBCLUSTER,
    *,
    question_kind: str | None = None,
) -> dict[int, list[ThemeLabel]]:
    """`label_sub_clusters`, retried once on `LabelingError` before giving up - same reasoning as
    `label_clusters_with_retry`. Sub-theme labeling already has its own graceful "fall back to no
    sub-themes" path one level up (`app/api_themes.py::_work`'s own `except LabelingError`) for when even
    the retry doesn't recover - this just means that fallback is reached less often, not a replacement
    for it."""
    return _retry_on_labeling_error(
        lambda: label_sub_clusters(sub_clusters, parent_labels, question, client, samples_per_cluster,
                                   question_kind=question_kind),
        what="Sub-theme labeling",
    )


def label_sub_clusters(
    sub_clusters: dict[int, list[Cluster]],
    parent_labels: dict[int, ThemeLabel],
    question: str,
    client: ClaudeClient,
    samples_per_cluster: int = DEFAULT_SAMPLES_PER_SUBCLUSTER,
    *,
    question_kind: str | None = None,
) -> dict[int, list[ThemeLabel]]:
    """Label every sub-cluster across every parent in `sub_clusters` (see `subthemes.sub_cluster_themes`)
    with ONE batched `client.complete()` call total, not one call per parent and not one per sub-cluster.
    Makes zero calls and returns `{}` if `sub_clusters` is empty.

    Builds a flat, globally-unique integer id space (0..K-1) across ALL parents' sub-clusters combined,
    in `sub_clusters`' own iteration order (and each parent's own sub-cluster list order) - not a
    composite string id like `f"{parent_id}:{local_id}"` (would fail `_parse_response`'s
    `isinstance(cluster_id, int) and not isinstance(cluster_id, bool)` check) and not the real Theme.id
    (does not exist yet at this point in the pipeline - parent `Theme` rows are only written to the
    database after labeling finishes, a later stream's job). An internal mapping from each flat id back
    to `(parent_cluster_id, sub_cluster)` lets the parsed reply be re-associated with the right parent
    and the right sub-`Cluster` after parsing.

    Reuses `_extract_json`/`_parse_response` unchanged - the reply schema is identical to
    `label_clusters`'s (`{"themes": [{"cluster_id", "label", "description", "merge_with", "note"}]}`);
    only the REQUEST side carries the added `parent_theme` context per entry, which Claude echoes
    nothing back about.

    Sizes always come from `len(sub_cluster.members)`, set in code, never trusted from Claude's reply -
    same discipline as `label_clusters`.

    Within one parent's own sibling sub-themes, if two get the identical label string from Claude's
    reply, later ones (in that parent's sub-cluster list order) are de-duplicated by appending " (2)",
    " (3)", etc. - a defensive guard, since `app/charts.py`'s treemap keys sub-theme rects by name and a
    same-named sibling would otherwise silently overwrite the first one when rendered.

    Returns `{parent_cluster_id: [ThemeLabel, ...]}` - one entry for every key in `sub_clusters`, in that
    parent's own sub-cluster order.
    """
    if not sub_clusters:
        return {}

    flat_by_id: dict[int, tuple[int, Cluster]] = {}  # flat_id -> (parent_cluster_id, sub_cluster)
    clusters_payload: list[dict[str, Any]] = []
    flat_id = 0
    for parent_id, subs in sub_clusters.items():
        parent_label = parent_labels[parent_id]
        for sub in subs:
            flat_by_id[flat_id] = (parent_id, sub)
            clusters_payload.append(
                {
                    "cluster_id": flat_id,
                    "parent_theme": {"label": parent_label.label, "description": parent_label.description},
                    "sample_answers": _representative_texts(sub, samples_per_cluster),
                }
            )
            flat_id += 1

    prompt = json.dumps({"survey_question": question, **kind_payload(question_kind), "clusters": clusters_payload})
    system = SUB_SYSTEM + QUESTION_KIND_SYSTEM if kind_payload(question_kind) else SUB_SYSTEM
    raw_response = client.complete(system, prompt, max_tokens=_max_tokens_for(len(clusters_payload)))
    parsed = _parse_response(raw_response, set(flat_by_id))

    result: dict[int, list[ThemeLabel]] = {parent_id: [] for parent_id in sub_clusters}
    seen_labels_by_parent: dict[int, dict[str, int]] = {parent_id: {} for parent_id in sub_clusters}
    for fid, (parent_id, sub) in flat_by_id.items():
        item = parsed[fid]
        seen = seen_labels_by_parent[parent_id]
        label_text = item["label"]
        seen[label_text] = seen.get(label_text, 0) + 1
        if seen[label_text] > 1:
            label_text = f"{label_text} ({seen[label_text]})"
        result[parent_id].append(
            ThemeLabel(
                cluster_id=fid,
                label=label_text,
                description=item["description"],
                size=len(sub.members),
                merge_with=item["merge_with"],
                note=item["note"],
            )
        )

    return result
