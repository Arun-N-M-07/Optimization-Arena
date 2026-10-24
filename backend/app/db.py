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
import os
import re
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from fastapi import HTTPException, status
from sqlalchemy import Connection, create_engine, event, exc as sa_exc, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from . import pubcache
from .auth import CurrentUser
from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", get_settings().database_url)
    if not get_settings().database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    # prepare_threshold=None: safe with Supabase pooler (no server-side prepared statements).
    # TCP keepalives + short recycle keep pooler connections from going stale. Instead of pre_ping on EVERY checkout (one extra
    # network round trip per request), connections are verified only after sitting idle (see _verify_if_idle).
    engine = create_engine(url, pool_size=int(os.getenv("DB_POOL_SIZE", "6")), max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")), pool_timeout=20, pool_pre_ping=False, pool_recycle=120, hide_parameters=True,
                         connect_args={"prepare_threshold": None, "connect_timeout": 10, "keepalives": 1,
                                       "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3})
    event.listen(engine, "connect", _set_session_timeouts)
    event.listen(engine, "checkout", _verify_if_idle)
    event.listen(engine, "checkin", lambda dbapi, rec: rec.info.__setitem__("last_used", time.monotonic()))
    return engine


IDLE_VERIFY_SECONDS = 10


def _set_session_timeouts(dbapi_conn, record):
    """A client that dies mid-transaction must not leave an orphaned session holding row locks (seen: 16+ min on a report row
    behind the pooler). Postgres itself ends such sessions. Set per connection because the pooler reuses backend sessions, so
    role-level defaults (migration 7) do not reliably apply."""
    with dbapi_conn.cursor() as cur:
        cur.execute("set idle_in_transaction_session_timeout = '60s'; set lock_timeout = '15s'")
    dbapi_conn.commit()


def _verify_if_idle(dbapi_conn, record, proxy):
    """A busy connection is known-good; one idle for a while may have been dropped by the pooler, so ping it first."""
    if time.monotonic() - record.info.get("last_used", 0) < IDLE_VERIFY_SECONDS:
        return
    try:
        with dbapi_conn.cursor() as cur:
            cur.execute("select 1")
    except Exception as e:                     # tells SQLAlchemy to discard this connection and open a fresh one
        raise sa_exc.DisconnectionError() from e


@contextmanager
def admin_tx() -> Iterator[Connection]:
    pubcache.reset()
    with get_engine().begin() as conn:
        yield conn
    pubcache.flush_if_changed()          # reached only after a successful commit


@contextmanager
def user_tx(user: CurrentUser) -> Iterator[Connection]:
    with get_engine().begin() as conn:
        claims = json.dumps({"sub": str(user.id), "role": "authenticated"})
        # One round trip: transaction-local role (same effect as SET LOCAL ROLE) + the caller's claims for auth.uid()
        conn.execute(text("select set_config('role', 'authenticated', true), set_config('request.jwt.claims', :c, true)"), {"c": claims})
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
