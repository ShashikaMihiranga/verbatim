"""Stream 6: build-themes API, now running as an async background job (see app/jobs.py). Fake embedding/
Claude/Jev clients only, no network."""
import json
import random
import shutil
import tempfile
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import app.db as db_module
from app.api_themes import _SLOTS, get_claude_client, get_embedding_client, get_jev_client_factory
from app.api_upload import current_user
from app.db import Base, get_db
from app.main import app
from app.text_pipeline import FakeEmbeddingClient, FakeJevClient
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
