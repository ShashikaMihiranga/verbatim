"""The question-context correction (app/api_context.py) and how reports read it back."""
from __future__ import annotations

import html
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.api_upload import current_user
from app.charts import render_report_parts
from app.db import Base, get_db
from app.findings import build_report_data
from app.main import app
from app.models import Column, Dataset, Project, Theme, User

QUESTION = "What is your favourite part of the product?"  # keyword guess: "facts" ("what is")


@pytest.fixture()
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ctx.db'}", poolclass=NullPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        owner, stranger = User(clerk_id="owner"), User(clerk_id="stranger")
        s.add_all([owner, stranger])
        s.flush()
        project = Project(user_id=owner.id, name="p")
        s.add(project)
        s.flush()
        ds = Dataset(project_id=project.id, filename="s.csv", file_hash="c" * 64, row_count=10,
                     profile={"confirmed": {"question": QUESTION}})
        s.add(ds)
        s.flush()
        s.add(Column(dataset_id=ds.id, name="Why", position=0, kind="open_text", stats={}))
        s.commit()
        ids = SimpleNamespace(owner=owner.id, stranger=stranger.id, ds=ds.id)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=ids.owner)
    yield SimpleNamespace(client=TestClient(app), Session=Session, ids=ids)
    app.dependency_overrides.clear()


def url(env):
    return f"/api/datasets/{env.ids.ds}/question-kind"


def test_starts_with_verbatims_guess_and_saves_a_correction(env):
    got = env.client.get(url(env), params={"column": "Why"}).json()
    assert (got["kind"], got["guessed_kind"], got["corrected"]) == ("facts", "facts", False)

    saved = env.client.put(url(env), json={"column": "Why", "kind": "opinions"})
    assert saved.status_code == 200, saved.text
    assert (saved.json()["kind"], saved.json()["corrected"]) == ("opinions", True)
    assert env.client.get(url(env), params={"column": "Why"}).json()["kind"] == "opinions"  # persisted
    with env.Session() as s:
        assert s.get(Dataset, env.ids.ds).profile["question_kinds"] == {"Why": "opinions"}


def test_reset_and_choosing_the_guess_both_clear_the_correction(env):
    env.client.put(url(env), json={"column": "Why", "kind": "opinions"})
    assert env.client.put(url(env), json={"column": "Why", "kind": None}).json()["corrected"] is False
    env.client.put(url(env), json={"column": "Why", "kind": "opinions"})
    assert env.client.put(url(env), json={"column": "Why", "kind": "facts"}).json()["corrected"] is False
    with env.Session() as s:
        assert s.get(Dataset, env.ids.ds).profile["question_kinds"] == {}


def test_rejects_unknown_kind_unknown_column_and_other_users(env):
    assert env.client.put(url(env), json={"column": "Why", "kind": "made up"}).status_code == 422
    assert env.client.put(url(env), json={"column": "Nope", "kind": "facts"}).status_code == 404
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=env.ids.stranger)
    assert env.client.put(url(env), json={"column": "Why", "kind": "facts"}).status_code == 404


def test_report_data_and_its_context_chart_use_the_saved_correction(env):
    env.client.put(url(env), json={"column": "Why", "kind": "reasons"})
    with env.Session() as s:
        ds = s.get(Dataset, env.ids.ds)
        theme = Theme(dataset_id=ds.id, column_name="Why", label="Cost", size=10, sentiment=-0.3,
                      tone={"neg": 60.0, "neu": 20.0, "pos": 20.0}, answer_refs=list(range(10)))
        data = build_report_data(ds, [theme], cleaning_report={}, question=QUESTION)
    assert (data.context.kind, data.context.guessed_kind, data.context.corrected) == ("reasons", "facts", True)

    body, _, height = render_report_parts("context", data)
    # The report version is plain text: no permanently-open menu, no fixed gap, no empty section.
    assert "How the charts were chosen" not in body and "position:absolute" not in body and height == 300
    assert "You changed this from Verbatim's guess, facts." in body
    payload = json.loads(html.unescape(body.split('data-context="', 1)[1].split('"', 1)[0]))
    assert payload["kind"] == "reasons" and payload["guessed_kind"] == "facts" and payload["corrected"] is True
    assert "reasons" in payload["options"]
