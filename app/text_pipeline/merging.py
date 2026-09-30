"""Actually applies the `merge_with` signal `labeling.py` already asks Claude for on every reply, but
which nothing consumed until now - confirmed via grep across app/*.py before this module existed: parsed
into `ThemeLabel.merge_with`, validated, and then never read again. A theme whose answers split across
several clusters that really describe the same underlying topic (e.g. "dress fit" and "pants fit" both
about fit and sizing - see labeling.py's SYSTEM prompt, which now asks Claude to prefer this kind of
merge) used to stay as separate, confusingly-similar theme boxes; this module actually consolidates them
into one, using the same batched Claude reply that already flagged it - no new LLM call, per CLAUDE.md's
"Claude sees samples and aggregated numbers only... cheap steps do the bulk" principle.

Every `merge_with` edge is treated as undirected: cluster A flagging cluster B is enough to merge them,
regardless of whether B's own reply reciprocates - under-merging (leaving two boxes that are really the
same theme) is worse than over-merging here, a deliberate choice, not an oversight. A merged theme's
label/description/note are inherited from the LARGEST original cluster in the merge, not a new Claude
call or a string concatenation - because every individual label was already pushed toward a consistent,
non-entity-specific axis by the SYSTEM prompt before any merging happens, the survivor's label is already
appropriate for the whole merged group, not just its own original slice.

`merge_with` alone was verified insufficient: a real rebuild against the dataset that originally exposed
the axis-mixing bug showed Claude reliably naming many clusters IDENTICALLY along the new consistent axis
(e.g. "Fit and sizing" x10) without exhaustively cross-referencing all of them against each other via
`merge_with` - so `_merge_one_level` also merges any two clusters sharing the exact same label
(case/whitespace-insensitive) as a code-level guarantee, not just an explicit `merge_with` edge.
"""
from __future__ import annotations

from .labeling import OTHER_CLUSTER_ID
from .schema import Cluster, ClusterResult, ThemeLabel


def merge_groups(cluster_ids: list[int], edges: dict[int, list[int]]) -> list[list[int]]:
    """Union-Find connected components over `cluster_ids`, treating every id in `edges.get(cid, [])` as
    an undirected edge from `cid` (an edge target not present in `cluster_ids` is ignored - defensive,
    though callers are expected to have already filtered to valid ids). A cluster with no edges is still
    returned as its own one-element component. Each component is returned as a sorted list of ids, in no
    particular order across components - callers that care about a specific ordering (e.g. largest-total-
    size-first) sort the returned list themselves, since this function has no notion of cluster "size"."""
    parent = {cid: cid for cid in cluster_ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for cid, targets in edges.items():
        if cid not in parent:
            continue
        for target in targets:
            if target in parent:
                union(cid, target)

    components: dict[int, list[int]] = {}
    for cid in cluster_ids:
        components.setdefault(find(cid), []).append(cid)
    return [sorted(group) for group in components.values()]


def _merge_one_level(
    cluster_ids: list[int], cluster_by_id: dict[int, Cluster], label_by_id: dict[int, ThemeLabel],
) -> tuple[list[Cluster], list[ThemeLabel]]:
    """Shared by `apply_merges` (top-level themes) and `apply_sub_merges` (one parent's own sub-themes):
    groups `cluster_ids` by `merge_with` (already filtered to this same id space by the caller - see
    `apply_sub_merges`'s same-parent-only filtering), combines each component's members, and renumbers
    0..K-1 largest-first, matching `label_clusters`'s/`sub_cluster_themes`'s own ordering convention.

    Merge edges come from two sources, not just `merge_with`: confirmed empirically (real rebuild against
    the same dataset that exposed the original axis-mixing bug, see docs/DECISIONS.md) that asking Claude
    to name a large batch of clusters along one consistent axis makes it name SEVERAL clusters identically
    (e.g. "Fit and sizing" x10) far more reliably than it exhaustively cross-references every one of those
    clusters against every other via `merge_with` - a same-label pair is useless to show as two separate
    boxes regardless of why Claude didn't also flag it, so two clusters sharing the exact same label
    (case/whitespace-insensitive) are merged as a code-level guarantee, independent of `merge_with`."""
    edges: dict[int, list[int]] = {cid: list(label_by_id[cid].merge_with) for cid in cluster_ids}
    by_label: dict[str, list[int]] = {}
    for cid in cluster_ids:
        by_label.setdefault(label_by_id[cid].label.strip().lower(), []).append(cid)
    for same_label_ids in by_label.values():
        for cid in same_label_ids[1:]:
            edges.setdefault(same_label_ids[0], []).append(cid)
    groups = merge_groups(cluster_ids, edges)
    groups.sort(key=lambda g: sum(label_by_id[cid].size for cid in g), reverse=True)

    new_clusters: list[Cluster] = []
    new_labels: list[ThemeLabel] = []
    for new_id, group in enumerate(groups):
        members = [m for cid in group for m in cluster_by_id[cid].members]
        # Centroid intentionally left None, not re-averaged: nothing downstream reads a Cluster's own
        # centroid after labeling (only `_representative_texts`, called before any merging happens, for
        # the ORIGINAL per-answer `.distance` values, which stay valid against their original centroid
        # and are never recomputed against a merged one either) - recomputing it would buy nothing.
        new_clusters.append(Cluster(id=new_id, members=members, centroid=None))
        biggest_id = max(group, key=lambda cid: label_by_id[cid].size)
        biggest = label_by_id[biggest_id]
        new_labels.append(ThemeLabel(
            cluster_id=new_id, label=biggest.label, description=biggest.description,
            size=len(members), merge_with=[], note=biggest.note,
        ))
    return new_clusters, new_labels


def apply_merges(result: ClusterResult, labels: list[ThemeLabel]) -> tuple[ClusterResult, list[ThemeLabel]]:
    """Consolidates `result.clusters`/`labels` per `merge_groups`, run over every real (non-"Other")
    cluster - "Other" (`cluster_id == OTHER_CLUSTER_ID`) is excluded from the merge graph entirely and
    passed through unchanged, since it's a locally-synthesized catch-all, never a real Claude-named
    theme, and must never absorb or be absorbed by one.

    Returns a new `ClusterResult` (same `column`/`noise`/`total_answers`; `clusters` rebuilt, still
    largest-first) and a new `labels` list (merged real themes first, in the rebuilt result's own order,
    then the "Other" entry if one existed) - both are drop-in replacements for their inputs at every
    downstream call site (`sub_cluster_themes`, `_write_theme_rows`), which read `ClusterResult`/
    `ThemeLabel` by their ordinary shape and need no changes to consume a merged result."""
    other_labels = [l for l in labels if l.cluster_id == OTHER_CLUSTER_ID]
    real_labels = [l for l in labels if l.cluster_id != OTHER_CLUSTER_ID]
    if not real_labels:
        return result, labels

    cluster_by_id = {c.id: c for c in result.clusters}
    label_by_id = {l.cluster_id: l for l in real_labels}
    new_clusters, new_labels = _merge_one_level(list(label_by_id), cluster_by_id, label_by_id)

    new_result = ClusterResult(
        column=result.column, clusters=new_clusters, noise=result.noise, total_answers=result.total_answers,
    )
    return new_result, new_labels + other_labels


def apply_sub_merges(
    sub_clusters: dict[int, list[Cluster]], sub_labels: dict[int, list[ThemeLabel]],
) -> tuple[dict[int, list[Cluster]], dict[int, list[ThemeLabel]]]:
    """Same consolidation as `apply_merges`, run INDEPENDENTLY within each parent theme's own sub-cluster
    list - never across parents. `label_sub_clusters` uses a flat, globally-unique id space across every
    parent's sub-clusters combined (see its own docstring), so a merge edge is restricted to ids already
    present in THIS parent's own `sub_labels[parent_id]` before grouping - structurally impossible to
    cross-merge into a different parent, regardless of what a reply's `merge_with` contains (SUB_SYSTEM's
    prompt already asks Claude not to suggest this; this is the code-level guarantee, not just a prompt
    instruction).

    After merging, re-applies `subthemes.py`'s own "at least 2 surviving sub-themes" gate
    (`MIN_SUBTHEME_COVERAGE`'s companion count check, `subthemes.sub_cluster_themes`'s `len(kept) >= 2`):
    if a parent's sub-clusters merge down to fewer than 2 groups, that parent is dropped from the
    returned dicts entirely (reverts to no stored sub-themes for it, the same outcome as if sub-clustering
    had never qualified it) rather than storing one "sub-theme" that's really just the parent again.
    Coverage itself never needs re-checking: merging only regroups the same members, so total coverage of
    the parent's answers is unchanged by construction."""
    new_sub_clusters: dict[int, list[Cluster]] = {}
    new_sub_labels: dict[int, list[ThemeLabel]] = {}
    for parent_id, clusters in sub_clusters.items():
        labels = sub_labels.get(parent_id) or []
        if not labels:
            continue
        cluster_by_id = dict(zip((l.cluster_id for l in labels), clusters))
        label_by_id = {l.cluster_id: l for l in labels}
        valid_ids = set(label_by_id)
        filtered_label_by_id = {
            cid: ThemeLabel(
                cluster_id=lbl.cluster_id, label=lbl.label, description=lbl.description, size=lbl.size,
                merge_with=[m for m in lbl.merge_with if m in valid_ids], note=lbl.note,
            )
            for cid, lbl in label_by_id.items()
        }
        merged_clusters, merged_labels = _merge_one_level(list(valid_ids), cluster_by_id, filtered_label_by_id)
        if len(merged_clusters) < 2:
            continue
        new_sub_clusters[parent_id] = merged_clusters
        new_sub_labels[parent_id] = merged_labels
    return new_sub_clusters, new_sub_labels
