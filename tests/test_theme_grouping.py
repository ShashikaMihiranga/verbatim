"""Theme grouping with Claude (app/theme_grouping.py): payload privacy and reply validation."""
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import theme_grouping as tg
from app.cleaning.models import CleaningPlan
from app.cleaning.payload import model_safe_rows


def theme(id_, label, size, centroid=None):
    return SimpleNamespace(id=id_, label=label, size=size, centroid=centroid, answer_refs=list(range(size)))


THEMES = {1: theme(1, "Cleaning", 50, [1, 0]), 2: theme(2, "Janitors", 30, [0.9, 0.1]),
          3: theme(3, "Parking", 20, [0, 1]), 4: theme(4, "Other", 99)}
ID_OF = {1: 1, 2: 2, 3: 3, 4: 4}  # payload number -> theme id


def reply(groups, kept=()):
    return json.dumps({"groups": groups, "kept_apart": list(kept)})


def test_valid_groups_get_bands_and_are_ordered():
    groups, kept, dropped = tg.validate(reply([
        {"name": "Cleanliness", "members": [1, 2], "confidence": 94, "reason": "Both are about cleaning."},
    ], [{"members": [1, 3], "reason": "Different places."}]), ID_OF, THEMES)
    assert dropped == 0
    assert [(g["name"], g["member_ids"], g["band"], g["confidence"]) for g in groups] == [("Cleanliness", [1, 2], "High", 94)]
    assert groups[0]["similarity"] == pytest.approx(0.994, abs=0.001)
    assert kept == [{"names": ["Cleaning", "Parking"], "reason": "Different places."}]


@pytest.mark.parametrize("bad", [
    {"name": "x", "members": [1, 99], "confidence": 90},  # unknown id
    {"name": "x", "members": [1], "confidence": 90},  # under 2 members
    {"name": "x", "members": [1, 4], "confidence": 90},  # Other
    {"name": "x", "members": "1,2", "confidence": 90},  # wrong type
    {"name": "x", "members": [True, 2], "confidence": 90},  # booleans are not ids
])
def test_invalid_groups_are_dropped_not_fatal(bad):
    groups, _, dropped = tg.validate(reply([bad, {"name": "ok", "members": [2, 3], "confidence": 50}]), ID_OF, THEMES)
    assert dropped == 1 and [g["member_ids"] for g in groups] == [[2, 3]]


def test_overlapping_groups_keep_the_stronger_one():
    groups, _, dropped = tg.validate(reply([
        {"name": "weak", "members": [2, 3], "confidence": 55},
        {"name": "strong", "members": [1, 2], "confidence": 90},
    ]), ID_OF, THEMES)
    assert [g["name"] for g in groups] == ["strong"] and dropped == 1


def test_bands_and_the_similarity_check():
    assert [tg.band(c) for c in (100, 85, 84, 60, 59, 0)] == ["High", "High", "Medium", "Medium", "Low", "Low"]
    # Claude is sure, but Cleaning and Parking point different ways: shown as Medium.
    groups, _, _ = tg.validate(reply([{"name": "x", "members": [1, 3], "confidence": 95}]), ID_OF, THEMES)
    assert groups[0]["band"] == "Medium" and groups[0]["confidence"] == 95 and groups[0]["similarity"] == 0.0
    # No stored centroid (an older build): not checked, Claude's band stands.
    no_c = {**THEMES, 3: theme(3, "Parking", 20)}
    groups, _, _ = tg.validate(reply([{"name": "x", "members": [1, 3], "confidence": 95}]), ID_OF, no_c)
    assert groups[0]["band"] == "High" and groups[0]["similarity"] is None


def test_order_is_confidence_then_combined_share():
    themes = {**THEMES, 5: theme(5, "Bins", 10, [1, 0]), 6: theme(6, "Lifts", 5, [0, 1])}
    id_of = {n: n for n in themes}
    groups, _, _ = tg.validate(reply([
        {"name": "small", "members": [3, 6], "confidence": 70},  # 25 answers
        {"name": "big", "members": [1, 5], "confidence": 70},  # 60 answers
        {"name": "twice", "members": [2, 2], "confidence": 90},  # one theme listed twice: not a group
    ]), id_of, themes)
    assert [g["name"] for g in groups] == ["big", "small"]  # same confidence: larger combined share first
    groups, _, _ = tg.validate(reply([
        {"name": "small", "members": [3, 6], "confidence": 70},
        {"name": "sure", "members": [2, 5], "confidence": 90},
    ]), id_of, themes)
    assert [g["name"] for g in groups] == ["sure", "small"]  # confidence first


def test_unreadable_replies_give_nothing():
    assert tg.validate("not json at all", ID_OF, THEMES) == ([], [], 0)
    assert tg.validate('Sure! {"groups": [{"name": "x", "members": [1, 2], "confidence": 90}]}', ID_OF, THEMES)[0][0]["name"] == "x"


def test_payload_masks_samples_leaves_out_other_and_sends_nothing_else(monkeypatch):
    df = pd.DataFrame({"Why": [
        "Email me at jane.doe@example.com about the dirty floors please",
        "Call 0412 345 678 because the bins overflow every single day",
        "The cleaners skip our floor on most Fridays this year",
        "Parking near the building is full by eight in the morning",
    ], "Secret": ["a", "b", "c", "d"]})
    seen = {}

    def fake_rows(clean_df, plan, column, rows):
        seen["column"], seen["rows"] = column, list(rows)
        return model_safe_rows(clean_df, plan, column, rows)

    monkeypatch.setattr(tg, "model_safe_rows", fake_rows)
    plan = SimpleNamespace(columns={"Why": {"kind": "open_text", "sensitive": False}})
    themes = [SimpleNamespace(id=7, label="Cleaning", size=3, answer_refs=[0, 1, 2], centroid=None),
              SimpleNamespace(id=8, label="Parking", size=1, answer_refs=[3], centroid=None),
              SimpleNamespace(id=9, label="Other", size=5, answer_refs=[]),]
    payload, id_of = tg.build_payload(themes, df, plan, "Why")
    assert seen["column"] == "Why"
    assert [t["name"] for t in payload["themes"]] == ["Cleaning", "Parking"] and id_of == {1: 7, 2: 8}
    text = json.dumps(payload)
    assert "jane.doe@example.com" not in text and "0412 345 678" not in text
    assert "Secret" not in text and "row" not in text
    assert set(payload["themes"][0]) == {"id", "name", "answers", "share", "samples"}
    assert len(payload["themes"][0]["samples"]) == 3
    assert tg.payload_hash(payload) == tg.payload_hash(json.loads(text))  # stable cache key


def test_payload_refuses_too_few_or_too_many_themes():
    plan = SimpleNamespace(columns={"Why": {"kind": "open_text", "sensitive": False}})
    df = pd.DataFrame({"Why": ["x"]})
    with pytest.raises(tg.GroupingRefused):
        tg.build_payload([SimpleNamespace(id=1, label="A", size=1, answer_refs=[0])], df, plan, "Why")
    many = [SimpleNamespace(id=i, label=f"T{i}", size=1, answer_refs=[]) for i in range(tg.MAX_THEMES + 1)]
    with pytest.raises(tg.GroupingRefused):
        tg.build_payload(many, df, plan, "Why")


# ---------------------------------------------------------------- graph grouping
import math as _math  # noqa: E402
import time  # noqa: E402

from app.text_pipeline.embeddings import FakeEmbeddingClient  # noqa: E402


def at(deg, id_, label=None, size=10, sentiment=None):
    """A theme whose 2-D centroid sits at `deg` degrees: cosine similarity of two is cos(angle between)."""
    r = _math.radians(deg)
    return SimpleNamespace(id=id_, label=label or f"T{id_}", size=size, sentiment=sentiment,
                           centroid=[_math.cos(r), _math.sin(r)], answer_refs=[])


def groups_of(result):
    return [g["member_ids"] for g in result["groups"]]


def test_chains_do_not_become_one_group():
    # A-B, B-C, C-D are each 30 degrees apart (cos 0.866); A-C is 60 degrees (0.5). Complete linkage keeps
    # every pair above the cutoff, so the chain splits instead of pulling A and D together.
    themes = [at(0, 1, size=40), at(30, 2, size=30), at(60, 3, size=20), at(90, 4, size=10)]
    out = tg.graph_suggestions(themes, cutoff=0.8, border=0.4, centre=False)
    assert out["groups"] and all(len(g) == 2 for g in groups_of(out))
    assert not any({1, 3} <= set(g) or {1, 4} <= set(g) for g in groups_of(out))


def test_a_tight_group_and_its_weakest_pair():
    themes = [at(0, 1, size=50), at(10, 2, size=40), at(20, 3, size=30), at(120, 4, size=20)]
    out = tg.graph_suggestions(themes, cutoff=0.9, border=0.5, centre=False)
    assert groups_of(out) == [[1, 2, 3]]
    assert out["groups"][0]["similarity"] == pytest.approx(_math.cos(_math.radians(20)), abs=0.001)


def test_opposite_tone_never_groups_and_is_reported():
    themes = [at(0, 1, "Pay is fair", sentiment=0.5), at(5, 2, "Pay is too low", sentiment=-0.6)]
    out = tg.graph_suggestions(themes, cutoff=0.8, border=0.5, centre=False)
    assert out["groups"] == [] and out["borderline"] == []
    assert [(a, b) for a, b, _s in out["tone_blocked"]] == [(1, 2)]
    # mild or unknown tone does not block
    assert groups_of(tg.graph_suggestions([at(0, 1, sentiment=0.1), at(5, 2, sentiment=-0.6)], 0.8, 0.5, centre=False)) == [[1, 2]]
    assert groups_of(tg.graph_suggestions([at(0, 1), at(5, 2, sentiment=-0.6)], 0.8, 0.5, centre=False)) == [[1, 2]]


def test_close_calls_sit_between_border_and_cutoff():
    themes = [at(0, 1, size=40), at(5, 2, size=30), at(40, 3, size=20), at(150, 4, size=10)]
    out = tg.graph_suggestions(themes, cutoff=0.9, border=0.7, centre=False)
    assert groups_of(out) == [[1, 2]]
    # theme 3 vs the group {1,2}: its weakest pair is with theme 1, cos 40 = 0.766, a close call
    assert out["borderline"] == [{"a": [1, 2], "b": [3], "similarity": pytest.approx(0.766, abs=0.001)}]


def test_other_and_themes_without_a_centroid_are_left_out():
    themes = [at(0, 1), at(1, 2, "Other"), at(2, 3)]
    themes[2].centroid = None
    out = tg.graph_suggestions(themes, cutoff=0.8, border=0.5, centre=False)
    assert out["groups"] == [] and out["missing_centroids"] == 1


def test_groups_never_exceed_the_merge_limit():
    themes = [at(i * 0.01, i + 1) for i in range(tg.MAX_GROUP + 5)]
    assert all(len(g) <= tg.MAX_GROUP for g in groups_of(tg.graph_suggestions(themes, 0.9, 0.5, centre=False)))


def test_same_themes_same_answer_whatever_the_order():
    themes = [at(0, 1, size=40), at(8, 2, size=30), at(16, 3, size=20), at(70, 4, size=15), at(76, 5, size=12)]
    first = tg.graph_suggestions(themes, 0.95, 0.8, centre=False)
    assert tg.graph_suggestions(list(reversed(themes)), 0.95, 0.8, centre=False) == first


def test_hundreds_of_themes_take_milliseconds():
    import random
    rnd = random.Random(1)
    themes = [SimpleNamespace(id=i, label=f"T{i}", size=rnd.randint(5, 500), sentiment=rnd.uniform(-1, 1),
                              centroid=[rnd.gauss(0, 1) for _ in range(1024)], answer_refs=[]) for i in range(300)]
    start = time.perf_counter()
    tg.graph_suggestions(themes)
    assert time.perf_counter() - start < 1.0


def test_ensure_centroids_embeds_masked_answers_once():
    df = pd.DataFrame({"Why": ["Email jane.doe@example.com, the floors are dirty", "Bins overflow daily",
                               "Parking is full", "Parking costs too much"]})
    plan = SimpleNamespace(columns={"Why": {"kind": "open_text", "sensitive": False}})
    sent = []

    class Spy(FakeEmbeddingClient):
        def embed(self, texts):
            sent.append(list(texts))
            return super().embed(texts)

    done = SimpleNamespace(id=3, label="Done", size=1, centroid=[1.0, 0.0], answer_refs=[2])
    themes = [SimpleNamespace(id=1, label="Cleaning", size=2, centroid=None, answer_refs=[0, 1]),
              SimpleNamespace(id=2, label="Parking", size=2, centroid=None, answer_refs=[2, 3]), done,
              SimpleNamespace(id=4, label="Other", size=9, centroid=None, answer_refs=[0])]
    client = Spy()
    assert tg.ensure_centroids(themes, df, plan, "Why", client) == 4
    assert len(sent) == 1 and "jane.doe@example.com" not in " ".join(sent[0])
    expected = np.mean(client.embed(["Parking is full", "Parking costs too much"]), axis=0)
    assert themes[1].centroid == [round(float(v), 4) for v in expected]
    assert done.centroid == [1.0, 0.0] and themes[3].centroid is None  # kept / Other never embedded
    sent.clear()
    assert tg.ensure_centroids(themes, df, plan, "Why", client) == 0 and sent == []  # second run: no call


def test_centring_removes_what_every_theme_shares():
    # Ten themes that all share one big direction (the survey's topic) plus a small own direction each:
    # raw similarity is high for every pair; centred, only the two themes with the same own direction match.
    rnd = np.random.default_rng(0)
    shared = rnd.normal(size=64) * 5
    own = [rnd.normal(size=64) for _ in range(9)]
    vecs = [shared + own[0], shared + own[0] + rnd.normal(size=64) * 0.1] + [shared + o for o in own[1:]]
    themes = [SimpleNamespace(id=i + 1, label=f"T{i + 1}", size=10, sentiment=None, centroid=list(v), answer_refs=[])
              for i, v in enumerate(vecs)]
    raw = tg.similarity_matrix(tg.graph_nodes(themes), centre=False)
    assert raw[np.triu_indices(10, 1)].min() > 0.8
    assert groups_of(tg.graph_suggestions(themes)) == [[1, 2]]


def checked(themes, cands, reply, graph=None):
    by_id = {t.id: t for t in themes}
    id_of = {n: i for n, i in enumerate(dict.fromkeys(i for c in cands for i in c["member_ids"]), start=1)}
    graph = graph or {"tone_blocked": [], "_sim": {}}
    return tg.apply_check(json.dumps(reply), cands, id_of, by_id, graph)


def cand(id_, ids, sim, close=False):
    return {"id": id_, "member_ids": ids, "similarity": sim, "close_call": close}


TH = [SimpleNamespace(id=i, label=n, size=s) for i, n, s in
      [(1, "Parking cost", 50), (2, "Parking safety", 40), (3, "Parking spaces", 30), (4, "Noise", 20), (5, "Loud coworkers", 10)]]
SIM = {"tone_blocked": [], "_sim": {(1, 2): 0.86, (1, 3): 0.8, (2, 3): 0.75, (4, 5): 0.9, (1, 4): 0.1, (1, 5): 0.1,
                                    (2, 4): 0.1, (2, 5): 0.1, (3, 4): 0.1, (3, 5): 0.1}}


def test_claude_keeps_rejects_and_shrinks_candidates():
    cands = [cand("c1", [1, 2, 3], 0.75), cand("c2", [4, 5], 0.9)]
    groups, kept, rejected = checked(TH, cands, {"candidates": [
        {"id": "c1", "merge": True, "drop": [2], "name": "Parking", "reason": "Both about finding a space."},
        {"id": "c2", "merge": False, "reason": "Different sources of noise."}]}, SIM)
    assert [(g["name"], g["member_ids"], g["band"], g["confidence"]) for g in groups] == [("Parking", [1, 3], "High", 80)]
    assert kept == [{"names": ["Noise", "Loud coworkers"], "reason": "Different sources of noise."}] and rejected == 1


def test_claude_cannot_add_themes_and_unreadable_verdicts_suggest_nothing():
    cands = [cand("c1", [4, 5], 0.9)]
    groups, _k, _r = checked(TH, cands, {"candidates": [{"id": "c1", "merge": True, "drop": [], "name": "Noise",
                                                         "reason": "x", "members": [1, 2, 3, 4, 5]}]}, SIM)
    assert [g["member_ids"] for g in groups] == [[4, 5]]
    assert tg.apply_check("not json", cands, {1: 4, 2: 5}, {t.id: t for t in TH}, SIM) == ([], [], 1)


def test_an_approved_close_call_extends_its_group_and_overlaps_are_skipped():
    cands = [cand("c1", [1, 3], 0.8), cand("c2", [2, 3], 0.75), cand("c3", [1, 3, 2], 0.7, close=True)]
    yes = lambda i: {"id": i, "merge": True, "name": "Parking", "reason": "r"}  # noqa: E731
    groups, _k, _r = checked(TH, cands, {"candidates": [yes("c1"), yes("c2"), yes("c3")]}, SIM)
    assert [sorted(g["member_ids"]) for g in groups] == [[1, 2, 3]]
    assert groups[0]["similarity"] == 0.75 and groups[0]["band"] == "Medium"


def test_tone_blocked_pairs_are_reported_as_kept_apart():
    graph = {**SIM, "tone_blocked": [(4, 5, 0.9)]}
    _g, kept, _r = checked(TH, [], {"candidates": []}, graph)
    assert kept == [{"names": ["Noise", "Loud coworkers"], "reason": "Similar topic, opposite tone."}]


def test_check_payload_sends_only_candidate_themes_masked():
    df = pd.DataFrame({"Why": ["Email jane.doe@example.com: parking costs a fortune every week",
                               "Parking at night feels unsafe and badly lit", "Too noisy near the kitchen area today"]})
    plan = SimpleNamespace(columns={"Why": {"kind": "open_text", "sensitive": False}})
    themes = [SimpleNamespace(id=7, label="Parking cost", size=1, answer_refs=[0]),
              SimpleNamespace(id=8, label="Parking safety", size=1, answer_refs=[1]),
              SimpleNamespace(id=9, label="Noise", size=1, answer_refs=[2])]
    payload, id_of = tg.build_check_payload([cand("c1", [7, 8], 0.8)], themes, df, plan, "Why")
    text = json.dumps(payload)
    assert id_of == {1: 7, 2: 8} and "Noise" not in text and "jane.doe@example.com" not in text
    assert payload["candidates"] == [{"id": "c1", "themes": [1, 2]}]
    assert set(payload["themes"][0]) == {"id", "name", "answers", "share", "samples"}


def test_unchecked_fallback_shows_only_strong_groups_as_low():
    graph = {"groups": [{"member_ids": [4, 5], "similarity": 0.9}, {"member_ids": [1, 2], "similarity": 0.72}]}
    out = tg.unchecked_groups(graph, {t.id: t for t in TH})
    assert [(g["member_ids"], g["band"], g["name"]) for g in out] == [([4, 5], "Low", "Noise")]
