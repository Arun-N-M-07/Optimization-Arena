"""Tests against a THROWAWAY LOCAL Postgres + PgBouncer (scripts/local_pg_harness.sh). Never Supabase.

Skipped unless ARENA_LOCAL_DB=1. Every fixture refuses to run if a database URL is not loopback, so a stray
DATABASE_URL pointing at the real project can never be written to by these tests.
"""
import os
import uuid
from urllib.parse import parse_qs, urlparse

import psycopg
import pytest

DIRECT = os.getenv("ARENA_LOCAL_DIRECT_URL", "postgresql://postgres@127.0.0.1:54329/postgres")
TX = os.getenv("ARENA_LOCAL_TX_URL", "postgresql://postgres@127.0.0.1:54330/arena_tx")          # transaction pooling (Supabase :6543)
SESS = os.getenv("ARENA_LOCAL_SESS_URL", "postgresql://postgres@127.0.0.1:54330/arena_sess")    # session pooling (Supabase :5432)
ADMIN = os.getenv("ARENA_LOCAL_PGBOUNCER_ADMIN_URL", "postgresql://postgres@127.0.0.1:54330/pgbouncer")


_LIBPQ_TARGET_OVERRIDES = {"host", "hostaddr", "service", "servicefile", "passfile"}   # query parameters libpq lets override the URL host


def assert_local(url: str) -> str:
    u = urlparse(url)
    assert u.hostname in ("127.0.0.1", "localhost", "::1"), f"refusing to use non-local database host {u.hostname!r}"
    assert not (_LIBPQ_TARGET_OVERRIDES & set(parse_qs(u.query))), "refusing a URL whose query string can override the target host"
    return url


for _u in (DIRECT, TX, SESS, ADMIN):          # fails at import, before any test can connect, if an env override points off-machine
    assert_local(_u)


def pytest_collection_modifyitems(config, items):
    if os.getenv("ARENA_LOCAL_DB") == "1":
        return
    skip = pytest.mark.skip(reason="local DB harness not enabled (ARENA_LOCAL_DB=1; see scripts/local_pg_harness.sh)")
    for item in items:
        if "/localdb/" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch):
    """The repo-root .env (real Supabase/Gemini values) is loaded when `app` is imported. These tests must not be able to use
    any of it, even by mistake: replace it with inert local values for the duration of every localdb test."""
    from app import config
    for k, v in {"DATABASE_URL": DIRECT, "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:9", "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "local-inert",
                 "SUPABASE_SECRET_KEY": "local-inert", "GEMINI_API_KEY": "local-inert"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def use_db(monkeypatch):
    """Point the app's engine at a local URL for one test; restores everything afterwards."""
    from app import config, db

    def reset():
        if db.get_engine.cache_info().currsize:
            db.get_engine().dispose()
        db.get_engine.cache_clear()
        config.get_settings.cache_clear()

    def _use(url: str, **env):
        reset()
        monkeypatch.setenv("DATABASE_URL", assert_local(url))
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
    yield _use
    reset()


@pytest.fixture(params=["direct", "tx"])
def db_url(request):
    """Run the test once against Postgres directly and once through the transaction pooler."""
    return {"direct": DIRECT, "tx": TX}[request.param]


@pytest.fixture
def raw():
    c = psycopg.connect(assert_local(DIRECT), autocommit=True)
    yield c
    c.close()


class World(dict):
    pass


@pytest.fixture
def world(raw):
    """One team with a participant, an admin, a published Round 1 question assigned to the team, a FINAL submission and a
    DRAFT report whose sections are long enough to submit. Round 1 is RUNNING."""
    n = uuid.uuid4().hex[:8]
    x = lambda sql, *a: raw.execute(sql, a)       # noqa: E731
    team = x("insert into public.teams (team_number, name) values ((select coalesce(max(team_number), 0) + 1 from public.teams), %s) returning id", f"LT {n}").fetchone()[0]
    ids = {}
    for role in ("participant", "admin"):
        uid = x("insert into auth.users (email) values (%s) returning id", f"{role}-{n}@example.test").fetchone()[0]
        x("update public.profiles set role = %s, team_id = %s where id = %s", role.upper(), team if role == "participant" else None, uid)
        ids[role] = uid
    q = x("insert into public.questions (round, category, title, status) values (1, 'DSA', %s, 'PUBLISHED') returning id", f"Q {n}").fetchone()[0]
    v = x("""insert into public.question_variants (question_id, label, description, expected_behavior, languages, original_code, status)
             values (%s, 'A', 'desc', 'behaviour', array['python'], '{"python": "def f(): pass"}', 'PUBLISHED') returning id""", q).fetchone()[0]
    x("insert into public.question_private (variant_id, expected_complexity, reference_concepts) values (%s, 'O(n)', 'hash map')", v)
    x("insert into public.question_assignments (team_id, variant_id, category) values (%s, %s, 'DSA')", team, v)
    s = x("insert into public.submissions (team_id, variant_id, submitted_by, language, code, kind) values (%s, %s, %s, 'python', 'def f(): return 1', 'FINAL') returning id",
          team, v, ids["participant"]).fetchone()[0]
    r = x("""insert into public.autopsy_reports (team_id, variant_id, inefficiency, approach, complexity, tradeoffs)
             values (%s, %s, %s, %s, %s, %s) returning id""", team, v, *(["x" * 40] * 4)).fetchone()[0]
    x("update public.contest_sessions set state = 'RUNNING', starts_at = now() - interval '1 hour', ends_at = now() + interval '1 hour' where round = 1")
    w = World(team=team, variant=v, submission=s, report=r, participant=ids["participant"], admin=ids["admin"], question=q)
    yield w
    x("delete from public.teams where id = %s", team)
    x("delete from public.questions where id = %s", q)
    x("delete from auth.users where id in (%s, %s)", ids["participant"], ids["admin"])
    x("delete from public.audit_logs")
    x("update public.contest_sessions set state = 'DRAFT', starts_at = null, ends_at = null where round = 1")
