"""Stream 6: build-themes API. Fake embedding/Claude/Jev clients only, no network."""
import json
import random
import shutil
import tempfile
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api_themes import _SLOTS, get_claude_client, get_embedding_client, get_jev_client_factory
from app.api_upload import current_user
from app.db import Base, get_db
from app.main import app
from app.text_pipeline import FakeEmbeddingClient, FakeJevClient
from app.text_pipeline.labeling import FakeClaudeClient as FakeLabelingClaudeClient

Q = "What could we do better?"

# `FakeEmbeddingClient` is a bag-of-words hash, not a real semantic embedding (see its docstring): it only
# separates two groups cleanly when each group repeats a small, mostly-disjoint vocabulary rather than
# using varied natural sentences with lots of shared connector words. Built with a fixed seed so the
# resulting clusters are stable across runs.
_WORDS_RELIABILITY = ["battery", "drains", "quickly", "overheats", "device", "constantly", "terrible", "annoying"]
_WORDS_SUPPORT = ["staff", "polite", "cheerful", "welcoming", "checkout", "friendly", "helpful", "wonderful"]


def _phrases(words: list[str], n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [" ".join(rng.sample(words, rng.randint(5, len(words)))) for _ in range(n)]


def _survey_texts() -> tuple[list[str], list[str]]:
    reliability = _phrases(_WORDS_RELIABILITY, 13, seed=1)
    support = _phrases(_WORDS_SUPPORT, 13, seed=2)
    # two support answers carry a real email, for the masked-vs-real-text tests below
    support[3] = support[3] + " mail sam42@example.com"
    support[7] = support[7] + " contact sam43@example.com"
    return reliability, support


def theme_df() -> pd.DataFrame:
    reliability, support = _survey_texts()
    text = reliability + support
    return pd.DataFrame({"Respondent ID": range(1, len(text) + 1), Q: text}).astype(object)


def small_df() -> pd.DataFrame:
    text = [
        "Prices are a bit too high for what you get",
        "Delivery took longer than the site promised",
        "The website navigation is confusing at first",
        "Packaging could be sturdier for fragile items",
        "Return process was slower than expected overall",
        "More size options would really help a lot",
        "Checkout page froze once during my last order",
        "Customer service replied a little late to my message",
        "The product description missed some key details",
        "Loyalty points expired before I could use them",
    ]
    return pd.DataFrame({"Respondent ID": range(1, len(text) + 1), Q: text}).astype(object)


def _fake_claude_reply(prompt: str) -> str:
    payload = json.loads(prompt)
    themes = [
        {"cluster_id": c["cluster_id"], "label": f"Theme {c['cluster_id']}",
         "description": f"About cluster {c['cluster_id']}.", "merge_with": [], "note": None}
        for c in payload["clusters"]
    ]
    return json.dumps({"themes": themes})


def install_fakes():
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))


# ---------------------------------------------------------------- fixtures
@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield SimpleNamespace(client=TestClient(app), Session=Session)
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


def upload_csv(env, df, name="survey.csv"):
    data = df.to_csv(index=False).encode("utf-8")
    r = env.client.post("/api/upload", files={"file": (name, data, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def clean_and_apply(env, did, disable_mask=False):
    r = env.client.post(f"/api/datasets/{did}/clean/plan")
    assert r.status_code == 200, r.text
    if disable_mask:
        off = "mask_pii:" + Q
        step_ids = {s["id"] for s in r.json()["plan"]["steps"]}
        assert off in step_ids, sorted(step_ids)
        r2 = env.client.patch(f"/api/datasets/{did}/clean/plan", json={"steps": [{"id": off, "enabled": False}]})
        assert r2.status_code == 200, r2.text
    r3 = env.client.post(f"/api/datasets/{did}/clean/apply")
    assert r3.status_code == 200, r3.text
    return r3.json()


# ---------------------------------------------------------------- round trip
def test_build_list_answers_round_trip(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    applied = clean_and_apply(env, did)
    rows_out = applied["report"]["rows_out"]

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dataset_id"] == did and body["column"] == Q
    assert body["total_answers"] == rows_out
    themes = body["themes"]
    assert len(themes) >= 2  # reliability + support at least
    assert sum(t["size"] for t in themes) == rows_out
    for t in themes:
        assert t["confidence"] in ("solid", "tentative")
        assert set(t["tone"]) == {"neg", "neu", "pos"}
        assert abs(sum(t["tone"].values()) - 100) < 0.01
        assert t["description"]
    real_theme_labels = [t["label"] for t in themes if t["label"] != "Other"]
    assert all(lbl.startswith("Theme ") for lbl in real_theme_labels)

    # GET list matches what build just returned
    got = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q})
    assert got.status_code == 200, got.text
    listed = got.json()
    assert listed["total_answers"] == rows_out
    assert {t["id"] for t in listed["themes"]} == {t["id"] for t in themes}

    # GET answers for the first (largest) theme: real cleaned text, paginated
    first = themes[0]
    ans = env.client.get(f"/api/datasets/{did}/themes/{first['id']}/answers", params={"limit": 5, "offset": 0})
    assert ans.status_code == 200, ans.text
    ans_body = ans.json()
    assert ans_body["theme_id"] == first["id"]
    assert ans_body["total"] == first["size"]
    assert len(ans_body["answers"]) == min(5, first["size"])
    for a in ans_body["answers"]:
        assert a["text"].strip()
        assert a["tone"] in ("neg", "neu", "pos")


def test_rebuild_replaces_themes_not_duplicates(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    first = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert first.status_code == 200, first.text
    first_ids = {t["id"] for t in first.json()["themes"]}
    first_count = len(first_ids)

    second = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert second.status_code == 200, second.text
    second_ids = {t["id"] for t in second.json()["themes"]}

    got = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q})
    listed_ids = {t["id"] for t in got.json()["themes"]}
    assert listed_ids == second_ids  # not first_ids | second_ids
    assert len(listed_ids) == first_count  # same shape rebuilt, not doubled
    assert first_ids.isdisjoint(second_ids)  # old rows were really deleted, not reused


def test_answers_are_real_unmasked_text_not_masked(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did, disable_mask=True)  # cleaned CSV keeps the raw email; the pipeline still masks it

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 200, r.text

    # The fake Claude client only ever saw masked text: the raw email address never reached it.
    claude = app.dependency_overrides[get_claude_client]()
    all_prompts = " ".join(c["prompt"] for c in claude.calls)
    assert "sam42@example.com" not in all_prompts
    assert "sam43@example.com" not in all_prompts

    themes = r.json()["themes"]
    found_real_email = False
    for t in themes:
        ans = env.client.get(f"/api/datasets/{did}/themes/{t['id']}/answers", params={"limit": 50})
        for a in ans.json()["answers"]:
            if "sam42@example.com" in a["text"] or "sam43@example.com" in a["text"]:
                found_real_email = True
            assert "[email]" not in a["text"]  # never the masked placeholder in the owner's own view
    assert found_real_email, "expected at least one real, unmasked email in the owner's verbatim view"


# ---------------------------------------------------------------- errors
def test_too_few_answers_returns_422(env):
    install_fakes()
    did = upload_csv(env, small_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 422, r.text
    assert "20" in r.json()["detail"]


def test_missing_embedding_key_returns_503(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 503, r.text
    assert "embedding" in r.json()["detail"].lower()
    assert "VOYAGE_API_KEY" in r.json()["detail"]


def test_missing_claude_key_returns_503(env):
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 503, r.text
    assert "claude" in r.json()["detail"].lower()
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_missing_jev_key_returns_503(env):
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q, "use_jev_sentiment": True})
    assert r.status_code == 503, r.text
    detail = r.json()["detail"].lower()
    assert "jev" in detail or "typesafe" in detail
    assert "TYPESAFE_API_KEY" in r.json()["detail"]


def test_concurrency_cap_returns_429(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    assert _SLOTS.acquire(blocking=False)  # simulate a job already running (default cap is 1)
    try:
        r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
        assert r.status_code == 429, r.text
    finally:
        _SLOTS.release()


# ---------------------------------------------------------------- ownership isolation
def test_ownership_isolation(env):
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    built = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert built.status_code == 200, built.text
    theme_id = built.json()["themes"][0]["id"]

    as_user(uid2)
    assert env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/themes/{theme_id}/answers").status_code == 404


# ---------------------------------------------------------------- the bug this stream fixes
def test_themes_build_after_the_disk_is_wiped_between_steps(env, monkeypatch, tmp_path):
    """The exact production bug this stream fixes: uploaded and cleaned file bytes used to live only on
    the container's disk (`UPLOAD_DIR`), which does not survive a Railway redeploy. This drives the real
    upload -> clean -> build-themes pipeline through the real HTTP API (as a real user would), and between
    every step wipes a dedicated scratch "disk" standing in for the OS temp directory that
    app.api_upload.scratch_file/app.api_cleaning._load_df use for library-compat-only temp files - proving
    nothing persists there between requests, and that themes/build succeeds purely from what
    app.models.UploadedFile/CleanedFile hold in the database.

    `tempfile.tempdir` (not the shared system temp directory used by the rest of the suite) is overridden so
    this test can safely rmtree it - deleting the real OS temp directory's contents would be unsafe to do in
    a shared test run.
    """
    install_fakes()
    scratch_disk = tmp_path / "scratch-disk"
    scratch_disk.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch_disk))

    did = upload_csv(env, theme_df())
    assert list(scratch_disk.iterdir()) == []  # the upload's own temp file was already cleaned up

    applied = clean_and_apply(env, did)
    assert list(scratch_disk.iterdir()) == []  # so was cleaning's

    # Simulate the disk disappearing entirely (a redeploy wiping the container filesystem, or the Railway
    # volume permission failure that motivated this change in the first place).
    shutil.rmtree(scratch_disk)
    scratch_disk.mkdir()
    assert list(scratch_disk.iterdir()) == []

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_answers"] == applied["report"]["rows_out"]
    themes = body["themes"]
    assert len(themes) >= 2 and sum(t["size"] for t in themes) == applied["report"]["rows_out"]

    # the disk is STILL gone (never repopulated) and reading the themes/answers back still works
    got = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q})
    assert got.status_code == 200 and {t["id"] for t in got.json()["themes"]} == {t["id"] for t in themes}
    ans = env.client.get(f"/api/datasets/{did}/themes/{themes[0]['id']}/answers", params={"limit": 5})
    assert ans.status_code == 200 and ans.json()["answers"]
    assert list(scratch_disk.iterdir()) == []  # building/reading themes never touched the scratch "disk" either
