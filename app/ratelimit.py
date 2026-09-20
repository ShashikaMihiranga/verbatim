"""Web-layer protection for a public deployment: per-client rate limits and request body size guards.

Pure ASGI middleware (no BaseHTTPMiddleware, so nothing is buffered and it costs almost nothing per request).

Rate limits (per client IP, per minute, all env-configurable):
  RATE_LIMIT_API_PER_MIN     120  every /api route together
  RATE_LIMIT_UPLOAD_PER_MIN   10  POST /api/upload (also counts toward the /api total)
  RATE_LIMIT_AUTH_PER_MIN     30  /api/signin-variant and any /api/auth* route (also counts toward the /api total)
  RATE_LIMIT_OTHER_PER_MIN   300  everything that is not under /api (pages, assets, charts)
  RATE_LIMIT_WINDOW_SECONDS   60  the window; RATE_LIMIT_MAX_KEYS 50000 the memory cap
  RATE_LIMIT_ENABLED        true  set to false only for tests or local debugging
/health is exempt so the platform health check never gets a 429. Over the limit: 429, a Retry-After header and a
generic JSON body.

Method: a sliding-window counter (this window's count plus the previous window's count weighted by how much of it
still overlaps). It needs three numbers per client and bucket, so memory is bounded by MAX_KEYS entries in an LRU
map; expired entries are swept and, if the cap is still exceeded, the least recently used entries are evicted.

Client IP: the socket address by default. X-Forwarded-For is read ONLY when TRUST_PROXY=true (set it on Railway,
where the platform's proxy sets the header). Then the FIRST address in the header is used, as requested; if the
platform appends to a client-supplied header instead of replacing it, that first entry can be forged, so set
PROXY_XFF_POSITION=last to take the entry your own proxy added. With TRUST_PROXY off the header is never read, so a
spoofed X-Forwarded-For cannot dodge or share a limit. IPv6 clients are grouped by /64.

Body size guards (checked from the Content-Length header before any of the body is read):
  POST /api/upload           413 above MAX_UPLOAD_MB + 1 MB (defence in depth; the streaming check in api_upload stays)
  other /api requests        413 above MAX_API_BODY_KB (default 1024 KB) since the JSON bodies are small
A bad Content-Length header gets a 400.

LIMITS: state is in this process's memory, so with N instances (or N uvicorn workers) each one keeps its own
counters and a client can get up to N times the limit. When the app is scaled out, move the counters to Redis (INCR
with EXPIRE per bucket key, or a sliding-window Lua script) and keep this class's rules and IP logic as they are.
Also put a coarse limit at the platform edge if one is offered.
"""
from __future__ import annotations

import ipaddress
import math
import os
import re
import time
from collections import OrderedDict
from typing import Any, Callable

from starlette.responses import JSONResponse

DEFAULT_LIMITS = {"api": 120, "upload": 10, "auth": 30, "other": 300}
_ENV = {"api": "RATE_LIMIT_API_PER_MIN", "upload": "RATE_LIMIT_UPLOAD_PER_MIN", "auth": "RATE_LIMIT_AUTH_PER_MIN",
        "other": "RATE_LIMIT_OTHER_PER_MIN"}
_SLASHES = re.compile(r"/+")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def _env_true(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def normalise_path(path: str) -> str:
    """Lower case, one slash between segments, no trailing slash, so /API//upload/ is classified like /api/upload."""
    p = _SLASHES.sub("/", path or "/").rstrip("/").lower()
    return p or "/"


def classify(method: str, path: str) -> tuple[str, ...] | None:
    """The buckets a request counts against, or None when exempt."""
    p = normalise_path(path)
    if p == "/health":
        return None
    if p == "/api" or p.startswith("/api/"):
        if method == "POST" and p == "/api/upload":
            return ("api", "upload")
        if p == "/api/signin-variant" or p.startswith("/api/auth"):
            return ("api", "auth")
        return ("api",)
    return ("other",)


def _header(scope: dict, name: bytes) -> str | None:
    for k, v in scope.get("headers") or ():
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _ip_key(text: str) -> str | None:
    try:
        ip = ipaddress.ip_address(text.strip().strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


class RateLimitMiddleware:
    def __init__(self, app: Any, limits: dict[str, int] | None = None, window_seconds: float | None = None,
                 max_keys: int | None = None, trust_proxy: bool | None = None, enabled: bool | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self.limits = {k: _env_int(_ENV[k], v) for k, v in DEFAULT_LIMITS.items()}
        self.limits.update({k: int(v) for k, v in (limits or {}).items() if k in DEFAULT_LIMITS})
        self.window = float(window_seconds if window_seconds is not None else _env_int("RATE_LIMIT_WINDOW_SECONDS", 60))
        self.max_keys = int(max_keys if max_keys is not None else _env_int("RATE_LIMIT_MAX_KEYS", 50_000))
        self._trust_proxy = trust_proxy  # None means read TRUST_PROXY from the environment on each request
        self._enabled = enabled
        self.clock = clock
        # (bucket, client) -> [window_start, count_in_window, count_in_previous_window]
        self._state: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
        self._last_sweep = clock()

    # ------------------------------------------------------------ client identity
    def client_key(self, scope: dict) -> str:
        trust = self._trust_proxy if self._trust_proxy is not None else _env_true("TRUST_PROXY", False)
        if trust:
            xff = _header(scope, b"x-forwarded-for")
            if xff:
                parts = [p for p in (x.strip() for x in xff.split(",")) if p][:20]
                if parts:
                    pick = parts[-1] if os.environ.get("PROXY_XFF_POSITION", "first").lower() == "last" else parts[0]
                    key = _ip_key(pick)
                    if key:
                        return key
        client = scope.get("client")
        if client and client[0]:
            return _ip_key(str(client[0])) or str(client[0])[:64]
        return "unknown"

    # ------------------------------------------------------------ counters
    def _sweep(self, now: float) -> None:
        stale = [k for k, v in self._state.items() if now - v[0] >= 2 * self.window]
        for k in stale:
            del self._state[k]
        while len(self._state) > self.max_keys:
            self._state.popitem(last=False)  # least recently used

    def _load(self, bucket: str, client: str, now: float) -> list[float]:
        key = (bucket, client)
        st = self._state.get(key)
        if st is None:
            st = [now, 0.0, 0.0]
            self._state[key] = st
            if len(self._state) > self.max_keys or now - self._last_sweep >= self.window:
                self._last_sweep = now
                self._sweep(now)
        else:
            self._state.move_to_end(key)
            elapsed = now - st[0]
            if elapsed >= 2 * self.window:
                st[0], st[1], st[2] = now, 0.0, 0.0
            elif elapsed >= self.window:
                st[2], st[1] = st[1], 0.0
                st[0] += self.window
        return st

    def _estimate(self, st: list[float], now: float) -> float:
        frac = max(0.0, min(1.0, (now - st[0]) / self.window))
        return st[1] + st[2] * (1.0 - frac)

    def check(self, buckets: tuple[str, ...], client: str) -> int | None:
        """Count one request. Returns None when allowed, else the seconds to wait (nothing is counted then)."""
        now = self.clock()
        states = [(b, self._load(b, client, now)) for b in buckets]
        wait = 0
        for b, st in states:
            if self._estimate(st, now) + 1 > self.limits[b]:
                wait = max(wait, math.ceil(self.window - (now - st[0])) or 1)
        if wait:
            return max(1, wait)
        for _, st in states:
            st[1] += 1
        return None

    def keys_in_memory(self) -> int:
        return len(self._state)

    # ------------------------------------------------------------ ASGI
    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method", "GET")).upper()
        path = scope.get("path", "/")
        enabled = self._enabled if self._enabled is not None else _env_true("RATE_LIMIT_ENABLED", True)
        buckets = classify(method, path)
        if enabled and buckets is not None:
            wait = self.check(buckets, self.client_key(scope))
            if wait is not None:
                resp = JSONResponse({"detail": "Too many requests. Please wait a moment and try again."},
                                    status_code=429, headers={"Retry-After": str(wait)})
                await resp(scope, receive, send)
                return
        if buckets is not None and buckets[0] == "api":
            rejected = self._body_guard(method, path, scope)
            if rejected is not None:
                await rejected(scope, receive, send)
                return
        await self.app(scope, receive, send)

    # ------------------------------------------------------------ body size
    def _body_guard(self, method: str, path: str, scope: dict) -> JSONResponse | None:
        raw = _header(scope, b"content-length")
        if raw is None:
            return None  # chunked upload: the streaming check in the upload route enforces the size
        raw = raw.strip()
        if not raw.isdigit() or len(raw) > 15:
            return JSONResponse({"detail": "The request could not be read."}, status_code=400)
        size = int(raw)
        if method == "POST" and normalise_path(path) == "/api/upload":
            try:
                mb = float(os.environ.get("MAX_UPLOAD_MB", "50"))
            except ValueError:
                mb = 50.0
            limit = int((mb + 1) * 1024 * 1024)
            msg = "That file is too large."
        else:
            limit = _env_int("MAX_API_BODY_KB", 1024) * 1024
            msg = "That request is too large."
        if size > limit:
            return JSONResponse({"detail": msg}, status_code=413)
        return None
