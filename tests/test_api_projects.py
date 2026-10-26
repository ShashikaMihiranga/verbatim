"""Stream 9: the projects-list API. Fake embedding/Claude clients only, no real network anywhere - see
test_zero_network_is_ever_attempted below (mirrors tests/test_api_report.py's own socket-blocking guard).

Reuses this repo's existing test fixtures rather than duplicating them: `tests.test_api_themes.install_fakes`
(fake embedding + Claude-labelling + Jev clients, so `POST /api/datasets/{id}/themes/build` can run for
real) and `tests.test_api_report.install_fake_claude`/`survey_df` (a Claude fake that also speaks
`write_headline`'s "findings" prompt shape, and a small two-cluster survey dataframe), so the full
upload -> confirm columns -> clean -> build themes -> build report pipeline can be driven through the real
HTTP API in sequence, exactly like a real user would, rather than seeding rows directly.
"""
from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import app.db as db_module
from app.api_projects import router as projects_router  # noqa: F401 (import proves the module loads cleanly)
from app.api_upload import current_user
from app.db import Base, get_db
from app.main import app
from tests.job_test_support import wait_for_job
from tests.test_api_report import Q, install_fake_claude, survey_df
from tests.test_api_themes import install_fakes as install_theme_fakes


# ---------------------------------------------------------------- fixtures (mirrors tests/test_api_report.py)

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    # A real file-backed SQLite database, not `sqlite://` (in-memory) with a single shared `StaticPool`
    # connection - this file drives `build_themes`/`build_report` through the real HTTP API, both of which
    # now run their real work on a background thread; see tests/test_api_themes.py's own `env` fixture for
    # why a shared in-memory connection serialises that badly.
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    # The background job thread build_themes/build_report now start does not go through FastAPI's DI (it
    # is not a request) - it opens its own session via `app.db.SessionLocal()` at call time (see
    # app/jobs.py). Point that same module attribute at this test's own engine.
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


def install_fakes():
    """Both fake providers this pipeline needs: a fake embedding client (from api_themes' own test module)
    plus a Claude fake that speaks BOTH prompt shapes build-themes and build-report send (from
    api_report's own test module) - the latter installed second so it wins for `get_claude_client`."""
    install_theme_fakes()
    install_fake_claude()


def upload_csv(env, df, name="survey.csv"):
    data = df.to_csv(index=False).encode("utf-8")
    r = env.client.post("/api/upload", files={"file": (name, data, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def confirm_columns(env, did):
    prof = env.client.get(f"/api/datasets/{did}/profile").json()["profile"]
    cols = [{"position": c["position"], "name": c["name"], "kind": c["kind"], "off": False} for c in prof["columns"]]
    r = env.client.patch(f"/api/datasets/{did}/columns", json={"columns": cols, "question": Q})
    assert r.status_code == 200, r.text
    return r.json()


def clean_and_apply(env, did):
    r = env.client.post(f"/api/datasets/{did}/clean/plan")
    assert r.status_code == 200, r.text
    r2 = env.client.post(f"/api/datasets/{did}/clean/apply")
    assert r2.status_code == 200, r2.text
    return r2.json()


def build_themes(env, did):
    """Both build routes are now async (202 + a `Job` row) rather than synchronous - drive the real
    request-then-poll sequence a real client would, same as tests/test_api_themes.py's own helper."""
    r = env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q})
    assert r.status_code == 202, r.text
    body = r.json()
    job = wait_for_job(env.client, did, body["job_id"], timeout=5)
    assert job["status"] == "done", job
    return job


def build_report(env, did):
    r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert r.status_code == 202, r.text
    body = r.json()
    job = wait_for_job(env.client, did, body["job_id"], timeout=5)
    assert job["status"] == "done", job
    return job


def by_id(projects, did):
    return next(p for p in projects if p["id"] == did)


# ---------------------------------------------------------------- status progression

def test_status_advances_through_every_stage_in_order(env):
    install_fakes()
    did = upload_csv(env, survey_df())

    projects = env.client.get("/api/projects").json()
    assert len(projects) == 1
    p = by_id(projects, did)
    assert p["status"] == "uploaded"
    assert p["question"] is None  # nothing confirmed yet
    assert p["filename"] == "survey.csv"

    confirm_columns(env, did)
    p = by_id(env.client.get("/api/projects").json(), did)
    assert p["status"] == "columns confirmed"
    assert p["question"] == Q  # now comes from the confirmed profile

    clean_and_apply(env, did)
    p = by_id(env.client.get("/api/projects").json(), did)
    assert p["status"] == "cleaned"

    build_themes(env, did)
    p = by_id(env.client.get("/api/projects").json(), did)
    assert p["status"] == "themes built"

    build_report(env, did)
    p = by_id(env.client.get("/api/projects").json(), did)
    assert p["status"] == "report ready"
    assert p["row_count"] == 80


# ---------------------------------------------------------------- ownership isolation

def test_ownership_isolation(env):
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, survey_df())
    assert len(env.client.get("/api/projects").json()) == 1

    as_user(uid2)
    assert env.client.get("/api/projects").json() == []
    # user 2 cannot even see dataset 1 exists
    assert env.client.get(f"/api/datasets/{did}/profile").status_code == 404


# ---------------------------------------------------------------- newest-first ordering

def test_newest_first_ordering(env):
    install_fakes()
    first = upload_csv(env, survey_df(), name="first.csv")
    second = upload_csv(env, survey_df(n_reliability=61, n_support=21), name="second.csv")

    ids = [p["id"] for p in env.client.get("/api/projects").json()]
    assert ids == [second, first]


# ---------------------------------------------------------------- empty-list case

def test_empty_list_for_a_user_with_no_datasets(env):
    make_users(env, "clerk-lonely")
    as_user(make_users(env, "clerk-lonely-2")[0])
    assert env.client.get("/api/projects").json() == []


# ---------------------------------------------------------------- delete

def test_delete_removes_the_dataset_and_its_dependent_rows(env):
    install_fakes()
    did = upload_csv(env, survey_df())
    confirm_columns(env, did)
    clean_and_apply(env, did)
    build_themes(env, did)
    build_report(env, did)

    from sqlalchemy import select
    from app.models import Column, Dataset, Finding, Report, Theme

    r = env.client.delete(f"/api/datasets/{did}")
    assert r.status_code == 200, r.text

    with env.Session() as s:
        assert s.get(Dataset, did) is None
        assert s.scalars(select(Theme).where(Theme.dataset_id == did)).all() == []
        assert s.scalars(select(Report).where(Report.dataset_id == did)).all() == []
        assert s.scalars(select(Finding).where(Finding.dataset_id == did)).all() == []
        assert s.scalars(select(Column).where(Column.dataset_id == did)).all() == []

    assert env.client.get("/api/projects").json() == []
    assert env.client.get(f"/api/datasets/{did}/profile").status_code == 404


def test_delete_drops_stored_files_unless_another_dataset_shares_them(env):
    from app.models import CleanedFile, Dataset, UploadedFile
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-a", "clerk-b")
    as_user(uid1)
    d1 = upload_csv(env, survey_df())
    confirm_columns(env, d1)
    clean_hash = clean_and_apply(env, d1)["clean_hash"]
    as_user(uid2)
    d2 = upload_csv(env, survey_df())  # same bytes: shares d1's UploadedFile row
    with env.Session() as s:
        file_hash = s.get(Dataset, d1).file_hash

    as_user(uid1)
    assert env.client.delete(f"/api/datasets/{d1}").status_code == 200
    with env.Session() as s:
        assert s.get(UploadedFile, file_hash) is not None  # user 2 still needs it
        assert s.get(CleanedFile, clean_hash) is None

    as_user(uid2)
    assert env.client.delete(f"/api/datasets/{d2}").status_code == 200
    with env.Session() as s:
        assert s.get(UploadedFile, file_hash) is None


def test_delete_is_owner_only(env):
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-a", "clerk-b")
    as_user(uid1)
    did = upload_csv(env, survey_df())

    as_user(uid2)
    assert env.client.delete(f"/api/datasets/{did}").status_code == 404

    as_user(uid1)
    assert env.client.get(f"/api/datasets/{did}/profile").status_code == 200  # untouched


# ---------------------------------------------------------------- no real network

class _NoSockets:
    """Mirrors tests/test_api_report.py's own socket-blocking guard."""

    def __enter__(self):
        self._orig = socket.socket

        def _guarded(family=socket.AF_INET, *a, **k):
            if family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("a real network socket was opened - network access is not allowed here")
            return self._orig(family, *a, **k)

        socket.socket = _guarded
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig


def test_zero_network_is_ever_attempted(env):
    install_fakes()
    did = upload_csv(env, survey_df())
    confirm_columns(env, did)
    clean_and_apply(env, did)
    build_themes(env, did)
    build_report(env, did)

    with _NoSockets():
        r = env.client.get("/api/projects")
        assert r.status_code == 200, r.text
        d = env.client.delete(f"/api/datasets/{did}")
        assert d.status_code == 200, d.text
