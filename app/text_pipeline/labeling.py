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
import os
import re
from typing import Any, Protocol, runtime_checkable

from .schema import Cluster, ClusterResult, ThemeLabel

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096
DEFAULT_SAMPLES_PER_CLUSTER = 20  # SPEC.md: "About 15 to 25 representative answers per cluster"

OTHER_LABEL = "Other"
OTHER_DESCRIPTION = "Answers that were too rare, unclear, or distinct to group into a theme."
OTHER_CLUSTER_ID = -1  # matches HDBSCAN's own noise label; never a real Cluster.id (those start at 0)

SYSTEM = (
    "You help summarise open-ended survey answers that an automatic algorithm has already grouped into "
    "clusters. You are given the survey question and, for each cluster, a handful of representative "
    "answers (already stripped of anything sensitive). Reply with JSON only, no prose before or after "
    'it: {"themes": [{"cluster_id": int, "label": str, "description": str, "merge_with": [int, ...], '
    '"note": str or null}, ...]}. Include exactly one entry per cluster id you were given, using that '
    "same id. "
    '"label" is a few words naming the theme. "description" is one plain sentence, in language a '
    'non-expert would understand, saying what the answers in that cluster have in common. "merge_with" '
    "lists the ids of OTHER clusters you were given that look like they are really the same theme as "
    'this one - use [] if none do. "note" is one short sentence flagging anything else worth a human\'s '
    "attention - most often that a cluster actually contains two distinct sub-themes and might be split "
    "- or null if there is nothing to add. "
    "You are not told how many answers are in any cluster and must never guess, invent, or state a "
    "count, percentage, or share for any cluster in your reply."
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
    `embeddings.EmbeddingClient.embed` - callers never see the underlying SDK shape."""

    def complete(self, system: str, prompt: str) -> str:
        ...


class AnthropicClaudeClient:
    """Real Claude client. Lazy-imports `anthropic` (not a hard requirement - see
    `app/profiling/claude_hook.py`), reads `ANTHROPIC_API_KEY` from the environment and raises
    `ClaudeNotConfigured` before ever touching the network if it is unset. Model defaults to
    `claude-haiku-4-5`, override with `VERBATIM_CLAUDE_MODEL` (the same env var `claude_hook.py` uses -
    one small model for both optional Claude steps unless told otherwise)."""

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
        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("VERBATIM_CLAUDE_MODEL", DEFAULT_MODEL)

    def complete(self, system: str, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(getattr(block, "text", "") for block in msg.content)


class FakeClaudeClient:
    """Deterministic, network-free stand-in for tests. `reply` is either the literal string to return
    every time, or a callable `(prompt) -> str` for tests that need the reply to depend on what was
    sent (e.g. echoing back exactly the cluster ids given). Every call is recorded in `self.calls` so
    tests can assert on batching (one call for every cluster, not one per cluster)."""

    def __init__(self, reply: str | Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append({"system": system, "prompt": prompt})
        return self.reply(prompt) if callable(self.reply) else self.reply


def _representative_texts(cluster: Cluster, n: int) -> list[str]:
    """Up to `n` sample texts, closest to the cluster's centroid first (a `None` distance, which only
    happens if the centroid could not be computed, sorts last) - a cheap, deterministic stand-in for
    "representative" that needs no extra call."""
    members = sorted(cluster.members, key=lambda m: (m.distance is None, m.distance))
    return [m.text for m in members[:n]]


def _build_prompt(clusters: list[Cluster], question: str, samples_per_cluster: int) -> str:
    payload = {
        "survey_question": question,
        "clusters": [
            {"cluster_id": cluster.id, "sample_answers": _representative_texts(cluster, samples_per_cluster)}
            for cluster in clusters
        ],
    }
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


def _parse_response(text: str, expected_ids: set[int]) -> dict[int, dict[str, Any]]:
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
            raise LabelingError(f"Claude's reply had a theme with a missing/invalid cluster_id: {item!r}", text)
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

        by_id[cluster_id] = {
            "label": label.strip()[:120],
            "description": description.strip()[:400],
            # Only ids we actually sent, and never the cluster's own id, survive into the result.
            "merge_with": sorted({m for m in merge_with if m in expected_ids and m != cluster_id}),
            "note": note.strip()[:240] if isinstance(note, str) and note.strip() else None,
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
    """
    labels: list[ThemeLabel] = []

    if result.clusters:
        expected_ids = {cluster.id for cluster in result.clusters}
        prompt = _build_prompt(result.clusters, question, samples_per_cluster)
        raw_response = client.complete(SYSTEM, prompt)
        parsed = _parse_response(raw_response, expected_ids)
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
                )
            )

    if result.noise:
        labels.append(_other_theme_label(result))

    return labels
