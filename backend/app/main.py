import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError

from .auth import CurrentUser, current_user, require_roles
from .config import get_settings
from .middleware import AccessLog, BodyLimit, RateLimit, SecurityHeaders
from .routers import assignments, ops, participant, public, questions, review, teams, workspace
from .settings_check import is_production, validate

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("arena")
PROD = is_production()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if PROD:                      # a misconfigured production API refuses to start instead of running permissively
        problems = validate(get_settings())
        if problems:
            for p in problems:
                log.error("config: %s", p)
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))
        log.info("production configuration validated")
    yield
    from .db import get_engine
    try:
        get_engine().dispose()    # graceful shutdown: return pooled connections
    except Exception:
        pass


app = FastAPI(title="The Optimization Arena API", version="0.4.0", lifespan=lifespan,
              docs_url=None if PROD else "/docs", redoc_url=None, openapi_url=None if PROD else "/openapi.json")
# Outermost first: log everything, then cap body size, then rate limit, then add headers.
app.add_middleware(SecurityHeaders, hsts=PROD)
app.add_middleware(RateLimit)
app.add_middleware(BodyLimit)
app.add_middleware(AccessLog)
# No CORS middleware on purpose: the browser only talks to the API through the same-origin /api rewrite.


@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def db_unavailable(_: Request, __: Exception):
    """A dropped/unreachable database connection is a retryable 503, not an opaque 500."""
    return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please retry."}, headers={"Retry-After": "2"})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Never leak internals (SQL, paths, participant content) to clients; log the type and a request id only."""
    rid = request.scope.get("state", {}).get("request_id", "-")
    log.error("unhandled %s on %s %s rid=%s", type(exc).__name__, request.method, request.url.path, rid)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": rid})

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
    """Liveness only: does not touch the database, so a DB blip never makes the host restart the process."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready() -> JSONResponse:
    """Readiness: the database answers. Used by monitors; reports which risky modes are active (no secrets)."""
    from .db import admin_tx
    s = get_settings()
    try:
        t0 = time.perf_counter()
        with admin_tx() as c:
            c.execute(text("select 1"))
        db_ms = round((time.perf_counter() - t0) * 1000)
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": False})
    return JSONResponse({"status": "ready", "database": True, "db_ms": db_ms,
                         "judge_provider": os.getenv("JUDGE_PROVIDER", "disabled"),
                         "evaluation_mode": os.getenv("EVALUATION_MODE", "background"),
                         "gemini_configured": bool(s.gemini_api_key), "environment": "production" if PROD else "development"})


@app.get("/api/me")
def me(user: CurrentUser = Depends(current_user)) -> dict:
    return {"id": str(user.id), "email": user.email, "role": user.role,
            "team_id": str(user.team_id) if user.team_id else None}


@app.get("/api/admin/ping")
def admin_ping(user: CurrentUser = Depends(require_roles("ADMIN"))) -> dict:
    return {"ok": True}
