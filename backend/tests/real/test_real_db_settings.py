"""REAL Postgres: every pooled connection carries the safety timeouts, and RLS role switching still works in one statement."""
import uuid

import pytest
from sqlalchemy import text

from app.auth import CurrentUser
from app.db import admin_tx, get_engine, user_tx

pytestmark = pytest.mark.real_supabase


def test_every_connection_has_idle_in_transaction_and_lock_timeouts():
    with get_engine().connect() as c:
        assert c.execute(text("show idle_in_transaction_session_timeout")).scalar() == "1min"
        assert c.execute(text("show lock_timeout")).scalar() == "15s"


def test_an_abandoned_transaction_is_ended_by_postgres_and_releases_its_lock():
    """Mechanism behind the fix: an idle-in-transaction session is terminated and its row lock freed (2 s here instead of 60 s)."""
    import time

    import psycopg

    from app.config import get_settings
    import re
    dsn = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql://", get_settings().database_url)
    with admin_tx() as c:
        tid = c.execute(text("insert into public.teams (team_number, name) values (99991, 'ZZ Team lock') returning id")).scalar()
    try:
        zombie = psycopg.connect(dsn, prepare_threshold=None)
        zombie.execute("set idle_in_transaction_session_timeout = '2s'")
        zombie.execute("select 1 from public.teams where id = %s for update", (str(tid),))     # holds the row lock, never commits
        with admin_tx() as c:
            c.execute(text("set local lock_timeout = '1s'"))
            with pytest.raises(Exception, match="lock timeout|canceling statement"):
                c.execute(text("update public.teams set name = 'blocked' where id = :i"), {"i": str(tid)})
        time.sleep(4)                                                                            # Postgres terminates the abandoned session
        with admin_tx() as c:
            assert c.execute(text("update public.teams set name = 'free' where id = :i returning name"), {"i": str(tid)}).scalar() == "free"
        with pytest.raises(Exception):
            zombie.execute("select 1")
    finally:
        with admin_tx() as c:
            c.execute(text("delete from public.teams where team_number = 99991"))


def test_single_statement_role_and_claims_setup_enforces_rls_and_does_not_leak():
    ghost = CurrentUser(id=uuid.uuid4(), email=None, role="PARTICIPANT", team_id=None)
    with user_tx(ghost) as c:
        assert c.execute(text("select current_user")).scalar() == "authenticated"
        assert c.execute(text("select auth.uid()::text")).scalar() == str(ghost.id)
        assert c.execute(text("select count(*) from public.teams")).scalar() == 0
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("insert into public.teams (team_number, name) values (99992, 'x')"))
    with admin_tx() as c:                                                                        # the next transaction on the pool is clean
        assert c.execute(text("select current_user")).scalar() == "postgres"
        assert c.execute(text("select coalesce(current_setting('request.jwt.claims', true), '')")).scalar() == ""
