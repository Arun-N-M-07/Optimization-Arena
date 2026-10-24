"""Database access via SQLAlchemy.

Two ways to open a transaction:
- `admin_tx()`: runs as the pooler's `postgres` role. Used only for admin/staff
  operations that the backend has already authorized.
- `user_tx(user)`: same connection but `SET LOCAL ROLE authenticated` with the
  caller's identity in `request.jwt.claims`, so Postgres RLS applies exactly as
  it would for that user. Participant-facing reads use this.
Both are single transactions: commit on success, rollback on any error. SET LOCAL
means role and claims can never leak to the next pooled request.
"""
import json
import re
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from fastapi import HTTPException, status
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from .auth import CurrentUser
from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", get_settings().database_url)
    if not get_settings().database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    # prepare_threshold=None: safe with Supabase pooler (no server-side prepared statements).
    return create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=300,
                         connect_args={"prepare_threshold": None, "connect_timeout": 10})


@contextmanager
def admin_tx() -> Iterator[Connection]:
    with get_engine().begin() as conn:
        yield conn


@contextmanager
def user_tx(user: CurrentUser) -> Iterator[Connection]:
    with get_engine().begin() as conn:
        conn.execute(text("set local role authenticated"))
        claims = json.dumps({"sub": str(user.id), "role": "authenticated"})
        conn.execute(text("select set_config('request.jwt.claims', :c, true)"), {"c": claims})
        yield conn


_SQLSTATE = {"23505": 409, "P0001": 409, "23514": 422, "23503": 409}


def map_db_error(exc: DBAPIError) -> HTTPException:
    """Turn constraint/trigger failures into client errors; never leak SQL text."""
    code = getattr(exc.orig, "sqlstate", None)
    if code == "P0001":  # our own RAISE EXCEPTION messages are safe to show
        msg = str(exc.orig).split("\n")[0]
        return HTTPException(409, msg)
    if code == "23505":
        return HTTPException(409, "That value already exists")
    if code in _SQLSTATE:
        return HTTPException(_SQLSTATE[code], "The change violates a data rule")
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database error")


def audit(conn: Connection, actor: CurrentUser, action: str, entity: str, entity_id, details: dict | None = None) -> None:
    conn.execute(
        text("insert into public.audit_logs (actor_id, action, entity, entity_id, details) "
             "values (:a, :act, :e, :eid, cast(:d as jsonb))"),
        {"a": str(actor.id), "act": action, "e": entity, "eid": str(entity_id), "d": json.dumps(details or {})},
    )


def rows(conn: Connection, sql: str, **params) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def one(conn: Connection, sql: str, **params) -> dict | None:
    r = conn.execute(text(sql), params).first()
    return dict(r._mapping) if r else None
