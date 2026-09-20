from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Column, Dataset

FIX = Path(__file__).parent / "fixtures" / "messy_survey.csv"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # tests never touch the network
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield SimpleEnv(TestClient(app), Session, tmp_path / "uploads")
    app.dependency_overrides.clear()


class SimpleEnv:
    def __init__(self, client, Session, uploads):
        self.client, self.Session, self.uploads = client, Session, uploads

    def post(self, name="s.csv", data=None, ctype="text/csv"):
        data = FIX.read_bytes() if data is None else data
        return self.client.post("/api/upload", files={"file": (name, data, ctype)})


def test_upload_success(env):
    r = env.post("survey.csv")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["filename"] == "survey.csv" and j["row_count"] == 12 and j["reused"] is False
    kinds = {c["name"]: c["kind"] for c in j["profile"]["columns"]}
    assert kinds["Survey date"] == "date" and kinds["Likelihood to buy"] == "score"
    assert j["profile"]["question"]["text"].startswith("Why haven't")
    files = [p.name for p in env.uploads.iterdir()]
    assert len(files) == 1 and files[0].endswith(".csv") and len(files[0]) == 64 + 4  # sha256 name, no temp left
    with env.Session() as s:
        ds = s.scalar(select(Dataset))
        assert len(ds.file_hash) == 64 and ds.profile["columns"]


def test_duplicate_hash_reuses_record(env):
    a = env.post("one.csv").json()
    b = env.post("two.csv").json()
    assert b["id"] == a["id"] and b["reused"] is True
    with env.Session() as s:
        assert len(s.scalars(select(Dataset)).all()) == 1


def test_wrong_type_400(env):
    r = env.post("notes.pdf", b"%PDF-1.4", "application/pdf")
    assert r.status_code == 400
    assert env.post("evil.exe", b"MZ").status_code == 400


def test_oversize_413(env):
    r = env.post("big.csv", b"a,b\n" + b"1,2\n" * 400_000)  # about 1.6 MB, limit is 1 MB
    assert r.status_code == 413
    assert not any(env.uploads.iterdir())  # partial file cleaned up


def test_unreadable_file_400_and_not_kept(env):
    r = env.post("bad.xlsx", b"this is not a zip")
    assert r.status_code == 400 and "xlsx" in r.json()["detail"]
    assert not any(env.uploads.iterdir())


def test_filename_traversal_is_neutralised(env):
    r = env.post("../../etc/pass wd<>.csv")
    assert r.status_code == 200
    assert "/" not in r.json()["filename"] and ".." not in r.json()["filename"]
    assert all(p.parent == env.uploads for p in env.uploads.iterdir())


def test_profile_fetch(env):
    ds = env.post().json()
    r = env.client.get(f"/api/datasets/{ds['id']}/profile")
    assert r.status_code == 200 and r.json()["confirmed"] is False
    assert r.json()["profile"]["columns"][0]["name"] == "Respondent ID"
    assert env.client.get("/api/datasets/999/profile").status_code == 404


def test_patch_columns(env):
    ds = env.post().json()
    cols = [{"name": c["name"], "kind": c["kind"], "off": False} for c in ds["profile"]["columns"]]
    cols[3]["kind"] = "segment"  # the user changes Age
    cols[3]["off"] = True
    r = env.client.patch(f"/api/datasets/{ds['id']}/columns", json={"columns": cols, "question": "  Why no EV?  "})
    assert r.status_code == 200 and r.json()["confirmed"] is True
    conf = env.client.get(f"/api/datasets/{ds['id']}/profile").json()["profile"]["confirmed"]
    assert conf["question"] == "Why no EV?"
    assert conf["columns"]["Age"] == {"kind": "segment", "off": True}
    with env.Session() as s:
        rows = {c.name: c for c in s.scalars(select(Column)).all()}
        assert rows["Age"].kind == "segment" and rows["Age"].stats["off"] is True and rows["Age"].stats["sensitive"]
        assert len(rows) == 7


def test_patch_validation(env):
    ds = env.post().json()
    url = f"/api/datasets/{ds['id']}/columns"
    good = [{"name": c["name"], "kind": c["kind"]} for c in ds["profile"]["columns"]]
    assert env.client.patch(url, json={"columns": good[:-1]}).status_code == 422  # a column is missing
    assert env.client.patch(url, json={"columns": good + [{"name": "Nope", "kind": "score"}]}).status_code == 422
    bad = [dict(g) for g in good]
    bad[0]["kind"] = "banana"
    assert env.client.patch(url, json={"columns": bad}).status_code == 422
    assert env.client.patch("/api/datasets/999/columns", json={"columns": good}).status_code == 404
