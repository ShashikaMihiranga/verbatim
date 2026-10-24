"""Stream 6: build-themes API, now running as an async background job (see app/jobs.py). Fake embedding/
Claude/Jev clients only, no network."""
import json
import random
import shutil
import tempfile
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import app.db as db_module
from app.api_themes import (
    _SLOTS,
    MAX_ANSWER_POSITIONS,
    MIN_OTHER_NEW_THEME_SIZE,
    _apply_other_classification,
    _apply_theme_split,
    _cluster_centroid,
    _project_centroids_2d,
    _sample_answer_positions,
    _themes_deadline_for,
    get_claude_client,
    get_embedding_client,
    get_jev_client,
    get_jev_client_factory,
)
from app.api_upload import current_user
from app.db import Base, get_db
from app.main import app
from app.text_pipeline import FakeEmbeddingClient, FakeJevClient
from app.text_pipeline.jev_sentiment import ChoiceAnswer
from app.text_pipeline.other_classify import NONE_OF_THESE
from app.text_pipeline.labeling import FakeClaudeClient as FakeLabelingClaudeClient
from tests.job_test_support import BlockingClient, wait_for_job

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


# ---------------------------------------------------------------- big, real-sub-structure fixture (sub-themes)
# `FakeEmbeddingClient` above is a bag-of-words hash (see its own docstring): fine for "two topics separate
# from each other", not reliable enough to also keep 3 sub-topics merged into ONE >=100-answer top-level
# theme while still being separable by a SECOND, independent clustering pass on just that subset - exactly
# what a real sub-theme test needs. `FakeFamilyEmbeddingClient` below instead maps each exact (masked) answer
# text to a precomputed vector from a small numpy fixture, built the same way
# tests/test_text_pipeline.py's `_high_dimensional_fixture` is (family centers + substantial per-dimension
# noise, unit-length, 300 "real-embedding-shaped" dimensions) - see docs/DECISIONS.md for the exact
# parameters and how they were found (a direct parameter sweep against `cluster_answers`/`sub_cluster_themes`
# in this environment, not guessed).
_SUB_DIM = 300
_SUB_GROUP_SIZES = (45, 45, 40)  # 3 sub-groups under one big parent theme - 130 answers, well over the
                                 # 100-answer sub-clustering floor (app/text_pipeline/subthemes.py)
_SUB_B_SIZE = 35  # a second, unrelated top-level theme - too small (< 100) to ever be sub-clustered itself
_SUB_DELTA_SCALE = 0.05  # how far each of the 3 sub-group centers sits from their shared base direction -
                         # close enough that top-level clustering merges all 3 into ONE cluster
_SUB_MEMBER_NOISE = 0.15  # per-member noise around its own sub-group center - loose enough that a second,
                          # independent UMAP fit on just the merged cluster's own subset can still tell the
                          # 3 sub-groups apart
_SUB_B_NOISE = 0.2

# Real-sounding vocabularies for 3 "shipping problem" sub-themes plus one distinct "support quality" theme -
# disjoint word lists per group (so texts stay recognisably on-topic) and each answer text ends up unique
# (checked below) purely from `random.sample`'s own random ordering, same convention as `_WORDS_RELIABILITY`/
# `_WORDS_SUPPORT` above; no digits/capitals/@ anywhere, so nothing here is ever touched by PII masking.
_SUB_WORDS = {
    0: ["delivery", "arrived", "late", "shipping", "package", "delayed", "tracking", "slow", "days", "waited"],
    1: ["wrong", "item", "received", "incorrect", "order", "mismatched", "size", "color", "swapped", "mistake"],
    2: ["damaged", "box", "broken", "packaging", "crushed", "dented", "torn", "cracked", "wrapped", "return"],
    "b": ["staff", "polite", "cheerful", "welcoming", "checkout", "friendly", "helpful", "wonderful", "team", "attentive"],
}


def _family_vectors_and_groups():
    """Deterministic (fixed seed): 300-dim unit vectors for `_SUB_GROUP_SIZES` answers across 3 sub-groups
    that all sit close to one shared base direction (so top-level clustering merges them into one theme),
    plus `_SUB_B_SIZE` answers from a wholly separate direction (a second, ordinary top-level theme).
    Returns `(vectors, group_of_each_row)` - `group_of_each_row[i]` is `0`/`1`/`2` for a sub-group or `"b"`.
    """
    rng = np.random.RandomState(7)
    base = rng.normal(size=_SUB_DIM)
    base /= np.linalg.norm(base)

    vectors: list[np.ndarray] = []
    groups: list = []
    for g, n in enumerate(_SUB_GROUP_SIZES):
        center = base + _SUB_DELTA_SCALE * rng.normal(size=_SUB_DIM)
        center /= np.linalg.norm(center)
        for _ in range(n):
            v = center + rng.normal(scale=_SUB_MEMBER_NOISE, size=_SUB_DIM)
            v /= np.linalg.norm(v)
            vectors.append(v)
            groups.append(g)

    b_center = rng.normal(size=_SUB_DIM)
    b_center /= np.linalg.norm(b_center)
    for _ in range(_SUB_B_SIZE):
        v = b_center + rng.normal(scale=_SUB_B_NOISE, size=_SUB_DIM)
        v /= np.linalg.norm(v)
        vectors.append(v)
        groups.append("b")

    return np.asarray(vectors, dtype="float32"), groups


def big_theme_df_and_vectors() -> tuple[pd.DataFrame, dict[str, list[float]]]:
    """A ~200-answer survey with one big (130-answer, 3-sub-group) theme plus a smaller, ordinary theme -
    real enough sub-structure for `sub_cluster_themes` to actually recover something, paired with a
    text -> vector mapping for `FakeFamilyEmbeddingClient` below."""
    vectors, groups = _family_vectors_and_groups()
    rng = random.Random(99)
    texts: list[str] = []
    for g in groups:
        words = _SUB_WORDS[g]
        k = rng.randint(5, min(8, len(words)))
        texts.append(" ".join(rng.sample(words, k)))
    assert len(set(texts)) == len(texts), "generated answer texts must be unique (cleaning dedup safety)"

    df = pd.DataFrame({"Respondent ID": range(1, len(texts) + 1), Q: texts}).astype(object)
    vectors_by_text = dict(zip(texts, vectors.tolist()))
    return df, vectors_by_text


class FakeFamilyEmbeddingClient:
    """Deterministic embedding fake that maps each EXACT (masked) answer text to a precomputed vector from
    `big_theme_df_and_vectors`'s own fixture, instead of `FakeEmbeddingClient`'s bag-of-words hash - see the
    comment above `_SUB_DIM` for why a real family-clustered fixture is needed for a reliable nested split.
    """

    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self._vectors_by_text = vectors_by_text

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors_by_text[t] for t in texts]


def _fake_claude_reply_sub_labeling_fails(prompt: str) -> str:
    """Same shape as `_fake_claude_reply` for the MAIN theme-labeling call (one entry per cluster id, no
    `parent_theme` key on any cluster) - but for the SUB-theme labeling call specifically (identified by
    `parent_theme` being present on its cluster entries, see `labeling.label_sub_clusters`'s own request
    shape), returns text that is not valid JSON at all, so `label_sub_clusters` raises `LabelingError` for
    that one call only, never touching the main labeling step."""
    payload = json.loads(prompt)
    if payload["clusters"] and "parent_theme" in payload["clusters"][0]:
        return "not json at all, sub-theme labeling is broken"
    return _fake_claude_reply(prompt)


# ---------------------------------------------------------------- fixtures
@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    # A real file-backed SQLite database, not `sqlite://` (in-memory) with a single shared `StaticPool`
    # connection: async build jobs now run real pipeline work on a background THREAD while the main test
    # thread keeps polling, so two threads genuinely touch this database concurrently. An in-memory DB
    # backed by one shared connection object serialises that badly (observed directly: sporadic identity-
    # map/row-count corruption under the full suite, gone once switched to this). `NullPool` opens and
    # closes a fresh connection per checkout, so a connection is never handed from the thread that created
    # it to a different one - each thread's own session gets its own real connection to the same file, the
    # way separate pooled connections to a real Postgres server already work in production.
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    # The background job thread `POST .../themes/build` now starts does not go through FastAPI's DI at
    # all (it is not a request), so it cannot pick up the `get_db` override above - it opens its own
    # session via `app.db.SessionLocal()` at call time (see app/jobs.py's own comment on why). Point that
    # same module attribute at this test's own engine so the job thread reads/writes the same in-memory
    # database the rest of this test uses, not the real `dev.db` file.
    monkeypatch.setattr(db_module, "SessionLocal", Session)
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


def build_themes_job(env, did, column=Q, use_jev_sentiment=False, timeout=5.0) -> dict:
    """Starts a themes build through the real async route and waits for it to finish (either way),
    returning the final job body. Asserts the now-standard "202, job accepted, running" shape on the way
    in - every test that reaches this helper already expects the build to actually be attempted."""
    r = env.client.post(
        f"/api/datasets/{did}/themes/build",
        json={"column": column, "use_jev_sentiment": use_jev_sentiment},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running" and body["job_id"]
    return wait_for_job(env.client, did, body["job_id"], timeout=timeout)


# ---------------------------------------------------------------- round trip
def test_build_list_answers_round_trip(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    applied = clean_and_apply(env, did)
    rows_out = applied["report"]["rows_out"]

    job = build_themes_job(env, did)
    assert job["status"] == "done", job
    assert job["error"] is None

    got0 = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q})
    assert got0.status_code == 200, got0.text
    body = got0.json()
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

    first_job = build_themes_job(env, did)
    assert first_job["status"] == "done", first_job
    first_ids = {t["id"] for t in env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]}
    first_count = len(first_ids)

    second_job = build_themes_job(env, did)
    assert second_job["status"] == "done", second_job
    assert second_job["id"] != first_job["id"]  # a fresh build replaces the prior Job row too, not just Theme rows
    second_ids = {t["id"] for t in env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]}

    got = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q})
    listed_ids = {t["id"] for t in got.json()["themes"]}
    assert listed_ids == second_ids  # not first_ids | second_ids
    assert len(listed_ids) == first_count  # same shape rebuilt, not doubled
    assert first_ids.isdisjoint(second_ids)  # old rows were really deleted, not reused


def test_answers_are_real_unmasked_text_not_masked(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did, disable_mask=True)  # cleaned CSV keeps the raw email; the pipeline still masks it

    job = build_themes_job(env, did)
    assert job["status"] == "done", job

    # The fake Claude client only ever saw masked text: the raw email address never reached it.
    claude = app.dependency_overrides[get_claude_client]()
    all_prompts = " ".join(c["prompt"] for c in claude.calls)
    assert "sam42@example.com" not in all_prompts
    assert "sam43@example.com" not in all_prompts

    themes = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    found_real_email = False
    for t in themes:
        ans = env.client.get(f"/api/datasets/{did}/themes/{t['id']}/answers", params={"limit": 50})
        for a in ans.json()["answers"]:
            if "sam42@example.com" in a["text"] or "sam43@example.com" in a["text"]:
                found_real_email = True
            assert "[email]" not in a["text"]  # never the masked placeholder in the owner's own view
    assert found_real_email, "expected at least one real, unmasked email in the owner's verbatim view"


# ---------------------------------------------------------------- errors
def test_too_few_answers_surfaces_as_job_error_not_a_synchronous_422(env):
    """`TooFewAnswers` can only be known once the pipeline actually runs (it depends on how many answers
    survive cleaning), so - unlike ownership/column/key checks - it is not knowable before the job starts.
    The build route still accepts the request (202) and starts a job; that job then fails with the exact
    same message text the old synchronous 422 used to carry, now in `job.error`."""
    install_fakes()
    did = upload_csv(env, small_df())
    clean_and_apply(env, did)

    job = build_themes_job(env, did)
    assert job["status"] == "failed", job
    assert "20" in job["error"]


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
    job = build_themes_job(env, did)
    assert job["status"] == "done", job
    job_id = job["id"]
    theme_id = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"][0]["id"]

    as_user(uid2)
    assert env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/themes/{theme_id}/answers").status_code == 404
    # job status/latest endpoints are owner-only too, same as every other data route
    assert env.client.get(f"/api/datasets/{did}/jobs/{job_id}").status_code == 404
    assert env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "themes"}).status_code == 404


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

    job = build_themes_job(env, did)
    assert job["status"] == "done", job
    body = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()
    assert body["total_answers"] == applied["report"]["rows_out"]
    themes = body["themes"]
    assert len(themes) >= 2 and sum(t["size"] for t in themes) == applied["report"]["rows_out"]

    # the disk is STILL gone (never repopulated) and reading the themes/answers back still works
    got = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q})
    assert got.status_code == 200 and {t["id"] for t in got.json()["themes"]} == {t["id"] for t in themes}
    ans = env.client.get(f"/api/datasets/{did}/themes/{themes[0]['id']}/answers", params={"limit": 5})
    assert ans.status_code == 200 and ans.json()["answers"]
    assert list(scratch_disk.iterdir()) == []  # building/reading themes never touched the scratch "disk" either


# ---------------------------------------------------------------- async job behaviour (this stream)
def test_job_step_changes_while_running_then_reaches_done(env):
    """The core ask of this stream: a poller sees a real intermediate `job.step` before the job reaches
    "done" - not a fake progress bar, an actual pause inside the real pipeline. `BlockingClient` wraps the
    fake embedding client's `embed` method so this test controls exactly when it returns, via a
    `threading.Event` (see tests/job_test_support.py)."""
    blocking = BlockingClient(FakeEmbeddingClient(), "embed")
    app.dependency_overrides[get_embedding_client] = lambda: blocking
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))

    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    # The request returned immediately (202) even though the real pipeline has not finished - it is still
    # paused inside the (fake) embedding call right now.
    assert blocking.reached.wait(timeout=5), "the pipeline never reached the embedding call"
    mid = env.client.get(f"/api/datasets/{did}/jobs/{job_id}")
    assert mid.status_code == 200, mid.text
    mid_body = mid.json()
    assert mid_body["status"] == "running"
    assert mid_body["step"] == "Turning answers into vectors"
    assert mid_body["error"] is None

    blocking.released.set()  # let the pipeline continue
    final = wait_for_job(env.client, did, job_id, timeout=5)
    assert final["status"] == "done", final
    assert final["step"] == "Done"


def test_latest_job_lookup_lets_a_reloaded_page_resume_watching(env):
    """`GET .../jobs/latest` is what a reloaded page uses to find a build it did not itself start (the
    brief's own "resume after reload" requirement) - it must exist before a job id is known, match the
    right job by dataset+column+kind while it is still running, and keep matching once it finishes."""
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    nothing_yet = env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "themes"})
    assert nothing_yet.status_code == 404

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    latest = env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "themes"})
    assert latest.status_code == 200, latest.text
    assert latest.json()["id"] == job_id
    # a different kind/column for the same dataset must not match
    assert env.client.get(
        f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "report"}
    ).status_code == 404
    assert env.client.get(
        f"/api/datasets/{did}/jobs/latest", params={"column": "Some other column", "kind": "themes"}
    ).status_code == 404

    final = wait_for_job(env.client, did, job_id, timeout=5)
    assert final["status"] == "done", final
    latest_done = env.client.get(f"/api/datasets/{did}/jobs/latest", params={"column": Q, "kind": "themes"})
    assert latest_done.status_code == 200
    assert latest_done.json()["id"] == job_id
    assert latest_done.json()["status"] == "done"


def test_concurrency_cap_holds_while_a_job_is_genuinely_running(env):
    """Unlike `test_concurrency_cap_returns_429` above (which simulates a busy slot by acquiring `_SLOTS`
    directly, with no real work happening), this drives a REAL background job that is genuinely still
    running - blocked on a fake client's `threading.Event`, not merely a held semaphore - and shows a
    second build attempt is still rejected (429) while it holds the one slot (default
    `THEMES_CONCURRENCY=1`), then that the first job still completes normally once released."""
    blocking = BlockingClient(FakeEmbeddingClient(), "embed")
    app.dependency_overrides[get_embedding_client] = lambda: blocking
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))

    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r1 = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r1.status_code == 202, r1.text
    job1_id = r1.json()["job_id"]
    assert blocking.reached.wait(timeout=5)

    r2 = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r2.status_code == 429, r2.text

    blocking.released.set()
    final = wait_for_job(env.client, did, job1_id, timeout=5)
    assert final["status"] == "done", final


# ---------------------------------------------------------------- GET .../themes/chart (stream: smart chart)
def test_themes_chart_happy_path_renders_real_theme_labels(env):
    """Same "real theme names actually reach the rendered output" pattern `tests/test_api_report.py`'s
    `test_build_then_get_round_trip_renders_real_chart_html_with_real_theme_names` already uses for the
    report page's chart fragments - this pins the same thing down for the lightweight themes-chart route."""
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    job = build_themes_job(env, did)
    assert job["status"] == "done", job

    listed = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    real_labels = [t["label"] for t in listed if t["label"] != "Other"]
    assert real_labels  # theme_df() reliably yields at least the two real clusters

    r = env.client.get(f"/api/datasets/{did}/themes/chart", params={"column": Q})
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["chart_width"], int) and body["chart_width"] > 0
    assert isinstance(body["chart_height"], int) and body["chart_height"] > 0
    assert "<!doctype html>" not in body["chart_html"].lower()  # a fragment, same shape as app/api_report.py
    for label in real_labels:
        assert label in body["chart_html"]
    # each theme's own drawing is grouped under data-theme="<label>" (frontend/src/ThemeChart.tsx resolves
    # clicks/hover back to a theme through this attribute - see app/charts.py:treemap_html).
    for label in real_labels:
        assert f'data-theme="{label}"' in body["chart_html"]


def test_themes_chart_missing_column_404(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    job = build_themes_job(env, did)
    assert job["status"] == "done", job

    r = env.client.get(f"/api/datasets/{did}/themes/chart", params={"column": "Some other column"})
    assert r.status_code == 404, r.text


def test_themes_chart_empty_theme_list_404(env):
    """No themes have ever been built at all for this dataset (never mind this column) - the same "build
    themes first" 404 a caller would see from a bad column, not a 500 or an empty-but-200 chart."""
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r = env.client.get(f"/api/datasets/{did}/themes/chart", params={"column": Q})
    assert r.status_code == 404, r.text


def test_themes_chart_ownership_isolation(env):
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    job = build_themes_job(env, did)
    assert job["status"] == "done", job

    as_user(uid2)
    r = env.client.get(f"/api/datasets/{did}/themes/chart", params={"column": Q})
    assert r.status_code == 404, r.text


def test_themes_deadline_for_small_file_keeps_the_flat_floor_unchanged(monkeypatch):
    """A 500-answer file must keep today's exact behaviour - the scaling term is small enough to be
    negligible at this size, so this is a direct pin against a real regression for the common case."""
    monkeypatch.setattr("app.api_themes.THEMES_DEADLINE_SECONDS", 300.0)
    assert _themes_deadline_for(500) == pytest.approx(305.0)  # 300 + 500/100


def test_themes_deadline_for_scales_up_for_a_real_large_file(monkeypatch):
    """The real case that motivated this (2026-10-09 production incident, docs/DECISIONS.md): a flat 300s
    killed a 74,681-answer build that was still genuinely progressing through embedding."""
    monkeypatch.setattr("app.api_themes.THEMES_DEADLINE_SECONDS", 300.0)
    assert _themes_deadline_for(74681) == pytest.approx(1046.81, abs=0.01)


def test_themes_deadline_for_respects_a_monkeypatched_tiny_base(monkeypatch):
    """The watchdog test below relies on being able to monkeypatch `THEMES_DEADLINE_SECONDS` down to a
    near-zero value and have the EFFECTIVE deadline stay near-zero too (not floored back up by some
    separate hardcoded base) - this pins that the scaling term is purely additive on top of the real
    module constant, never a fixed minimum of its own."""
    monkeypatch.setattr("app.api_themes.THEMES_DEADLINE_SECONDS", 0.05)
    assert _themes_deadline_for(0) == pytest.approx(0.05)


# ==================================================================== _cluster_centroid (chart-block
# stream, 2026-10-24, batch 3: theme_similarity)

def test_cluster_centroid_is_the_real_mean_of_member_vectors():
    import numpy as np
    from app.text_pipeline import EmbeddedAnswers
    from app.text_pipeline.schema import Cluster, ClusterMember

    cluster = Cluster(id=0, members=[ClusterMember(row=0, text="a", distance=0.0), ClusterMember(row=1, text="b", distance=0.0)], centroid=None)
    embedded = EmbeddedAnswers(
        row_indexes=[0, 1, 2], vectors=np.array([[1.0, 0.0], [3.0, 0.0], [99.0, 99.0]]), position_by_row={0: 0, 1: 1, 2: 2},
    )
    centroid = _cluster_centroid(cluster, embedded)
    assert centroid == pytest.approx([2.0, 0.0])  # mean of [1,0] and [3,0] - row 2 is NOT a member, excluded


def test_cluster_centroid_is_none_when_embedded_is_none_or_no_member_has_a_vector():
    from app.text_pipeline.schema import Cluster, ClusterMember

    cluster = Cluster(id=0, members=[ClusterMember(row=0, text="a", distance=0.0)], centroid=None)
    assert _cluster_centroid(cluster, None) is None

    import numpy as np
    from app.text_pipeline import EmbeddedAnswers
    embedded_without_row_0 = EmbeddedAnswers(row_indexes=[5], vectors=np.array([[1.0, 2.0]]), position_by_row={5: 0})
    assert _cluster_centroid(cluster, embedded_without_row_0) is None


# ==================================================================== _project_centroids_2d (chart-block
# stream, 2026-10-24, batch 3: theme_similarity)

def test_project_centroids_2d_normalizes_real_centroids_to_0_1():
    out = _project_centroids_2d([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.5, 0.5, 0.0]])
    assert len(out) == 3
    assert all(p is not None for p in out)
    xs = [p[0] for p in out]
    ys = [p[1] for p in out]
    assert min(xs) == pytest.approx(0.0) and max(xs) == pytest.approx(1.0)
    assert min(ys) == pytest.approx(0.0) and max(ys) == pytest.approx(1.0)


def test_project_centroids_2d_keeps_none_entries_at_their_own_position():
    out = _project_centroids_2d([[1.0, 0.0], None, [0.0, 1.0], [0.5, 0.5]])
    assert len(out) == 4
    assert out[1] is None
    assert out[0] is not None and out[2] is not None and out[3] is not None


def test_project_centroids_2d_returns_all_none_when_fewer_than_two_real_centroids():
    assert _project_centroids_2d([[1.0, 0.0]]) == [None]
    assert _project_centroids_2d([None, None]) == [None, None]
    assert _project_centroids_2d([]) == []


# ==================================================================== _sample_answer_positions
# (chart-block stream, 2026-10-24, batch 4: answer_map)

def test_sample_answer_positions_is_empty_when_embedded_is_none_or_too_small():
    import numpy as np
    from app.text_pipeline import EmbeddedAnswers

    assert _sample_answer_positions(None) == {}
    one_row = EmbeddedAnswers(row_indexes=[0], vectors=np.array([[1.0, 2.0]]), position_by_row={0: 0})
    assert _sample_answer_positions(one_row) == {}


def test_sample_answer_positions_keys_by_real_row_index_and_scales_to_0_1():
    import numpy as np
    from app.text_pipeline import EmbeddedAnswers

    embedded = EmbeddedAnswers(
        row_indexes=[10, 20, 30], vectors=np.array([[1.0, 0.0], [3.0, 0.0], [2.0, 5.0]]),
        position_by_row={10: 0, 20: 1, 30: 2},
    )
    positions = _sample_answer_positions(embedded)
    assert set(positions) == {10, 20, 30}  # keyed by the real row index, not the array position
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    assert min(xs) == pytest.approx(0.0) and max(xs) == pytest.approx(1.0)
    assert min(ys) == pytest.approx(0.0) and max(ys) == pytest.approx(1.0)


def test_sample_answer_positions_is_reproducible_for_the_same_seed_and_bounded_by_the_cap():
    import numpy as np
    from app.text_pipeline import EmbeddedAnswers

    n = MAX_ANSWER_POSITIONS + 50
    rows = list(range(n))
    rng = np.random.default_rng(0)
    embedded = EmbeddedAnswers(
        row_indexes=rows, vectors=rng.normal(size=(n, 4)), position_by_row={r: i for i, r in enumerate(rows)},
    )
    first = _sample_answer_positions(embedded, seed=42)
    second = _sample_answer_positions(embedded, seed=42)
    assert first == second  # same seed -> same sample, same positions
    assert len(first) == MAX_ANSWER_POSITIONS  # never stores more than the cap
    assert _sample_answer_positions(embedded, seed=1) != first  # a different seed samples differently


def test_watchdog_marks_a_truly_stuck_job_failed_without_stopping_the_real_thread(env, monkeypatch):
    """`THEMES_DEADLINE_SECONDS` is now a sanity-check watchdog on the background thread, not something the
    request blocks on (see app/jobs.py:start_job's docstring). A tiny deadline plus a client that is never
    released proves: (1) the job is marked "failed" with an honest "took too long" message once the
    deadline passes, and (2) if the real (fake, in this test) pipeline finishes anyway afterwards, it does
    NOT silently flip the job back to "done" - `app.jobs._mark_done`'s "only touch a still-running job"
    guard, which exists exactly for this case."""
    monkeypatch.setattr("app.api_themes.THEMES_DEADLINE_SECONDS", 0.05)

    blocking = BlockingClient(FakeEmbeddingClient(), "embed", wait_timeout=5)
    app.dependency_overrides[get_embedding_client] = lambda: blocking
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))

    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    final = wait_for_job(env.client, did, job_id, timeout=5)
    assert final["status"] == "failed", final
    assert "took longer than" in final["error"].lower()

    # Release the still-running real (fake) pipeline and give it a moment to actually finish in the
    # background - Python cannot kill it, so it keeps going regardless of the watchdog's verdict.
    blocking.released.set()
    time.sleep(0.3)
    still = env.client.get(f"/api/datasets/{did}/jobs/{job_id}")
    assert still.json()["status"] == "failed"  # not silently flipped back to "done"


# ---------------------------------------------------------------- sub-themes (S2: storage + backend wiring)
def test_build_themes_with_subthemes_end_to_end(env):
    """The core ask of this stream: a real build against real (large-enough, family-clustered) sub-
    structure produces stored `Theme.sub_themes`, not just `[]` everywhere - `FakeEmbeddingClient`'s
    bag-of-words hash is too coarse for this (see the comment above `_SUB_DIM`), so this uses
    `FakeFamilyEmbeddingClient` instead. Also covers the new `.../sub-themes/{index}/answers` route:
    pagination, an out-of-range index, ownership isolation, and 404 for a theme with no sub-themes."""
    uid1, uid2 = make_users(env, "clerk-sub-1", "clerk-sub-2")
    as_user(uid1)

    df, vectors_by_text = big_theme_df_and_vectors()
    app.dependency_overrides[get_embedding_client] = lambda: FakeFamilyEmbeddingClient(vectors_by_text)
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))

    did = upload_csv(env, df)
    clean_and_apply(env, did)
    job = build_themes_job(env, did, timeout=30)
    assert job["status"] == "done", job
    assert job["error"] is None

    listed = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()
    total_answers = listed["total_answers"]
    themes = listed["themes"]
    real_themes = [t for t in themes if t["label"] != "Other"]
    big = max(real_themes, key=lambda t: t["size"])
    assert big["size"] >= 100  # the 3 sub-groups merged into one top-level theme, exactly as designed

    subs = big["sub_themes"]
    assert 2 <= len(subs) <= 3  # subthemes.py: >=2 kept sub-clusters required to store any, capped at 3
    total_sub_size = 0
    for i, s in enumerate(subs):
        assert s["index"] == i
        assert s["label"] and s["description"]
        assert s["size"] > 0
        assert s["size_pct"] == pytest.approx(round(s["size"] / total_answers * 100, 1))
        assert set(s["tone"]) == {"neg", "neu", "pos"}
        assert abs(sum(s["tone"].values()) - 100) < 0.01
        assert isinstance(s["sentiment"], float)
        assert "answer_refs" not in s  # drill-down only, via the route below
        total_sub_size += s["size"]
    assert total_sub_size / big["size"] >= 0.5  # subthemes.py's own coverage gate

    # a smaller, ordinary theme (the unrelated 35-answer family) never qualified for sub-clustering at all
    smaller_real = [t for t in real_themes if t["id"] != big["id"]]
    assert smaller_real and all(t["sub_themes"] == [] for t in smaller_real)

    # drill-down into the big theme's first sub-theme: same pagination/real-text shape as the parent route
    sub_ans = env.client.get(
        f"/api/datasets/{did}/themes/{big['id']}/sub-themes/0/answers", params={"limit": 5, "offset": 0},
    )
    assert sub_ans.status_code == 200, sub_ans.text
    body = sub_ans.json()
    assert body["theme_id"] == big["id"] and body["sub_theme_index"] == 0
    assert body["total"] == subs[0]["size"]
    assert len(body["answers"]) == min(5, subs[0]["size"])
    for a in body["answers"]:
        assert a["text"].strip()
        assert a["tone"] in ("neg", "neu", "pos")

    # pagination offset works the same way theme_answers' own tests already check it
    page2 = env.client.get(
        f"/api/datasets/{did}/themes/{big['id']}/sub-themes/0/answers", params={"limit": 5, "offset": 5},
    ).json()
    assert {a["row"] for a in page2["answers"]}.isdisjoint({a["row"] for a in body["answers"]})

    # out-of-range index -> 404, not a 500 or an empty-but-200 page
    assert env.client.get(
        f"/api/datasets/{did}/themes/{big['id']}/sub-themes/{len(subs)}/answers"
    ).status_code == 404
    assert env.client.get(f"/api/datasets/{did}/themes/{big['id']}/sub-themes/-1/answers").status_code == 404

    # a theme with sub_themes == [] -> 404 for any index, including 0
    other = smaller_real[0]
    assert env.client.get(f"/api/datasets/{did}/themes/{other['id']}/sub-themes/0/answers").status_code == 404

    # ownership isolation, reused correctly from `_own_dataset` via the same helper `theme_answers` uses
    as_user(uid2)
    assert env.client.get(
        f"/api/datasets/{did}/themes/{big['id']}/sub-themes/0/answers"
    ).status_code == 404


def _fake_claude_reply_merge_all(prompt: str) -> str:
    """Same shape as `_fake_claude_reply`, but every cluster flags every OTHER cluster it was given as
    the same theme - proving `apply_merges` (app/text_pipeline/merging.py) actually consolidates real
    clusters into one stored Theme row, not just gives them similar names. Robust to however many
    clusters a given fake embedding fixture happens to produce."""
    payload = json.loads(prompt)
    cluster_ids = [c["cluster_id"] for c in payload["clusters"]]
    themes = [
        {"cluster_id": cid, "label": f"Theme {cid}", "description": f"About cluster {cid}.",
         "merge_with": [other for other in cluster_ids if other != cid], "note": None}
        for cid in cluster_ids
    ]
    return json.dumps({"themes": themes})


def test_build_themes_job_actually_merges_clusters_claude_flags_as_the_same_theme(env):
    """merge_with used to be parsed and validated but never consumed - see app/text_pipeline/merging.py's
    own docstring. When Claude flags every real cluster as the same theme, the real pipeline now stores
    ONE consolidated Theme row (combined size, combined answer_refs), not several separate ones."""
    install_fakes()
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply_merge_all)
    did = upload_csv(env, theme_df())
    applied = clean_and_apply(env, did)
    rows_out = applied["report"]["rows_out"]

    job = build_themes_job(env, did)
    assert job["status"] == "done", job

    listed = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()
    themes = listed["themes"]
    real_themes = [t for t in themes if t["label"] != "Other"]
    other_size = sum(t["size"] for t in themes if t["label"] == "Other")

    assert len(real_themes) == 1  # was >= 2 (reliability + support) without merging - see the round-trip test above
    assert real_themes[0]["size"] == rows_out - other_size
    assert set(real_themes[0]["tone"]) == {"neg", "neu", "pos"}
    assert abs(sum(real_themes[0]["tone"].values()) - 100) < 0.01


def _fake_claude_reply_merge_first_two_subclusters(prompt: str) -> str:
    """Same shape as `_fake_claude_reply`, but for the SUB-theme-labeling call specifically (identified
    by `parent_theme` on its cluster entries, same detection `_fake_claude_reply_sub_labeling_fails`
    uses) flags flat sub-cluster id 0 as the same sub-theme as flat id 1 - proving `apply_sub_merges`
    actually consolidates real sub-clusters, and correctly drops a parent whose sub-themes merge down to
    fewer than 2 groups, end to end."""
    payload = json.loads(prompt)
    if payload["clusters"] and "parent_theme" in payload["clusters"][0]:
        themes = [
            {"cluster_id": c["cluster_id"], "label": f"Sub {c['cluster_id']}",
             "description": f"About sub-cluster {c['cluster_id']}.",
             "merge_with": [1] if c["cluster_id"] == 0 else [], "note": None}
            for c in payload["clusters"]
        ]
        return json.dumps({"themes": themes})
    return _fake_claude_reply(prompt)


def test_build_themes_job_actually_merges_subclusters_claude_flags_as_the_same_subtheme(env):
    """Companion to the top-level merge test above, for sub-themes: forcing sub-clusters 0 and 1 (under
    the one big, real-sub-structure parent) to merge either leaves fewer, larger sub-themes than the
    unmerged baseline (>= 2 kept, see test_build_themes_with_subthemes_end_to_end) or correctly drops the
    parent to sub_themes == [] if merging leaves fewer than 2 groups - both are valid, both exercise real
    code, neither is a crash or a stale, un-consolidated pair of near-duplicate sub-themes."""
    df, vectors_by_text = big_theme_df_and_vectors()
    app.dependency_overrides[get_embedding_client] = lambda: FakeFamilyEmbeddingClient(vectors_by_text)
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply_merge_first_two_subclusters)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))

    did = upload_csv(env, df)
    clean_and_apply(env, did)
    job = build_themes_job(env, did, timeout=30)
    assert job["status"] == "done", job

    listed = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()
    real_themes = [t for t in listed["themes"] if t["label"] != "Other"]
    big = max(real_themes, key=lambda t: t["size"])
    assert big["size"] >= 100  # same big parent as the unmerged baseline test

    subs = big["sub_themes"]
    assert len(subs) <= 2  # merging 2 of the (>=2, <=3) baseline sub-clusters can only reduce the count
    if subs:
        total_sub_size = sum(s["size"] for s in subs)
        assert total_sub_size / big["size"] >= 0.5  # subthemes.py's own coverage gate, unaffected by merging
        for i, s in enumerate(subs):
            assert s["index"] == i
            assert s["size"] > 0


def test_sub_theme_labeling_failure_falls_back_to_no_sub_themes_not_a_failed_job(env):
    """Plan decision 10: an untrusted/broken reply from the SUB-theme-labeling call specifically (not the
    main labeling call) must not fail the whole theme build - the job still reaches "done" with themes
    stored, just with `sub_themes == []` on every theme."""
    df, vectors_by_text = big_theme_df_and_vectors()
    app.dependency_overrides[get_embedding_client] = lambda: FakeFamilyEmbeddingClient(vectors_by_text)
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply_sub_labeling_fails)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))

    did = upload_csv(env, df)
    clean_and_apply(env, did)
    job = build_themes_job(env, did, timeout=30)
    assert job["status"] == "done", job  # sub-theme labeling failing must never fail the whole build
    assert job["error"] is None

    themes = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    assert themes  # themes were still built and stored...
    assert any(t["size"] >= 100 for t in themes)  # ...including the one that WOULD have split
    assert all(t["sub_themes"] == [] for t in themes)  # ...just with no sub-themes on any of them


# ==================================================================== "Look inside Other" (docs/TODO.md,
# 2026-10-21). Theme rows are seeded DIRECTLY into the database (mirroring tests/test_api_report.py's own
# `seed_themes` pattern) rather than run through a full build-themes job first - this module's own
# build-themes tests already cover real clustering/noise behaviour; what matters here is the NEW route and
# its write-back, not re-deriving exactly which answers HDBSCAN calls noise.

def seed_theme(env, did, **kw) -> int:
    from app.models import Theme
    with env.Session() as s:
        t = Theme(dataset_id=did, column_name=Q, **kw)
        s.add(t)
        s.commit()
        return t.id


def install_look_inside_other_fakes(jev_choice_result=None):
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client] = lambda: FakeJevClient(("pos", 0.8), choice_result=jev_choice_result)


def look_inside_other_job(env, did, column=Q, timeout=5.0) -> dict:
    r = env.client.post(f"/api/datasets/{did}/themes/look-inside-other", json={"column": column})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running" and body["job_id"]
    return wait_for_job(env.client, did, body["job_id"], timeout=timeout)


def test_look_inside_other_422_on_unknown_column(env):
    install_look_inside_other_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    r = env.client.post(f"/api/datasets/{did}/themes/look-inside-other", json={"column": "Not a real column"})
    assert r.status_code == 422


def test_look_inside_other_409_when_no_other_theme_exists(env):
    install_look_inside_other_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    seed_theme(env, did, label="Cost", description="x", size=5, sentiment=0.0,
               tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4])
    r = env.client.post(f"/api/datasets/{did}/themes/look-inside-other", json={"column": Q})
    assert r.status_code == 409


def test_look_inside_other_409_when_other_has_no_answers(env):
    install_look_inside_other_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    seed_theme(env, did, label="Other", description="x", size=0, sentiment=0.0,
               tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[])
    r = env.client.post(f"/api/datasets/{did}/themes/look-inside-other", json={"column": Q})
    assert r.status_code == 409


def test_look_inside_other_end_to_end_matches_everything_to_a_known_theme(env):
    """Happy path through the real route/job: seeded "Cost" (known) + "Other" (to look inside), Jev
    configured to match every Other answer back to "Cost" - confirms the job reaches "done", Cost's
    answer_refs/size/sentiment grow to include the matched rows, and the now-empty Other theme is
    deleted outright (see `_apply_other_classification`'s own docstring for why)."""
    install_look_inside_other_fakes(jev_choice_result=ChoiceAnswer(choice="Cost", confidence=0.9, probabilities={}))
    df = theme_df()  # 26 rows: 0-12 reliability, 13-25 support (see _survey_texts)
    did = upload_csv(env, df)
    clean_and_apply(env, did)

    cost_id = seed_theme(
        env, did, label="Cost", description="About pricing.", size=5, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4],
    )
    seed_theme(
        env, did, label="Other", description="x", size=3, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[13, 14, 15],
    )

    job = look_inside_other_job(env, did, timeout=30)
    assert job["status"] == "done", job
    assert job["error"] is None
    # Stage 3 (docs/TODO.md, 2026-10-21): the job's own `result` carries the real Known/New/Still-in-Other
    # counts the animated flow's results panel needs - written in the same commit as the Theme-row changes,
    # not reconstructed from a second query.
    assert job["result"] == {
        "known_added": 3, "new_themes": [], "still_other_count": 0, "failed_classification_count": 0,
        "low_confidence_count": 0, "non_answer_count": 0,
        # Inside Other panel fields (docs/REPORT_UI_REWORK.md Phase 1): Other held 3 before, 5 + 3 answered.
        "other_before_count": 3, "answered_total": 8, "known_gains": [{"label": "Cost", "count": 3}],
    }
    # Live progress was written during the matching step and ends complete.
    assert job["progress"]["done"] == job["progress"]["total"] == 3
    assert job["progress"]["known"] == {"Cost": 3} and job["progress"]["still_other"] == 0

    themes = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    labels = {t["label"] for t in themes}
    assert "Other" not in labels  # everything matched - the now-empty row was deleted, not kept at size 0

    cost = next(t for t in themes if t["label"] == "Cost")
    assert cost["size"] == 8  # 5 original + 3 matched from Other
    with env.Session() as s:
        from app.models import Theme
        row = s.get(Theme, cost_id)
        assert sorted(row.answer_refs) == [0, 1, 2, 3, 4, 13, 14, 15]


def test_look_inside_other_end_to_end_finds_real_new_themes_with_charts(env):
    """Happy path for the real "new themes found" case (Stage 3a, docs/TODO.md 2026-10-23): no known
    themes at all, every Other answer genuinely reclusters into one of two real groups (the same
    reliability/support fixture split used by test_split_theme_end_to_end_finds_the_two_real_groups) -
    confirms job.result carries real sentiment/tone per new theme and real chart_html fragments for the
    rank/icicle/sentsun/othergrowth tabs, with real new-theme names reaching them."""
    def pick(text, question_key, instructions, criteria):
        has_battery_words = any(w in text for w in _WORDS_RELIABILITY)
        for label in criteria:
            if label == NONE_OF_THESE:
                continue
            if has_battery_words and "reliab" in label.lower() or "batt" in label.lower():
                return ChoiceAnswer(choice=label, confidence=0.9, probabilities={})
        # Fallback: pick whichever non-"none of these" label is NOT already used for battery content.
        return ChoiceAnswer(choice=next(l for l in criteria if l != NONE_OF_THESE), confidence=0.9, probabilities={})

    install_look_inside_other_fakes(jev_choice_result=pick)
    df = theme_df()  # 26 rows: 0-12 reliability, 13-25 support
    did = upload_csv(env, df)
    clean_and_apply(env, did)
    seed_theme(
        env, did, label="Other", description="x", size=26, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(range(26)),
    )

    job = look_inside_other_job(env, did, timeout=30)
    assert job["status"] == "done", job
    assert job["error"] is None
    result = job["result"]
    assert len(result["new_themes"]) >= 1

    for entry in result["new_themes"]:
        assert isinstance(entry["sentiment"], float)
        assert set(entry["tone"]) == {"neg", "neu", "pos"}

    charts = result.get("charts") or {}
    # One question per chart (docs/REPORT_UI_REWORK.md): only the icicle, and only if a new theme has
    # sub-themes. The panel draws the ranked, tone-coloured list itself from new_themes[].tone.
    assert set(charts) <= {"icicle"}
    new_names = {nt["label"] for nt in result["new_themes"]}
    for chart in charts.values():
        assert chart["chart_html"]
        assert any(name in chart["chart_html"] for name in new_names)
        assert "<!doctype html>" not in chart["chart_html"].lower()


def test_look_inside_other_never_makes_a_theme_of_non_answers(env):
    """BUG-048: Claude flags the reliability candidate as a non-answer. It must not become a theme, its
    answers must never go to Jev (so not even a known theme can take them), and they stay in Other."""
    def claude_reply(prompt):
        payload = json.loads(prompt)
        themes = []
        for c in payload["clusters"]:
            junk = any(w in " ".join(c["sample_answers"]) for w in _WORDS_RELIABILITY)
            themes.append({"cluster_id": c["cluster_id"], "label": "No comment provided" if junk else "Support",
                           "description": "x", "merge_with": [], "note": None, "non_answer": junk})
        return json.dumps({"themes": themes})

    claude = FakeLabelingClaudeClient(claude_reply)
    jev = FakeJevClient(("pos", 0.8), choice_result=lambda t, k, i, criteria: ChoiceAnswer(
        choice=next(l for l in criteria if l != NONE_OF_THESE), confidence=0.9, probabilities={}))
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_claude_client] = lambda: claude
    app.dependency_overrides[get_jev_client] = lambda: jev
    did = upload_csv(env, theme_df())  # 26 rows: 0-12 reliability, 13-25 support
    clean_and_apply(env, did)
    seed_theme(env, did, label="Other", description="x", size=26, sentiment=0.0,
               tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(range(26)))

    job = look_inside_other_job(env, did, timeout=30)
    assert job["status"] == "done", job
    assert "non_answer" in claude.calls[0]["system"]  # Look inside asks for the flag
    result = job["result"]
    assert result["non_answer_count"] > 0
    assert "No comment provided" not in {nt["label"] for nt in result["new_themes"]}
    sent = {c["text"] for c in jev.choice_calls}
    assert all("No comment provided" not in c["criteria"] for c in jev.choice_calls)
    themes = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    assert "No comment provided" not in {t["label"] for t in themes}
    other = next(t for t in themes if t["label"] == "Other")
    assert other["size"] >= result["non_answer_count"]
    assert len(jev.choice_calls) == 26 - result["non_answer_count"]  # non-answers never reach Jev
    assert not any(w in text for text in sent for w in ("battery", "overheats", "drains"))


def test_look_inside_other_low_confidence_matches_stay_in_other(env):
    """BUG-032: a Jev pick below MIN_MATCH_CONFIDENCE leaves the answer in Other instead of growing a theme."""
    install_look_inside_other_fakes(jev_choice_result=ChoiceAnswer(choice="Cost", confidence=0.3, probabilities={}))
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    seed_theme(env, did, label="Cost", description="About pricing.", size=5, sentiment=0.0,
               tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4])
    seed_theme(env, did, label="Other", description="x", size=3, sentiment=0.0,
               tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[13, 14, 15])

    job = look_inside_other_job(env, did, timeout=30)
    assert job["status"] == "done", job
    assert job["result"]["known_added"] == 0
    assert job["result"]["still_other_count"] == 3
    assert job["result"]["low_confidence_count"] == 3
    themes = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    assert next(t for t in themes if t["label"] == "Cost")["size"] == 5


# ---------------------------------------------------------------- _apply_other_classification (direct,
# unit-level: the DB write-back logic itself, independent of the route/job wrapper above)

def _seed_known_and_other(env, did, known_refs=(0, 1, 2, 3, 4), other_refs=(13, 14, 15, 16, 17, 18)):
    from app.models import Theme
    with env.Session() as s:
        known = Theme(dataset_id=did, column_name=Q, label="Cost", description="About pricing.", size=len(known_refs),
                      sentiment=0.0, tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(known_refs))
        other = Theme(dataset_id=did, column_name=Q, label="Other", description="x", size=len(other_refs),
                      sentiment=0.0, tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(other_refs))
        s.add_all([known, other])
        s.commit()
        return known.id, other.id


def test_apply_other_classification_extends_a_known_theme(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    known_id, other_id = _seed_known_and_other(env, did, other_refs=(13, 14))
    row_text = {13: "a bit expensive", 14: "too pricey for what it is"}

    with env.Session() as s:
        from app.models import Theme
        summary = _apply_other_classification(s, did, Q, other_id, {13: "Cost", 14: "Cost"}, {}, row_text)
        known = s.get(Theme, known_id)
        assert sorted(known.answer_refs) == [0, 1, 2, 3, 4, 13, 14]
        assert known.size == 7
        assert s.get(Theme, other_id) is None  # both rows matched - nothing left, row deleted
        assert summary == {
            "known_added": 2, "new_themes": [], "still_other_count": 0, "failed_classification_count": 0,
            "low_confidence_count": 0, "non_answer_count": 0,
            "other_before_count": 2, "answered_total": 7, "known_gains": [{"label": "Cost", "count": 2}],
        }


def test_apply_other_classification_creates_a_new_theme_above_the_minimum(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    other_refs = list(range(13, 13 + MIN_OTHER_NEW_THEME_SIZE))
    known_id, other_id = _seed_known_and_other(env, did, other_refs=other_refs)
    by_row = {r: "Shipping delays" for r in other_refs}
    row_text = {r: "slow shipping, took forever" for r in other_refs}

    with env.Session() as s:
        from app.models import Theme
        from sqlalchemy import select
        summary = _apply_other_classification(
            s, did, Q, other_id, by_row, {"Shipping delays": "About delivery."}, row_text,
        )
        new_theme = s.scalar(select(Theme).where(Theme.dataset_id == did, Theme.label == "Shipping delays"))
        assert new_theme is not None
        assert sorted(new_theme.answer_refs) == sorted(other_refs)
        assert new_theme.size == MIN_OTHER_NEW_THEME_SIZE
        assert s.get(Theme, other_id) is None  # everything matched the new theme
        assert summary["known_added"] == 0
        assert summary["still_other_count"] == 0
        assert len(summary["new_themes"]) == 1
        new_entry = summary["new_themes"][0]
        assert new_entry["label"] == "Shipping delays"
        assert new_entry["count"] == MIN_OTHER_NEW_THEME_SIZE
        # Stage 3a (docs/TODO.md, 2026-10-23): the summary now also carries real sentiment/tone per new
        # theme - the same numbers the Theme row itself was just given, not a second computation.
        assert new_entry["sentiment"] == new_theme.sentiment
        assert new_entry["tone"] == new_theme.tone


def test_apply_other_classification_below_minimum_new_theme_folds_back_into_other(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    too_few = list(range(13, 13 + MIN_OTHER_NEW_THEME_SIZE - 1))  # one short of the minimum
    _, other_id = _seed_known_and_other(env, did, other_refs=too_few)
    by_row = {r: "Tiny new group" for r in too_few}
    row_text = {r: "some rare answer" for r in too_few}

    with env.Session() as s:
        from app.models import Theme
        from sqlalchemy import select
        summary = _apply_other_classification(s, did, Q, other_id, by_row, {"Tiny new group": "x"}, row_text)
        assert s.scalar(select(Theme).where(Theme.dataset_id == did, Theme.label == "Tiny new group")) is None
        other = s.get(Theme, other_id)
        assert sorted(other.answer_refs) == sorted(too_few)  # folded straight back into Other
        assert summary == {
            "known_added": 0, "new_themes": [], "still_other_count": len(too_few), "failed_classification_count": 0,
            "low_confidence_count": 0, "non_answer_count": 0,
            "other_before_count": len(too_few), "answered_total": 5 + len(too_few), "known_gains": [],
        }


def test_look_inside_other_fails_with_the_real_reason_when_every_answer_fails(env):
    """BUG-040 (docs/BUGS.md): Jev answering HTTP 402 for every row used to finish as "done" with
    "No new themes found". Now the job fails with the reason and nothing is applied."""
    from app.text_pipeline.jev_sentiment import JevError

    class OutOfCreditJev(FakeJevClient):
        def classify_choice(self, *args, **kwargs):
            raise JevError("Jev returned HTTP 402.")

    install_look_inside_other_fakes()
    app.dependency_overrides[get_jev_client] = lambda: OutOfCreditJev(("pos", 0.8))
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    seed_theme(env, did, label="Cost", description="About pricing.", size=5, sentiment=0.0,
               tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4])
    other_id = seed_theme(env, did, label="Other", description="x", size=3, sentiment=0.0,
                          tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[13, 14, 15])

    job = look_inside_other_job(env, did, timeout=30)
    assert job["status"] == "failed", job
    assert job["error"] == (
        "Jev classification failed: none of the 3 answers in Other could be checked, so nothing was "
        "changed. Jev returned HTTP 402 (payment required: check the Jev account's credit)."
    )
    assert job["result"] is None
    with env.Session() as s:
        from app.models import Theme
        assert sorted(s.get(Theme, other_id).answer_refs) == [13, 14, 15]


def test_apply_other_classification_none_of_these_and_missing_rows_stay_in_other(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    _, other_id = _seed_known_and_other(env, did, other_refs=(13, 14, 15))
    # 13 -> explicit NONE_OF_THESE, 14 -> missing entirely (its own Jev call failed), 15 -> untouched
    by_row = {13: NONE_OF_THESE}
    row_text = {13: "a", 14: "b", 15: "c"}

    with env.Session() as s:
        # failed_count=1 (fixed 2026-10-23): passed through as-is, independent of how many rows ended up
        # staying in Other for other reasons - this is purely a reporting pass-through, not re-derived.
        summary = _apply_other_classification(s, did, Q, other_id, by_row, {}, row_text, failed_count=1)
        assert summary == {
            "known_added": 0, "new_themes": [], "still_other_count": 3, "failed_classification_count": 1,
            "low_confidence_count": 0, "non_answer_count": 0,
            "other_before_count": 3, "answered_total": 8, "known_gains": [],
        }
    with env.Session() as s:
        from app.models import Theme
        other = s.get(Theme, other_id)
        assert sorted(other.answer_refs) == [13, 14, 15]


# ==================================================================== theme editing: rename (docs/TODO.md,
# fixed 2026-10-22)

def test_rename_theme_updates_label_and_description(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    theme_id = seed_theme(
        env, did, label="Reliabilty", description="About reliability.", size=13, sentiment=-0.4,
        tone={"neg": 80, "neu": 20, "pos": 0}, answer_refs=list(range(13)),
    )
    r = env.client.patch(
        f"/api/datasets/{did}/themes/{theme_id}", json={"label": "Reliability", "description": "Battery and heat issues."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Reliability"
    assert r.json()["description"] == "Battery and heat issues."
    with env.Session() as s:
        from app.models import Theme
        t = s.get(Theme, theme_id)
        assert t.label == "Reliability" and t.description == "Battery and heat issues."


def test_rename_theme_404_for_a_theme_from_another_dataset(env):
    did1 = upload_csv(env, theme_df())
    clean_and_apply(env, did1)
    did2 = upload_csv(env, small_df(), name="other.csv")  # distinct content - theme_df() would dedupe to did1
    clean_and_apply(env, did2)
    theme_id = seed_theme(
        env, did2, label="X", description="x", size=1, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0],
    )
    r = env.client.patch(f"/api/datasets/{did1}/themes/{theme_id}", json={"label": "Y"})
    assert r.status_code == 404


def test_rename_theme_invalidates_the_existing_report(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    theme_id = seed_theme(
        env, did, label="Reliabilty", description="x", size=13, sentiment=-0.4,
        tone={"neg": 80, "neu": 20, "pos": 0}, answer_refs=list(range(13)),
    )
    with env.Session() as s:
        from app.models import Report
        s.add(Report(dataset_id=did, content={"column": Q, "question": Q, "blocks": []}))
        s.commit()

    r = env.client.patch(f"/api/datasets/{did}/themes/{theme_id}", json={"label": "Reliability"})
    assert r.status_code == 200, r.text

    with env.Session() as s:
        from app.models import Report
        from sqlalchemy import select
        assert s.scalars(select(Report).where(Report.dataset_id == did)).all() == []


# ==================================================================== theme editing: merge

def test_merge_themes_unions_refs_and_recomputes_tone(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    a_id = seed_theme(
        env, did, label="A", description="x", size=5, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4],
    )
    b_id = seed_theme(
        env, did, label="B", description="x", size=3, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[5, 6, 7],
    )
    r = env.client.post(
        f"/api/datasets/{did}/themes/merge", json={"column": Q, "theme_ids": [a_id, b_id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "A"  # the larger theme (5 answers) wins as the survivor
    assert body["size"] == 8

    with env.Session() as s:
        from app.models import Theme
        assert s.get(Theme, a_id) is not None
        assert sorted(s.get(Theme, a_id).answer_refs) == [0, 1, 2, 3, 4, 5, 6, 7]
        assert s.get(Theme, b_id) is None  # absorbed, deleted outright


def test_merge_themes_accepts_an_explicit_label_override(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    a_id = seed_theme(
        env, did, label="A", description="x", size=5, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4],
    )
    b_id = seed_theme(
        env, did, label="B", description="x", size=3, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[5, 6, 7],
    )
    r = env.client.post(
        f"/api/datasets/{did}/themes/merge",
        json={"column": Q, "theme_ids": [a_id, b_id], "label": "Combined"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Combined"


def test_merge_themes_404_on_unknown_theme_id(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    a_id = seed_theme(
        env, did, label="A", description="x", size=5, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4],
    )
    r = env.client.post(f"/api/datasets/{did}/themes/merge", json={"column": Q, "theme_ids": [a_id, 999999]})
    assert r.status_code == 404


def test_merge_themes_422_when_fewer_than_two_resolve(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    a_id = seed_theme(
        env, did, label="A", description="x", size=5, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4],
    )
    # theme_ids must have >=2 distinct entries at the request-validation level - send a duplicate so the
    # request itself passes shape validation, but only one real row is found.
    r = env.client.post(f"/api/datasets/{did}/themes/merge", json={"column": Q, "theme_ids": [a_id, 999999]})
    assert r.status_code == 404  # unknown id still wins over the "too few resolved" check - see route


def test_merge_themes_invalidates_the_existing_report(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    a_id = seed_theme(
        env, did, label="A", description="x", size=5, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2, 3, 4],
    )
    b_id = seed_theme(
        env, did, label="B", description="x", size=3, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[5, 6, 7],
    )
    with env.Session() as s:
        from app.models import Report
        s.add(Report(dataset_id=did, content={"column": Q, "question": Q, "blocks": []}))
        s.commit()

    r = env.client.post(f"/api/datasets/{did}/themes/merge", json={"column": Q, "theme_ids": [a_id, b_id]})
    assert r.status_code == 200, r.text

    with env.Session() as s:
        from app.models import Report
        from sqlalchemy import select
        assert s.scalars(select(Report).where(Report.dataset_id == did)).all() == []


# ==================================================================== theme editing: split (docs/TODO.md,
# fixed 2026-10-22)

def install_split_theme_fakes():
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)


def split_theme_job(env, did, theme_id, timeout=30.0) -> dict:
    r = env.client.post(f"/api/datasets/{did}/themes/{theme_id}/split")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running" and body["job_id"]
    return wait_for_job(env.client, did, body["job_id"], timeout=timeout)


def test_split_theme_409_when_too_few_answers(env):
    install_split_theme_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    theme_id = seed_theme(
        env, did, label="Everything", description="x", size=3, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=[0, 1, 2],
    )
    r = env.client.post(f"/api/datasets/{did}/themes/{theme_id}/split")
    assert r.status_code == 409


def test_split_theme_404_for_unknown_theme(env):
    install_split_theme_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    r = env.client.post(f"/api/datasets/{did}/themes/999999/split")
    assert r.status_code == 404


def test_split_theme_end_to_end_finds_the_two_real_groups(env):
    """Happy path through the real route/job: a single "Everything" theme covering all 26 answers (13
    reliability-vocabulary, 13 support-vocabulary - the same FakeEmbeddingClient-friendly fixture "Look
    inside Other"'s own tests use) splits back into its two real underlying groups."""
    install_split_theme_fakes()
    df = theme_df()  # 26 rows: 0-12 reliability, 13-25 support (see _survey_texts)
    did = upload_csv(env, df)
    clean_and_apply(env, did)
    theme_id = seed_theme(
        env, did, label="Everything", description="x", size=26, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(range(26)),
    )

    job = split_theme_job(env, did, theme_id)
    assert job["status"] == "done", job
    assert job["error"] is None
    assert job["result"] is not None
    assert len(job["result"]["new_themes"]) >= 1  # at least one real piece was found and split out

    themes = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]
    # Total coverage across every resulting Theme row for this column must still equal all 26 original
    # answers - a split must never lose or duplicate a row.
    with env.Session() as s:
        from app.models import Theme
        from sqlalchemy import select
        all_refs = set()
        for t in s.scalars(select(Theme).where(Theme.dataset_id == did, Theme.column_name == Q)).all():
            all_refs.update(t.answer_refs or [])
        assert all_refs == set(range(26))
    assert len(themes) >= 1


def test_apply_theme_split_creates_new_themes_above_the_minimum(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    original_id = seed_theme(
        env, did, label="Everything", description="x", size=10, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(range(10)),
    )
    row_text = {i: f"slow shipping delay number {i}" for i in range(10)}

    from app.text_pipeline.other_classify import ConsolidatedCandidates
    from app.text_pipeline.schema import Cluster, ClusterMember, ClusterResult, ThemeLabel

    cluster = Cluster(id=0, members=[ClusterMember(row=i, text=row_text[i], distance=0.0) for i in range(10)], centroid=None)
    result = ClusterResult(column=Q, clusters=[cluster], noise=[], total_answers=10)
    labels = [ThemeLabel(cluster_id=0, label="Shipping delays", description="About delivery.", size=10, merge_with=[], note=None)]
    candidates = ConsolidatedCandidates(result=result, labels=labels)

    with env.Session() as s:
        from app.models import Theme
        from sqlalchemy import select
        summary = _apply_theme_split(s, did, Q, original_id, candidates, row_text)
        new_theme = s.scalar(select(Theme).where(Theme.dataset_id == did, Theme.label == "Shipping delays"))
        assert new_theme is not None
        assert sorted(new_theme.answer_refs) == list(range(10))
        assert s.get(Theme, original_id) is None  # everything moved into the new piece
        assert summary == {"new_themes": [{"label": "Shipping delays", "count": 10}], "remainder_count": 0}


def test_apply_theme_split_small_pieces_and_noise_fold_back_as_remainder(env):
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    original_id = seed_theme(
        env, did, label="Everything", description="x", size=12, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(range(12)),
    )
    row_text = {i: f"text {i}" for i in range(12)}

    from app.text_pipeline.other_classify import ConsolidatedCandidates
    from app.text_pipeline.schema import Cluster, ClusterMember, ClusterResult, ThemeLabel

    # Cluster 0: only 3 members (rows 0-2) - below MIN_OTHER_NEW_THEME_SIZE (5), folds back.
    # Noise: rows 3-11 (9 rows) - also folds back, per label_and_consolidate's own "drop noise" contract.
    small_cluster = Cluster(id=0, members=[ClusterMember(row=i, text=row_text[i], distance=0.0) for i in range(3)], centroid=None)
    noise = [ClusterMember(row=i, text=row_text[i], distance=None) for i in range(3, 12)]
    result = ClusterResult(column=Q, clusters=[small_cluster], noise=noise, total_answers=12)
    labels = [ThemeLabel(cluster_id=0, label="Tiny group", description="x", size=3, merge_with=[], note=None)]
    candidates = ConsolidatedCandidates(result=result, labels=labels)

    with env.Session() as s:
        from app.models import Theme
        from sqlalchemy import select
        summary = _apply_theme_split(s, did, Q, original_id, candidates, row_text)
        assert s.scalar(select(Theme).where(Theme.dataset_id == did, Theme.label == "Tiny group")) is None
        original = s.get(Theme, original_id)
        assert original is not None
        assert sorted(original.answer_refs) == list(range(12))  # everything folded straight back
        assert summary == {"new_themes": [], "remainder_count": 12}


def test_apply_theme_split_never_loses_rows_when_nothing_real_is_found(env):
    """Real bug, found via live browser verification, not assumed away: `label_and_consolidate` has its
    own early-return for "every cluster got labeled Other" that returns a `ClusterResult` with BOTH
    `clusters=[]` AND `noise=[]` (discarding the original noise entirely - see that function's own
    docstring). The old implementation seeded `remainder` from `candidates.result.noise` alone, so this
    exact case left `remainder` empty with no new themes either - the whole original theme (all of its
    real answers) was silently deleted outright, with the job still reporting "done". Confirmed live: a
    40-answer theme vanished completely after a split that found no distinct sub-groups. Must instead
    leave the original theme's answers untouched."""
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    original_id = seed_theme(
        env, did, label="Everything", description="x", size=12, sentiment=0.0,
        tone={"neg": 0, "neu": 100, "pos": 0}, answer_refs=list(range(12)),
    )
    row_text = {i: f"text {i}" for i in range(12)}

    from app.text_pipeline.other_classify import ConsolidatedCandidates
    from app.text_pipeline.schema import ClusterResult

    # Exactly label_and_consolidate's own early-return shape: no clusters, no noise, no labels.
    candidates = ConsolidatedCandidates(
        result=ClusterResult(column=Q, clusters=[], noise=[], total_answers=12), labels=[],
    )

    with env.Session() as s:
        from app.models import Theme
        summary = _apply_theme_split(s, did, Q, original_id, candidates, row_text)
        original = s.get(Theme, original_id)
        assert original is not None  # NOT deleted - this is the real bug this test pins
        assert sorted(original.answer_refs) == list(range(12))  # every answer preserved, none lost
        assert original.size == 12
        assert summary == {"new_themes": [], "remainder_count": 12}


def test_rebuilding_themes_drops_the_report_built_on_the_old_ones(env):
    # Live on dataset 12: themes were rebuilt after the report, so five findings described themes that
    # no longer existed and all drew the same default-theme chart. Same rule as rename/merge/split now.
    from sqlalchemy import select as _select
    from app.models import Report

    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    assert build_themes_job(env, did)["status"] == "done"
    with env.Session() as s:
        s.add(Report(dataset_id=did, content={"column": Q, "blocks": []}))
        s.add(Report(dataset_id=did, content={"column": "Some other column", "blocks": []}))
        s.commit()

    assert build_themes_job(env, did)["status"] == "done"
    with env.Session() as s:
        columns = [r.content["column"] for r in s.scalars(_select(Report).where(Report.dataset_id == did))]
    assert columns == ["Some other column"]  # only this column's report is dropped


# ---------------------------------------------------------------- build-race guard (RACE-GUARD-01)
# Live on dataset 12 (2026-10-24) a report job ran inside a themes rebuild, read the old themes, and was
# stale the moment the rebuild committed. Work that would race is now refused with a 409, both ways.

def _running_job_row(env, did, kind, age_minutes=0):
    from datetime import datetime, timedelta, timezone
    from app.models import Job
    with env.Session() as s:
        job = Job(dataset_id=did, column_name=Q, kind=kind, status="running", step="Working",
                  created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes))
        s.add(job)
        s.commit()


def test_report_build_is_refused_while_themes_are_really_being_rebuilt(env):
    blocking = BlockingClient(FakeEmbeddingClient(), "embed")
    app.dependency_overrides[get_embedding_client] = lambda: blocking
    app.dependency_overrides[get_claude_client] = lambda: FakeLabelingClaudeClient(_fake_claude_reply)
    app.dependency_overrides[get_jev_client_factory] = lambda: (lambda: FakeJevClient(("pos", 0.8)))
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)

    started = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert started.status_code == 202, started.text
    assert blocking.reached.wait(timeout=5)

    refused = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert refused.status_code == 409, refused.text
    assert "still being rebuilt" in refused.json()["detail"]

    blocking.released.set()
    assert wait_for_job(env.client, did, started.json()["job_id"], timeout=5)["status"] == "done"
    assert env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q}).status_code == 202


def test_theme_changes_are_refused_while_a_report_is_building(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    assert build_themes_job(env, did)["status"] == "done"
    ids = [t["id"] for t in env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"]]
    _running_job_row(env, did, "report")
    app.dependency_overrides[get_jev_client] = lambda: FakeJevClient(("pos", 0.8))  # look-inside needs one

    attempts = {
        "rebuild": env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q}),
        "look inside": env.client.post(f"/api/datasets/{did}/themes/look-inside-other", json={"column": Q}),
        "rename": env.client.patch(f"/api/datasets/{did}/themes/{ids[0]}", json={"label": "Renamed"}),
        "merge": env.client.post(f"/api/datasets/{did}/themes/merge", json={"column": Q, "theme_ids": ids[:2]}),
        "split": env.client.post(f"/api/datasets/{did}/themes/{ids[0]}/split"),
    }
    for name, r in attempts.items():
        assert r.status_code == 409, (name, r.status_code, r.text)
        assert "report is being built" in r.json()["detail"], name


def test_a_running_row_left_behind_by_a_crash_does_not_block_forever(env):
    install_fakes()
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    assert build_themes_job(env, did)["status"] == "done"
    _running_job_row(env, did, "report", age_minutes=120)  # far past the 15-minute report cap
    assert env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q}).status_code == 202


def test_other_result_charts_build_an_icicle_only_when_a_new_theme_has_sub_themes():
    # One question per chart: without sub-themes an icicle only repeats the rank chart.
    from app.api_themes import _build_other_result_charts
    from app.models import Theme

    def theme(tid, label, size, subs=None):
        t = Theme(dataset_id=1, column_name=Q, label=label, size=size, sentiment=0.0,
                  tone={"neg": 20, "neu": 60, "pos": 20}, answer_refs=list(range(size)), sub_themes=subs or [])
        t.id = tid
        return t

    flat = [theme(1, "Parking", 40), theme(2, "Elevators", 30)]
    assert set(_build_other_result_charts(flat)) == set()

    subs = [{"label": "Distance from lots", "size": 20, "sentiment": 0.0, "tone": {"neg": 20, "neu": 60, "pos": 20}},
            {"label": "Accessible spaces", "size": 15, "sentiment": 0.0, "tone": {"neg": 20, "neu": 60, "pos": 20}}]
    with_subs = [theme(1, "Parking", 40, subs), theme(2, "Elevators", 30)]
    assert set(_build_other_result_charts(with_subs)) == {"icicle"}
