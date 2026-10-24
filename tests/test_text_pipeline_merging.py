"""Pure graph-logic tests for app/text_pipeline/merging.py - no network, no fakes needed, since merging
only ever operates on already-labeled ClusterResult/ThemeLabel data. See that module's own docstring for
why this exists: Claude's `merge_with` field was parsed and validated but never consumed anywhere before
this module."""
from app.text_pipeline import Cluster, ClusterMember, ClusterResult, ThemeLabel
from app.text_pipeline.labeling import OTHER_CLUSTER_ID
from app.text_pipeline.merging import apply_merges, apply_sub_merges, merge_groups, star_groups


def _cluster(id_: int, n: int) -> Cluster:
    return Cluster(id=id_, members=[ClusterMember(row=r, text=f"t{r}", distance=0.1) for r in range(n)], centroid=None)


def _label(cluster_id: int, label: str, size: int, merge_with: list[int] | None = None, note: str | None = None) -> ThemeLabel:
    return ThemeLabel(
        cluster_id=cluster_id, label=label, description=f"About {label}.", size=size,
        merge_with=merge_with or [], note=note,
    )


# ---------------------------------------------------------------------------------- merge_groups


def test_merge_groups_no_edges_returns_all_singletons():
    assert merge_groups([0, 1, 2], {}) == [[0], [1], [2]]


def test_merge_groups_one_directional_edge_still_merges():
    """A flags B; B's own edge list never mentions A. Under-merging is worse than over-merging here -
    a deliberate choice, not a bug to "fix" into requiring reciprocation."""
    assert merge_groups([0, 1, 2], {0: [1]}) == [[0, 1], [2]]


def test_merge_groups_transitive_chain_merges_into_one_component():
    assert merge_groups([0, 1, 2], {0: [1], 1: [2]}) == [[0, 1, 2]]


def test_merge_groups_ignores_edge_targets_outside_the_given_ids():
    """Defensive: an edge pointing outside the id space handed in (e.g. the Other sentinel, or an id
    apply_sub_merges already filtered out) is silently ignored, not an error."""
    assert merge_groups([0, 1], {0: [1, -1, 99]}) == [[0, 1]]


# ---------------------------------------------------------------------------------- apply_merges


def test_apply_merges_combines_members_and_sums_size():
    result = ClusterResult(
        column="c", clusters=[_cluster(0, 10), _cluster(1, 5)],
        noise=[], total_answers=15,
    )
    labels = [_label(0, "Dress fit", 10, merge_with=[1]), _label(1, "Pants fit", 5)]

    new_result, new_labels = apply_merges(result, labels)

    assert len(new_result.clusters) == 1
    assert len(new_result.clusters[0].members) == 15
    assert new_labels[0].size == 15


def test_apply_merges_inherits_largest_clusters_label_and_description():
    result = ClusterResult(column="c", clusters=[_cluster(0, 10), _cluster(1, 5)], noise=[], total_answers=15)
    labels = [_label(0, "Dress fit", 10, merge_with=[1]), _label(1, "Pants fit", 5)]

    _, new_labels = apply_merges(result, labels)

    assert new_labels[0].label == "Dress fit"
    assert new_labels[0].description == "About Dress fit."


def test_apply_merges_renumbers_ids_largest_first():
    result = ClusterResult(
        column="c", clusters=[_cluster(0, 3), _cluster(1, 10), _cluster(2, 5)],
        noise=[], total_answers=18,
    )
    labels = [_label(0, "Small", 3), _label(1, "Big", 10), _label(2, "Medium", 5)]

    new_result, new_labels = apply_merges(result, labels)

    assert [c.id for c in new_result.clusters] == [0, 1, 2]
    assert [l.size for l in new_labels] == [10, 5, 3]  # largest first, no merges happened


def test_apply_merges_noise_and_total_answers_untouched():
    noise = [ClusterMember(row=99, text="x", distance=None)]
    result = ClusterResult(column="c", clusters=[_cluster(0, 10)], noise=noise, total_answers=11)
    labels = [_label(0, "Only", 10)]

    new_result, _ = apply_merges(result, labels)

    assert new_result.noise == noise
    assert new_result.total_answers == 11
    assert new_result.column == "c"


def test_apply_merges_no_merges_is_a_no_op_in_content():
    result = ClusterResult(column="c", clusters=[_cluster(0, 10), _cluster(1, 5)], noise=[], total_answers=15)
    labels = [_label(0, "A", 10), _label(1, "B", 5)]

    new_result, new_labels = apply_merges(result, labels)

    assert [(c.id, len(c.members)) for c in new_result.clusters] == [(0, 10), (1, 5)]
    assert [(l.cluster_id, l.label, l.size) for l in new_labels] == [(0, "A", 10), (1, "B", 5)]


def test_apply_merges_also_merges_clusters_sharing_the_exact_same_label_with_no_merge_with_edge():
    """Confirmed empirically necessary (docs/DECISIONS.md): Claude reliably names several clusters
    identically along a consistent axis without exhaustively flagging every pair via merge_with - two
    same-labeled clusters must still consolidate, not stay as separate, confusingly-duplicate boxes."""
    result = ClusterResult(column="c", clusters=[_cluster(0, 10), _cluster(1, 5), _cluster(2, 3)], noise=[], total_answers=18)
    labels = [_label(0, "Fit and sizing", 10), _label(1, "Fit and sizing", 5), _label(2, "Cost", 3)]

    new_result, new_labels = apply_merges(result, labels)

    assert len(new_result.clusters) == 2
    fit = next(l for l in new_labels if l.label == "Fit and sizing")
    assert fit.size == 15


def test_apply_merges_same_label_match_is_case_and_whitespace_insensitive():
    result = ClusterResult(column="c", clusters=[_cluster(0, 10), _cluster(1, 5)], noise=[], total_answers=15)
    labels = [_label(0, "Fit and sizing", 10), _label(1, "  fit AND sizing  ", 5)]

    new_result, _ = apply_merges(result, labels)

    assert len(new_result.clusters) == 1


def test_apply_sub_merges_also_merges_same_labeled_sub_clusters_within_one_parent():
    sub_clusters = {10: [_cluster(0, 8), _cluster(1, 4), _cluster(2, 2)]}
    sub_labels = {10: [_label(0, "Fabric quality", 8), _label(1, "Fabric quality", 4), _label(2, "Length", 2)]}

    new_sc, new_sl = apply_sub_merges(sub_clusters, sub_labels)

    assert len(new_sc[10]) == 2
    assert sorted(l.size for l in new_sl[10]) == [2, 12]


def test_apply_merges_excludes_other_from_the_merge_graph_and_passes_it_through():
    result = ClusterResult(column="c", clusters=[_cluster(0, 10)], noise=[ClusterMember(row=5, text="x", distance=None)], total_answers=11)
    labels = [_label(0, "Real theme", 10), _label(OTHER_CLUSTER_ID, "Other", 1)]

    new_result, new_labels = apply_merges(result, labels)

    assert len(new_result.clusters) == 1
    other = [l for l in new_labels if l.cluster_id == OTHER_CLUSTER_ID]
    assert len(other) == 1 and other[0].label == "Other" and other[0].size == 1


# ---------------------------------------------------------------------------------- apply_sub_merges


def test_apply_sub_merges_merges_within_one_parent():
    sub_clusters = {10: [_cluster(0, 8), _cluster(1, 4), _cluster(2, 2)]}
    sub_labels = {10: [_label(0, "A", 8, merge_with=[1]), _label(1, "B", 4), _label(2, "E", 2)]}

    new_sc, new_sl = apply_sub_merges(sub_clusters, sub_labels)

    assert len(new_sc[10]) == 2  # A+B merged, E stays separate
    assert sorted(len(c.members) for c in new_sc[10]) == [2, 12]


def test_apply_sub_merges_never_merges_across_parents():
    """Two parents whose sub-clusters happen to carry overlapping-looking merge targets across the flat
    id space - a same-parent-only filter must prevent any cross-parent merge regardless."""
    sub_clusters = {
        10: [_cluster(0, 8), _cluster(1, 4), _cluster(2, 2)],
        20: [_cluster(3, 6), _cluster(4, 3)],
    }
    sub_labels = {
        10: [_label(0, "A", 8, merge_with=[3]), _label(1, "B", 4), _label(2, "E", 2)],
        20: [_label(3, "C", 6), _label(4, "D", 3)],
    }

    new_sc, _ = apply_sub_merges(sub_clusters, sub_labels)

    assert len(new_sc[10]) == 3  # the cross-parent merge_with=[3] was ignored entirely
    assert len(new_sc[20]) == 2


def test_apply_sub_merges_drops_parent_when_merge_leaves_fewer_than_two_groups():
    sub_clusters = {10: [_cluster(0, 8), _cluster(1, 4)], 20: [_cluster(2, 6), _cluster(3, 3)]}
    sub_labels = {
        10: [_label(0, "A", 8, merge_with=[1]), _label(1, "B", 4)],  # merges down to 1 group
        20: [_label(2, "C", 6), _label(3, "D", 3)],
    }

    new_sc, new_sl = apply_sub_merges(sub_clusters, sub_labels)

    assert 10 not in new_sc and 10 not in new_sl
    assert 20 in new_sc and len(new_sc[20]) == 2


def test_apply_sub_merges_keeps_parent_when_merge_leaves_two_or_more_groups():
    sub_clusters = {10: [_cluster(0, 8), _cluster(1, 4), _cluster(2, 2)]}
    sub_labels = {10: [_label(0, "A", 8, merge_with=[1]), _label(1, "B", 4), _label(2, "E", 2)]}

    new_sc, new_sl = apply_sub_merges(sub_clusters, sub_labels)

    assert 10 in new_sc
    assert len(new_sc[10]) == 2 and len(new_sl[10]) == 2


def test_apply_sub_merges_empty_input_is_a_no_op():
    assert apply_sub_merges({}, {}) == ({}, {})


# ---------------------------------------------------------------------------------- no chaining (BUG-032)


def test_star_groups_does_not_follow_a_chain_past_the_anchor():
    """A-B and B-C, A largest: C was only ever linked to B, so it keeps its own group."""
    assert star_groups([[0], [1], [2]], {0: [1], 1: [2]}, {0: 30, 1: 20, 2: 10}) == [[0, 1], [2]]


def test_star_groups_largest_node_anchors_everything_it_links_directly():
    assert star_groups([[0], [1], [2]], {0: [1], 1: [2]}, {0: 10, 1: 30, 2: 20}) == [[0, 1, 2]]


def test_apply_merges_without_chains_keeps_narrow_labels_out_of_a_broad_one():
    """The dataset 12 shape: a broad candidate flags one neighbour, which flags the next, and so on.
    Union-find made one theme under the broad label; without chains only direct neighbours join it."""
    result = ClusterResult(column="q", clusters=[_cluster(i, 10 - i) for i in range(4)], noise=[], total_answers=34)
    labels = [_label(0, "Office layout and facility condition", 10, [1]), _label(1, "Cubicle walls", 9, [2]),
              _label(2, "Desk handedness", 8, [3]), _label(3, "Desk furniture", 7)]

    _res, chained_labels = apply_merges(result, labels)
    assert [l.label for l in chained_labels] == ["Office layout and facility condition"]

    _res, star_labels = apply_merges(result, labels, allow_chains=False)
    assert [(l.label, l.size) for l in star_labels] == [
        ("Office layout and facility condition", 19), ("Desk handedness", 15),
    ]


def test_apply_merges_without_chains_still_merges_same_label_clusters():
    result = ClusterResult(column="q", clusters=[_cluster(0, 5), _cluster(1, 4), _cluster(2, 3)], noise=[], total_answers=12)
    labels = [_label(0, "Fit", 5), _label(1, "fit ", 4), _label(2, "Price", 3)]
    _res, new_labels = apply_merges(result, labels, allow_chains=False)
    assert [(l.label, l.size) for l in new_labels] == [("Fit", 9), ("Price", 3)]


def test_apply_merges_keeps_the_biggest_labels_parent_theme():
    """Look inside Other places a group inside an existing theme (`parent_theme`); merging candidates must
    not drop that placement."""
    result = ClusterResult(column="Q", clusters=[_cluster(0, 5), _cluster(1, 3), _cluster(2, 4)], noise=[], total_answers=12)
    labels = [_label(0, "Delivery delays", 5, merge_with=[1]), _label(1, "Late parcels", 3), _label(2, "Colour", 4)]
    labels[0].parent_theme = "Shipping"
    _, merged = apply_merges(result, labels, allow_chains=False)
    by_label = {l.label: l for l in merged}
    assert by_label["Delivery delays"].parent_theme == "Shipping"
    assert by_label["Colour"].parent_theme is None
