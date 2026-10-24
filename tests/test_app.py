import pytest
from fastapi.testclient import TestClient

from app.charts import FRAMES
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_api_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True}


def test_frame_count():
    # A deliberate tripwire, not self-referential: bump this literal by hand whenever a chart is added or
    # removed, so adding one is a conscious count change, not something that silently passes either way.
    assert len(FRAMES) == 33


@pytest.mark.parametrize("frame_id", list(FRAMES))
def test_frame_ok(frame_id):
    assert client.get(f"/frame/{frame_id}").status_code == 200


def test_unknown_frame():
    assert client.get("/frame/nope").status_code == 404


def test_index():
    assert client.get("/").status_code == 200


def test_unknown_api_path_404():
    assert client.get("/api/nope").status_code == 404
