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
     still unclassifiable. (Since BUG-032 a pick Jev itself rates below 50% also stays in Other - see
     `MIN_MATCH_CONFIDENCE`.)
  4. Run EVERY Other-bucket answer through Jev with that one question (`classify_other_answers` below) -
     cheap, high-volume, fixed-choice - exactly the profile that already motivated using Jev for
     sentiment (see `jev_sentiment.py`'s own docstring).

This module does not write to the database - see `app/api_themes.py` (or wherever the "Look inside
Other" job route lives) for how its outputs become updated `Theme` rows.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .clustering import MIN_MIN_CLUSTER_SIZE, cluster_answers
from .jev_sentiment import ChoiceAnswer, JevClient
from .labeling import OTHER_CLUSTER_ID, ClaudeClient, label_clusters_with_retry
from .merging import apply_merges
from .schema import Cluster, ClusterMember, ClusterResult, ThemeLabel
from .subthemes import MAX_SUBTHEMES_PER_THEME, MIN_SUBTHEME_COVERAGE, MIN_THEME_SIZE_FOR_SUBTHEMES, sub_cluster_min_size

log = logging.getLogger("verbatim.other_classify")

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

# A Jev theme match below this confidence stays in Other (docs/BUGS.md BUG-032). Jev's confidence is its
# probability for the chosen option, so below 0.5 its own numbers say the answer is more likely NOT that
# theme (some other option, or "None of these", holds the larger share) - the same "does not clearly
# match" bar NONE_OF_THESE_DESCRIPTION asks for, and independent of how many options were offered.
# Conservative on purpose: on dataset 12 one broad new label took 5,833 of 6,041 answers, and a broad
# label is exactly what a weak "closest of many" pick lands on; an answer wrongly left in Other can still
# be found by a later run, while one wrongly put in a theme is invisible.
MIN_MATCH_CONFIDENCE = 0.5


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
    reusing `labeling.py`'s own `size`-from-`len(members)` discipline (never trusted from a reply).
    `non_answer_rows`: members of candidates Claude flagged as non-answers (`for_other=True` only) - never
    a theme, and the caller keeps them in Other without classifying them (BUG-048)."""
    result: ClusterResult
    labels: list[ThemeLabel]
    non_answer_rows: list[int] = field(default_factory=list)


def label_and_consolidate(
    result: ClusterResult, question: str, client: ClaudeClient, *, for_other: bool = False,
) -> ConsolidatedCandidates:
    """Labels every raw candidate cluster `recluster_other` found with ONE batched Claude call
    (`label_clusters_with_retry`, completely unchanged - same retry-once-on-a-malformed-reply behaviour
    as the normal top-level labeling step), then consolidates near-duplicate candidates down via
    `merging.apply_merges` (also unchanged) - the SAME label+merge mechanism already trusted for a
    normal build, just applied to the Other-bucket's own re-clustered candidates. No noise/"Other" entry
    is synthesized here (`result.noise`, if any, is simply dropped - see the module docstring: whatever
    Jev's own "None of these" classification later decides is still unclassifiable is this feature's own
    answer to leftover noise, not a second, locally-synthesized "Other"-within-"Other").

    `for_other=True` (Look inside Other; split keeps the default) adds two guards found on dataset 12:
      - BUG-048: Claude also flags each candidate as a non-answer or not (`NON_ANSWER_SYSTEM`). A flagged
        candidate is dropped before merging, so it can never become a theme, and its rows come back in
        `non_answer_rows`.
      - BUG-032: merges never chain (`apply_merges(allow_chains=False)`), so one broad label cannot
        swallow a run of narrower candidates and leave Jev only that broad label to choose."""
    labels = label_clusters_with_retry(result, question, client, flag_non_answers=for_other)
    real_labels = [l for l in labels if l.cluster_id != OTHER_CLUSTER_ID]  # drop any synthesized "Other"
    non_answer_ids = {l.cluster_id for l in real_labels if l.non_answer}
    non_answer_rows = [m.row for c in result.clusters if c.id in non_answer_ids for m in c.members]
    real_labels = [l for l in real_labels if not l.non_answer]
    if not real_labels:
        return ConsolidatedCandidates(
            result=ClusterResult(column=result.column, clusters=[], noise=[], total_answers=result.total_answers),
            labels=[], non_answer_rows=non_answer_rows,
        )
    kept = ClusterResult(
        column=result.column, clusters=[c for c in result.clusters if c.id not in non_answer_ids],
        noise=result.noise, total_answers=result.total_answers,
    )
    merged_result, merged_labels = apply_merges(kept, real_labels, allow_chains=not for_other)
    return ConsolidatedCandidates(result=merged_result, labels=merged_labels, non_answer_rows=non_answer_rows)


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
    unclassifiable"). A match below `MIN_MATCH_CONFIDENCE` is already `NONE_OF_THESE` in `by_row` and is
    listed in `low_confidence_rows`; `confidence_by_row` keeps Jev's raw number for every answered row."""
    by_row: dict[int, str] = field(default_factory=dict)
    confidence_by_row: dict[int, float] = field(default_factory=dict)
    low_confidence_rows: list[int] = field(default_factory=list)  # Jev picked a theme, but below the floor
    failed_rows: list[int] = field(default_factory=list)  # a row whose Jev call raised, text never lost
    sample_error: str | None = None  # the first failure's message, e.g. "JevError: Jev returned HTTP 402."


def classify_other_answers(
    row_indexes: list[int],
    texts: list[str],
    criteria: dict[str, str | None],
    client: JevClient,
    *,
    instructions: str = "Classify which theme this survey answer is about.",
    concurrency: int = DEFAULT_CLASSIFY_CONCURRENCY,
    min_confidence: float = MIN_MATCH_CONFIDENCE,
    on_progress: Callable[[int, int, dict[int, str], list[int]], None] | None = None,
    progress_interval: float = 1.0,
) -> OtherClassification:
    """Runs every `(row, text)` pair through `client.classify_choice` against the SAME shared `criteria`,
    in parallel via a thread pool (same "network I/O releases the GIL, so this is real wall-clock
    parallelism" reasoning as `embeddings.py`'s own concurrent batching - Jev calls are blocking HTTP,
    not CPU work). A single row's failure (a real `JevError`, e.g. a transient network issue Jev's own
    one-retry already could not recover from) is recorded in `failed_rows` and does not stop the rest of
    the batch - thousands of independent per-row calls should not all be thrown away for one bad one.

    Found live, 2026-10-23: a SYSTEMIC failure (every single call rejected - a bad/expired API key, say)
    used to look identical to "every answer genuinely didn't match anything": nothing was ever logged
    here, and the caller's own summary (`app/api_themes.py::_apply_other_classification`) had nowhere to
    report `failed_rows` either - a 19,799-row job that failed 19,799/19,799 times on an auth error
    finished looking like a clean, legitimate zero-match result. Now logs once per call (not once per
    row - this can run at thousands of rows), at `warning` for any failures and `error` when EVERY row
    failed (the systemic case), with one sample exception message to point at the real cause.

    A theme match below `min_confidence` (default `MIN_MATCH_CONFIDENCE`) is recorded as `NONE_OF_THESE`,
    so the answer stays in Other (BUG-032)."""
    out = OtherClassification()
    if not row_indexes:
        return out

    def _one(row: int, text: str) -> tuple[int, ChoiceAnswer | None, str | None]:
        try:
            answer = client.classify_choice(
                text, question_key="other_classification", instructions=instructions, criteria=criteria,
            )
            return row, answer, None
        except Exception as e:
            return row, None, f"{type(e).__name__}: {e}"

    sample_error: str | None = None
    total, done, last_report = len(row_indexes), 0, float("-inf")
    with ThreadPoolExecutor(max_workers=min(concurrency, len(row_indexes))) as pool:
        for row, answer, error in pool.map(_one, row_indexes, texts):
            done += 1
            if answer is None:
                out.failed_rows.append(row)
                sample_error = sample_error or error
            elif answer.choice != NONE_OF_THESE and answer.confidence < min_confidence:
                out.by_row[row] = NONE_OF_THESE
                out.confidence_by_row[row] = answer.confidence
                out.low_confidence_rows.append(row)
            else:
                out.by_row[row] = answer.choice
                out.confidence_by_row[row] = answer.confidence
            # Live progress for the report's "Inside Other" panel: throttled (thousands of rows), and
            # always sent once at the end so the last counts are complete.
            if on_progress is not None:
                now = time.monotonic()
                if now - last_report >= progress_interval or done == total:
                    last_report = now
                    on_progress(done, total, out.by_row, out.failed_rows)
    out.sample_error = sample_error
    if out.failed_rows:
        level = log.error if len(out.failed_rows) == len(row_indexes) else log.warning
        level(
            "classify_other_answers: %d/%d rows failed%s. Sample error: %s",
            len(out.failed_rows), len(row_indexes),
            " (EVERY row failed - likely a systemic/auth problem, not per-row noise)"
            if len(out.failed_rows) == len(row_indexes) else "",
            sample_error,
        )
    return out


def sub_cluster_candidates(
    rows_by_parent: dict[int, list[int]], vec_by_row: dict[int, list[float]], text_by_row: dict[int, str],
) -> dict[int, list[Cluster]]:
    """Stage 3a (docs/TODO.md, 2026-10-23): the same sub-clustering technique
    `subthemes.sub_cluster_themes` already uses for a normal top-level build - "Look inside Other"'s own
    newly-discovered themes get a second, nested pass too, so their own Icicle chart has real sub-theme
    data instead of flat blocks. Adapted to run against a plain `{parent_id: [row, ...]}` map and a
    `{row: vector}` lookup rather than a `ClusterResult`/`EmbeddedAnswers` pair from a just-finished
    HDBSCAN build - these candidates came from Jev's own classification, not from `cluster_answers`, so
    there is no such pair to reuse directly. Reuses `subthemes.py`'s own constants/floor
    (`MIN_THEME_SIZE_FOR_SUBTHEMES`, `MAX_SUBTHEMES_PER_THEME`, `MIN_SUBTHEME_COVERAGE`,
    `sub_cluster_min_size`) unchanged, so a newly-found theme is held to the exact same "worth a second
    pass" bar as any top-level theme, not a second, looser standard invented for this feature.

    `parent_id` is caller-assigned (the caller's own enumeration over its surviving new themes, not a
    real `Theme.id` - those don't exist yet at this point, same reasoning `label_sub_clusters`'s own
    docstring gives for the top-level case). Returns only the parents that actually got a kept sub-split
    (>=2 surviving sub-clusters covering >=50% of the parent) - same contract as `sub_cluster_themes`."""
    out: dict[int, list[Cluster]] = {}
    for parent_id, rows in rows_by_parent.items():
        if len(rows) < MIN_THEME_SIZE_FOR_SUBTHEMES:
            continue
        vectors = [vec_by_row[r] for r in rows]
        texts = [text_by_row[r] for r in rows]
        sub_result = cluster_answers(vectors, texts, rows, min_cluster_size=sub_cluster_min_size(len(rows)))
        kept = sub_result.clusters[:MAX_SUBTHEMES_PER_THEME]
        coverage = sum(len(c.members) for c in kept) / len(rows) if rows else 0.0
        if len(kept) >= 2 and coverage >= MIN_SUBTHEME_COVERAGE:
            out[parent_id] = kept
    return out
