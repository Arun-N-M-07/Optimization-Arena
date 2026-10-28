#!/usr/bin/env bash
# Throwaway LOCAL Postgres + PgBouncer for tests/localdb. Never touches Supabase.
#   scripts/local_pg_harness.sh start <dir>   create + start everything under <dir>, apply supabase/migrations
#   scripts/local_pg_harness.sh stop  <dir>   stop it (delete <dir> yourself)
# Ports (loopback only): 54329 Postgres direct | 54330 PgBouncer: db "arena_tx" = transaction pooling (like Supabase :6543),
# db "arena_sess" = session pooling (like Supabase :5432). Server pool size is deliberately tiny (PG_POOL, default 4).
# The auth schema and the anon/authenticated/service_role roles that Supabase provides are emulated minimally.
set -euo pipefail
cmd="${1:?start|stop}"; dir="${2:?harness directory}"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@16/bin}"
PG_POOL="${PG_POOL:-4}"
PG_OPTS="-p 54329 -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c max_connections=100"
repo="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$dir"; dir="$(cd "$dir" && pwd)"

case "$cmd" in
start)
  if [ -f "$dir/pg/PG_VERSION" ]; then      # restart an existing harness: data, schema and PgBouncer config are kept
    "$PGBIN/pg_ctl" -D "$dir/pg" -o "$PG_OPTS" -l "$dir/pg.log" -w start >/dev/null
    pgbouncer -d "$dir/pgbouncer.ini"
    echo "harness restarted"; exit 0
  fi
  "$PGBIN/initdb" -D "$dir/pg" -U postgres --auth=trust -E UTF8 >/dev/null
  "$PGBIN/pg_ctl" -D "$dir/pg" -o "$PG_OPTS" -l "$dir/pg.log" -w start >/dev/null
  psql="$PGBIN/psql -h 127.0.0.1 -p 54329 -U postgres -v ON_ERROR_STOP=1 -q"
  $psql -d postgres <<'SQL'
create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
create schema auth;
create table auth.users (id uuid primary key default gen_random_uuid(), email text, raw_user_meta_data jsonb default '{}'::jsonb);
create function auth.uid() returns uuid language sql stable as
  $$ select nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')::uuid $$;
grant usage on schema public, auth to anon, authenticated, service_role;
grant all on all tables in schema public to anon, authenticated, service_role;   -- Supabase's default, which migration 6 narrows
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
create publication supabase_realtime;
SQL
  for f in "$repo"/supabase/migrations/*.sql; do $psql -d postgres -f "$f"; done
  cat > "$dir/pgbouncer.ini" <<EOF
[databases]
arena_tx = host=127.0.0.1 port=54329 dbname=postgres pool_mode=transaction pool_size=$PG_POOL
arena_sess = host=127.0.0.1 port=54329 dbname=postgres pool_mode=session pool_size=$PG_POOL
[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 54330
unix_socket_dir =
auth_type = trust
auth_file = $dir/userlist.txt
admin_users = postgres
pool_mode = transaction
max_client_conn = 500
default_pool_size = $PG_POOL
server_reset_query_always = 0
query_wait_timeout = 8
max_prepared_statements = 0
ignore_startup_parameters = extra_float_digits,options
pidfile = $dir/pgbouncer.pid
logfile = $dir/pgbouncer.log
EOF
  echo '"postgres" ""' > "$dir/userlist.txt"
  pgbouncer -d "$dir/pgbouncer.ini"
  echo "harness up: direct postgresql://postgres@127.0.0.1:54329/postgres | tx-pool postgresql://postgres@127.0.0.1:54330/arena_tx | session-pool .../arena_sess"
  ;;
stop)
  [ -f "$dir/pgbouncer.pid" ] && kill "$(cat "$dir/pgbouncer.pid")" 2>/dev/null || true
  "$PGBIN/pg_ctl" -D "$dir/pg" -m fast stop >/dev/null 2>&1 || true
  echo "harness stopped"
  ;;
*) echo "usage: $0 start|stop <dir>" >&2; exit 2 ;;
esac
