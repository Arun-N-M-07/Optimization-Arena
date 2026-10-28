"""Is the app safe behind a TRANSACTION-mode pooler (Supabase :6543 / Supavisor)? Modelled with PgBouncer in transaction mode
(server pool deliberately tiny = 4) in front of the migrated local schema. This models the pooling semantics; it is not Supavisor."""
import json
import threading
import time
import uuid

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from app import db
from app.auth import CurrentUser

from .conftest import ADMIN, DIRECT, SESS, TX


def instance(**kw):
    """A brand-new engine = one more Vercel function instance (get_engine() itself is a per-process singleton)."""
    return db.get_engine.__wrapped__()


def hammer(engine, threads, per_thread, hold=0.005):
    errors, done = [], []

    def work():
        for _ in range(per_thread):
            try:
                with engine.begin() as c:
                    c.execute(text("select pg_sleep(:s)"), {"s": hold})
                    done.append(c.execute(text("select 1")).scalar())
            except Exception as e:                     # noqa: BLE001
                errors.append(type(e).__name__)
    ts = [threading.Thread(target=work) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return len(done), errors


def test_repeated_statements_from_many_threads_work_without_prepared_statements(use_db):
    use_db(TX, DB_POOL_SIZE=3, DB_MAX_OVERFLOW=0)
    errors = []

    def work():
        try:
            for i in range(60):
                with db.admin_tx() as c:
                    assert db.one(c, "select cast(:i as int) + 1 as n, now() as t", i=i)["n"] == i + 1
        except Exception as e:                          # noqa: BLE001
            errors.append(repr(e))
    ts = [threading.Thread(target=work) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []


def test_role_and_claims_never_leak_between_clients_sharing_server_connections(use_db):
    use_db(TX, DB_POOL_SIZE=3, DB_MAX_OVERFLOW=0)
    bad, n = [], 0

    def work(k):
        nonlocal n
        user = CurrentUser(id=uuid.uuid4(), email=None, role="PARTICIPANT", team_id=None)
        for i in range(80):
            if (i + k) % 2:
                with db.user_tx(user) as c:
                    got = c.execute(text("select current_user, auth.uid()::text, (select count(*) from public.teams)")).one()
                    if got != ("authenticated", str(user.id), 0):
                        bad.append(("user", got))
            else:
                with db.admin_tx() as c:
                    got = c.execute(text("select current_user, coalesce(current_setting('request.jwt.claims', true), '')")).one()
                    if got != ("postgres", ""):
                        bad.append(("admin", got))
            n += 1
    ts = [threading.Thread(target=work, args=(k,)) for k in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert n == 960 and bad == []


def test_one_transaction_stays_on_one_server_connection(use_db):
    use_db(TX, DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0)
    stop = threading.Event()
    noise = threading.Thread(target=lambda: [hammer(db.get_engine(), 3, 5) for _ in iter(stop.is_set, True)])
    noise.start()
    try:
        for _ in range(20):
            with db.admin_tx() as c:
                pids = {c.execute(text("select pg_backend_pid()")).scalar() for _ in range(5)}
                c.execute(text("select pg_sleep(0.01)"))
                pids.add(c.execute(text("select pg_backend_pid()")).scalar())
            assert len(pids) == 1                     # BEGIN..COMMIT is pinned, so FOR UPDATE / SET LOCAL / set_config(..., true) are safe
    finally:
        stop.set()
        noise.join()


def test_safety_timeouts_come_from_role_defaults_so_the_connect_hook_is_not_needed(use_db):
    use_db(TX, DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0)
    with db.admin_tx() as c:
        assert c.execute(text("show lock_timeout")).scalar() == "15s"
        assert c.execute(text("show idle_in_transaction_session_timeout")).scalar() == "1min"
    with psycopg.connect(TX, autocommit=True) as plain:         # a client that never ran the hook
        assert plain.execute("show lock_timeout").fetchone()[0] == "15s"
        assert plain.execute("show idle_in_transaction_session_timeout").fetchone()[0] == "1min"


def test_session_level_set_is_NOT_isolated_in_transaction_mode(use_db):
    """Why the app must never rely on session-level SET behind :6543 (migration 7 role defaults + SET LOCAL are used instead).
    Characterisation of pooler behaviour; cleans up after itself."""
    use_db(TX)
    seen = set()
    try:
        with psycopg.connect(TX, autocommit=True) as polluter:
            polluter.execute("set lock_timeout = '7s'")
        for _ in range(12):
            with psycopg.connect(TX, autocommit=True) as other:
                seen.add(other.execute("show lock_timeout").fetchone()[0])
        assert "7s" in seen                                    # a DIFFERENT client inherited the first client's session setting
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as a:
            a.execute("RECONNECT arena_tx")                    # drop server connections so the polluted ones are discarded
        time.sleep(0.5)
        with psycopg.connect(TX, autocommit=True) as clean:
            assert clean.execute("show lock_timeout").fetchone()[0] == "15s"


def test_many_instances_share_a_tiny_server_pool_in_transaction_mode(use_db):
    """12 'instances' x pool of 3 = 36 client connections over only 4 server connections."""
    use_db(TX, DB_POOL_SIZE=3, DB_MAX_OVERFLOW=0)
    engines = [instance() for _ in range(12)]
    results = []
    ts = [threading.Thread(target=lambda e=e: results.append(hammer(e, 5, 12))) for e in engines]
    [t.start() for t in ts]
    [t.join() for t in ts]
    [e.dispose() for e in engines]
    assert sum(r[0] for r in results) == 12 * 5 * 12 and [r[1] for r in results if r[1]] == []


def test_session_mode_cannot_serve_the_same_fleet(use_db):
    """Contrast: in session mode every idle pooled connection pins a server connection, so a later instance never gets in."""
    use_db(SESS, DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0)
    engines = [instance() for _ in range(3)]
    held, failures = [], []
    for e in engines:                                         # 3 instances x 2 held connections = 6 > 4 server connections
        for _ in range(2):
            try:
                c = e.connect()
                c.execute(text("select 1"))
                held.append(c)
            except DBAPIError as ex:
                failures.append(type(ex).__name__)
    for c in held:
        c.close()
    [e.dispose() for e in engines]
    assert len(held) == 4 and failures                        # exactly the 4 server connections were usable; the rest failed


def test_a_dropped_pooler_connection_is_detected_after_idle_and_surfaces_as_a_retryable_error_otherwise(use_db, monkeypatch):
    use_db(TX, DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0)

    def kill_all_clients():
        with psycopg.connect(ADMIN, autocommit=True) as a:
            a.execute("KILL arena_tx")
            a.execute("RESUME arena_tx")

    with db.admin_tx() as c:
        c.execute(text("select 1"))
    kill_all_clients()                                        # busy connection dropped within IDLE_VERIFY_SECONDS: no pre-check
    with pytest.raises((OperationalError, InterfaceError)):   # app.main maps both to HTTP 503 + Retry-After
        with db.admin_tx() as c:
            c.execute(text("select 1"))
    with db.admin_tx() as c:                                  # the pool discarded it; the retry succeeds
        assert c.execute(text("select 1")).scalar() == 1

    kill_all_clients()                                        # a frozen/idle Vercel instance resuming later
    monkeypatch.setattr(db, "IDLE_VERIFY_SECONDS", 0)
    with db.admin_tx() as c:                                  # verified on checkout, transparently replaced
        assert c.execute(text("select 1")).scalar() == 1


def test_negative_control_named_prepared_statements_DO_break_behind_the_pooler(use_db):
    """Proves this harness would catch prepared-statement use (max_prepared_statements=0, like a pooler without support), and that the
    app's prepare_threshold=None setting is what keeps it safe."""
    errors = []

    def naive_client(k):
        with psycopg.connect(TX, autocommit=True, prepare_threshold=0) as c:     # always prepare = named statements
            for i in range(40):
                try:
                    c.execute(f"select {k}::int + %s", (i,))                       # distinct text per client, same _pg3_N names
                    time.sleep(0.002)
                except psycopg.Error as e:
                    errors.append(type(e).__name__)
    ts = [threading.Thread(target=naive_client, args=(k,)) for k in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors                                                                  # the harness detects it
    use_db(TX, DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0)
    for i in range(30):                                                       # the app's own settings: never a prepared statement
        with db.admin_tx() as c:
            assert c.execute(text("select cast(:i as int)"), {"i": i}).scalar() == i
