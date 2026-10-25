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


def test_themes_kind_follows_the_build_and_old_builds_count_as_the_guess(env):
    from app.api_themes import _record_themes_question_kind
    got = env.client.get(url(env), params={"column": "Why"}).json()
    assert got["themes_kind"] == "facts"  # no record yet: counts as the guess, so nothing to rebuild
    env.client.put(url(env), json={"column": "Why", "kind": "reasons"})
    assert env.client.get(url(env), params={"column": "Why"}).json()["themes_kind"] == "facts"
    with env.Session() as s:
        _record_themes_question_kind(s, env.ids.ds, "Why", "reasons")
    got = env.client.get(url(env), params={"column": "Why"}).json()
    assert (got["kind"], got["themes_kind"]) == ("reasons", "reasons")


def test_report_is_stale_after_the_question_kind_changes(env):
    from app.api_report import _stale_reason
    with env.Session() as s:
        ds = s.get(Dataset, env.ids.ds)
        built_with_guess = {"question_kind": "facts"}
        assert _stale_reason(ds, "Why", built_with_guess, [], False) is None
        assert _stale_reason(ds, "Why", {}, [], False) is None  # older report: counts as the guess
    env.client.put(url(env), json={"column": "Why", "kind": "reasons"})
    with env.Session() as s:
        ds = s.get(Dataset, env.ids.ds)
        assert _stale_reason(ds, "Why", {"question_kind": "facts"}, [], False) == "question_kind"
        assert _stale_reason(ds, "Why", {}, [], False) == "question_kind"
        assert _stale_reason(ds, "Why", {"question_kind": "reasons"}, [], False) is None
        assert _stale_reason(ds, "Why", {"question_kind": "reasons"}, [], True) == "themes"


def test_prompts_carry_the_question_kind_only_when_it_says_something():
    from app.findings import HEADLINE_KIND_SYSTEM, _build_headline_prompt
    from app.text_pipeline.labeling import QUESTION_KIND_SYSTEM, _build_prompt
    assert json.loads(_build_prompt([], "Why?", 3, None, "reasons"))["question_asks_for"] == "reasons"
    assert "question_asks_for" not in json.loads(_build_prompt([], "Why?", 3, None, "anything else"))
    assert "question_asks_for" not in json.loads(_build_prompt([], "Why?", 3))
    assert json.loads(_build_headline_prompt([], "Why?", "improvements"))["question_asks_for"] == "improvements"
    assert "question_asks_for" not in json.loads(_build_headline_prompt([], "Why?"))
    assert "question_asks_for" in QUESTION_KIND_SYSTEM and "question_asks_for" in HEADLINE_KIND_SYSTEM


def test_labelling_and_headline_send_the_kind_to_claude():
    from app.findings import Candidate, write_headline
    from app.text_pipeline.labeling import label_sub_clusters

    class Fake:
        def __init__(self, reply):
            self.reply, self.calls = reply, []

        def complete(self, system, prompt, **kw):
            self.calls.append((system, json.loads(prompt)))
            return self.reply

    fake = Fake(json.dumps({"headlines": [{"id": "c1", "sentence": "Cost is the most common reason."}]}))
    cand = Candidate(id="c1", kind="dominant_theme", theme_id=1, theme_name="Cost", count=10, score=1.0,
                     numbers={"theme": "Cost"})
    write_headline([cand], fake, "Why?", "reasons")
    system, payload = fake.calls[0]
    assert payload["question_asks_for"] == "reasons" and "question_asks_for" in system

    from app.text_pipeline.schema import Cluster, ThemeLabel
    fake = Fake(json.dumps({"themes": [{"cluster_id": 0, "label": "Price", "description": "d", "merge_with": [], "note": None}]}))
    parent = ThemeLabel(cluster_id=5, label="Cost", description="d", size=4, merge_with=[], note=None)
    label_sub_clusters({5: [Cluster(id=0, members=[], centroid=None)]}, {5: parent}, "Why?", fake, question_kind="reasons")
    assert fake.calls[0][1]["question_asks_for"] == "reasons"
