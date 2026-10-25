"""Theme grouping with Claude (app/theme_grouping.py): payload privacy and reply validation."""
import json
from types import SimpleNamespace

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
