"""Synthetic competition load against a RUNNING API (see docs/TESTING.md). Uses real Supabase Auth/Postgres with clearly named
throwaway data (prefix LOADTEST) and removes it afterwards. Not for use against a live event database.

    # terminal 1: API with the mock judge and no AI calls
    cd backend && JUDGE_PROVIDER=mock EVALUATION_MODE=manual ../.venv/bin/python -m uvicorn app.main:app --port 8010
    # terminal 2
    cd backend && ../.venv/bin/python -m scripts.loadtest --participants 40 --seconds 60
"""
import argparse
import concurrent.futures as cf
import random
import statistics
import threading
import time
import uuid
from collections import defaultdict

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.db import admin_tx
from tests.real import supa

BASE = "http://127.0.0.1:8010/api"
LAT: dict[str, list[float]] = defaultdict(list)
ERR: dict[str, int] = defaultdict(int)
LOCK = threading.Lock()
LIMITED = [0]


def timed(client: httpx.Client, name: str, method: str, path: str, **kw):
    t0 = time.perf_counter()
    try:
        r = client.request(method, BASE + path, timeout=60, **kw)
        ms = (time.perf_counter() - t0) * 1000
        with LOCK:
            LAT[name].append(ms)
            if r.status_code >= 400:
                ERR[f"{name} {r.status_code}"] += 1
        return r
    except httpx.HTTPError as e:
        with LOCK:
            ERR[f"{name} {type(e).__name__}"] += 1


def participant(token: str, variants: list[str], seconds: int, idx: int):
    h = {"Authorization": f"Bearer {token}"}
    end = time.monotonic() + seconds
    code = "x = 1\n" * 50
    with httpx.Client(headers=h) as c:
        time.sleep(random.random() * 3)                                      # staggered start
        timed(c, "GET questions", "GET", "/participant/questions")
        n = 0
        while time.monotonic() < end:
            n += 1
            v = variants[n % len(variants)]
            timed(c, "PUT draft (autosave)", "PUT", f"/participant/variants/{v}/draft", json={"language": "python", "code": code + f"# {n}\n"})
            if n % 7 == 0:
                timed(c, "GET questions (poll)", "GET", "/participant/questions")
            if n % 13 == 0:
                timed(c, "POST run", "POST", f"/participant/variants/{v}/run", json={"language": "python", "code": code}, headers={"Idempotency-Key": uuid.uuid4().hex})
            if n % 29 == 0:
                timed(c, "POST submit", "POST", f"/participant/variants/{v}/submit", json={"language": "python", "code": code}, headers={"Idempotency-Key": uuid.uuid4().hex})
            if n % 31 == 0:
                timed(c, "GET history", "GET", f"/participant/variants/{v}/submissions")
            time.sleep(1.5)


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--participants", type=int, default=40)
    ap.add_argument("--seconds", type=int, default=60)
    a = ap.parse_args()
    s = get_settings()
    users, team_ids = [], []
    print(f"setting up {a.participants} synthetic participants…")
    try:
        with admin_tx() as c:
            qid = c.execute(text("insert into public.questions (round, category, title, status) values (1, 'DSA', 'LOADTEST q', 'PUBLISHED') returning id")).scalar()
            vid = c.execute(text("""insert into public.question_variants (question_id, label, description, expected_behavior, languages, original_code, status)
                                    values (:q, 'A', 'load', 'load', array['python'], '{"python":"pass"}'::jsonb, 'PUBLISHED') returning id"""), {"q": qid}).scalar()
            c.execute(text("insert into public.question_private (variant_id, hidden_tests) values (:v, '[{\"input\":\"1\",\"expected_output\":\"1\"}]'::jsonb)"), {"v": vid})
            for i in range(a.participants):
                tid = c.execute(text("insert into public.teams (team_number, name) values (:n, :nm) returning id"), {"n": 90000 + i, "nm": f"LOADTEST {i}"}).scalar()
                team_ids.append(tid)
                c.execute(text("insert into public.question_assignments (team_id, variant_id, category, locked) values (:t, :v, 'DSA', true)"), {"t": tid, "v": vid})
            c.execute(text("update public.contest_sessions set state = 'RUNNING', starts_at = now(), ends_at = now() + interval '2 hours' where round = 1"))

        def make(i):
            u = supa.create_user("PARTICIPANT", str(team_ids[i]))
            for attempt in range(12):                      # Supabase Auth rate-limits sign-ins per IP (default 30 / 5 min): back off
                try:
                    return u, supa.sign_in(u["email"])
                except httpx.HTTPStatusError as e:
                    if e.response.status_code != 429:
                        raise
                    LIMITED[0] += 1
                    time.sleep(15)
            raise RuntimeError("sign-in kept being rate limited")
        with cf.ThreadPoolExecutor(2) as ex:
            made = list(ex.map(make, range(a.participants)))
        users = [u for u, _ in made]
        print(f"running {a.participants} concurrent participants for {a.seconds}s…")
        t0 = time.perf_counter()
        with cf.ThreadPoolExecutor(a.participants) as ex:
            list(ex.map(lambda i: participant(made[i][1], [str(vid)], a.seconds, i), range(a.participants)))
        dur = time.perf_counter() - t0
        with httpx.Client() as c:
            ready = c.get(BASE + "/ready").json()
        total = sum(len(v) for v in LAT.values())
        print(f"\n{total} requests in {dur:.0f}s = {total / dur:.1f} req/s; API /ready after load: {ready}\n")
        print(f"{'endpoint':28s} {'n':>6s} {'p50 ms':>8s} {'p95 ms':>8s} {'max ms':>8s}")
        for k, v in sorted(LAT.items()):
            print(f"{k:28s} {len(v):6d} {statistics.median(v):8.0f} {pct(v, .95):8.0f} {max(v):8.0f}")
        print("\nerrors:", dict(ERR) or "none")
        print(f"Supabase Auth sign-in 429s during set-up: {LIMITED[0]}")
    finally:
        with admin_tx() as c:
            c.execute(text("delete from public.teams where name like 'LOADTEST %'"))
            c.execute(text("delete from public.questions where title = 'LOADTEST q'"))
            c.execute(text("update public.contest_sessions set state = 'DRAFT', starts_at = null, ends_at = null where round = 1"))
            if users:
                c.execute(text("delete from public.audit_logs where actor_id = any(cast(:i as uuid[]))"), {"i": [u["id"] for u in users]})
        for u in users:
            supa.delete_user(u["id"])
        print("cleaned up synthetic data")


if __name__ == "__main__":
    main()
