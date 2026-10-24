from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from .auth import CurrentUser, current_user, require_roles
from .routers import assignments, ops, participant, public, questions, review, teams, workspace

app = FastAPI(title="The Optimization Arena API", version="0.3.0")


@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def db_unavailable(_: Request, __: Exception):
    """A dropped/unreachable database connection is a retryable 503, not an opaque 500."""
    return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please retry."}, headers={"Retry-After": "2"})

app.include_router(teams.router)
app.include_router(questions.router)
app.include_router(assignments.router)
app.include_router(participant.router)
app.include_router(workspace.router)
app.include_router(review.router)
app.include_router(ops.router)
app.include_router(public.router)


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
