"""Tests for `GET /api/jobs` - the dataset-wide jobs dashboard (docs/TODO.md, 2026-10-23), covering only
what `test_api_themes.py`'s own job tests don't: cross-dataset listing, ownership scoping, and the
`status` filter. The individual job lifecycle (create/poll/finish) is already covered there and in
`tests/test_api_report.py` - this file never starts a real job, it only lists rows already written
straight into the test database, since listing doesn't care how a `Job` row came to exist.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.models import Job
from tests.test_api_themes import as_user, env, make_users, upload_csv  # noqa: F401 (env is a fixture)

pytestmark = pytest.mark.usefixtures("env")


def _df() -> pd.DataFrame:
    return pd.DataFrame({"Comment": [f"answer {i}" for i in range(5)]})


def _add_job(env, dataset_id, *, column="Comment", kind="themes", status="running", step="Starting") -> int:
    with env.Session() as s:
        job = Job(dataset_id=dataset_id, column_name=column, kind=kind, status=status, step=step)
        s.add(job)
        s.commit()
        return job.id


def test_list_jobs_returns_newest_first_with_dataset_name(env):
    uid = make_users(env, "u1")[0]
    as_user(uid)
    did = upload_csv(env, _df())
    j1 = _add_job(env, did, step="first")
    j2 = _add_job(env, did, step="second")

    r = env.client.get("/api/jobs")
    assert r.status_code == 200, r.text
    jobs = r.json()
    ids = [j["id"] for j in jobs]
    assert ids.index(j2) < ids.index(j1)  # newest (higher id) first
    assert all(j["dataset_name"] for j in jobs)


def test_list_jobs_only_shows_the_caller_s_own_datasets(env):
    uid_a, uid_b = make_users(env, "owner", "someone-else")
    as_user(uid_a)
    did = upload_csv(env, _df())
    _add_job(env, did)

    as_user(uid_b)
    r = env.client.get("/api/jobs")
    assert r.status_code == 200, r.text
    assert r.json() == []  # owner's job never leaks to a different user


def test_list_jobs_status_filter(env):
    uid = make_users(env, "u1")[0]
    as_user(uid)
    did = upload_csv(env, _df())
    _add_job(env, did, status="running")
    done_id = _add_job(env, did, status="done", step="Done")

    r = env.client.get("/api/jobs", params={"status": "done"})
    assert r.status_code == 200, r.text
    jobs = r.json()
    assert {j["id"] for j in jobs} == {done_id}
    assert all(j["status"] == "done" for j in jobs)


def test_list_jobs_rejects_an_unknown_status(env):
    uid = make_users(env, "u1")[0]
    as_user(uid)
    r = env.client.get("/api/jobs", params={"status": "sideways"})
    assert r.status_code == 422, r.text


def test_list_jobs_timestamps_carry_an_explicit_utc_marker(env):
    # Fixed 2026-10-23: SQLite round-trips a naive datetime, which used to serialize without a 'Z'/offset
    # suffix - a client parsing it with plain `new Date(...)` then read it as local time, not UTC
    # (confirmed live: a job started seconds ago showed "11h ago" on the jobs dashboard).
    uid = make_users(env, "u1")[0]
    as_user(uid)
    did = upload_csv(env, _df())
    _add_job(env, did)

    r = env.client.get("/api/jobs")
    assert r.status_code == 200, r.text
    job = r.json()[0]
    for field in ("created_at", "updated_at"):
        value = job[field]
        assert value.endswith("+00:00") or value.endswith("Z"), f"{field}={value!r} has no UTC marker"


def test_list_jobs_respects_the_limit_param(env):
    uid = make_users(env, "u1")[0]
    as_user(uid)
    did = upload_csv(env, _df())
    for _ in range(5):
        _add_job(env, did)

    r = env.client.get("/api/jobs", params={"limit": 2})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2
