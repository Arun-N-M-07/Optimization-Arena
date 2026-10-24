import pytest
from fastapi.testclient import TestClient

from app.auth import get_gateway
from app.main import app

UID = "11111111-1111-1111-1111-111111111111"
TID = "22222222-2222-2222-2222-222222222222"


class FakeGateway:
    PROFILES = {
        "tok-participant": {"id": UID, "email": "p@x.io", "role": "PARTICIPANT", "team_id": TID},
        "tok-admin": {"id": UID, "email": "a@x.io", "role": "ADMIN", "team_id": None},
        "tok-judge": {"id": UID, "email": "j@x.io", "role": "JUDGE", "team_id": None},
        "tok-noprofile": None,
    }

    def get_auth_user(self, token):
        return {"id": UID} if token in self.PROFILES else None

    def get_profile(self, user_id):
        return None  # overridden per token below


@pytest.fixture
def client():
    class G(FakeGateway):
        token = None

        def get_auth_user(self, token):
            G.token = token
            return super().get_auth_user(token)

        def get_profile(self, user_id):
            return self.PROFILES.get(G.token)

    app.dependency_overrides[get_gateway] = lambda: G()
    yield TestClient(app)
    app.dependency_overrides.clear()


def h(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_missing_token_rejected(client):
    assert client.get("/api/me").status_code == 401


def test_invalid_token_rejected(client):
    assert client.get("/api/me", headers=h("bogus")).status_code == 401


def test_account_without_profile_forbidden(client):
    assert client.get("/api/me", headers=h("tok-noprofile")).status_code == 403


def test_me_returns_role_and_team(client):
    body = client.get("/api/me", headers=h("tok-participant")).json()
    assert body["role"] == "PARTICIPANT" and body["team_id"] == TID


@pytest.mark.parametrize("token,code", [("tok-participant", 403), ("tok-judge", 403), ("tok-admin", 200)])
def test_admin_endpoint_role_enforcement(client, token, code):
    assert client.get("/api/admin/ping", headers=h(token)).status_code == code


def test_upstream_network_failure_is_a_503_not_a_500(monkeypatch):
    """A transient Supabase outage must not surface as an unhandled 500."""
    import httpx

    from app import auth

    calls = []

    def boom(method, url, **kw):
        calls.append(1)
        raise httpx.ConnectTimeout("handshake timed out")
    monkeypatch.setattr(auth._http, "request", boom)
    r = TestClient(app).get("/api/me", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"]
    assert len(calls) == 2                       # one retry for an idempotent GET


def test_upstream_blip_is_retried_transparently(monkeypatch):
    import httpx

    from app import auth

    state = {"n": 0}

    class R:
        status_code = 200

        def json(self):
            return {"id": "11111111-1111-1111-1111-111111111111"} if state["n"] == 2 else [{"id": "11111111-1111-1111-1111-111111111111", "email": "a@x.io", "role": "ADMIN", "team_id": None}]

    def flaky(method, url, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectTimeout("blip")
        return R()
    monkeypatch.setattr(auth._http, "request", flaky)
    gw = auth.SupabaseGateway(auth.get_settings())
    assert gw.get_auth_user("tok") == {"id": "11111111-1111-1111-1111-111111111111"}      # first call failed, retry succeeded


def test_database_connection_loss_is_a_retryable_503(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy.exc import OperationalError

    from app.routers import participant

    @contextmanager
    def broken(*a, **k):
        raise OperationalError("select 1", {}, Exception("server closed the connection unexpectedly"))
        yield
    monkeypatch.setattr(participant, "user_tx", broken)

    class G:
        def get_auth_user(self, t):
            return {"id": "11111111-1111-1111-1111-111111111111"}

        def get_profile(self, i):
            return {"id": i, "email": "p@x.io", "role": "PARTICIPANT", "team_id": "22222222-2222-2222-2222-222222222222"}
    app.dependency_overrides[get_gateway] = lambda: G()
    try:
        r = TestClient(app).get("/api/participant/team", headers={"Authorization": "Bearer t"})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503 and "temporarily unavailable" in r.json()["detail"] and r.headers["retry-after"] == "2"
    assert "server closed" not in r.text                       # no internals leaked
