"""The local-database test package must be physically unable to touch anything but a loopback database."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.localdb.conftest import assert_local

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("url", [
    "postgresql://postgres@127.0.0.1:54329/postgres", "postgresql://postgres@localhost:5432/x", "postgresql://postgres@[::1]:5432/x",
])
def test_loopback_urls_are_accepted(url):
    assert assert_local(url) == url


@pytest.mark.parametrize("url", [
    "postgresql://postgres.abcdefgh:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres",     # the real transaction pooler
    "postgresql://postgres.abcdefgh:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres",     # the real session pooler
    "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres",                               # the real direct host
    "postgresql://u@10.0.0.5/db", "postgresql://u@192.168.1.10/db",                                 # other machines
    "postgresql://u@127.0.0.1.evil.example/db", "postgresql://u@localhost.evil.example/db",         # look-alike hostnames
    "postgresql://127.0.0.1@evil.example/db",                                                       # loopback only in the userinfo
    "postgresql://u@evil.example/db?host=127.0.0.1",                                                # loopback only in a query parameter
    "postgresql://u@127.0.0.1/db?host=db.abc.supabase.co", "postgresql://u@localhost/db?hostaddr=10.1.2.3",     # loopback host, overridden by libpq
    "postgresql://u@127.0.0.1/db?service=prod",
    "postgresql:///db", "", "not a url",                                                            # no host (could resolve via PG* env vars / unix socket)
])
def test_everything_else_is_refused(url):
    with pytest.raises(AssertionError, match="refusing"):
        assert_local(url)


def test_a_query_string_without_overrides_is_fine():
    assert_local("postgresql://postgres@127.0.0.1:54330/arena_tx?application_name=x&connect_timeout=5")


@pytest.mark.parametrize("var", ["ARENA_LOCAL_DIRECT_URL", "ARENA_LOCAL_TX_URL", "ARENA_LOCAL_SESS_URL", "ARENA_LOCAL_PGBOUNCER_ADMIN_URL"])
def test_a_remote_override_aborts_before_any_test_can_connect(var):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARENA_LOCAL_")}
    env[var] = "postgresql://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
    r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); import tests.localdb.conftest"],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "refusing to use non-local database host" in r.stderr
    assert "pw@" not in r.stderr and "pooler.supabase.com:6543/postgres" not in r.stderr          # the password-bearing URL is not echoed


def test_localdb_tests_are_skipped_unless_explicitly_enabled():
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARENA_LOCAL_")}
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/localdb", "-q", "-p", "no:cacheprovider", "-rs"],
                       cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert "passed" not in r.stdout.split("\n")[-2] and "skipped" in r.stdout and r.returncode == 0
