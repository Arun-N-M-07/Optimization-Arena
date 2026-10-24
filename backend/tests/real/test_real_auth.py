"""REAL Supabase: genuine sign-in, genuine bearer tokens, genuine profile lookup."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from . import supa

pytestmark = pytest.mark.real_supabase


@pytest.fixture(scope="module")
def users():
    made = {"admin": supa.create_user("ADMIN"), "participant": supa.create_user("PARTICIPANT")}
    yield made
    for u in made.values():
        supa.delete_user(u["id"])


def bearer(u):
    return {"Authorization": f"Bearer {supa.sign_in(u['email'])}"}


def test_real_participant_me(users):
    r = TestClient(app).get("/api/me", headers=bearer(users["participant"]))
    assert r.status_code == 200 and r.json()["role"] == "PARTICIPANT"


def test_real_admin_me_and_admin_endpoint(users):
    c = TestClient(app)
    assert c.get("/api/me", headers=bearer(users["admin"])).json()["role"] == "ADMIN"
    assert c.get("/api/admin/ping", headers=bearer(users["admin"])).status_code == 200


def test_real_participant_blocked_from_admin(users):
    assert TestClient(app).get("/api/admin/ping", headers=bearer(users["participant"])).status_code == 403


def test_real_garbage_token_rejected():
    assert TestClient(app).get("/api/me", headers={"Authorization": "Bearer not.a.token"}).status_code == 401
