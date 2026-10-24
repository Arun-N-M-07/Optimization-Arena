"""Helpers for tests against the REAL Supabase project. Never print keys."""
import uuid

import httpx

from app.config import get_settings

S = get_settings()
ADMIN_H = {"apikey": S.supabase_secret_key, "Authorization": f"Bearer {S.supabase_secret_key}"}
PASSWORD = "Arena-test-" + uuid.uuid4().hex[:12]


def create_user(role: str = "PARTICIPANT", team_id: str | None = None) -> dict:
    email = f"arena-test-{uuid.uuid4().hex[:10]}@example.com"
    r = httpx.post(f"{S.supabase_url}/auth/v1/admin/users", headers=ADMIN_H, timeout=15,
                   json={"email": email, "password": PASSWORD, "email_confirm": True})
    r.raise_for_status()
    uid = r.json()["id"]
    patch = {"role": role, "team_id": team_id}
    p = httpx.patch(f"{S.supabase_url}/rest/v1/profiles", params={"id": f"eq.{uid}"},
                    headers={**ADMIN_H, "Prefer": "return=minimal"}, json=patch, timeout=15)
    p.raise_for_status()
    return {"id": uid, "email": email}


def sign_in(email: str) -> str:
    r = httpx.post(f"{S.supabase_url}/auth/v1/token?grant_type=password", timeout=15,
                   headers={"apikey": S.supabase_publishable_key},
                   json={"email": email, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


def delete_user(uid: str) -> None:
    httpx.delete(f"{S.supabase_url}/auth/v1/admin/users/{uid}", headers=ADMIN_H, timeout=15)
