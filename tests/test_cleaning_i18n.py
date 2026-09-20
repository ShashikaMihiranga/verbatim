"""Non-English safety: multilingual non-answers, no keyboard-mash rules on non-Latin or accented text, user terms."""
import pandas as pd
import pytest

from app.cleaning import apply_plan, plan_cleaning, plan_with_preview
from app.cleaning.steps_text import clean_terms, is_mash, is_non_answer, mash_applicable


def profile_for(df, kinds):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": False} for c in df.columns]}


def step(report, key, col=None):
    return next(s for s in report.steps if s.key == key and (col is None or s.column == col))


@pytest.mark.parametrize("text", [
    "No sé", "no se", "Ninguno", "NADA", "Ni idea", "Sin comentarios", "Rien", "Aucun", "Je ne sais pas.", "Keine",
    "Keine Ahnung", "Weiß nicht", "Kein Kommentar", "Não sei", "nao sei", "Nenhum", "Sem comentários", "Nada.",
    "нет", "没有", "不知道", "なし", "모름",
])
def test_multilingual_non_answers_are_recognised(text):
    assert is_non_answer(text)


@pytest.mark.parametrize("text", [
    "no", "Nada me gusta del coche", "好", "Rien ne marche", "Keine Ladestationen in der Nähe", "Mein Auto", "sí",
    "Quiero más información",
])
def test_real_answers_are_not_non_answers(text):
    assert not is_non_answer(text)


def test_single_ascii_letter_is_non_answer_but_single_cjk_character_is_not():
    assert is_non_answer("x") and not is_non_answer("好")


@pytest.mark.parametrize("text", [
    "哈哈哈", "ああああ", "ффффф", "аааааа", "ааа ббб", "jajaja", "kkkkk", "haha", "Estoy muy contento con el coche",
    "ñññññ", "éééé", "Größe", "señor", "pfffff ñ", "ゔゔゔ",
])
def test_mash_rules_skip_non_latin_and_accented_text(text):
    assert not is_mash(text, 0.1)


@pytest.mark.parametrize("text", ["asdf", "qwerty", "aaaaa", "hjkl", "....", "0000", "xxxx", "sdfghjkl"])
def test_mash_rules_still_work_for_plain_ascii(text):
    assert is_mash(text, 0.1)


def test_mash_applicable_flags():
    assert mash_applicable("asdf") and mash_applicable("....") and mash_applicable("12345")
    assert not mash_applicable("aaaaé") and not mash_applicable("ああああ")


def test_safe_words_are_never_mash():
    assert is_mash("brrrrr", None)
    assert not is_mash("brrrrr", None, frozenset({"brrrrr"}))


def _spanish_survey():
    real = [f"Me preocupa la batería y el precio del coche número {i}, además de la carga en casa" for i in range(30)]
    text = real + ["No sé"] * 4 + ["Ninguno"] * 3 + ["Rien"] * 2 + ["Keine"] * 2 + ["Não sei"] * 2 + ["哈哈哈"] * 3
    text += ["ñññññ"] * 2 + ["asdf"] * 2 + ["n/a"] * 2 + ["kein Plan"] * 2
    df = pd.DataFrame({"Por qué": text}).astype(object)
    return df, profile_for(df, {"Por qué": "open_text"})


def test_multilingual_survey_blanks_non_answers_and_keeps_real_and_non_latin_text():
    df, prof = _spanish_survey()
    plan, rep = plan_with_preview(df, prof)
    clean, rep = apply_plan(df, plan)
    col = clean["Por qué"]
    assert step(rep, "blank_non_answers").cells_affected == 4 + 3 + 2 + 2 + 2 + 2  # incl. n/a
    assert step(rep, "blank_keyboard_mash").cells_affected == 2  # only "asdf"; the laugh and ñññññ are kept
    assert (col == "哈哈哈").sum() == 3 and (col == "ñññññ").sum() == 2 and (col == "kein Plan").sum() == 2
    assert step(rep, "blank_keyboard_mash").details["skipped_non_english"] > 0
    assert col.isna().sum() == 15 + 2


def test_user_extra_terms_are_added_via_the_plan_and_validated():
    df, prof = _spanish_survey()
    ov = {"blank_non_answers:Por qué": {"params": {"extra_terms": ["Kein Plan", "  Sin novedad "]}}}
    plan, rep = plan_with_preview(df, prof, ov)
    st = step(rep, "blank_non_answers")
    assert st.cells_affected == 4 + 3 + 2 + 2 + 2 + 2 + 2
    assert [s for s in plan.steps if s.key == "blank_non_answers"][0].params["extra_terms"] == ["kein plan", "sin novedad"]
    clean, _ = apply_plan(df, plan)
    assert (clean["Por qué"] == "kein Plan").sum() == 0
    assert clean_terms("nope") == [] and clean_terms([1, None, "x" * 500])[0].startswith("x") and len(clean_terms(["a"] * 500)) == 1


def test_non_answer_step_is_always_listed_so_terms_can_be_added():
    df = pd.DataFrame({"Why": ["Battery worries me a lot right now, honestly"] * 10}).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))
    assert any(s.key == "blank_non_answers" for s in plan.steps)


def test_safe_words_param_keeps_a_word_from_being_blanked():
    df = pd.DataFrame({"Why": ["brrrrr"] * 5 + ["Battery worries me a lot right now, honestly"] * 5}).astype(object)
    prof = profile_for(df, {"Why": "open_text"})
    clean, _ = apply_plan(df, plan_cleaning(df, prof))
    assert clean["Why"].isna().sum() == 5
    ov = {"blank_keyboard_mash:Why": {"params": {"safe_words": ["brrrrr"]}}}
    plan, rep = plan_with_preview(df, prof, ov)
    clean, _ = apply_plan(df, plan)
    assert clean["Why"].isna().sum() == 0
