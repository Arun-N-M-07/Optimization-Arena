from fastapi import Depends, FastAPI

from .auth import CurrentUser, current_user, require_roles

app = FastAPI(title="The Optimization Arena API", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email, "role": user.role,
            "team_id": str(user.team_id) if user.team_id else None}


@app.get("/api/admin/ping")
def admin_ping(user: CurrentUser = Depends(require_roles("ADMIN"))) -> dict:
    return {"ok": True}
