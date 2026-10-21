import json
import random
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.profiling import LoadError, profile_file
from app.profiling.claude_hook import collect_samples, refine_profile
from app.profiling.columns import _segment_max_distinct, profile_column, profile_dataframe

FIX = Path(__file__).parent / "fixtures"


def kinds(profile):
    return {c["name"]: c["kind"] for c in profile["columns"]}


def test_messy_csv():
    profile, loaded = profile_file(FIX / "messy_survey.csv")
    assert loaded.meta["encoding"] == "utf-8-sig" and loaded.meta["delimiter"] == ";"
    assert profile["row_count"] == 12  # blank rows and the title row are not data
    k = kinds(profile)
    assert k["Respondent ID"] == "id_or_junk"
    assert k["Survey date"] == "date"
    assert k["Likelihood to buy"] == "score"
    assert k["Age"] == "numeric"
    assert k["Region"] == "segment"
    assert k["Own a car"] == "yes_no"
    q = "Why haven't you bought an electric vehicle yet?"
    assert k[q] == "open_text"
    assert profile["question"]["text"] == q
    by = {c["name"]: c for c in profile["columns"]}
    assert by["Age"]["sensitive"] and by["Age"]["unit"] == "years"
    assert by["Likelihood to buy"]["missing"] == 1  # "n/a" counted as blank
    assert not by["Region"]["sensitive"]
    for c in profile["columns"]:
        assert 0 <= c["confidence"] <= 1 and c["reason"] and 1 <= len(c["samples"]) <= 5
    assert any("blank" in n for n in profile["notes"])  # cleaning is reported, not silent


def test_segment_max_distinct_scales_with_row_count():
    assert _segment_max_distinct(100) == 12  # floor, unchanged from before this fix
    assert _segment_max_distinct(1597) == 20  # round(1597/80)
    assert _segment_max_distinct(10_000) == 30  # ceiling


def test_profile_column_classifies_low_diversity_large_column_as_segment():
    """Pin for the real bug this fixes: a 1,597-row column with only 19 distinct, long, heavily-repeated
    category-breadcrumb strings (98.8% of rows are one of 19 exact values) used to fall through the old
    fixed 12-value segment cap straight to open_text, get run through embed+cluster theme discovery, and
    produce meaningless near-duplicate "themes" with nothing left to sub-split. Must classify segment."""
    breadcrumbs = [f"Amazon Devices,Home,Category {i},Sub Category {i},Electronics Features" for i in range(19)]
    values = [breadcrumbs[i % 19] for i in range(1597)]
    result = profile_column("categories", values, total_rows=1597)
    assert result["kind"] == "segment"


def test_profile_column_small_dataset_segment_ceiling_unchanged():
    """Regression pin: the floor stays exactly 12 for small datasets, same as before this fix - 15
    distinct values in a 100-row dataset must NOT become segment (falls through to open_text/short_text
    exactly as it always has)."""
    values = [f"answer number {i % 15} with some words in it" for i in range(100)]
    result = profile_column("notes", values, total_rows=100)
    assert result["kind"] != "segment"


# ---------------------------------------------------------------- headerless detection (2026-10-21)


def test_looks_headerless_numeric_header_on_numeric_column():
    values = [str(30 + i % 20) for i in range(200)]
    result = profile_column("42", values, total_rows=200)  # header cell is itself a number
    assert result["kind"] == "numeric"
    assert result["looks_headerless"] is True


def test_looks_headerless_date_header_on_date_column():
    values = [f"2024-01-{(i % 28) + 1:02d}" for i in range(200)]
    result = profile_column("2024-01-03", values, total_rows=200)
    assert result["kind"] == "date"
    assert result["looks_headerless"] is True


def test_looks_headerless_segment_value_repeated_as_its_own_header():
    values = (["North"] * 120) + (["South"] * 80)
    result = profile_column("North", values, total_rows=200)  # header is one of the column's own values
    assert result["kind"] == "segment"
    assert result["looks_headerless"] is True


def test_looks_headerless_false_for_a_normal_label():
    values = [str(20 + i % 50) for i in range(200)]
    result = profile_column("Age", values, total_rows=200)
    assert result["kind"] == "numeric"
    assert result["looks_headerless"] is False


def test_looks_headerless_never_true_for_id_or_junk():
    # A repeated question-like header forces id_or_junk; a header that happens to look numeric must
    # still never flag for a kind this ambiguous to judge.
    values = ["Why did you buy this?"] * 200
    result = profile_column("42", values, total_rows=200)
    assert result["kind"] == "id_or_junk"
    assert result["looks_headerless"] is False


def test_headerless_suspected_true_when_most_eligible_columns_flag():
    df = pd.DataFrame({
        "103": [str(100 + i % 10) for i in range(200)],          # numeric, header looks like data
        "2024-01-03": [f"2024-0{1 + i % 9}-01" for i in range(200)],  # date, header looks like data
        "North": (["North"] * 120) + (["South"] * 80),           # segment, header looks like data
    })
    profile = profile_dataframe(df)
    assert profile["headerless_suspected"] is True


def test_headerless_suspected_false_for_one_coincidentally_numeric_header():
    df = pd.DataFrame({
        "2024": [str(100 + i % 10) for i in range(200)],  # the one column whose header looks like data
        "Age": [str(20 + i % 50) for i in range(200)],
        "Region": (["North"] * 120) + (["South"] * 80),
        "Comment": [f"this is answer number {i}" for i in range(200)],
    })
    profile = profile_dataframe(df)
    assert profile["headerless_suspected"] is False


def test_cp1252_and_tab(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes("Name\tCity\tComment\nZoë\tMünchen\tgood\n".encode("cp1252"))
    _, loaded = profile_file(p)
    assert loaded.meta["encoding"] == "cp1252" and loaded.meta["delimiter"] == "\t"
    assert loaded.df["City"][0] == "München"


def test_question_column_and_gender_by_values(tmp_path):
    q = "How could we improve our service for you?"
    lines = ["Question,Answer,Who"]
    answers = ["Faster replies from support please", "Cheaper plans for students would help a lot", "Nothing really, it works fine for me",
               "Better mobile app with fewer crashes", "More payment options at checkout", "Clearer pricing on the website"]
    for i in range(12):
        lines.append(f"{q},{answers[i % 6]} {i},{'male' if i % 2 else 'female'}")
    p = tmp_path / "q.csv"
    p.write_text("\n".join(lines))
    profile, _ = profile_file(p)
    assert profile["question"] == {"text": q, "source": "column", "column": "Question"}
    by = {c["name"]: c for c in profile["columns"]}
    assert by["Question"]["kind"] == "id_or_junk" and by["Question"]["is_question"]
    assert by["Answer"]["kind"] == "open_text"
    assert by["Who"]["sensitive"]  # flagged from the values, the name says nothing


def test_no_question_returns_none(tmp_path):
    p = tmp_path / "n.csv"
    p.write_text("City,Score\n" + "\n".join(f"{c},{i % 5 + 1}" for i, c in enumerate(["A", "B", "A", "B", "C", "A", "B", "C"])))
    profile, _ = profile_file(p)
    assert profile["question"] is None
    assert kinds(profile)["Score"] == "score"


def test_xlsx(tmp_path):
    import datetime as dt

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Income", "Joined", "Feedback", "Plan", "Email"])
    rng = random.Random(1)
    for i in range(40):
        ws.append([
            rng.randint(30, 150) * 1000,
            dt.datetime(2025, 1 + i % 12, 1 + i % 27),
            f"Feedback number {i} says the product could be quicker to set up",
            rng.choice(["Basic", "Pro", "Team"]),
            f"user{i}@example.com",
        ])
    ws.merge_cells("A1:B1")  # odd merged header must not crash
    p = tmp_path / "s.xlsx"
    wb.save(p)
    profile, loaded = profile_file(p)
    k = kinds(profile)
    assert loaded.meta["format"] == "xlsx"
    assert k["Income"] == "numeric" and k["Feedback"] == "open_text" and k["Plan"] == "segment"
    assert k["Email"] == "id_or_junk"
    by = {c["name"]: c for c in profile["columns"]}
    assert by["Income"]["sensitive"] and by["Income"]["unit"] == "currency"
    assert "Column 2" in k and k["Column 2"] == "date"  # merged header cell became blank and got a name


def test_empty_and_binary_files_rejected(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("\n\n")
    with pytest.raises(LoadError):
        profile_file(p)
    b = tmp_path / "b.csv"
    b.write_bytes(b"\x00\x01\x02" * 100)
    with pytest.raises(LoadError):
        profile_file(b)
    x = tmp_path / "bad.xlsx"
    x.write_bytes(b"not a zip")
    with pytest.raises(LoadError):
        profile_file(x)


def test_50k_rows_under_10_seconds(tmp_path):
    rng = random.Random(7)
    words = "battery charger price range home work drive cost service quality wait trust".split()
    p = tmp_path / "big.csv"
    with p.open("w") as f:
        f.write("id,date,score,age,segment,answer\n")
        for i in range(50_000):
            ans = " ".join(rng.choices(words, k=rng.randint(5, 14))) + f" {i}"
            f.write(f"{i + 1},2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d},{rng.randint(0, 10)},{rng.randint(18, 90)},{rng.choice('ABCDE')},{ans}\n")
    t = time.perf_counter()
    profile, _ = profile_file(p)
    elapsed = time.perf_counter() - t
    assert elapsed < 10, elapsed
    assert profile["row_count"] == 50_000
    assert kinds(profile) == {"id": "id_or_junk", "date": "date", "score": "score", "age": "numeric",
                              "segment": "segment", "answer": "open_text"}


# ---- Claude hook: fake client, no network
class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(text=self.reply)])


def test_refine_is_noop_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    profile, _ = profile_file(FIX / "messy_survey.csv")
    assert refine_profile(profile, {}) is profile


def test_refine_with_fake_client_sends_only_samples():
    profile, loaded = profile_file(FIX / "messy_survey.csv")
    samples = collect_samples(loaded.df, profile)
    assert samples["Age"] == []  # sensitive columns send no values
    assert all(len(v) <= 30 for v in samples.values())
    reply = json.dumps({"columns": [
        {"name": "Region", "kind": "short_text", "unit": None, "reason": "Regions are names."},
        {"name": "Age", "kind": "nonsense", "unit": "years", "reason": "x"},
    ], "question": "ignored because one exists"})
    client = FakeClient("Here you go: " + reply)
    out = refine_profile(profile, samples, client=client)
    assert len(client.calls) == 1
    sent = client.calls[0]["messages"][0]["content"]
    assert "R-1001" in sent and "2026-06-30" in sent
    by = {c["name"]: c for c in out["columns"]}
    assert by["Region"]["kind"] == "short_text" and by["Region"]["refined_by"] == "claude"
    assert by["Age"]["kind"] == "numeric"  # invalid kind rejected
    assert {c["name"]: c for c in profile["columns"]}["Region"]["kind"] == "segment"  # input not mutated


def test_refine_attaches_suggested_name_only_to_a_flagged_column():
    values = [str(100 + i % 10) for i in range(200)]
    profile = profile_dataframe(pd.DataFrame({"103": values, "Region": (["North"] * 120) + (["South"] * 80)}))
    assert profile["columns"][0]["looks_headerless"] is True  # "103" - numeric header on a numeric column
    assert profile["columns"][1]["looks_headerless"] is False  # "Region" - a normal label
    samples = {"103": values[:5], "Region": ["North", "South"]}
    reply = json.dumps({"columns": [
        {"name": "103", "kind": "numeric", "unit": None, "reason": "x", "suggested_name": "Order Count"},
        # Claude tries to attach a suggestion to a column we never flagged - must be ignored.
        {"name": "Region", "kind": "segment", "unit": None, "reason": "x", "suggested_name": "Area"},
    ], "question": None})
    out = refine_profile(profile, samples, client=FakeClient(reply))
    by = {c["name"]: c for c in out["columns"]}
    assert by["103"]["suggested_name"] == "Order Count"
    assert "suggested_name" not in by["Region"]


def test_refine_is_noop_without_key_even_with_headerless_columns(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    values = [str(100 + i % 10) for i in range(200)]
    profile = profile_dataframe(pd.DataFrame({"103": values}))
    out = refine_profile(profile, {"103": values[:5]})
    assert out is profile
    assert "suggested_name" not in out["columns"][0]


def test_refine_survives_bad_reply_and_errors():
    profile, _ = profile_file(FIX / "messy_survey.csv")
    assert refine_profile(profile, {}, client=FakeClient("no json here")) is profile

    class Boom:
        messages = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))

    assert refine_profile(profile, {}, client=Boom()) is profile
