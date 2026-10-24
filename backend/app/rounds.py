"""Server-authoritative round state. The browser clock is never consulted."""
from fastapi import HTTPException

from .db import one

VISIBLE_STATES = ("RUNNING", "PAUSED", "ENDED", "RESULTS_PUBLISHED")


def session(conn, rnd: int, lock: bool = False) -> dict:
    """Effective state: a RUNNING round whose end time has passed is reported as ENDED."""
    r = one(conn, f"""select round, case when state = 'RUNNING' and ends_at is not null and ends_at <= now()
                                   then 'ENDED' else state::text end as state,
                             state::text as stored_state, starts_at, ends_at, now() as server_now,
                             results_published, finalists_locked, config
                      from public.contest_sessions where round = :r {'for update' if lock else ''}""", r=rnd)
    return r


def require_open(conn, rnd: int) -> dict:
    s = session(conn, rnd)
    if s["state"] != "RUNNING":
        raise HTTPException(409, f"Round {rnd} is not open for submissions (state: {s['state']})")
    return s
