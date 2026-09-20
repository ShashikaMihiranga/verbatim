"""Auth tests: local RSA key pair, fake JWKS (no network), no Clerk account needed."""
import base64
import hashlib
import hmac
import json
import time
from collections import Counter
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth as auth
from app.db import Base, get_db
from app.main import app
from app.models import SigninVariantLog, User
from app.security import build_csp

ISSUER = "https://clerk.verbatim.test"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"
FIX = Path(__file__).parent / "fixtures" / "messy_survey.csv"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV = _KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
)
OTHER_PRIV = _OTHER_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
)
PUB_PEM = _KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key()))
JWK.update(kid="test-kid", use="sig", alg="RS256")


def make_token(sub="user_A", key=PRIV, kid="test-kid", **over):
    now = int(time.time())
    claims = {"sub": sub, "iss": ISSUER, "iat": now, "nbf": now - 5, "exp": now + 300, "azp": "https://app.test"}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def b64(data: dict | bytes) -> str:
    raw = data if isinstance(data, bytes) else json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Env:
    def __init__(self, client, Session):
        self.client, self.Session = client, Session

    def get(self, url, token=None, **kw):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get(url, headers=headers, **kw)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_DEV_USER", raising=False)
    monkeypatch.setenv("CLERK_JWKS_URL", JWKS_URL)
    monkeypatch.setenv("CLERK_ISSUER", ISSUER)
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://app.test")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(auth, "_fetch_jwks", lambda url: {"keys": [JWK]})
    auth.jwks_cache.clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield Env(TestClient(app), Session)
    app.dependency_overrides.clear()
    auth.jwks_cache.clear()


# ---------------------------------------------------------------- accepted
def test_valid_token_accepted_and_user_created(env):
    r = env.get("/api/me", make_token("user_A", email="a@example.com"))
    assert r.status_code == 200
    assert r.json()["email"] == "a@example.com"
    with env.Session() as s:
        users = s.scalars(select(User)).all()
    assert [u.clerk_id for u in users] == ["user_A"]
    assert r.json()["id"] == users[0].id
    env.get("/api/me", make_token("user_A"))  # second sight does not duplicate
    with env.Session() as s:
        assert len(s.scalars(select(User)).all()) == 1


def test_me_without_email_claim_has_only_id(env):
    assert set(env.get("/api/me", make_token()).json()) == {"id"}


def test_small_clock_skew_is_tolerated(env):
    assert env.get("/api/me", make_token(exp=int(time.time()) - 3)).status_code == 200


# ---------------------------------------------------------------- rejected
def _assert_generic_401(r):
    assert r.status_code == 401
    assert r.json() == {"detail": "Sign-in is required."}


def test_expired_token(env):
    _assert_generic_401(env.get("/api/me", make_token(exp=int(time.time()) - 120)))


def test_not_yet_valid_token(env):
    _assert_generic_401(env.get("/api/me", make_token(nbf=int(time.time()) + 600)))


def test_wrong_issuer(env):
    _assert_generic_401(env.get("/api/me", make_token(iss="https://evil.test")))


def test_wrong_and_missing_azp(env):
    _assert_generic_401(env.get("/api/me", make_token(azp="https://evil.test")))
    _assert_generic_401(env.get("/api/me", make_token(azp=None)))


def test_azp_not_checked_when_allow_list_unset(env, monkeypatch):
    monkeypatch.delenv("CLERK_AUTHORIZED_PARTIES")
    assert env.get("/api/me", make_token(azp="https://anything.test")).status_code == 200


def test_missing_exp_or_sub(env):
    _assert_generic_401(env.get("/api/me", make_token(exp=None)))
    _assert_generic_401(env.get("/api/me", make_token(sub=None)))


def test_pending_session_rejected(env):
    _assert_generic_401(env.get("/api/me", make_token(sts="pending")))


def test_tampered_signature_and_payload(env):
    head, payload, sig = make_token("user_A").split(".")
    forged = b64({"sub": "user_B", "iss": ISSUER, "exp": int(time.time()) + 300, "azp": "https://app.test"})
    _assert_generic_401(env.get("/api/me", f"{head}.{forged}.{sig}"))
    _assert_generic_401(env.get("/api/me", f"{head}.{payload}.{sig[:-4]}AAAA"))


def test_signed_with_a_different_key(env):
    _assert_generic_401(env.get("/api/me", make_token(key=OTHER_PRIV)))


def test_unknown_kid(env):
    _assert_generic_401(env.get("/api/me", make_token(kid="nope")))


def test_alg_none(env):
    now = int(time.time())
    claims = {"sub": "user_A", "iss": ISSUER, "exp": now + 300, "azp": "https://app.test"}
    token = jwt.encode(claims, None, algorithm="none", headers={"kid": "test-kid"})
    _assert_generic_401(env.get("/api/me", token))
    _assert_generic_401(env.get("/api/me", f"{b64({'alg': 'none', 'kid': 'test-kid'})}.{b64(claims)}."))


def test_hs256_signed_with_the_public_key(env):
    """The classic algorithm-confusion attack: HMAC with the public PEM as the secret."""
    header = b64({"alg": "HS256", "typ": "JWT", "kid": "test-kid"})
    payload = b64({"sub": "user_A", "iss": ISSUER, "exp": int(time.time()) + 300, "azp": "https://app.test"})
    sig = hmac.new(PUB_PEM, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    _assert_generic_401(env.get("/api/me", f"{header}.{payload}.{b64(sig)}"))


def test_missing_and_malformed_authorization_header(env):
    _assert_generic_401(env.client.get("/api/me"))
    good = make_token()
    for value in ["", "Bearer", "Bearer ", good, f"Basic {good}", f"Bearer {good} extra", "Bearer not.a.jwt",
                  "Bearer " + "a" * 20000]:
        _assert_generic_401(env.client.get("/api/me", headers={"Authorization": value}))


def test_fails_closed_when_clerk_not_configured(env, monkeypatch):
    monkeypatch.delenv("CLERK_JWKS_URL")
    _assert_generic_401(env.get("/api/me", make_token()))
    monkeypatch.setenv("CLERK_JWKS_URL", JWKS_URL)
    monkeypatch.delenv("CLERK_ISSUER")
    _assert_generic_401(env.get("/api/me", make_token()))


def test_http_jwks_url_refused_in_production(env, monkeypatch):
    monkeypatch.setenv("CLERK_JWKS_URL", "http://clerk.verbatim.test/jwks.json")
    _assert_generic_401(env.get("/api/me", make_token()))


def test_jwks_fetch_failure_is_a_401_not_a_500(env, monkeypatch):
    def boom(url):
        raise OSError("network down")

    auth.jwks_cache.clear()
    monkeypatch.setattr(auth, "_fetch_jwks", boom)
    _assert_generic_401(env.get("/api/me", make_token()))


def test_unknown_kid_does_not_refetch_every_time(env, monkeypatch):
    calls = []
    monkeypatch.setattr(auth, "_fetch_jwks", lambda url: calls.append(url) or {"keys": [JWK]})
    for _ in range(5):
        env.get("/api/me", make_token(kid="junk"))
    assert len(calls) == 1


def test_data_routes_need_a_token(env):
    assert env.client.get("/api/datasets/1/profile").status_code == 401
    assert env.client.post("/api/upload", files={"file": ("a.csv", b"a,b\n1,2\n")}).status_code == 401


def test_dev_user_refused_in_production_even_if_flag_set(env, monkeypatch):
    monkeypatch.setenv("ALLOW_DEV_USER", "true")
    monkeypatch.setenv("ENV", "production")
    _assert_generic_401(env.client.get("/api/me"))
    assert env.client.post("/api/upload", files={"file": ("a.csv", b"a,b\n1,2\n")}).status_code == 401
    monkeypatch.delenv("ENV")  # unset means production too
    _assert_generic_401(env.client.get("/api/me"))


def test_dev_user_works_only_in_dev_with_flag(env, monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("ALLOW_DEV_USER", "true")
    assert env.client.get("/api/me").status_code == 200
    monkeypatch.delenv("ALLOW_DEV_USER")
    assert env.client.get("/api/me").status_code == 401


# ---------------------------------------------------------------- ownership
def test_user_b_cannot_see_user_a_dataset(env):
    ta, tb = make_token("user_A"), make_token("user_B")
    up = env.client.post(
        "/api/upload", files={"file": ("s.csv", FIX.read_bytes(), "text/csv")},
        headers={"Authorization": f"Bearer {ta}"},
    )
    assert up.status_code == 200, up.text
    ds_id = up.json()["id"]
    assert env.get(f"/api/datasets/{ds_id}/profile", ta).status_code == 200
    assert env.get(f"/api/datasets/{ds_id}/profile", tb).status_code == 404
    patch = env.client.patch(
        f"/api/datasets/{ds_id}/columns", json={"columns": []}, headers={"Authorization": f"Bearer {tb}"}
    )
    assert patch.status_code == 404


# ---------------------------------------------------------------- sign-in variant
def test_variant_valid_and_logged_without_personal_data(env):
    r = env.client.get("/api/signin-variant", headers={"User-Agent": "secret-agent/1.0"})
    assert r.status_code == 200
    variant = r.json()["variant"]
    assert variant in {"a", "b", "c", "d"}
    assert r.headers["cache-control"] == "no-store"
    with env.Session() as s:
        rows = s.scalars(select(SigninVariantLog)).all()
    assert [x.variant for x in rows] == [variant]
    assert {c.name for c in SigninVariantLog.__table__.columns} == {"id", "variant", "created_at"}


def test_variant_weights_honoured(env, monkeypatch):
    monkeypatch.setenv("SIGNIN_VARIANT_WEIGHTS", "a=0,b=1,c=0,d=0")
    assert {env.client.get("/api/signin-variant").json()["variant"] for _ in range(15)} == {"b"}
    monkeypatch.setenv("SIGNIN_VARIANT_WEIGHTS", "a=1,b=0,c=0,d=3")
    seen = Counter(env.client.get("/api/signin-variant").json()["variant"] for _ in range(200))
    assert set(seen) <= {"a", "d"} and seen["d"] > seen["a"]


def test_variant_default_is_equal_and_bad_weights_fall_back(env, monkeypatch):
    from app.api_auth import variant_weights

    monkeypatch.delenv("SIGNIN_VARIANT_WEIGHTS", raising=False)
    assert variant_weights() == [1, 1, 1, 1]
    for bad in ["", "zzz", "a=-1", "a=x", "a=0,b=0,c=0,d=0", "a=1,a=2", "e=1", "a=nan"]:
        monkeypatch.setenv("SIGNIN_VARIANT_WEIGHTS", bad)
        assert variant_weights() == [1, 1, 1, 1], bad
    seen = {env.client.get("/api/signin-variant").json()["variant"] for _ in range(80)}
    assert seen == {"a", "b", "c", "d"}


# ---------------------------------------------------------------- CSP
def test_csp_strict_without_clerk(monkeypatch):
    monkeypatch.delenv("CLERK_FRONTEND_API", raising=False)
    csp = TestClient(app).get("/health").headers["content-security-policy"]
    assert "clerk" not in csp and "cloudflare" not in csp
    assert "script-src 'self';" in csp


def test_csp_allows_clerk_when_configured(monkeypatch):
    monkeypatch.setenv("CLERK_FRONTEND_API", "clerk.verbatim.test")
    csp = TestClient(app).get("/health").headers["content-security-policy"]
    parts = {p.split()[0]: p for p in csp.split("; ") if p}
    for directive in ("script-src", "connect-src", "frame-src", "img-src"):
        assert "https://clerk.verbatim.test" in parts[directive], directive
    assert "https://img.clerk.com" in parts["img-src"]
    for directive in ("script-src", "frame-src", "connect-src"):
        assert "https://challenges.cloudflare.com" in parts[directive]
    assert "'unsafe-inline'" not in parts["script-src"] and "'unsafe-eval'" not in csp
    assert parts["default-src"] == "default-src 'self'"
    assert "frame-ancestors 'self'" in csp


def test_csp_ignores_hostile_frontend_api_value(monkeypatch):
    for bad in ["x.test; script-src *", "x.test\r\nSet-Cookie: a=b", "*", "localhost", "https://a.test/path"]:
        monkeypatch.setenv("CLERK_FRONTEND_API", bad)
        csp = TestClient(app).get("/health").headers["content-security-policy"]
        assert csp == build_csp(None), bad
    monkeypatch.setenv("CLERK_FRONTEND_API", "https://xx.clerk.accounts.dev/")
    assert "https://xx.clerk.accounts.dev" in TestClient(app).get("/health").headers["content-security-policy"]
