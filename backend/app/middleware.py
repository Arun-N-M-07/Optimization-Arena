"""Production middleware (pure ASGI, no dependencies): security headers, body-size cap, per-caller rate limit, access log.

Nothing here logs headers, query strings or bodies, so tokens and participant code never reach the logs.
"""
import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque

log = logging.getLogger("arena.access")

MAX_BODY_BYTES = 1_500_000          # code is capped at 200k chars; reports at 4×4k; this leaves room for JSON escaping
AUTHED_PER_MINUTE = 600             # a participant autosaving every 1.5 s plus polling stays far below this
ANON_PER_MINUTE = 600               # public pages poll lightly; many viewers can share one NAT/proxy address


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
    """Sliding one-minute window per caller (hash of the bearer token, else client address). In-process: one API instance."""

    def __init__(self, app, authed: int = AUTHED_PER_MINUTE, anon: int = ANON_PER_MINUTE):
        self.app, self.authed, self.anon = app, authed, anon
        self.hits: dict[str, deque] = defaultdict(deque)
        self.last_prune = time.monotonic()

    def _key(self, scope) -> tuple[str, int]:
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization")
        if auth:
            return "t:" + hashlib.sha256(auth).hexdigest()[:16], self.authed
        fwd = headers.get(b"x-forwarded-for")
        ip = fwd.split(b",")[0].strip().decode() if fwd else (scope.get("client") or ("?", 0))[0]
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
