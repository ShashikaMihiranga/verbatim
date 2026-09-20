"""Hardening of adaptive cleaning: name/address masks, bare phones, scale guessing, dedupe, unicode, CSV guard."""
import pandas as pd
import pytest

from app.cleaning import CleaningError, apply_plan, model_safe_samples, plan_cleaning, plan_with_preview, redact_text
from app.cleaning.redact import bare_digits_for_kind


def profile_for(df, kinds, sensitive=()):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": c in sensitive}
                        for c in df.columns]}


def step(report, key, col=None):
    for s in report.steps:
        if s.key == key and (col is None or s.column == col):
            return s
    raise AssertionError(f"no step {key} {col}")


# ---------------------------------------------------------------- 1. names and addresses
@pytest.mark.parametrize("text,gone", [
    ("Hi, my name is Sarah Jones and I like it", "Sarah"),
    ("I'm Priya, and the chargers are far", "Priya"),
    ("I am Michael O'Brien from work", "Brien"),
    ("This is Wei Chen writing", "Wei"),
    ("Call me Bob", "Bob"),
    ("Dr Patel said no", "Patel"),
    ("Mrs. Alvarez-Smith asked", "Alvarez"),
    ("i'm Élodie Martin", "Élodie"),
])
def test_names_after_cues_are_masked(text, gone):
    out, c = redact_text(text)
    assert gone not in out and "[name]" in out and c["name"] == 1


@pytest.mark.parametrize("text", [
    "I am very happy with it", "I'm not sure", "I am Very happy", "This is Monday", "I'm Australian",
    "Tesla Model 3 is fine", "This is great", "my name is",
])
def test_names_are_not_masked_without_capitalised_words_or_for_common_words(text):
    out, c = redact_text(text)
    assert out == text and c["name"] == 0


@pytest.mark.parametrize("text,gone", [
    ("I live at 12 Smith Street near the shops", "Smith"),
    ("Send it to 5 High St", "High"),
    ("Unit 4/12 Oak Road, thanks", "Oak"),
    ("221B Baker Street", "Baker"),
    ("100 Ocean Blvd", "Ocean"),
    ("Bondi NSW 2026", "2026"),
    ("Portland OR 97201-1234", "97201"),
    ("London SW1A 1AA", "SW1A"),
    ("77 Green Valley Hwy", "Valley"),
])
def test_addresses_are_masked(text, gone):
    out, c = redact_text(text)
    assert gone not in out and c["address"] >= 1


@pytest.mark.parametrize("text", [
    "It is a 10 minutes drive", "about 5 min walk", "I paid 2000 dollars in 2024", "waited 3 Long Weeks in March",
])
def test_addresses_are_not_over_masked(text):
    out, c = redact_text(text)
    assert out == text and c["address"] == 0


def test_partial_mode_names_and_addresses_for_review_only():
    out, c = redact_text("my name is Sarah Jones at 12 Smith Street", partial=True)
    assert "Sa…[name]" in out and "12…[address]" in out and "Jones" not in out and "Smith" not in out


def test_name_masking_is_linear_on_hostile_input():
    import time
    t0 = time.time()
    redact_text("I am " + "Abcd " * 5000 + "12 " + "Abcd " * 5000 + "Street")
    redact_text("1 " + "Aa " * 9000)
    assert time.time() - t0 < 2


def _survey_with_names(n_names):
    text = [f"I'm Person{i} and I like the range" for i in range(0)]
    text += [f"The dealer said John Smith would call about it, case {i}" for i in range(n_names)]
    text += [f"The charging network needs more chargers near me, case {i}" for i in range(100 - n_names)]
    df = pd.DataFrame({"Why": text}).astype(object)
    return df, profile_for(df, {"Why": "open_text"})


def test_warning_when_capitalised_names_remain_in_text_column():
    df, prof = _survey_with_names(20)
    plan, rep = plan_with_preview(df, prof)
    assert any("may still contain names" in w and "Why" in w for w in rep.warnings)
    assert step(rep, "mask_pii", "Why").details["possible_names_left"] == 20


def test_no_warning_for_ordinary_text():
    df, prof = _survey_with_names(0)
    _, rep = plan_with_preview(df, prof)
    assert not [w for w in rep.warnings if "personal details" in w]


def test_cue_names_and_addresses_counted_in_report_with_examples():
    text = [f"My name is Anna Lee, I live at {i + 1} Park Road and I want a cheaper car" for i in range(6)]
    text += ["The battery worries me a lot and so does the price of it"] * 4
    df = pd.DataFrame({"Why": text}).astype(object)
    plan, rep = plan_with_preview(df, profile_for(df, {"Why": "open_text"}))
    st = step(rep, "mask_pii", "Why")
    assert st.details["counts"]["name"] == 6 and st.details["counts"]["address"] == 6
    assert rep.pii["name"] == 6 and rep.pii["address"] == 6
    assert st.examples and "Lee" not in st.examples[0]["before"] and "Park Road" not in st.examples[0]["before"]
    clean, _ = apply_plan(df, plan)
    assert not clean["Why"].str.contains("Anna|Park Road").any()


def test_model_safe_samples_masks_names_addresses_and_bare_phones():
    df = pd.DataFrame({"Why": ["my name is Sam Wu, 4 Elm Court, 0412345678 or 61412345678", "plain answer here"]})
    df = df.astype(object)
    prof = profile_for(df, {"Why": "open_text"})
    plan = plan_cleaning(df, prof)
    out = model_safe_samples(df, plan, "Why")  # raw df: payload masks again on its own
    assert "Sam" not in out[0] and "Elm" not in out[0] and "0412345678" not in out[0] and "61412345678" not in out[0]
    assert out[1] == "plain answer here"
    with pytest.raises(CleaningError):
        model_safe_samples(df, plan, "Nope")


# ---------------------------------------------------------------- 2. bare digit phone numbers
def test_bare_digits_are_phone_in_text_and_id_in_id_or_numeric_columns():
    t = "ring 61412345678 or 0412345678 or 123456789012"
    out, c = redact_text(t)
    assert c["phone"] == 3 and c["id"] == 0 and "[id]" not in out
    out, c = redact_text(t, bare_digits="id")
    assert c["id"] >= 2 and "61412345678" not in out
    assert bare_digits_for_kind("open_text") == bare_digits_for_kind("short_text") == "phone"
    assert bare_digits_for_kind("id_or_junk") == bare_digits_for_kind("numeric") == "id"
    with pytest.raises(ValueError):
        redact_text(t, bare_digits="nope")


def test_mask_pii_step_uses_phone_for_text_columns():
    df = pd.DataFrame({"Why": ["my number is 61412345678 thanks"] * 3 + ["nothing to say really here"] * 3}).astype(object)
    _, rep = plan_with_preview(df, profile_for(df, {"Why": "open_text"}))
    counts = step(rep, "mask_pii", "Why").details["counts"]
    assert counts["phone"] == 3 and counts["id"] == 0
