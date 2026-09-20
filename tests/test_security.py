from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_upload_and_data_routes_fail_closed(monkeypatch):
    monkeypatch.delenv("ALLOW_DEV_USER", raising=False)
    assert c.post("/api/upload", files={"file": ("a.csv", b"a,b\n1,2\n")}).status_code == 401
    assert c.get("/api/datasets/1/profile").status_code == 401
    assert c.patch("/api/datasets/1/columns", json={"columns": []}).status_code == 401


def test_security_headers_present():
    r = c.get("/health")
    for h in ("Content-Security-Policy", "X-Content-Type-Options", "Strict-Transport-Security", "X-Frame-Options"):
        assert h in r.headers


def test_api_docs_hidden_outside_dev():
    assert "swagger" not in c.get("/docs").text.lower()
    r = c.get("/openapi.json")
    assert r.headers.get("content-type", "").split(";")[0] != "application/json"
