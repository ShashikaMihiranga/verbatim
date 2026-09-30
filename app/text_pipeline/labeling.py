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


def label_sub_clusters(
    sub_clusters: dict[int, list[Cluster]],
    parent_labels: dict[int, ThemeLabel],
    question: str,
    client: ClaudeClient,
    samples_per_cluster: int = DEFAULT_SAMPLES_PER_SUBCLUSTER,
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

    prompt = json.dumps({"survey_question": question, "clusters": clusters_payload})
    raw_response = client.complete(SUB_SYSTEM, prompt)
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
