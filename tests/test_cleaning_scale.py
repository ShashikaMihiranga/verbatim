"""Scale guessing: header hints first, observed values last, never blank on a guess."""
import pandas as pd
import pytest

from app.cleaning import apply_plan, plan_cleaning, plan_with_preview


def profile_for(df, kinds):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": False} for c in df.columns]}


def step(report, key):
    return next(s for s in report.steps if s.key == key)


def _score_df(col, values):
    df = pd.DataFrame({col: [str(v) for v in values]}).astype(object)
    return df, profile_for(df, {col: "score"})


def _one_to_ten_max_seven():
    # a real 1-10 question; 98 of 100 people chose 7 or below, 2 chose 9 or 10
    return [1 + i % 7 for i in range(98)] + [9, 10]


def test_scale_from_observed_values_never_blanks_out_of_range_values():
    col = "How likely are you to recommend us"
    df, prof = _score_df(col, _one_to_ten_max_seven())
    plan, rep = plan_with_preview(df, prof)
    st = step(rep, "check_score_range")
    assert st.details["scale"] == [1, 7] and st.details["scale_source"] == "observed"
    assert st.details["needs_confirmation"] and st.details["invalid"] == 0 and st.details["outside_guessed_scale"] == 2
    assert any("confirm the scale" in w.lower() for w in rep.warnings)
    clean, _ = apply_plan(df, plan)
    c = clean[col]
    assert c.isna().sum() == 0 and sorted(c[c > 7]) == [9, 10]
    assert clean["_verbatim_flags"].dropna().astype(str).str.contains("confirm the scale").sum() == 2


def test_nobody_above_seven_is_guessed_as_1_to_7_and_still_keeps_everything():
    df, prof = _score_df("Rating", [1 + i % 7 for i in range(70)])
    plan, rep = plan_with_preview(df, prof)
    st = step(rep, "check_score_range")
    assert st.details["scale"] == [1, 7] and st.details["scale_source"] == "observed"
    assert "nothing is blanked" in st.description
    clean, _ = apply_plan(df, plan)
    assert clean["Rating"].isna().sum() == 0


def test_user_confirming_a_scale_is_what_allows_blanking():
    col = "How likely are you to recommend us"
    df, prof = _score_df(col, _one_to_ten_max_seven() + [15])
    ov = {f"check_score_range:{col}": {"params": {"scale": [1, 10]}}}
    plan, rep = plan_with_preview(df, prof, ov)
    st = step(rep, "check_score_range")
    assert st.details["scale"] == [1, 10] and st.details["scale_source"] == "user" and st.details["invalid"] == 1
    clean, _ = apply_plan(df, plan)
    c = clean[col]
    assert c.isna().sum() == 1 and c.max() == 10  # the 15 is blanked, the 8-10 answers survive
    assert not any("confirm the scale" in w.lower() for w in rep.warnings)


@pytest.mark.parametrize("header,scale", [
    ("Likelihood to recommend (0-10)", [0, 10]), ("Rate us out of 10", [1, 10]), ("Satisfaction, 1 to 5", [1, 5]),
    ("Score /10", [1, 10]), ("NPS 0 to 10", [0, 10]),
])
def test_header_hint_sets_scale_first(header, scale):
    vals = (([0] if scale[0] == 0 else []) + _one_to_ten_max_seven()) if scale[1] == 10 else [1, 2, 3, 4, 5, 3, 4, 8] * 5
    df, prof = _score_df(header, vals)
    _, rep = plan_with_preview(df, prof)
    st = step(rep, "check_score_range")
    assert st.details["scale"] == scale and st.details["scale_source"] == "header" and not st.details["needs_confirmation"]


def test_header_hint_beats_observed_values():
    # values only reach 7 mostly, but the header says 1 to 10: the 8 to 10 answers must survive
    df, prof = _score_df("Rating (1-10)", _one_to_ten_max_seven())
    plan, rep = plan_with_preview(df, prof)
    assert step(rep, "check_score_range").details["scale"] == [1, 10]
    clean, _ = apply_plan(df, plan)
    assert clean["Rating (1-10)"].isna().sum() == 0


def test_header_out_of_n_uses_zero_only_if_someone_answered_zero():
    df, prof = _score_df("Rate us out of 10", [0, 3, 5, 7, 9, 10] * 4)
    assert step(plan_with_preview(df, prof)[1], "check_score_range").details["scale"] == [0, 10]


def test_old_stored_plan_without_scale_source_never_blanks():
    df, prof = _score_df("Rating", [1, 2, 3, 4, 5] * 10 + [9])
    plan = plan_cleaning(df, prof)
    for s in plan.steps:
        s.params.pop("scale_source", None)
    clean, _ = apply_plan(df, plan)
    assert clean["Rating"].isna().sum() == 0
