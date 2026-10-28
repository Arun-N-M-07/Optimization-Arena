"""Production middleware (pure ASGI, no dependencies): security headers, body-size cap, per-caller rate limit, access log.

Nothing here logs headers, query strings or bodies, so tokens and participant code never reach the logs.
"""
import hashlib
import ipaddress
import logging
import os
import time
import uuid
from collections import defaultdict, deque

log = logging.getLogger("arena.access")

MAX_BODY_BYTES = 1_500_000          # code is capped at 200k chars; reports at 4×4k; this leaves room for JSON escaping
AUTHED_PER_MINUTE = 600             # a participant autosaving every 1.5 s plus polling stays far below this
ANON_PER_MINUTE = 600               # unauthenticated calls to anything but /api/public (they all fail fast with 401)
PUBLIC_PER_MINUTE = 6000            # /api/public/* is read-only and served from a 3 s cache, so it is cheap; and every viewer behind one
                                    # proxy/NAT (a lab, the Vercel frontend's egress) may share a single key: 100 viewers x 2 endpoints x 6/min = 1200
PUBLIC_PREFIX = "/api/public/"
MAX_TRUSTED_HOPS = 5


def _int_env(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return v if lo <= v <= hi else default


def rate_limit_settings() -> dict:
    """RateLimit keyword arguments from the environment. Invalid values fall back to the safe defaults (production start-up
    validation, settings_check, rejects them loudly instead)."""
    return {"authed": _int_env("RATE_LIMIT_AUTHED_PER_MINUTE", AUTHED_PER_MINUTE, 1, 1_000_000),
            "anon": _int_env("RATE_LIMIT_ANON_PER_MINUTE", ANON_PER_MINUTE, 1, 1_000_000),
            "public": _int_env("RATE_LIMIT_PUBLIC_PER_MINUTE", PUBLIC_PER_MINUTE, 1, 10_000_000),
            "trusted_hops": _int_env("TRUSTED_PROXY_HOPS", 0, 0, MAX_TRUSTED_HOPS)}


def client_ip(scope, trusted_hops: int = 0) -> str:
    """The caller's address for rate limiting, WITHOUT trusting client-supplied headers.

    X-Forwarded-For is a list that each proxy appends to; everything a client sends sits at its LEFT end and is attacker-controlled.
    Only entries appended by proxies we operate or trust are reliable, and those are at the RIGHT end. So:
      trusted_hops = 0  -> ignore every forwarding header; use the TCP peer (safe default, also correct when there is no proxy).
      trusted_hops = N  -> use the entry the N-th trusted proxy from the right appended (N=1 on Vercel, whose edge OVERWRITES
                           X-Forwarded-For with the address it saw and forwards no client-supplied values).
    If the header is shorter than N entries, or the chosen entry is not an IP address, the request did not come through the proxy
    chain we configured, so fall back to the peer. IPv6 addresses are keyed by /64 so a client cannot rotate through its prefix."""
    peer = (scope.get("client") or ("?", 0))[0]
    if trusted_hops <= 0:
        return peer
    raw = b",".join(v for k, v in scope["headers"] if k == b"x-forwarded-for")
    parts = [p.strip() for p in raw.decode("latin-1").split(",") if p.strip()]
    if len(parts) < trusted_hops:
        return peer
    try:
        ip = ipaddress.ip_address(parts[-trusted_hops])
    except ValueError:
        return peer
    if ip.version == 6:
        ip = ip.ipv4_mapped or ipaddress.ip_network(f"{ip}/64", strict=False).network_address
    return str(ip)


async def _send_json(send, status: int, detail: str, extra: list[tuple[bytes, bytes]] | None = None):
    body = ('{"detail":"%s"}' % detail).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *(extra or [])]})
    await send({"type": "http.response.body", "body": body})


class SecurityHeaders:
    def __init__(self, app, hsts: bool = False):
        self.app, self.hsts = app, hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wrapped(message):
            if message["type"] == "http.response.start":
                h = message.setdefault("headers", [])
                h += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer"),
                      (b"cache-control", b"no-store"), (b"cross-origin-resource-policy", b"same-site")]
                if self.hsts:
                    h.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
            await send(message)
        await self.app(scope, receive, wrapped)


class BodyLimit:
    """Rejects oversized bodies by Content-Length and, for chunked uploads, by counting bytes as they arrive."""

    def __init__(self, app, limit: int = MAX_BODY_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.limit:
            return await _send_json(send, 413, "Request body too large")
        seen = 0

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.limit:
                    raise _TooLarge()
            return msg
        try:
            await self.app(scope, limited, send)
        except _TooLarge:
            await _send_json(send, 413, "Request body too large")


class _TooLarge(Exception):
    pass


class RateLimit:
    """Sliding one-minute window per caller, in-process (each function instance counts separately, so limits are per instance).
    Authenticated calls are keyed by a hash of the bearer token. Everything else is keyed by client_ip(): /api/public/* gets its own
    higher bucket, other anonymous calls a lower one. See docs/DEPLOYMENT.md "Client IP and rate limiting"."""

    def __init__(self, app, authed: int = AUTHED_PER_MINUTE, anon: int = ANON_PER_MINUTE, public: int = PUBLIC_PER_MINUTE, trusted_hops: int = 0):
        self.app, self.authed, self.anon, self.public, self.trusted_hops = app, authed, anon, public, trusted_hops
        self.hits: dict[str, deque] = defaultdict(deque)
        self.last_prune = time.monotonic()

    def _key(self, scope) -> tuple[str, int]:
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization")
        if auth:
            return "t:" + hashlib.sha256(auth).hexdigest()[:16], self.authed
        ip = client_ip(scope, self.trusted_hops)
        if scope["path"].startswith(PUBLIC_PREFIX):
            return "pub:" + ip, self.public
        return "ip:" + ip, self.anon

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/api/health":
            return await self.app(scope, receive, send)
        now = time.monotonic()
        key, limit = self._key(scope)
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return await _send_json(send, 429, "Too many requests", [(b"retry-after", b"10")])
        q.append(now)
        if now - self.last_prune > 120:                      # drop idle callers so memory stays bounded
            self.last_prune = now
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                del self.hits[k]
        await self.app(scope, receive, send)


class AccessLog:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid.uuid4().hex[:12]
        start, status = time.perf_counter(), 500

        async def wrapped(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)
        scope.setdefault("state", {})["request_id"] = rid
        try:
            await self.app(scope, receive, wrapped)
        finally:
            if scope["path"] != "/api/health":
                log.info("%s %s %s %dms rid=%s", scope["method"], scope["path"], status, (time.perf_counter() - start) * 1000, rid)
