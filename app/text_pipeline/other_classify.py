""""Look inside Other" (docs/TODO.md, 2026-10-21): re-clusters a dataset's "Other"/noise answers to find
real structure hiding in them, then classifies every one of those answers against the dataset's known
themes PLUS whatever new themes were found - using each tool in this pipeline for what it is already
good at, not inventing a third approach:

  1. Re-embed and re-cluster the Other-bucket answers as their own pool (`recluster_other` below) -
     `Theme` rows never persist embedding vectors (confirmed - see docs/DECISIONS.md), so this always
     pays for a fresh, Other-bucket-scoped Voyage embedding call, never a full-dataset one.
  2. Label and consolidate the raw candidate clusters this finds using the EXISTING, already-proven
     `labeling.label_clusters_with_retry` + `merging.apply_merges` pipeline, completely unchanged - the
     same "one batched Claude call, then merge same-label/merge_with clusters" mechanism this codebase
     already trusts for the normal top-level build, just pointed at the Other-bucket's own re-clustered
     candidates instead of the whole dataset's top-level clusters. No new Claude-prompt design needed.
  3. Build one Jev Choice question (`build_classification_question` below) whose `criteria` combine the
     dataset's known theme labels with the newly consolidated candidate labels, plus an explicit "none
     of these" option - deliberately explicit rather than a confidence-threshold guess, so Jev's own
     calibration (not an arbitrary cutoff this module would have to pick) decides what is genuinely
     still unclassifiable.
  4. Run EVERY Other-bucket answer through Jev with that one question (`classify_other_answers` below) -
     cheap, high-volume, fixed-choice - exactly the profile that already motivated using Jev for
     sentiment (see `jev_sentiment.py`'s own docstring).

This module does not write to the database - see `app/api_themes.py` (or wherever the "Look inside
Other" job route lives) for how its outputs become updated `Theme` rows.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .clustering import MIN_MIN_CLUSTER_SIZE, cluster_answers
from .jev_sentiment import ChoiceAnswer, JevClient
from .labeling import OTHER_CLUSTER_ID, ClaudeClient, label_clusters_with_retry
from .merging import apply_merges
from .schema import ClusterMember, ClusterResult, ThemeLabel

NONE_OF_THESE = "None of these"
NONE_OF_THESE_DESCRIPTION = (
    "The answer does not clearly match any of the listed themes well enough to count as that theme."
)

# Jev calls are cheap, I/O-bound, and (per jev_sentiment.py's own comment) return tiny replies - lighter
# per-call than Voyage's embedding responses, which is why this starts higher than
# embeddings.py's own DEFAULT_CONCURRENCY=5. Not yet measured against real production CPU the way that
# value was (docs/DECISIONS.md, 2026-10-09) - revisit with real numbers if a build shows CPU pressure,
# the same discipline already applied to every other concurrency knob in this pipeline. Env-overridable,
# matching the rest of this codebase's `os.environ.get("...", default)` convention.
DEFAULT_CLASSIFY_CONCURRENCY = max(1, int(os.environ.get("JEV_CLASSIFY_CONCURRENCY", "8") or 8))


def recluster_other(
    row_indexes: list[int], texts: list[str], vectors: list[list[float]],
) -> ClusterResult:
    """Clusters the given Other-bucket answers (already embedded by the caller - see this module's own
    docstring for why re-embedding happens one level up, in the job route, not here) as their own
    standalone pool, via `clustering.cluster_answers` with `finer_floor=True` - the same "recover
    small-but-real topics instead of writing them off" setting `pipeline.embed_and_cluster_with_vectors`
    already uses for a normal top-level build, appropriate here too since these answers already failed
    the dataset-wide floor once and a second, equally lenient pass is the fairest retry.

    Guards against fewer answers than `MIN_MIN_CLUSTER_SIZE` (clustering.py's own absolute floor for "a
    group big enough to call a theme") BEFORE calling `cluster_answers` - unlike every other call site in
    this codebase, which only ever reaches `cluster_answers` after `pipeline.py`'s own
    `MIN_ANSWERS_TO_CLUSTER` gate, this is the first one driven by however many rows happen to be in
    "Other", which can legitimately be smaller than that floor. sklearn's own `HDBSCAN` raises a hard
    `ValueError` (not a graceful "no clusters found") when asked for `min_samples` greater than the
    sample count - confirmed live by this module's own first end-to-end test. Returns every answer as
    noise (zero real clusters) rather than attempting that: there is no way to form even one valid
    cluster from fewer answers than the floor anyway, so this is not a lossy shortcut, just skipping a
    call that could only ever fail or - at that size - find nothing real."""
    if len(row_indexes) < MIN_MIN_CLUSTER_SIZE:
        return ClusterResult(
            column="", clusters=[],
            noise=[ClusterMember(row=r, text=t, distance=None) for r, t in zip(row_indexes, texts)],
            total_answers=len(row_indexes),
        )
    return cluster_answers(vectors, texts, row_indexes, finer_floor=True)


@dataclass
class ConsolidatedCandidates:
    """Output of labeling + merging the raw clusters `recluster_other` found - everything downstream
    needs: the merged `ClusterResult` (for `answer_refs` per new theme) and its matching labels, already
    reusing `labeling.py`'s own `size`-from-`len(members)` discipline (never trusted from a reply)."""
    result: ClusterResult
    labels: list[ThemeLabel]


def label_and_consolidate(
    result: ClusterResult, question: str, client: ClaudeClient,
) -> ConsolidatedCandidates:
    """Labels every raw candidate cluster `recluster_other` found with ONE batched Claude call
    (`label_clusters_with_retry`, completely unchanged - same retry-once-on-a-malformed-reply behaviour
    as the normal top-level labeling step), then consolidates near-duplicate candidates down via
    `merging.apply_merges` (also unchanged) - the SAME label+merge mechanism already trusted for a
    normal build, just applied to the Other-bucket's own re-clustered candidates. No noise/"Other" entry
    is synthesized here (`result.noise`, if any, is simply dropped - see the module docstring: whatever
    Jev's own "None of these" classification later decides is still unclassifiable is this feature's own
    answer to leftover noise, not a second, locally-synthesized "Other"-within-"Other")."""
    labels = label_clusters_with_retry(result, question, client)
    real_labels = [l for l in labels if l.cluster_id != OTHER_CLUSTER_ID]  # drop any synthesized "Other"
    if not real_labels:
        return ConsolidatedCandidates(result=ClusterResult(column=result.column, clusters=[], noise=[], total_answers=result.total_answers), labels=[])
    merged_result, merged_labels = apply_merges(result, real_labels)
    return ConsolidatedCandidates(result=merged_result, labels=merged_labels)


def build_classification_question(
    known_themes: dict[str, str | None], new_candidates: ConsolidatedCandidates,
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Combines `known_themes` (label -> description, already-known top-level themes) with
    `new_candidates`'s own consolidated labels into one Jev `criteria` dict, plus an explicit
    `NONE_OF_THESE` option (see the module docstring for why this is explicit, not a confidence
    threshold this module would otherwise have to guess at). Returns `(criteria, new_label_descriptions)`
    - the second dict (new labels only, label -> description) is what the job route needs to create new
    `Theme` rows for whichever new labels actually end up with any matched answers; it is NOT part of
    what gets sent to Jev (criteria is)."""
    new_label_descriptions = {l.label: l.description for l in new_candidates.labels}
    criteria: dict[str, str | None] = dict(known_themes)
    for label, description in new_label_descriptions.items():
        if label not in criteria:  # a new label happening to collide with a known one stays the known one
            criteria[label] = description
    criteria[NONE_OF_THESE] = NONE_OF_THESE_DESCRIPTION
    return criteria, new_label_descriptions


@dataclass
class OtherClassification:
    """Per-answer results of running every Other-bucket answer through Jev with one shared question.
    `by_row` is the authoritative result (row -> the chosen label, `NONE_OF_THESE` for "still
    unclassifiable"); `low_confidence_rows` is tracked separately (not folded into a different label)
    so a caller can choose its own policy for a low-confidence match - this module does not decide one,
    consistent with every other confidence-carrying result in this pipeline (`AnswerScore`, `ThemeLabel`'s
    own confidence handling) never silently discarding the number."""
    by_row: dict[int, str] = field(default_factory=dict)
    confidence_by_row: dict[int, float] = field(default_factory=dict)
    failed_rows: list[int] = field(default_factory=list)  # a row whose Jev call raised, text never lost


def classify_other_answers(
    row_indexes: list[int],
    texts: list[str],
    criteria: dict[str, str | None],
    client: JevClient,
    *,
    instructions: str = "Classify which theme this survey answer is about.",
    concurrency: int = DEFAULT_CLASSIFY_CONCURRENCY,
) -> OtherClassification:
    """Runs every `(row, text)` pair through `client.classify_choice` against the SAME shared `criteria`,
    in parallel via a thread pool (same "network I/O releases the GIL, so this is real wall-clock
    parallelism" reasoning as `embeddings.py`'s own concurrent batching - Jev calls are blocking HTTP,
    not CPU work). A single row's failure (a real `JevError`, e.g. a transient network issue Jev's own
    one-retry already could not recover from) is recorded in `failed_rows` and does not stop the rest of
    the batch - thousands of independent per-row calls should not all be thrown away for one bad one."""
    out = OtherClassification()
    if not row_indexes:
        return out

    def _one(row: int, text: str) -> tuple[int, ChoiceAnswer | None]:
        try:
            answer = client.classify_choice(
                text, question_key="other_classification", instructions=instructions, criteria=criteria,
            )
            return row, answer
        except Exception:
            return row, None

    with ThreadPoolExecutor(max_workers=min(concurrency, len(row_indexes))) as pool:
        for row, answer in pool.map(_one, row_indexes, texts):
            if answer is None:
                out.failed_rows.append(row)
                continue
            out.by_row[row] = answer.choice
            out.confidence_by_row[row] = answer.confidence
    return out
