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
