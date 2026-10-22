"""Sharing/roles API (docs/TODO.md, fixed 2026-10-22). Reuses test_api_themes.py's own `env` fixture and
multi-user helpers (`as_user`/`make_users`) - pytest resolves an imported fixture function by name the
same as one defined locally, and this repo already has precedent for importing test helpers across files
(see test_api_projects.py's own `from tests.test_api_themes import install_fakes`)."""
from __future__ import annotations

from sqlalchemy import select

from app.api_upload import current_user
from app.main import app
from tests.job_test_support import wait_for_job
from tests.test_api_themes import (
    Q,
    as_user,
    build_themes_job,
    clean_and_apply,
    env,
    install_fakes,
    make_users,
    theme_df,
    upload_csv,
)


def _build_report(env, did, timeout=10.0):
    r = env.client.post(f"/api/datasets/{did}/report/build", json={"column": Q})
    assert r.status_code == 202, r.text
    return wait_for_job(env.client, did, r.json()["job_id"], timeout=timeout)


# ---------------------------------------------------------------- editor invite links

def test_create_invite_link_is_owner_only(env):
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    assert env.client.post(f"/api/datasets/{did}/invite-links").status_code == 201

    as_user(uid2)
    assert env.client.post(f"/api/datasets/{did}/invite-links").status_code == 404


def test_accept_invite_link_grants_editor_access(env):
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    token = env.client.post(f"/api/datasets/{did}/invite-links").json()["token"]

    as_user(uid2)
    # Before accepting: no access at all.
    assert env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).status_code == 404

    r = env.client.post(f"/api/invite-links/{token}/accept")
    assert r.status_code == 200, r.text
    assert r.json() == {"dataset_id": did, "role": "editor"}

    # After accepting: editor can both read AND write (build themes).
    job = build_themes_job(env, did)
    assert job["status"] == "done", job


def test_accept_invite_link_is_idempotent(env):
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    token = env.client.post(f"/api/datasets/{did}/invite-links").json()["token"]

    as_user(uid2)
    first = env.client.post(f"/api/invite-links/{token}/accept")
    second = env.client.post(f"/api/invite-links/{token}/accept")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()

    with env.Session() as s:
        from app.models import DatasetCollaborator
        rows = s.scalars(select(DatasetCollaborator).where(DatasetCollaborator.dataset_id == did)).all()
        assert len(rows) == 1  # not duplicated by accepting twice


def test_accept_invite_link_404_for_an_unknown_token(env):
    make_users(env, "clerk-1")
    as_user(1)
    assert env.client.post("/api/invite-links/not-a-real-token/accept").status_code == 404


def test_revoke_invite_link_is_owner_only_and_disables_future_accepts(env):
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    link = env.client.post(f"/api/datasets/{did}/invite-links").json()
    assert env.client.delete(f"/api/datasets/{did}/invite-links/{link['id']}").status_code == 204

    as_user(uid2)
    assert env.client.post(f"/api/invite-links/{link['token']}/accept").status_code == 404


# ---------------------------------------------------------------- viewer role (added directly - the
# invite-link path only ever grants "editor", matching the module's own documented design)

def _add_viewer(env, did, user_id):
    with env.Session() as s:
        from app.models import DatasetCollaborator
        s.add(DatasetCollaborator(dataset_id=did, user_id=user_id, role="viewer"))
        s.commit()


def test_viewer_can_read_but_not_write(env):
    install_fakes()
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    build_themes_job(env, did)

    _add_viewer(env, did, uid2)
    as_user(uid2)
    assert env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).status_code == 200
    assert env.client.post(f"/api/datasets/{did}/themes/build", json={"column": Q}).status_code == 404


def test_viewer_gets_no_verbatim_text_but_owner_and_editor_do(env):
    install_fakes()
    uid1, uid2, uid3 = make_users(env, "clerk-1", "clerk-2", "clerk-3")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    build_themes_job(env, did)
    theme_id = env.client.get(f"/api/datasets/{did}/themes", params={"column": Q}).json()["themes"][0]["id"]

    owner_answers = env.client.get(f"/api/datasets/{did}/themes/{theme_id}/answers").json()["answers"]
    assert owner_answers and all(a["text"] for a in owner_answers)

    with env.Session() as s:
        from app.models import DatasetCollaborator
        s.add(DatasetCollaborator(dataset_id=did, user_id=uid2, role="editor"))
        s.add(DatasetCollaborator(dataset_id=did, user_id=uid3, role="viewer"))
        s.commit()

    as_user(uid2)
    editor_answers = env.client.get(f"/api/datasets/{did}/themes/{theme_id}/answers").json()["answers"]
    assert editor_answers and all(a["text"] for a in editor_answers)

    as_user(uid3)
    viewer_answers = env.client.get(f"/api/datasets/{did}/themes/{theme_id}/answers").json()["answers"]
    assert viewer_answers and all(a["text"] is None for a in viewer_answers)
    assert all(a["tone"] for a in viewer_answers)  # tone is NOT hidden, only the raw text


# ---------------------------------------------------------------- deletion stays owner-only

def test_delete_dataset_is_owner_only_not_editor(env):
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    with env.Session() as s:
        from app.models import DatasetCollaborator
        s.add(DatasetCollaborator(dataset_id=did, user_id=uid2, role="editor"))
        s.commit()

    as_user(uid2)
    assert env.client.delete(f"/api/datasets/{did}").status_code == 404

    as_user(uid1)
    assert env.client.delete(f"/api/datasets/{did}").status_code == 200


# ---------------------------------------------------------------- read-only share links

def test_create_share_link_is_owner_only(env):
    uid1, uid2 = make_users(env, "clerk-1", "clerk-2")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    assert env.client.post(f"/api/datasets/{did}/share-links", json={"column": Q}).status_code == 201

    as_user(uid2)
    assert env.client.post(f"/api/datasets/{did}/share-links", json={"column": Q}).status_code == 404


def test_public_share_link_returns_the_report_with_no_auth(env):
    install_fakes()
    uid1, = make_users(env, "clerk-1")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    build_themes_job(env, did)
    report_job = _build_report(env, did)
    assert report_job["status"] == "done", report_job

    token = env.client.post(f"/api/datasets/{did}/share-links", json={"column": Q}).json()["token"]

    app.dependency_overrides.pop(current_user, None)  # simulate a genuinely unauthenticated request
    try:
        r = env.client.get(f"/api/share/{token}/report")
        assert r.status_code == 200, r.text
        assert r.json()["column"] == Q
    finally:
        as_user(uid1)  # restore for any fixture teardown that still needs a user


def test_public_share_link_404_when_expired(env):
    install_fakes()
    uid1, = make_users(env, "clerk-1")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    build_themes_job(env, did)
    _build_report(env, did)
    link = env.client.post(f"/api/datasets/{did}/share-links", json={"column": Q, "expires_at": "2020-01-01"}).json()

    app.dependency_overrides.pop(current_user, None)
    try:
        assert env.client.get(f"/api/share/{link['token']}/report").status_code == 404
    finally:
        as_user(uid1)


def test_revoked_share_link_404s(env):
    install_fakes()
    uid1, = make_users(env, "clerk-1")
    as_user(uid1)
    did = upload_csv(env, theme_df())
    clean_and_apply(env, did)
    build_themes_job(env, did)
    _build_report(env, did)
    link = env.client.post(f"/api/datasets/{did}/share-links", json={"column": Q}).json()
    assert env.client.delete(f"/api/datasets/{did}/share-links/{link['id']}").status_code == 204

    app.dependency_overrides.pop(current_user, None)
    try:
        assert env.client.get(f"/api/share/{link['token']}/report").status_code == 404
    finally:
        as_user(uid1)
