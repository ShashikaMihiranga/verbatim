"""Adaptive cleaning (stream 5). All data is written inline; no network."""
import hashlib
import json
import random
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api_upload import current_user
from app.cleaning import (CleaningError, apply_plan, model_safe_samples, plan_cleaning, plan_with_preview,
                          redact_text)
from app.db import Base, get_db
from app.main import app

Q = "Why haven't you bought an EV?"


# ---------------------------------------------------------------- fixtures
def profile_for(df, kinds, sensitive=()):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": c in sensitive}
                        for c in df.columns]}


def _shuffled(items, seed):
    items = list(items)
    random.Random(seed).shuffle(items)
    return items


def car_survey():
    """300 rows of a messy EV survey. Counts are exact so the tests can check them."""
    long_a = "The public charging network is not reliable anywhere near where I live or work at all"  # 16 words
    long_b = "I simply cannot afford the upfront price of a new electric car at the moment sorry"  # 15 words
    openers = ["Worried about", "Concerned by", "Not sure about", "Put off by", "Waiting on"]
    topics = ["battery life", "resale value", "charging time", "insurance cost", "range anxiety", "home wiring",
              "winter driving", "servicing costs", "the price", "long trips", "second hand supply"]
    ends = ["for now", "at this stage", "these days", "right now", "in my area"]
    text = (["n/a"] * 5 + ["N/A"] * 3 + ["None"] * 3 + ["idk"] * 2 + ["...."] * 2 + ["asdf"] * 3 + ["qwerty"] * 2
            + ["aaaaa"] * 2 + ["hjkl"] * 1)  # 15 non-answers + 8 mash
    text += [f"{openers[i % 5]} {topics[i % 11]} {ends[i % 5]} case {i}, mail me at person{i}@example.com" for i in range(12)]
    text += [f"{openers[i % 5]} {topics[i % 11]} {ends[i % 5]} case {i}, ring 04{i % 10}2 345 67{i % 10}" for i in range(6)]
    text += [long_a] * 9 + [long_b] * 6  # 8 + 5 removable repeats
    text += [f"{openers[i % 5]} {topics[i % 11]} {ends[i % 5]} case {i}" for i in range(300 - len(text))]
    assert len(text) == 300
    brand = (["Tesla"] * 80 + ["tesla"] * 20 + ["TESLA "] * 10 + ["Telsa"] * 5 + ["Toyota"] * 60 + ["toyota"] * 15
             + ["Toyotta"] * 4 + ["Ford"] * 50 + ["Rivian"] * 30 + ["Rivan"] * 3 + ["Lucid"] * 23)
    score = ["5", "4", "3", "2", "1", " 3 "] * 48 + ["9"] * 3 + ["10"] * 2 + ["x"] * 2 + ["4/5"] * 5
    date = (["2025-03-14"] * 100 + ["14/03/2025"] * 60 + ["03/04/2025"] * 40 + ["Mar 5, 2025"] * 50
            + ["31/02/2025"] * 5 + ["sometime"] * 3 + ["2025-06-01"] * 42)
    spend = (["$1,250"] * 50 + ["2,500"] * 50 + ["(300)"] * 20 + ["50k"] * 10 + ["1.250,50"] * 20 + ["abc"] * 5
             + [str(1800 + 10 * i) for i in range(142)] + ["$250,000"] * 3)
    owns = ["Y"] * 60 + ["yes"] * 60 + ["Yes"] * 40 + ["No"] * 50 + ["n"] * 40 + ["NO"] * 30 + ["Maybe"] * 20
    gender = ["Male"] * 150 + ["Female"] * 130 + ["Non-binary"] * 12 + ["Prefer to self-describe"] * 8
    age = [25 + (i % 40) for i in range(299)] + [91357]
    cols = {
        "Respondent ID": list(range(1, 301)), Q: _shuffled(text, 1), "Brand": _shuffled(brand, 2),
        "Likelihood to buy": _shuffled(score, 3), "Survey date": _shuffled(date, 4), "Spend": _shuffled(spend, 5),
        "Owns an EV": _shuffled(owns, 6), "Gender": _shuffled(gender, 7), "Age": _shuffled(age, 8),
    }
    for k, v in cols.items():
        assert len(v) == 300, k
    kinds = {"Respondent ID": "id_or_junk", Q: "open_text", "Brand": "short_text", "Likelihood to buy": "score",
             "Survey date": "date", "Spend": "numeric", "Owns an EV": "yes_no", "Gender": "segment", "Age": "numeric"}
    df = pd.DataFrame(cols).astype(object)
    return df, profile_for(df, kinds, sensitive={"Gender", "Age"})


def store_survey():
    """No text column at all: scores, a segment, dates, a number and a yes/no."""
    n = 120
    df = pd.DataFrame({
        "Store": ["North", "south", "South", "East", "West", "North"] * 20,
        "NPS": [i % 11 for i in range(n)],
        "Visit date": ["2025-01-%02d" % (1 + i % 28) for i in range(n)],
        "Basket": [f"${20 + i}.50" for i in range(n)],
        "Member": ["Yes", "No", "Y", "N"] * 30,
    }).astype(object)
    kinds = {"Store": "segment", "NPS": "score", "Visit date": "date", "Basket": "numeric", "Member": "yes_no"}
    return df, profile_for(df, kinds)


def short_comments():
    """Short comments only (typically 4 to 6 words), with one comment repeated."""
    subj = ["Staff", "Queues", "Parking", "Prices", "Cleanliness", "Music", "Lighting", "Signage"]
    verb = ["were great", "took ages", "felt tight", "seemed high", "was fine", "was loud"]
    comments = [f"{subj[i % 8]} {verb[i % 6]} today {i}" for i in range(80)]
    comments += ["Would come back again next month"] * 4  # 6 words, repeated
    df = pd.DataFrame({"Comment": comments, "Region": ["A", "B"] * 42}).astype(object)
    return df, profile_for(df, {"Comment": "open_text", "Region": "segment"})


def step(report, key, col=None):
    for s in report.steps:
        if s.key == key and (col is None or s.column == col):
            return s
    raise AssertionError(f"no step {key} {col}")


NO_DEDUPE = {"collapse_duplicate_answers": {"enabled": False}}  # keeps all 300 rows so per-column counts are exact


def keys(plan):
    return {s.key for s in plan.steps}


# ---------------------------------------------------------------- redaction
def test_redaction_masks_and_counts():
    text = ("Mail jane.doe@example.co.uk or call +61 412 345 678, also (02) 9876 5432. See https://foo.com/x?y=1 "
            "and www.bar.org. Card 4111 1111 1111 1111, SSN 123-45-6789, passport 123456789.")
    out, c = redact_text(text)
    # the bare 9-digit "passport" run is a phone number in a text column (see test_cleaning_hardening.py)
    assert c == {"email": 1, "phone": 3, "url": 2, "id": 2, "name": 0, "address": 0}
    for leak in ("jane", "412 345", "9876", "foo.com", "bar.org", "4111", "123-45", "123456789"):
        assert leak not in out
    assert "[email]" in out and "[phone]" in out and "[link]" in out and "[id]" in out


def test_redaction_leaves_dates_prices_and_ordinary_numbers_alone():
    text = "Bought on 2025-03-14 or 14/03/2025 for $1,250.50, rated 4.5 out of 5, about 12345 km."
    out, c = redact_text(text)
    assert out == text and sum(c.values()) == 0


def test_redaction_is_linear_on_hostile_input():
    t0 = time.time()
    redact_text("a" * 50_000 + "@" + "1 " * 20_000 + "-" * 30_000)
    assert time.time() - t0 < 2


def test_partial_redaction_only_for_review():
    out, _ = redact_text("write to bob@example.com", partial=True)
    assert out == "write to bo…[email]"


# ---------------------------------------------------------------- open text
def test_open_text_steps_and_counts():
    df, prof = car_survey()
    plan, rep = plan_with_preview(df, prof)
    assert step(rep, "blank_non_answers", Q).cells_affected == 15
    assert step(rep, "blank_keyboard_mash", Q).cells_affected == 8
    pii = step(rep, "mask_pii", Q)
    assert pii.details["counts"]["email"] == 12 and pii.details["counts"]["phone"] == 6
    assert "12 emails" in pii.details["summary"] and rep.pii["email"] == 12
    assert step(rep, "collapse_duplicate_answers").rows_affected == 13  # 8 + 5 repeats of the two long answers
    ex = step(rep, "blank_non_answers", Q).examples
    assert 1 <= len(ex) <= 3 and all(set(e) == {"before", "after"} for e in ex)
    # PII example shows a partial mask, never the full address
    assert all("@example.com" not in e["before"] for e in pii.examples)


def test_clean_text_has_no_pii_and_non_answers_are_blank():
    df, prof = car_survey()
    plan = plan_cleaning(df, prof)
    clean, rep = apply_plan(df, plan)
    txt = clean[Q].dropna().astype(str)
    assert not txt.str.contains("@example.com").any() and not txt.str.contains("345 67").any()
    assert not txt.isin(["n/a", "N/A", "None", "idk", "....", "asdf", "qwerty", "aaaaa", "hjkl"]).any()
    assert clean[Q].isna().sum() >= 23  # blanked cells stay as rows, they are not silently dropped


def test_repeated_long_answers_are_flagged_not_removed():
    df, prof = car_survey()
    plan, rep0 = plan_with_preview(df, prof)
    clean, rep = apply_plan(df, plan)
    assert rep.rows_in == 300 and rep.rows_out == 300 and rep.removed_rows_total == 0  # different people, same sentence
    st = step(rep, "collapse_duplicate_answers")
    assert st.details["repeats_flagged"] == 13 and st.details["identical_rows_removed"] == 0
    a = clean[clean[Q].astype(str).str.startswith("The public charging")]
    assert len(a) == 9 and int(a["_verbatim_dup_count"].max()) == 9
    assert a["_verbatim_flags"].astype(str).str.contains("same answer as row").sum() == 8


def test_fully_identical_rows_with_a_repeated_answer_are_removed_and_reported():
    df, prof = car_survey()
    i = int(df.index[df[Q].astype(str).str.startswith("The public charging")][0])
    df.loc[len(df)] = df.loc[i].tolist()
    df.loc[len(df)] = df.loc[i].tolist()
    plan, _ = plan_with_preview(df, prof)
    clean, rep = apply_plan(df, plan)
    st = step(rep, "collapse_duplicate_answers")
    assert st.details["identical_rows_removed"] == 2 and st.details["repeats_flagged"] == 13
    assert rep.rows_in == 302 and rep.rows_out == 300 and rep.removed_rows_total == 2 and rep.accounted_for
    assert all("identical to an earlier row in every column" in r["reason"] for r in rep.removed_rows)
    assert {r["row"] for r in rep.removed_rows} == {301, 302}


def test_nothing_dropped_silently():
    df, prof = car_survey()
    df.loc[len(df)] = [None] * df.shape[1]  # a blank row on top of the repeats
    df.loc[len(df)] = [None] * df.shape[1]
    j = int(df.index[df[Q].astype(str).str.startswith("The public charging")][0])
    df.loc[len(df)] = df.loc[j].tolist()  # a whole-row copy: the only kind of repeat that is removed
    clean, rep = apply_plan(df, plan_cleaning(df, prof))
    assert rep.rows_in - rep.rows_out == rep.removed_rows_total == len(rep.removed_rows) == sum(rep.removed_by_step.values())
    assert rep.accounted_for and not rep.removed_rows_truncated
    removed_numbers = {r["row"] for r in rep.removed_rows}
    kept_numbers = set(clean["_verbatim_row"])
    assert removed_numbers.isdisjoint(kept_numbers)
    assert removed_numbers | kept_numbers == set(range(1, len(df) + 1))  # every source row is kept or listed
    assert {"drop_empty_rows", "collapse_duplicate_answers"} == set(rep.removed_by_step)


# ---------------------------------------------------------------- short text
def test_short_text_merge_table_and_review_edit():
    df, prof = car_survey()
    plan, rep = plan_with_preview(df, prof)
    st = next(s for s in plan.steps if s.key == "merge_variants")
    table = {e["from"]: e["to"] for e in st.params["merges"]}
    assert table["tesla"] == "Tesla" and table["Telsa"] == "Tesla" and table["toyota"] == "Toyota"
    assert table["Toyotta"] == "Toyota" and table["Rivan"] == "Rivian"
    assert "Lucid" not in table and "Ford" not in table and "Tesla" not in table
    assert step(rep, "merge_variants").cells_affected == 20 + 10 + 5 + 15 + 4 + 3  # "TESLA " is trimmed by the tidy step, then merged
    # the user unticks one merge and renames another
    ov = {"merge_variants:Brand": {"merges": {"Telsa": {"enabled": False}, "Toyotta": {"to": "Toyota Motor"}}}}
    plan2, rep2 = plan_with_preview(df, prof, {**ov, **NO_DEDUPE})
    clean, _ = apply_plan(df, plan2)
    assert (clean["Brand"] == "Telsa").sum() == 5 and (clean["Brand"] == "Toyota Motor").sum() == 4
    assert (clean["Brand"] == "Tesla").sum() == 80 + 20 + 10


def test_model_x_and_model_y_are_not_merged():
    names = ["Model X"] * 40 + ["Model Y"] * 30 + ["Model 3"] * 30 + ["model x"] * 5
    df = pd.DataFrame({"Model": names}).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Model": "short_text"}))
    table = {e["from"]: e["to"] for e in next(s for s in plan.steps if s.key == "merge_variants").params["merges"]}
    assert table == {"model x": "Model X"}


# ---------------------------------------------------------------- scores, dates, numbers
def test_score_scale_guessed_keeps_values_until_confirmed_then_blanks():
    df, prof = car_survey()
    plan, rep = plan_with_preview(df, prof, NO_DEDUPE)
    rng = step(rep, "check_score_range")
    assert rng.details["scale"] == [1, 5] and rng.details["scale_source"] == "observed"
    assert rng.details["invalid"] == 0 and rng.details["outside_guessed_scale"] == 5 and rng.details["needs_confirmation"]
    assert any("confirm the scale" in w.lower() for w in rep.warnings)
    coerce = step(rep, "coerce_numbers", "Likelihood to buy")
    assert coerce.details["unreadable"] == 2
    clean, _ = apply_plan(df, plan)
    assert clean["Likelihood to buy"].isna().sum() == 2  # only the 2 unreadable "x"; the 9s and 10s are still there
    assert (clean["Likelihood to buy"] == 9).sum() == 3 and (clean["Likelihood to buy"] == 10).sum() == 2
    flags = clean["_verbatim_flags"].dropna().astype(str)
    assert flags.str.contains("outside the guessed 1 to 5 scale (was 9)", regex=False).sum() == 3
    # the user confirms the scale: now, and only now, out-of-range answers are blanked (original value kept in the flag)
    ov = {**NO_DEDUPE, "check_score_range:Likelihood to buy": {"params": {"scale": [1, 5]}}}
    plan2, rep2 = plan_with_preview(df, prof, ov)
    rng2 = step(rep2, "check_score_range")
    assert rng2.details["scale_source"] == "user" and rng2.details["invalid"] == 5
    clean2, _ = apply_plan(df, plan2)
    col = clean2["Likelihood to buy"]
    assert col.dropna().between(1, 5).all() and col.isna().sum() == 7  # 5 invalid + 2 unreadable, none "fixed"
    flags2 = clean2["_verbatim_flags"].dropna().astype(str)
    assert flags2.str.contains("invalid, outside 1 to 5 (was 9)", regex=False).sum() == 3
    assert (col == 4).sum() >= 48 + 5  # "4/5" read as 4


def test_scale_zero_to_ten_detected_on_other_data():
    df, prof = store_survey()
    plan = plan_cleaning(df, prof)
    assert next(s for s in plan.steps if s.key == "check_score_range").params["scale"] == [0, 10]


def test_dates_mixed_formats_ambiguity_and_impossible():
    df, prof = car_survey()
    plan, rep = plan_with_preview(df, prof, NO_DEDUPE)
    d = step(rep, "parse_dates")
    assert d.details["day_first"] is True  # 14/03 and 31/02 can only be day first
    assert d.details["ambiguous"] == 40 and d.details["impossible"] == 5 and d.details["unreadable"] == 3
    assert any("could be day first or month first" in w for w in rep.warnings)
    clean, _ = apply_plan(df, plan)
    vals = set(clean["Survey date"].dropna())
    assert {"2025-03-14", "2025-04-03", "2025-03-05", "2025-06-01"} <= vals
    assert clean["Survey date"].isna().sum() == 8
    assert clean["_verbatim_flags"].astype(str).str.contains("impossible date").sum() == 5


def test_dates_with_no_evidence_say_so_honestly():
    df = pd.DataFrame({"When": ["03/04/2025", "05/06/2025", "07/08/2025", "2025-01-02"] * 10}).astype(object)
    plan, rep = plan_with_preview(df, profile_for(df, {"When": "date"}))
    s = next(s for s in plan.steps if s.key == "parse_dates")
    assert s.params["day_first"] is None and "Nothing in the file shows which order" in s.params["basis"]
    assert step(rep, "parse_dates").details["ambiguous"] == 30 and rep.warnings


def test_numbers_currency_percent_separators_and_outliers_flagged_not_removed():
    df, prof = car_survey()
    plan, rep = plan_with_preview(df, prof, NO_DEDUPE)
    clean, rep = apply_plan(df, plan)
    spend = clean["Spend"]
    assert {1250, 2500, -300, 50000, 1250.5, 250000} <= set(spend.dropna())
    assert spend.isna().sum() == 5  # "abc"
    out = step(rep, "flag_numeric_outliers", "Spend")
    high = next(s for s in plan.steps if s.key == "flag_numeric_outliers" and s.column == "Spend").params["high"]
    assert out.details["unusually_high"] == int((spend > high).sum()) >= 13
    assert (spend == 250000).sum() == 3  # still there
    assert rep.rows_out == 300  # the numeric step removed nothing


# ---------------------------------------------------------------- labels and groups
def test_yes_no_standardised():
    df, prof = car_survey()
    clean, rep = apply_plan(df, plan_cleaning(df, prof))
    vc = clean["Owns an EV"].value_counts()
    assert set(clean["Owns an EV"].dropna()) == {"Yes", "No", "Maybe"}
    assert step(rep, "standardise_yes_no").details["other_answers_left"] > 0


def test_segment_labels_and_tiny_groups_merge_only_above_threshold():
    labels = ["Sydney"] * 100 + ["sydney"] * 20 + ["Perth"] * 60 + ["Hobart"] * 40 + ["Darwin"] * 1 + ["Alice"] * 1 + ["Cairns"] * 2
    df = pd.DataFrame({"City": labels}).astype(object)
    prof = profile_for(df, {"City": "segment"})
    plan, rep = plan_with_preview(df, prof)
    assert step(rep, "standardise_labels").cells_affected == 20
    sm = next(s for s in plan.steps if s.key == "merge_small_groups")
    assert sm.params["min_count"] == 3 and {e["from"] for e in sm.params["merges"]} == {"Darwin", "Alice", "Cairns"}
    clean, _ = apply_plan(df, plan)
    assert (clean["City"] == "Other").sum() == 4 and (clean["City"] == "Sydney").sum() == 120
    # a higher threshold is a user setting and rebuilds the table
    plan2 = plan_cleaning(df, prof, {"merge_small_groups:City": {"params": {"min_count": 50}}})
    sm2 = next(s for s in plan2.steps if s.key == "merge_small_groups")
    assert {e["from"] for e in sm2.params["merges"]} == {"Darwin", "Alice", "Cairns", "Hobart"}
    # one tiny group alone is not merged
    df1 = pd.DataFrame({"City": ["Sydney"] * 100 + ["Perth"] * 60 + ["Darwin"]}).astype(object)
    assert "merge_small_groups" not in keys(plan_cleaning(df1, profile_for(df1, {"City": "segment"})))


def test_id_or_junk_excluded_never_deleted():
    df, prof = car_survey()
    clean, rep = apply_plan(df, plan_cleaning(df, prof))
    assert "Respondent ID" in rep.excluded_columns and "Respondent ID" in clean.columns
    assert list(clean["Respondent ID"]) == [df["Respondent ID"][r - 1] for r in clean["_verbatim_row"]]
    # switching the step off means the column is analysed after all
    plan = plan_cleaning(df, prof, {"exclude_columns": {"enabled": False}})
    _, rep2 = apply_plan(df, plan)
    assert rep2.excluded_columns == []


def test_dataset_level_empty_columns_and_duplicate_rows_reported():
    df = pd.DataFrame({"a": ["x", "y", "x", None, "z"], "b": [1, 2, 1, None, 3], "empty": [None] * 5,
                       "blank": ["  ", "", None, None, " "]}).astype(object)
    prof = profile_for(df, {"a": "segment", "b": "numeric"})
    clean, rep = apply_plan(df, plan_cleaning(df, prof))
    assert [c["name"] for c in rep.removed_columns] == ["empty", "blank"]
    assert "empty" not in clean.columns and rep.rows_out == 4 and rep.removed_by_step == {"drop_empty_rows": 1}
    dup = step(rep, "report_duplicate_rows")
    assert dup.rows_affected == 1 and rep.rows_out == 4  # reported and flagged, not dropped


# ---------------------------------------------------------------- adaptive
def test_plan_differs_by_dataset():
    a, pa = car_survey()
    b, pb = store_survey()
    c, pc = short_comments()
    ka, kb, kc = keys(plan_cleaning(a, pa)), keys(plan_cleaning(b, pb)), keys(plan_cleaning(c, pc))
    text_keys = {"normalise_text", "mask_pii", "blank_non_answers", "blank_keyboard_mash", "collapse_duplicate_answers",
                 "merge_variants", "flag_length_outliers"}
    assert not (kb & text_keys)  # no text column, no text steps
    assert {"mask_pii", "merge_variants", "check_score_range", "parse_dates"} <= ka
    assert "mask_pii" in kc and "check_score_range" not in kc and "parse_dates" not in kc
    assert ka != kb != kc and ka != kc
    # thresholds come from the data: the repeat limit follows how long answers are
    pa_min = next(s for s in plan_cleaning(a, pa).steps if s.key == "collapse_duplicate_answers").params["min_words"]
    pc_min = next(s for s in plan_cleaning(c, pc).steps if s.key == "collapse_duplicate_answers").params["min_words"]
    assert pa_min > pc_min
    # the same column kind gets different numbers in different files
    assert next(s for s in plan_cleaning(a, pa).steps if s.key == "check_score_range").params["scale"] != \
        next(s for s in plan_cleaning(b, pb).steps if s.key == "check_score_range").params["scale"]
    # the store survey has no repeats to collapse, and short comments repeat once
    assert step(plan_with_preview(c, pc)[1], "collapse_duplicate_answers").rows_affected == 3


def test_steps_carry_plain_description_counts_and_examples():
    df, prof = car_survey()
    plan, rep = plan_with_preview(df, prof)
    assert all(len(s.description) > 20 and s.title for s in plan.steps)
    assert {s.id for s in plan.steps} == {s.id for s in rep.steps}
    for s in rep.steps:
        assert s.rows_affected >= 0 and s.cells_affected >= 0 and len(s.examples) <= 3
    json.dumps(plan.to_dict())
    json.dumps(rep.to_dict())


def test_disabled_step_is_skipped_and_reported():
    df, prof = car_survey()
    plan = plan_cleaning(df, prof, {f"blank_non_answers:{Q}": {"enabled": False}})
    clean, rep = apply_plan(df, plan)
    s = step(rep, "blank_non_answers")
    assert s.status == "skipped" and s.cells_affected == 0
    assert clean[Q].astype(str).str.lower().isin(["n/a", "idk", "none"]).any()


# ---------------------------------------------------------------- sensitive columns
def test_small_group_suppression_metadata():
    df, prof = car_survey()
    _, rep = apply_plan(df, plan_cleaning(df, prof))
    g = rep.suppression["Gender"]
    assert g["min_group_size"] == 30 and g["hidden_groups"] == 2 and g["raw_rows_in_report"] is False
    by = {x["label"]: x for x in g["groups"]}
    assert by["Non-binary"]["hidden"] and by["Non-binary"]["count"] is None
    assert by["Prefer to self-describe"]["hidden"] and not by["Male"]["hidden"] and by["Male"]["count"] >= 30
    assert rep.suppression["Age"]["groups"] is None and "Age" in rep.suppression


def test_min_group_size_is_configurable(monkeypatch):
    monkeypatch.setenv("MIN_GROUP_SIZE", "10")
    df, prof = car_survey()
    _, rep = apply_plan(df, plan_cleaning(df, prof))
    by = {x["label"]: x for x in rep.suppression["Gender"]["groups"]}
    assert not by["Non-binary"]["hidden"] and by["Prefer to self-describe"]["hidden"]


def test_sensitive_values_never_in_report_payload():
    df, prof = car_survey()
    plan, preview = plan_with_preview(df, prof)
    _, rep = apply_plan(df, plan)
    for blob in (json.dumps(rep.to_dict()), json.dumps(preview.to_dict()), json.dumps(plan.to_dict())):
        assert "91357" not in blob  # the one unusual age
    sens_steps = [s for s in rep.steps if s.column in ("Age", "Gender")]
    assert sens_steps and all(s.examples == [] for s in sens_steps)
    flagged = step(rep, "flag_numeric_outliers", "Age")
    assert flagged.cells_affected >= 1 and flagged.examples == []
    # the tiny sensitive groups are offered for merging but left off, with counts hidden
    sm = next(s for s in plan.steps if s.key == "merge_small_groups" and s.column == "Gender")
    assert sm.enabled is False and all(e["count"] is None for e in sm.params["merges"])


def test_model_payload_refuses_sensitive_and_masks_again():
    df, prof = car_survey()
    plan = plan_cleaning(df, prof, {f"mask_pii:{Q}": {"enabled": False}})
    clean, _ = apply_plan(df, plan)
    assert clean[Q].astype(str).str.contains("@example.com").any()  # user switched masking off
    samples = model_safe_samples(clean, plan, Q, limit=200)
    assert samples and not any("@example.com" in s for s in samples)
    with pytest.raises(CleaningError):
        model_safe_samples(clean, plan, "Gender")
    with pytest.raises(CleaningError):
        model_safe_samples(clean, plan, "Spend")


# ---------------------------------------------------------------- safety
def test_hostile_cells_stay_text_and_examples_are_strings():
    evil = ["<script>alert(1)</script>", "=cmd|' /C calc'!A0", "‮gnp.exe", "a\x00b\x07c", "{{7*7}}", "${jndi:ldap://x}"]
    df = pd.DataFrame({"Answer": [f"{e}  with extra   words about the thing {i}" for i, e in enumerate(evil * 10)]}).astype(object)
    plan, rep = plan_with_preview(df, profile_for(df, {"Answer": "open_text"}))
    clean, _ = apply_plan(df, plan)
    txt = " ".join(clean["Answer"].astype(str))
    assert "‮" not in txt and "\x00" not in txt and "\x07" not in txt
    assert "<script>" in txt  # kept as text: escaping is the renderer's job, nothing is evaluated
    for s in rep.steps:
        for e in s.examples:
            assert isinstance(e["before"], str) and isinstance(e["after"], str) and "\x00" not in e["before"]


def test_caps_and_column_name_clash():
    df = pd.DataFrame({"a": range(5)})
    with pytest.raises(CleaningError):
        plan_cleaning(df, None, settings={"max_rows": 3})
    with pytest.raises(CleaningError):
        plan_cleaning(df, None, settings={"max_columns": 0})
    with pytest.raises(CleaningError):
        plan_cleaning(pd.DataFrame([[1, 2]], columns=["a", "a"]), None)


def test_timeout_stops_cleaning():
    df, prof = car_survey()
    with pytest.raises(CleaningError):
        plan_cleaning(df, prof, settings={"timeout_seconds": -1})


# ---------------------------------------------------------------- performance
def test_fifty_thousand_rows_under_ten_seconds():
    rng = random.Random(7)
    words = ["battery", "price", "range", "charging", "home", "service", "cost", "quality", "design", "reliable",
             "slow", "great", "poor", "support", "delivery", "app", "software", "seats", "noise", "warranty"]
    n = 50_000
    brands = ["Tesla", "tesla", "Toyota", "Ford", "Rivian", "BYD", "Kia", "Hyundai"] * 5
    df = pd.DataFrame({
        "ID": range(n),
        "Comment": [" ".join(rng.choices(words, k=rng.randint(4, 14))) + (f" mail a{i}@x.com" if i % 50 == 0 else "")
                    for i in range(n)],
        "Brand": [rng.choice(brands) for _ in range(n)],
        "Score": [str(rng.randint(1, 5)) for _ in range(n)],
        "Date": [f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/2025" for _ in range(n)],
        "Spend": [f"${rng.randint(500, 9000):,}" for _ in range(n)],
    }).astype(object)
    prof = profile_for(df, {"Comment": "open_text", "Brand": "short_text", "Score": "score", "Date": "date", "Spend": "numeric"})
    t0 = time.time()
    plan, preview = plan_with_preview(df, prof)
    clean, rep = apply_plan(df, plan)
    elapsed = time.time() - t0
    assert elapsed < 10, f"took {elapsed:.1f}s"
    assert rep.accounted_for and rep.rows_in == n and rep.pii["email"] == 1000


# ---------------------------------------------------------------- API
@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield SimpleNamespace(client=TestClient(app), Session=Session, uploads=tmp_path / "uploads")
    app.dependency_overrides.clear()


def as_user(uid):
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uid)


def make_users(env, *clerk_ids):
    from app.models import User
    ids = []
    with env.Session() as s:
        for c in clerk_ids:
            u = User(clerk_id=c)
            s.add(u)
            s.commit()
            ids.append(u.id)
    return ids


def survey_csv() -> bytes:
    df, _ = car_survey()
    return df.drop(columns=[]).to_csv(index=False).encode("utf-8")


def upload(env, data=None, name="survey.csv"):
    r = env.client.post("/api/upload", files={"file": (name, data or survey_csv(), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_api_requires_sign_in(env, monkeypatch):
    monkeypatch.delenv("ALLOW_DEV_USER", raising=False)
    c = env.client
    assert c.post("/api/datasets/1/clean/plan").status_code == 401
    assert c.patch("/api/datasets/1/clean/plan", json={"steps": []}).status_code == 401
    assert c.post("/api/datasets/1/clean/apply").status_code == 401
    assert c.get("/api/datasets/1/clean/report").status_code == 401


def test_api_full_flow(env):
    did = upload(env)
    original = next(env.uploads.iterdir()).read_bytes()
    r = env.client.post(f"/api/datasets/{did}/clean/plan")
    assert r.status_code == 200, r.text
    body = r.json()
    plan_steps = {s["id"]: s for s in body["plan"]["steps"]}
    assert body["preview"]["rows_in"] == 300 and plan_steps and "mask_pii:" + Q in plan_steps
    assert env.client.get(f"/api/datasets/{did}/clean/report").status_code == 404  # nothing applied yet

    off = "mask_pii:" + Q
    r = env.client.patch(f"/api/datasets/{did}/clean/plan", json={"steps": [{"id": off, "enabled": False}]})
    assert r.status_code == 200, r.text
    assert next(s for s in r.json()["preview"]["steps"] if s["id"] == off)["status"] == "skipped"
    r = env.client.patch(f"/api/datasets/{did}/clean/plan", json={"steps": [{"id": off, "enabled": True}]})
    assert next(s for s in r.json()["preview"]["steps"] if s["id"] == off)["status"] == "applied"

    r = env.client.post(f"/api/datasets/{did}/clean/apply")
    assert r.status_code == 200, r.text
    out = r.json()
    rep = out["report"]
    assert rep["accounted_for"] and rep["rows_in"] - rep["rows_out"] == rep["removed_rows_total"]
    files = sorted(p.name for p in env.uploads.iterdir())
    assert len(files) == 2 and any(f.endswith(".clean.csv") for f in files)
    cleaned = env.uploads / f"{out['clean_hash']}.clean.csv"
    assert hashlib.sha256(cleaned.read_bytes()).hexdigest() == out["clean_hash"]  # named by its hash
    assert not any(p.name.startswith(".tmp") for p in env.uploads.iterdir())
    df = pd.read_csv(cleaned)
    assert len(df) == rep["rows_out"] and "_verbatim_row" in df.columns
    assert "@example.com" not in cleaned.read_text()
    assert next(p for p in env.uploads.iterdir() if not p.name.endswith(".clean.csv")).read_bytes() == original

    got = env.client.get(f"/api/datasets/{did}/clean/report")
    assert got.status_code == 200 and got.json()["report"] == rep and got.json()["clean_hash"] == out["clean_hash"]
    # the report also shows on the profile record
    assert env.client.get(f"/api/datasets/{did}/profile").json()["profile"]["cleaning"]["clean_hash"] == out["clean_hash"]


def test_api_merge_table_edit_and_threshold(env):
    did = upload(env)
    plan = env.client.post(f"/api/datasets/{did}/clean/plan").json()["plan"]
    mv = next((s for s in plan["steps"] if s["column"] == "Brand" and "merges" in s["params"]), None)
    assert mv is not None  # the real profiler calls Brand a segment, so this is the label-standardising table
    target = mv["params"]["merges"][0]
    r = env.client.patch(f"/api/datasets/{did}/clean/plan", json={"steps": [
        {"id": mv["id"], "merges": [{"from": target["from"], "to": "  Renamed\x00 ", "enabled": True}]}]})
    assert r.status_code == 200, r.text
    new = next(s for s in r.json()["plan"]["steps"] if s["id"] == mv["id"])
    assert any(e["from"] == target["from"] and e["to"] == "Renamed" for e in new["params"]["merges"])
    bad = env.client.patch(f"/api/datasets/{did}/clean/plan", json={"steps": [
        {"id": mv["id"], "merges": [{"from": "not in the table", "to": "x"}]}]})
    assert bad.status_code == 422


def test_api_rejects_bad_edits(env):
    did = upload(env)
    assert env.client.patch(f"/api/datasets/{did}/clean/plan", json={"steps": []}).status_code == 409
    env.client.post(f"/api/datasets/{did}/clean/plan")
    p = lambda body: env.client.patch(f"/api/datasets/{did}/clean/plan", json=body).status_code
    assert p({"steps": [{"id": "nope", "enabled": False}]}) == 422
    assert p({"steps": [{"id": "mask_pii:" + Q, "params": {"anything": 1}}]}) == 422
    assert p({"steps": [{"id": "mask_pii:" + Q, "enabled": "maybe"}]}) == 422
    assert p({"steps": [{"id": "mask_pii:" + Q, "surprise": True}]}) == 422
    assert p({"steps": [{"id": f"check_score_range:Likelihood to buy", "params": {"scale": [5, 1]}}]}) == 422
    assert p({"steps": [{"id": f"check_score_range:Likelihood to buy", "params": {"scale": [0, 10]}}]}) == 200
    assert p({"steps": [{"id": "x"}] * 501}) == 422
    assert env.client.post(f"/api/datasets/{did}/clean/plan", json={"min_group_size": 1}).status_code == 422


def test_api_ownership(env):
    u1, u2 = make_users(env, "clerk_alice", "clerk_bob")
    as_user(u1)
    did = upload(env)
    assert env.client.post(f"/api/datasets/{did}/clean/plan").status_code == 200
    assert env.client.post(f"/api/datasets/{did}/clean/apply").status_code == 200
    as_user(u2)
    c = env.client
    assert c.post(f"/api/datasets/{did}/clean/plan").status_code == 404
    assert c.patch(f"/api/datasets/{did}/clean/plan", json={"steps": []}).status_code == 404
    assert c.post(f"/api/datasets/{did}/clean/apply").status_code == 404
    assert c.get(f"/api/datasets/{did}/clean/report").status_code == 404
    assert c.get(f"/api/datasets/{did}/profile").status_code == 404
    as_user(u1)
    assert c.get(f"/api/datasets/{did}/clean/report").status_code == 200


def test_api_missing_original_and_unknown_dataset(env):
    assert env.client.post("/api/datasets/999/clean/plan").status_code == 404
    did = upload(env)
    for p in env.uploads.iterdir():
        p.unlink()
    assert env.client.post(f"/api/datasets/{did}/clean/plan").status_code == 404


def test_api_row_cap_returns_422(env, monkeypatch):
    monkeypatch.setenv("CLEAN_MAX_ROWS", "50")
    did = upload(env)
    r = env.client.post(f"/api/datasets/{did}/clean/plan")
    assert r.status_code == 422 and "limited to 50 rows" in r.json()["detail"]


def test_api_no_text_dataset_has_no_text_steps(env):
    b, _ = store_survey()
    did = upload(env, b.to_csv(index=False).encode(), "stores.csv")
    steps = env.client.post(f"/api/datasets/{did}/clean/plan").json()["plan"]["steps"]
    assert not {s["key"] for s in steps} & {"mask_pii", "blank_non_answers", "merge_variants", "flag_length_outliers"}
