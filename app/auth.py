"""Clerk session-token verification (public JWKS only; the Clerk secret key is never needed).

Rules: `Authorization: Bearer <jwt>`, RS256 only, signature checked against the JWKS at CLERK_JWKS_URL,
`iss` must equal CLERK_ISSUER, `exp`/`nbf` checked with a small leeway, `azp` checked against the optional
CLERK_AUTHORIZED_PARTIES allow-list. Every failure gives the same generic 401 so nothing helps an attacker;
the real reason goes to the server log only. Fails closed when the Clerk settings are missing.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request

import jwt
from fastapi import HTTPException, Request
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .models import User

log = logging.getLogger("verbatim.auth")

LEEWAY_SECONDS = 10
MAX_TOKEN_BYTES = 8192
JWKS_MIN_REFRESH_SECONDS = 60  # an unknown `kid` can trigger at most one refetch per minute
JWKS_MAX_AGE_SECONDS = 3600
JWKS_TIMEOUT_SECONDS = 5
JWKS_MAX_BYTES = 256 * 1024


def unauthorized() -> HTTPException:
    return HTTPException(401, "Sign-in is required.", headers={"WWW-Authenticate": "Bearer"})


# ---------------------------------------------------------------- settings (read per call)
def _setting(env_name: str, attr: str) -> str | None:
    value = os.environ.get(env_name)
    if value is None:
        value = getattr(get_settings(), attr, None)
    value = str(value).strip() if value is not None else ""
    return value or None


def app_env() -> str:
    return (_setting("ENV", "env") or "production").lower()


def dev_user_allowed() -> bool:
    """The shared dev user exists only when ENV=dev AND ALLOW_DEV_USER=true, never in production."""
    return app_env() == "dev" and os.environ.get("ALLOW_DEV_USER", "").strip().lower() == "true"


def authorized_parties() -> list[str]:
    raw = _setting("CLERK_AUTHORIZED_PARTIES", "clerk_authorized_parties") or ""
    return [p.strip() for p in raw.split(",") if p.strip()]


# ---------------------------------------------------------------- JWKS cache
def _fetch_jwks(url: str) -> dict:
    """Network fetch of the public key set. Tests replace this function."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=JWKS_TIMEOUT_SECONDS) as resp:  # https is enforced in verify_token
        data = resp.read(JWKS_MAX_BYTES + 1)
    if len(data) > JWKS_MAX_BYTES:
        raise ValueError("JWKS too large")
    return json.loads(data)


class _JwksCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, object] = {}
        self._url: str | None = None
        self._fetched_at = 0.0

    def clear(self) -> None:
        with self._lock:
            self._keys, self._url, self._fetched_at = {}, None, 0.0

    def get(self, url: str, kid: str):
        with self._lock:
            now = time.monotonic()
            same = self._url == url
            stale = not same or now - self._fetched_at > JWKS_MAX_AGE_SECONDS
            if same and not stale and kid in self._keys:
                return self._keys[kid]
            # Unknown kid: refetch at most once per JWKS_MIN_REFRESH_SECONDS, so junk tokens cannot hammer Clerk.
            if same and not stale and now - self._fetched_at < JWKS_MIN_REFRESH_SECONDS:
                raise LookupError("unknown kid")
            doc = _fetch_jwks(url)
            keys: dict[str, object] = {}
            for jwk in doc.get("keys", []):
                if jwk.get("kty") == "RSA" and jwk.get("kid") and jwk.get("use", "sig") == "sig":
                    keys[jwk["kid"]] = RSAAlgorithm.from_jwk(json.dumps(jwk))
            self._keys, self._url, self._fetched_at = keys, url, now
            if kid not in keys:
                raise LookupError("unknown kid")
            return keys[kid]


jwks_cache = _JwksCache()


# ---------------------------------------------------------------- verification
def verify_token(token: str) -> dict:
    """Return the verified claims or raise ValueError (the caller turns that into a generic 401)."""
    jwks_url = _setting("CLERK_JWKS_URL", "clerk_jwks_url")
    issuer = _setting("CLERK_ISSUER", "clerk_issuer")
    if not jwks_url or not issuer:
        raise ValueError("CLERK_JWKS_URL / CLERK_ISSUER are not set")  # fail closed
    if not jwks_url.lower().startswith("https://") and app_env() != "dev":
        raise ValueError("CLERK_JWKS_URL must be https")
    if len(token) > MAX_TOKEN_BYTES:
        raise ValueError("token too large")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise ValueError("malformed token") from e
    if header.get("alg") != "RS256":  # rejects none, HS*, ES*, PS* before any key is looked up
        raise ValueError("algorithm not allowed")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise ValueError("no kid")
    try:
        key = jwks_cache.get(jwks_url, kid)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iss", "sub"], "verify_aud": False},
        )
    except (jwt.PyJWTError, LookupError, OSError, ValueError) as e:
        raise ValueError(f"verification failed: {type(e).__name__}") from e

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > 255:
        raise ValueError("bad sub")
    parties = authorized_parties()
    if parties and claims.get("azp") not in parties:
        raise ValueError("azp not allowed")
    if claims.get("sts") not in (None, "active"):  # Clerk 'pending' sessions are not signed in yet
        raise ValueError("session not active")
    return claims


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


def user_for_subject(db: Session, sub: str) -> User:
    user = db.scalar(select(User).where(User.clerk_id == sub))
    if user is not None:
        return user
    user = User(clerk_id=sub)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two first requests at once: the other one won
        db.rollback()
        user = db.scalar(select(User).where(User.clerk_id == sub))
        if user is None:
            raise
    return user


def authenticate(request: Request, db: Session) -> tuple[User, dict]:
    """Return (user, claims); the dev user has empty claims."""
    if dev_user_allowed():
        return user_for_subject(db, "dev-user"), {}
    token = bearer_token(request)
    if token is None:
        raise unauthorized()
    try:
        claims = verify_token(token)
    except ValueError as e:
        log.info("auth rejected: %s", e)
        raise unauthorized() from None
    return user_for_subject(db, claims["sub"]), claims
