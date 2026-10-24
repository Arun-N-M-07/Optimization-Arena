"""Authentication and authorization.

The browser sends its Supabase access token as a Bearer token. We validate it
with Supabase Auth (so revoked/expired sessions are rejected), then load the
role and team from `profiles` using the server-side secret key.
"""
from dataclasses import dataclass
from typing import Callable
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

ROLES = ("PARTICIPANT", "ADMIN", "JUDGE")

# One pooled client (keep-alive) instead of a TLS handshake per call.
_http = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), limits=httpx.Limits(max_keepalive_connections=20, max_connections=50))


def _upstream(method: str, url: str, *, retries: int = 1, **kw) -> httpx.Response:
    """Call Supabase. Network failures are retried (idempotent calls only) and surface as 503, never as a bare 500."""
    for attempt in range(retries + 1):
        try:
            return _http.request(method, url, **kw)
        except httpx.TransportError:
            if attempt == retries:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Authentication service is temporarily unavailable. Please retry.") from None
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None
    role: str
    team_id: UUID | None


class SupabaseGateway:
    """Thin wrapper over Supabase HTTP APIs; replaced by a fake in tests."""

    def __init__(self, settings: Settings):
        self.s = settings

    def get_auth_user(self, token: str) -> dict | None:
        r = _upstream("GET", f"{self.s.supabase_url}/auth/v1/user",
                      headers={"Authorization": f"Bearer {token}", "apikey": self.s.supabase_publishable_key})
        return r.json() if r.status_code == 200 else None

    def get_profile(self, user_id: str) -> dict | None:
        r = _upstream("GET", f"{self.s.supabase_url}/rest/v1/profiles",
                      params={"id": f"eq.{user_id}", "select": "id,email,role,team_id"},
                      headers={"apikey": self.s.supabase_secret_key, "Authorization": f"Bearer {self.s.supabase_secret_key}"})
        rows = r.json() if r.status_code == 200 else []
        return rows[0] if rows else None


    def create_auth_user(self, email: str, password: str, full_name: str) -> str:
        r = _upstream("POST", f"{self.s.supabase_url}/auth/v1/admin/users", retries=0,   # not idempotent: never auto-retried
                      headers={"apikey": self.s.supabase_secret_key, "Authorization": f"Bearer {self.s.supabase_secret_key}"},
                      json={"email": email, "password": password, "email_confirm": True, "user_metadata": {"full_name": full_name}})
        if r.status_code in (409, 422):
            raise HTTPException(status.HTTP_409_CONFLICT, "Could not create that account (email may already exist)")
        r.raise_for_status()
        return r.json()["id"]

    def delete_auth_user(self, user_id: str) -> None:
        _upstream("DELETE", f"{self.s.supabase_url}/auth/v1/admin/users/{user_id}",
                  headers={"apikey": self.s.supabase_secret_key, "Authorization": f"Bearer {self.s.supabase_secret_key}"})


def get_gateway() -> SupabaseGateway:
    return SupabaseGateway(get_settings())


def current_user(
    authorization: str | None = Header(default=None),
    gateway: SupabaseGateway = Depends(get_gateway),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    auth_user = gateway.get_auth_user(authorization[7:].strip())
    if not auth_user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    profile = gateway.get_profile(auth_user["id"])
    if not profile or profile["role"] not in ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No profile for this account")
    return CurrentUser(
        id=UUID(profile["id"]),
        email=profile.get("email"),
        role=profile["role"],
        team_id=UUID(profile["team_id"]) if profile.get("team_id") else None,
    )


def require_roles(*allowed: str) -> Callable[[CurrentUser], CurrentUser]:
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return dependency
