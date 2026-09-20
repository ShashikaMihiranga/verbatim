"""Rate limiting and body-size guards, using the ASGI test client on a small app with a shrunk limit."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.ratelimit import RateLimitMiddleware, classify, normalise_path


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(clock=None, trust_proxy=False, limits=None, window=60.0, max_keys=50_000, enabled=True):
    app = FastAPI()
    calls = {"upload": 0}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/things")
    def things():
        return {"ok": True}

    @app.get("/api/other")
    def other():
        return {"ok": True}

    @app.post("/api/upload")
    async def upload(request: Request):
        calls["upload"] += 1
        return {"bytes": len(await request.body())}

    @app.post("/api/patch")
    async def patch(request: Request):
        return {"bytes": len(await request.body())}

    @app.get("/api/signin-variant")
    def signin():
        return {"ok": True}

    @app.get("/api/auth/callback")
    def auth():
        return {"ok": True}

    @app.get("/page")
    def page():
        return {"ok": True}

    clock = clock or Clock()
    app.add_middleware(RateLimitMiddleware, limits=limits, window_seconds=window, max_keys=max_keys,
                       trust_proxy=trust_proxy, enabled=enabled, clock=clock)
    app.state.rl_calls = calls
    return TestClient(app), clock, app


def hits(client, method, path, n, **kw):
    return [client.request(method, path, **kw).status_code for _ in range(n)]


# ---------------------------------------------------------------- limits and 429 shape
def test_api_overall_limit_returns_429_with_retry_after_and_generic_body():
    c, clock, _ = make(limits={"api": 5})
    assert hits(c, "GET", "/api/things", 5) == [200] * 5
    r = c.get("/api/things")
    assert r.status_code == 429
    assert r.json() == {"detail": "Too many requests. Please wait a moment and try again."}
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert "127.0.0.1" not in r.text and "testclient" not in r.text  # nothing about the client or the limits


def test_limit_recovers_after_the_window():
    c, clock, _ = make(limits={"api": 3})
    assert hits(c, "GET", "/api/things", 3) == [200] * 3
    assert c.get("/api/things").status_code == 429
    clock.t += 125
    assert c.get("/api/things").status_code == 200
    clock.t += 200
    assert hits(c, "GET", "/api/things", 3) == [200] * 3
    assert c.get("/api/things").status_code == 429


def test_sliding_window_does_not_reset_all_at_once_at_the_boundary():
    c, clock, _ = make(limits={"api": 10})
    assert hits(c, "GET", "/api/things", 10) == [200] * 10
    clock.t += 61  # just into the next window: the previous window still weighs almost fully
    assert c.get("/api/things").status_code == 429
    clock.t += 40  # the old burst has mostly slid out
    assert hits(c, "GET", "/api/things", 5).count(200) >= 4


def test_upload_has_its_own_smaller_limit_and_counts_toward_api_total():
    c, clock, app = make(limits={"upload": 2, "api": 4})
    assert hits(c, "POST", "/api/upload", 2, content=b"x") == [200, 200]
    assert c.post("/api/upload", content=b"x").status_code == 429
    assert app.state.rl_calls["upload"] == 2  # the blocked request never reached the route
    # the two uploads used half of the 4-request API allowance
    assert hits(c, "GET", "/api/things", 3) == [200, 200, 429]


def test_auth_routes_have_their_own_limit():
    c, _, _ = make(limits={"auth": 3, "api": 100})
    assert hits(c, "GET", "/api/signin-variant", 3) == [200] * 3
    assert c.get("/api/signin-variant").status_code == 429
    assert c.get("/api/auth/callback").status_code == 429  # same auth bucket
    assert c.get("/api/things").status_code == 200


def test_everything_else_uses_the_other_limit_and_health_is_exempt():
    c, _, _ = make(limits={"other": 4, "api": 2})
    assert hits(c, "GET", "/page", 4) == [200] * 4
    assert c.get("/page").status_code == 429
    assert hits(c, "GET", "/health", 50) == [200] * 50
    assert hits(c, "GET", "/health/", 5).count(429) == 0


def test_path_tricks_do_not_dodge_the_upload_bucket():
    c, _, _ = make(limits={"upload": 1})
    assert c.post("/api/upload", content=b"x").status_code == 200
    for p in ("/API/upload", "/api//upload", "/api/upload/"):
        assert c.post(p, content=b"x").status_code in (429,), p


def test_disabled_and_env_switch():
    c, _, _ = make(limits={"api": 1}, enabled=False)
    assert hits(c, "GET", "/api/things", 5) == [200] * 5


def test_env_configures_limits(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_API_PER_MIN", "2")
    monkeypatch.setenv("RATE_LIMIT_UPLOAD_PER_MIN", "bogus")
    c, _, _ = make()
    assert hits(c, "GET", "/api/things", 3) == [200, 200, 429]
    assert RateLimitMiddleware(None).limits["upload"] == 10  # bad value falls back to the default


def test_default_limits_match_the_spec():
    m = RateLimitMiddleware(None)
    assert m.limits == {"api": 120, "upload": 10, "auth": 30, "other": 300} and m.max_keys == 50_000


def test_classification():
    assert classify("GET", "/health") is None
    assert classify("POST", "/api/upload") == ("api", "upload")
    assert classify("GET", "/api/upload") == ("api",)
    assert classify("GET", "/api/signin-variant") == ("api", "auth")
    assert classify("POST", "/api/auth/login") == ("api", "auth")
    assert classify("GET", "/assets/x.js") == ("other",)
    assert normalise_path("/API//Upload/") == "/api/upload"


# ---------------------------------------------------------------- client identity
def test_spoofed_forwarded_for_does_not_bypass_limits_when_proxy_not_trusted():
    c, _, _ = make(limits={"api": 3}, trust_proxy=False)
    codes = [c.get("/api/things", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(6)]
    assert codes == [200, 200, 200, 429, 429, 429]


def test_forwarded_for_is_never_read_without_trust_even_via_env(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY", raising=False)
    c, _, _ = make(limits={"api": 2}, trust_proxy=None)
    codes = [c.get("/api/things", headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]
    monkeypatch.setenv("TRUST_PROXY", "false")
    assert c.get("/api/things", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 429


def test_with_trust_each_forwarded_client_has_its_own_budget(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "true")
    c, _, _ = make(limits={"api": 2}, trust_proxy=None)
    a, b = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}, {"X-Forwarded-For": "198.51.100.9, 10.0.0.1"}
    assert [c.get("/api/things", headers=a).status_code for _ in range(3)] == [200, 200, 429]
    assert [c.get("/api/things", headers=b).status_code for _ in range(3)] == [200, 200, 429]


def test_trusted_header_uses_first_address_and_garbage_falls_back_to_socket():
    c, _, _ = make(limits={"api": 2}, trust_proxy=True)
    codes = [c.get("/api/things", headers={"X-Forwarded-For": "203.0.113.7, 198.51.100.1"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    # garbage is ignored: the socket address is used, which is a different client from 203.0.113.7
    assert c.get("/api/things", headers={"X-Forwarded-For": "not-an-ip"}).status_code == 200
    assert c.get("/api/things", headers={"X-Forwarded-For": "<script>"}).status_code == 200
    assert c.get("/api/things", headers={"X-Forwarded-For": ""}).status_code == 429  # socket bucket is now full


def test_last_position_option(monkeypatch):
    monkeypatch.setenv("PROXY_XFF_POSITION", "last")
    c, _, _ = make(limits={"api": 2}, trust_proxy=True)
    hdr = lambda first: {"X-Forwarded-For": f"{first}, 203.0.113.7"}  # forged first entry, real last entry
    codes = [c.get("/api/things", headers=hdr(f"1.1.1.{i}")).status_code for i in range(4)]
    assert codes == [200, 200, 429, 429]


def test_ipv6_clients_are_grouped_by_prefix():
    c, _, _ = make(limits={"api": 2}, trust_proxy=True)
    codes = [c.get("/api/things", headers={"X-Forwarded-For": f"2001:db8:1:2::{i:x}"}).status_code for i in range(1, 5)]
    assert codes == [200, 200, 429, 429]


# ---------------------------------------------------------------- bounded memory
def test_memory_is_capped_and_old_keys_are_evicted():
    c, clock, app = make(limits={"api": 100}, trust_proxy=True, max_keys=50)
    c.get("/api/things", headers={"X-Forwarded-For": "198.17.0.1"})
    mw = _find_middleware(app)
    for i in range(400):
        c.get("/api/things", headers={"X-Forwarded-For": f"198.18.{i // 250}.{i % 250}"})
    assert mw.keys_in_memory() <= 50
    clock.t += 500
    c.get("/api/things", headers={"X-Forwarded-For": "198.19.0.1"})
    for i in range(3):  # a fresh key after everything went stale triggers a sweep
        c.get("/api/things", headers={"X-Forwarded-For": f"198.20.0.{i}"})
    assert mw.keys_in_memory() <= 5


def test_default_cap_is_50000_keys():
    assert RateLimitMiddleware(None).max_keys == 50_000


def _find_middleware(app):
    assert app.middleware_stack is not None, "make one request first so the stack is built"
    node = app.middleware_stack
    while node is not None and not isinstance(node, RateLimitMiddleware):
        node = getattr(node, "app", None)
    assert node is not None
    return node


# ---------------------------------------------------------------- body size guard
def test_upload_content_length_over_limit_is_413_before_the_body_is_read(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    c, _, app = make(limits={"upload": 100, "api": 100})
    ok = c.post("/api/upload", content=b"x" * (1024 * 1024))
    assert ok.status_code == 200
    ok2 = c.post("/api/upload", content=b"x" * (2 * 1024 * 1024))  # exactly MAX + 1 MB is still allowed
    assert ok2.status_code == 200
    big = c.post("/api/upload", content=b"x" * (2 * 1024 * 1024 + 1))
    assert big.status_code == 413 and big.json() == {"detail": "That file is too large."}
    assert app.state.rl_calls["upload"] == 2  # the route never saw the oversized request


def test_oversized_declared_length_is_rejected_without_sending_a_body(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "50")
    c, _, app = make(limits={"upload": 100, "api": 100})
    r = c.post("/api/upload", headers={"Content-Length": str(900 * 1024 * 1024)}, content=b"tiny")
    assert r.status_code in (413, 400) and app.state.rl_calls["upload"] == 0


def test_bad_content_length_is_400():
    from starlette.testclient import TestClient as TC  # noqa: F401
    c, _, _ = make(limits={"upload": 100, "api": 100})
    for v in ("abc", "-5", "1e9"):
        r = c.post("/api/upload", headers={"Content-Length": v}, content=b"")
        assert r.status_code in (400, 413), v


def test_other_api_bodies_have_a_small_cap(monkeypatch):
    monkeypatch.setenv("MAX_API_BODY_KB", "4")
    c, _, _ = make(limits={"api": 100})
    assert c.post("/api/patch", content=b"x" * 4096).status_code == 200
    assert c.post("/api/patch", content=b"x" * 4097).status_code == 413


def test_chunked_upload_without_content_length_passes_to_the_route():
    c, _, app = make(limits={"upload": 100, "api": 100})

    def gen():
        yield b"abc"
        yield b"def"

    r = c.post("/api/upload", content=gen())
    assert r.status_code == 200 and r.json() == {"bytes": 6}


# ---------------------------------------------------------------- the real app
def test_real_app_registers_the_middleware_and_keeps_security_headers_on_429(monkeypatch):
    from app.main import app as real

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("TRUST_PROXY", "false")
    names = [m.cls.__name__ for m in real.user_middleware]
    assert names.index("SecurityHeadersMiddleware") < names.index("RateLimitMiddleware")  # outer first
    TestClient(real).get("/health")
    mw = _find_middleware(real)
    old = dict(mw.limits)
    mw.limits["other"] = 2
    mw._state.clear()
    try:
        c = TestClient(real)
        assert 429 not in [c.get("/nope-page").status_code for _ in range(2)]
        r = c.get("/nope-page")
        r = c.get("/nope-page")
        assert r.status_code == 429 and "Content-Security-Policy" in r.headers and "Retry-After" in r.headers
        assert c.get("/health").status_code == 200
    finally:
        mw.limits.update(old)
        mw._state.clear()
