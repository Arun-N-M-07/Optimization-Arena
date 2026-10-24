"""Production hardening: headers, body/rate limits, sanitized errors, fail-fast config, Judge0 adapter, CSV, worker."""
import base64
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import middleware, settings_check, worker
from app.config import Settings
from app.judge0_provider import Judge0Provider
from app.judge_provider import JudgeRequest, TestCase
from app.main import app
from app.routers import ops


# ---------------- middleware ----------------
def test_security_headers_and_request_id_on_every_response():
    r = TestClient(app).get("/api/health")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    assert h["cache-control"] == "no-store" and h["x-request-id"]


def test_health_is_liveness_only_and_does_not_touch_the_database(monkeypatch):
    from app import db
    monkeypatch.setattr(db, "get_engine", lambda: (_ for _ in ()).throw(AssertionError("health must not use the DB")))
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def _mini(**limits):
    a = FastAPI()
    a.add_middleware(middleware.RateLimit, **limits)
    a.add_middleware(middleware.BodyLimit, limit=1000)

    @a.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}

    @a.get("/ping")
    def ping():
        return {"ok": 1}
    return TestClient(a)


def test_oversized_body_is_rejected_by_content_length():
    c = _mini()
    assert c.post("/echo", content=b"x" * 5000).status_code == 413


def test_oversized_chunked_body_is_rejected_without_content_length():
    c = _mini()

    def gen():
        for _ in range(10):
            yield b"x" * 500
    assert c.post("/echo", content=gen()).status_code == 413


def test_rate_limit_is_per_caller_and_returns_retry_after():
    c = _mini(authed=3, anon=3)
    a = {"Authorization": "Bearer user-a"}
    assert [c.get("/ping", headers=a).status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/ping", headers=a)
    assert r.status_code == 429 and r.headers["retry-after"] == "10"
    assert c.get("/ping", headers={"Authorization": "Bearer user-b"}).status_code == 200      # other callers unaffected
    assert [c.get("/ping").status_code for _ in range(4)][-1] == 429                             # anonymous: by address


def test_unhandled_errors_never_leak_internals():
    from app.main import app as real
    secret = "postgresql://user:SECRETPASSWORD@host/db"

    @real.get("/api/_boom_test")
    def boom():
        raise RuntimeError(f"connect failed {secret} participant code: print('x')")
    try:
        r = TestClient(real, raise_server_exceptions=False).get("/api/_boom_test")
    finally:
        real.router.routes[:] = [x for x in real.router.routes if getattr(x, "path", "") != "/api/_boom_test"]
    assert r.status_code == 500 and r.json()["detail"] == "Internal server error" and r.json()["request_id"]
    assert "SECRETPASSWORD" not in r.text and "RuntimeError" not in r.text and "print(" not in r.text


# ---------------- fail-fast production config ----------------
GOOD = Settings(supabase_url="https://x.supabase.co", supabase_publishable_key="sb_publishable_x", supabase_secret_key="sb_secret_x",
                gemini_api_key="g", gemini_model="gemini-3.5-flash-lite", database_url="postgresql://u:p@aws-0-eu.pooler.supabase.com:5432/postgres")


def test_good_production_config_passes(monkeypatch):
    monkeypatch.setenv("JUDGE_PROVIDER", "disabled")
    monkeypatch.setenv("EVALUATION_MODE", "worker")
    assert settings_check.validate(GOOD) == []


@pytest.mark.parametrize("env,expected", [
    ({"JUDGE_PROVIDER": "mock"}, "mock"),
    ({"JUDGE_PROVIDER": "evil"}, "not a known provider"),
    ({"EVALUATION_MODE": "yolo"}, "EVALUATION_MODE"),
])
def test_dangerous_production_settings_are_refused(monkeypatch, env, expected):
    monkeypatch.setenv("JUDGE_PROVIDER", "disabled")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert any(expected in p for p in settings_check.validate(GOOD))


def test_missing_secrets_and_direct_db_host_are_refused(monkeypatch):
    monkeypatch.setenv("JUDGE_PROVIDER", "disabled")
    bad = Settings("", "", "", "", "gemini-3.5-flash-lite", "postgresql://u:p@db.x.supabase.co:5432/postgres")
    probs = " | ".join(settings_check.validate(bad))
    for needle in ("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SECRET_KEY", "pooler", "GEMINI_API_KEY"):
        assert needle in probs


def test_production_refuses_to_start_when_misconfigured(monkeypatch):
    import importlib

    import app.main as m
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JUDGE_PROVIDER", "mock")
    importlib.reload(m)
    try:
        with pytest.raises(RuntimeError, match="Invalid production configuration"):
            with TestClient(m.app):
                pass
        assert m.app.docs_url is None and m.app.openapi_url is None            # no API explorer in production
    finally:
        monkeypatch.delenv("APP_ENV")
        importlib.reload(m)


# ---------------- Judge0 adapter (fake transport; NOT a live-service test) ----------------
def _j0(responses, seen=None):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append((str(request.url), dict(request.headers), body))
        r = responses.pop(0)
        return httpx.Response(200, json=r) if isinstance(r, dict) else r
    return Judge0Provider("https://j0.example", "tok", httpx.Client(transport=httpx.MockTransport(handler)))


def _req(n=2, lang="python"):
    return JudgeRequest(language=lang, code="print(1)", tests=[TestCase(input="1", expected_output="1")] * n)


def test_judge0_accepted_requires_every_test_to_pass_and_never_sends_network_or_unbounded_output():
    seen = []
    p = _j0([{"status": {"id": 3}, "time": "0.01", "memory": 900}] * 2, seen)
    res = p.run(_req())
    assert res.outcome == "ACCEPTED" and res.passed == 2 and res.total == 2 and res.provider == "judge0" and not res.is_mock
    url, headers, body = seen[0]
    assert "wait=true" in url and headers["x-auth-token"] == "tok"
    assert body["enable_network"] is False and body["max_file_size"] <= 1024 and body["cpu_time_limit"] == 2.0
    assert base64.b64decode(body["expected_output"]) == b"1"                      # expected output stays server-side, sent only to the judge


@pytest.mark.parametrize("sid,outcome", [(4, "WRONG_ANSWER"), (5, "TIME_LIMIT_EXCEEDED"), (11, "RUNTIME_ERROR"), (12, "RUNTIME_ERROR")])
def test_judge0_status_mapping(sid, outcome):
    res = _j0([{"status": {"id": 3}}, {"status": {"id": sid}}]).run(_req())
    assert res.outcome == outcome and res.passed == 1


def test_judge0_compile_error_returns_clipped_compiler_text():
    msg = base64.b64encode(b"error: boom\n" * 1000).decode()
    res = _j0([{"status": {"id": 6}, "compile_output": msg}]).run(_req())
    assert res.outcome == "COMPILATION_ERROR" and len(res.message) <= 2000


def test_judge0_provider_failures_are_system_errors_never_wrong_answers():
    for responses in ([httpx.Response(503)], [httpx.Response(200, text="not json")], [{"status": {"id": 13}}], [{"status": {"id": 14}}]):
        res = _j0(list(responses)).run(_req())
        assert res.outcome == "SYSTEM_ERROR"
    assert Judge0Provider("", "").run(_req()).outcome == "SYSTEM_ERROR"            # unconfigured
    assert _j0([]).run(_req(lang="sql")).outcome == "SYSTEM_ERROR"                  # unsupported language


def test_a_participant_cannot_fabricate_a_result_the_api_has_no_endpoint_for_it():
    paths = {r.path for r in app.routes if hasattr(r, "methods")}
    writers = [p for p in paths if p.startswith("/api/participant") and any(k in p for k in ("result", "outcome", "verdict", "score"))]
    assert writers == []                                                             # results exist only as a product of the judge call


# ---------------- CSV and worker ----------------
def test_csv_neutralises_spreadsheet_formulas():
    r = ops._csv("x", ["name"], [["=HYPERLINK(\"http://evil\")"], ["+cmd"], ["-1+1"], ["@SUM(1)"], ["safe"]])
    lines = r.body.decode().splitlines()[1:]
    assert all(l.startswith(("\"'", "'")) for l in lines[:4]) and lines[4] == "safe"
    assert r.headers["content-type"].startswith("text/csv")


def test_worker_survives_failures_and_stops_on_signal(monkeypatch):
    calls = {"n": 0}

    def flaky(limit=10):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db blip")
        worker._stop = True
        return {"abcdef123456": "COMPLETED"}
    monkeypatch.setattr(worker.evaluation, "run_pending", flaky)
    monkeypatch.setenv("WORKER_INTERVAL_SECONDS", "0.1")
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    worker._stop = False
    worker.main()
    assert calls["n"] == 2 and worker._stop is True       # one failure was survived, then it processed and exited cleanly
    worker._stop = False


# ---------------- latency work: token cache and idle-only connection verification ----------------
class CountingGateway:
    def __init__(self, role="PARTICIPANT"):
        self.auth_calls = self.profile_calls = 0
        self.role = role

    def get_auth_user(self, token):
        self.auth_calls += 1
        return {"id": "11111111-1111-1111-1111-111111111111"} if token != "bad" else None

    def get_profile(self, uid):
        self.profile_calls += 1
        return {"id": uid, "email": "p@x.io", "role": self.role, "team_id": None}


def _client_with(gw):
    from app.auth import get_gateway
    app.dependency_overrides[get_gateway] = lambda: gw
    return TestClient(app)


def test_validated_tokens_are_cached_so_repeat_requests_skip_both_supabase_calls(monkeypatch):
    monkeypatch.setenv("AUTH_CACHE_SECONDS", "30")
    gw = CountingGateway()
    try:
        c = _client_with(gw)
        for _ in range(5):
            assert c.get("/api/me", headers={"Authorization": "Bearer tok-1"}).json()["role"] == "PARTICIPANT"
        assert (gw.auth_calls, gw.profile_calls) == (1, 1)
        c.get("/api/me", headers={"Authorization": "Bearer tok-2"})            # a different token is validated on its own
        assert gw.auth_calls == 2
    finally:
        app.dependency_overrides.clear()


def test_failed_validations_are_never_cached(monkeypatch):
    monkeypatch.setenv("AUTH_CACHE_SECONDS", "30")
    gw = CountingGateway()
    try:
        c = _client_with(gw)
        assert [c.get("/api/me", headers={"Authorization": "Bearer bad"}).status_code for _ in range(3)] == [401, 401, 401]
        assert gw.auth_calls == 3
    finally:
        app.dependency_overrides.clear()


def test_a_role_change_or_revocation_is_honoured_after_the_ttl(monkeypatch):
    import time
    monkeypatch.setenv("AUTH_CACHE_SECONDS", "0.2")
    gw = CountingGateway("PARTICIPANT")
    try:
        c = _client_with(gw)
        h = {"Authorization": "Bearer tok-r"}
        assert c.get("/api/admin/ping", headers=h).status_code == 403
        gw.role = "ADMIN"                                                       # promoted in the database
        assert c.get("/api/admin/ping", headers=h).status_code == 403            # still within the TTL: documented trade-off
        time.sleep(0.3)
        assert c.get("/api/admin/ping", headers=h).status_code == 200            # TTL passed: fresh lookup
        gw.role = "PARTICIPANT"
        time.sleep(0.3)
        assert c.get("/api/admin/ping", headers=h).status_code == 403            # demotion also takes effect
    finally:
        app.dependency_overrides.clear()


def test_cache_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AUTH_CACHE_SECONDS", "0")
    gw = CountingGateway()
    try:
        c = _client_with(gw)
        for _ in range(3):
            c.get("/api/me", headers={"Authorization": "Bearer t"})
        assert gw.auth_calls == 3
    finally:
        app.dependency_overrides.clear()


def test_connections_are_pinged_only_after_sitting_idle():
    import time

    from sqlalchemy import exc as sa_exc

    from app import db

    class Rec:
        def __init__(self, last):
            self.info = {"last_used": last} if last is not None else {}

    class Cur:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            self.conn.executed.append(sql)
            if self.conn.dead:
                raise RuntimeError("server closed the connection")

    class Conn:
        def __init__(self, dead=False):
            self.executed, self.dead = [], dead

        def cursor(self):
            return Cur(self)

    busy = Conn()
    db._verify_if_idle(busy, Rec(time.monotonic()), None)
    assert busy.executed == []                                     # used a moment ago: no extra round trip
    idle = Conn()
    db._verify_if_idle(idle, Rec(time.monotonic() - 60), None)
    assert idle.executed == ["select 1"]                           # idle: verified
    with pytest.raises(sa_exc.DisconnectionError):
        db._verify_if_idle(Conn(dead=True), Rec(None), None)       # dead: discarded so SQLAlchemy reconnects


def test_connect_hook_sets_session_timeouts_and_commits():
    from app import db

    class Cur:
        def __init__(self, log):
            self.log = log

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            self.log.append(sql)

    class Conn:
        def __init__(self):
            self.log, self.committed = [], False

        def cursor(self):
            return Cur(self.log)

        def commit(self):
            self.committed = True
    c = Conn()
    db._set_session_timeouts(c, None)
    assert "idle_in_transaction_session_timeout = '60s'" in c.log[0] and "lock_timeout = '15s'" in c.log[0] and c.committed


def test_public_cache_never_stores_a_result_computed_across_an_invalidation():
    """A slow reader that started before a write and finishes after the cache was cleared must not repopulate it with stale data."""
    import threading

    from app import pubcache
    pubcache.clear()
    started, release, results = threading.Event(), threading.Event(), {}

    def slow_reader():
        def compute():
            started.set()
            release.wait(5)
            return "STALE (snapshot taken before the write)"
        results["slow"] = pubcache.cached("k", compute)
    t = threading.Thread(target=slow_reader)
    t.start()
    assert started.wait(5)
    pubcache.clear()                         # the writer commits and invalidates while the reader is still computing
    release.set()
    t.join()
    assert results["slow"].startswith("STALE")                    # the slow reader's own response is its own snapshot
    assert pubcache.cached("k", lambda: "FRESH") == "FRESH"       # ...but the next reader recomputes instead of seeing it cached
    assert pubcache.cached("k", lambda: "SHOULD-NOT-RUN") == "FRESH"   # and normal caching still works


def test_public_cache_ttl_and_clear():
    from app import pubcache
    pubcache.clear()
    n = {"c": 0}

    def f():
        n["c"] += 1
        return n["c"]
    assert [pubcache.cached("x", f) for _ in range(3)] == [1, 1, 1]
    pubcache.clear()
    assert pubcache.cached("x", f) == 2
