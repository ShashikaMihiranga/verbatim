from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pandas as pd

from app.db import Base, get_db
from app.main import app
from app.models import CleanedFile, Column, Dataset, UploadedFile

FIX = Path(__file__).parent / "fixtures" / "messy_survey.csv"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # tests never touch the network
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield SimpleEnv(TestClient(app), Session)
    app.dependency_overrides.clear()


class SimpleEnv:
    def __init__(self, client, Session):
        self.client, self.Session = client, Session

    def post(self, name="s.csv", data=None, ctype="text/csv"):
        data = FIX.read_bytes() if data is None else data
        return self.client.post("/api/upload", files={"file": (name, data, ctype)})

    def uploaded_files(self):
        with self.Session() as s:
            return s.scalars(select(UploadedFile)).all()


def test_upload_success(env):
    r = env.post("survey.csv")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["filename"] == "survey.csv" and j["row_count"] == 12 and j["reused"] is False
    kinds = {c["name"]: c["kind"] for c in j["profile"]["columns"]}
    assert kinds["Survey date"] == "date" and kinds["Likelihood to buy"] == "score"
    assert j["profile"]["question"]["text"].startswith("Why haven't")
    with env.Session() as s:
        ds = s.scalar(select(Dataset))
        assert len(ds.file_hash) == 64 and ds.profile["columns"]
        # the raw bytes are stored in the database, content-addressed by hash - not on disk
        rows = s.scalars(select(UploadedFile)).all()
        assert len(rows) == 1
        assert rows[0].file_hash == ds.file_hash
        assert rows[0].content == FIX.read_bytes()


def test_duplicate_hash_reuses_record(env):
    a = env.post("one.csv").json()
    b = env.post("two.csv").json()
    assert b["id"] == a["id"] and b["reused"] is True
    with env.Session() as s:
        assert len(s.scalars(select(Dataset)).all()) == 1
        # the second, identical upload reused the existing blob row rather than duplicating it
        assert len(s.scalars(select(UploadedFile)).all()) == 1


def test_wrong_type_400(env):
    r = env.post("notes.pdf", b"%PDF-1.4", "application/pdf")
    assert r.status_code == 400
    assert env.post("evil.exe", b"MZ").status_code == 400


def test_oversize_413(env):
    r = env.post("big.csv", b"a,b\n" + b"1,2\n" * 400_000)  # about 1.6 MB, limit is 1 MB
    assert r.status_code == 413
    assert env.uploaded_files() == []  # nothing was ever stored: the size limit trips mid-stream


def test_unreadable_file_400_and_not_kept(env):
    r = env.post("bad.xlsx", b"this is not a zip")
    assert r.status_code == 400 and "xlsx" in r.json()["detail"]
    assert env.uploaded_files() == []  # bytes for a file that never became a Dataset are not kept


def test_filename_traversal_is_neutralised(env):
    r = env.post("../../etc/pass wd<>.csv")
    assert r.status_code == 200
    assert "/" not in r.json()["filename"] and ".." not in r.json()["filename"]


def test_profile_fetch(env):
    ds = env.post().json()
    r = env.client.get(f"/api/datasets/{ds['id']}/profile")
    assert r.status_code == 200 and r.json()["confirmed"] is False
    assert r.json()["profile"]["columns"][0]["name"] == "Respondent ID"
    assert env.client.get("/api/datasets/999/profile").status_code == 404


def _choices(profile):
    return [{"position": c["position"], "name": c["name"], "kind": c["kind"], "off": False} for c in profile["columns"]]


def test_patch_columns(env):
    ds = env.post().json()
    cols = _choices(ds["profile"])
    cols[3]["kind"] = "segment"  # the user changes Age
    cols[3]["off"] = True
    r = env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols, "question": "  Why no EV?  "})
    assert r.status_code == 200 and r.json()["confirmed"] is True
    conf = env.client.get(f"/api/datasets/{ds['id']}/profile").json()["profile"]["confirmed"]
    assert conf["question"] == "Why no EV?"
    assert conf["columns"]["Age"] == {"kind": "segment", "off": True}
    assert conf["renames"] == {}  # no name changed, so no rename recorded
    with env.Session() as s:
        rows = {c.name: c for c in s.scalars(select(Column)).all()}
        assert rows["Age"].kind == "segment" and rows["Age"].stats["off"] is True and rows["Age"].stats["sensitive"]
        assert len(rows) == 7


def test_patch_columns_primary_open_text(env):
    """docs/TODO.md (fixed 2026-10-22): a user can now explicitly pick which open_text column is the
    report's subject. "Why haven't..." is this fixture's own single open_text column (position 5)."""
    ds = env.post().json()
    cols = _choices(ds["profile"])
    open_text_name = next(c["name"] for c in cols if c["kind"] == "open_text")
    r = env.client.patch(
        f"/api/datasets/{ds['id']}/columns",
        json={"columns": cols, "primary_open_text": open_text_name},
    )
    assert r.status_code == 200, r.text
    conf = env.client.get(f"/api/datasets/{ds['id']}/profile").json()["profile"]["confirmed"]
    assert conf["primary_open_text"] == open_text_name


def test_patch_columns_primary_open_text_defaults_to_none(env):
    ds = env.post().json()
    cols = _choices(ds["profile"])
    r = env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols})
    assert r.status_code == 200, r.text
    conf = env.client.get(f"/api/datasets/{ds['id']}/profile").json()["profile"]["confirmed"]
    assert conf["primary_open_text"] is None


def test_patch_columns_primary_open_text_rejects_unknown_column(env):
    ds = env.post().json()
    cols = _choices(ds["profile"])
    r = env.client.patch(
        f"/api/datasets/{ds['id']}/columns",
        json={"columns": cols, "primary_open_text": "Not a real column"},
    )
    assert r.status_code == 422


def test_patch_columns_primary_open_text_rejects_non_open_text_kind(env):
    ds = env.post().json()
    cols = _choices(ds["profile"])
    numeric_name = next(c["name"] for c in cols if c["kind"] == "numeric")
    r = env.client.patch(
        f"/api/datasets/{ds['id']}/columns",
        json={"columns": cols, "primary_open_text": numeric_name},
    )
    assert r.status_code == 422


def test_patch_columns_rename(env):
    ds = env.post().json()
    cols = _choices(ds["profile"])
    original_name = cols[3]["name"]  # "Age"
    cols[3]["name"] = "Years Old"
    r = env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"]["columns"][3]["name"] == "Years Old"
    assert body["profile"]["confirmed"]["renames"] == {original_name: "Years Old"}
    assert "Years Old" in body["profile"]["confirmed"]["columns"]

    with env.Session() as s:
        rows = {c.name: c for c in s.scalars(select(Column)).all()}
        assert "Years Old" in rows and original_name not in rows
        assert rows["Years Old"].stats["original_name"] == original_name

    # a follow-up GET /profile reflects the renamed name as current, same as kind/off do today
    again = env.client.get(f"/api/datasets/{ds['id']}/profile").json()
    assert again["profile"]["columns"][3]["name"] == "Years Old"


def test_patch_columns_rename_twice_chains_back_to_the_literal_header(env):
    """A second confirm, before anything downstream is built, must still map the ORIGINAL file header
    to the final name - not the intermediate renamed name - since that's what `_load_df` always reloads
    the raw file under."""
    ds = env.post().json()
    original_name = ds["profile"]["columns"][3]["name"]  # "Age"

    cols = _choices(ds["profile"])
    cols[3]["name"] = "Years Old"
    env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols})

    profile = env.client.get(f"/api/datasets/{ds['id']}/profile").json()["profile"]
    cols2 = _choices(profile)
    cols2[3]["name"] = "Respondent Age"  # rename again, from the now-current "Years Old"
    r = env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols2})
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["confirmed"]["renames"] == {original_name: "Respondent Age"}


def test_rename_survives_cleaning_reloading_the_raw_file(env):
    """The ripple fix: `app/api_cleaning.py::_load_df` reloads the ORIGINAL raw bytes on every cleaning
    call, under their literal header text - a rename made at confirm time must be re-applied there every
    time, or cleaning would silently see the pre-rename column name again."""
    ds = env.post().json()
    cols = _choices(ds["profile"])
    original_name = cols[3]["name"]  # "Age"
    cols[3]["name"] = "Years Old"
    r = env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols})
    assert r.status_code == 200, r.text

    plan_r = env.client.post(f"/api/datasets/{ds['id']}/clean/plan")
    assert plan_r.status_code == 200, plan_r.text  # must not 404/mismatch on the renamed column

    apply_r = env.client.post(f"/api/datasets/{ds['id']}/clean/apply")
    assert apply_r.status_code == 200, apply_r.text
    digest = apply_r.json()["clean_hash"]
    with env.Session() as s:
        cleaned = s.get(CleanedFile, digest)
        cleaned_df = pd.read_csv(pd.io.common.BytesIO(cleaned.content))
        assert "Years Old" in cleaned_df.columns
        assert original_name not in cleaned_df.columns


def test_patch_validation(env):
    ds = env.post().json()
    url = f"/api/datasets/{ds['id']}/columns"
    good = _choices(ds["profile"])
    assert env.client.patch(url, json={"columns": good[:-1]}).status_code == 422  # a column is missing
    bad_position = [dict(g) for g in good]
    bad_position[0]["position"] = 999  # a position that doesn't exist in the profiled columns
    assert env.client.patch(url, json={"columns": bad_position}).status_code == 422
    bad = [dict(g) for g in good]
    bad[0]["kind"] = "banana"
    assert env.client.patch(url, json={"columns": bad}).status_code == 422
    assert env.client.patch("/api/datasets/999/columns", json={"columns": good}).status_code == 404
