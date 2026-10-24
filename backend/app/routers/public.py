"""Unauthenticated, read-only. Only published data; never emails, drafts, tests or judge notes."""
from fastapi import APIRouter, HTTPException

from .. import scoring
from ..pubcache import cached
from ..db import admin_tx, rows
from ..rounds import session

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/state")
def state():
    return cached("state", _state)


def _state():
    with admin_tx() as c:
        s = {}
        for n in (1, 2):
            r = session(c, n)
            s[str(n)] = {"state": r["state"], "starts_at": r["starts_at"], "ends_at": r["ends_at"], "results_published": r["results_published"]}
        ann = rows(c, "select id, round, message, created_at from public.contest_announcements order by created_at desc limit 10")
        return {"server_now": session(c, 1)["server_now"], "rounds": s, "announcements": ann}


@router.get("/leaderboard")
def leaderboard(round: str = "1"):
    if round not in ("1", "2", "final"):
        raise HTTPException(422, "round must be 1, 2 or final")
    return cached(("lb", round), lambda: _leaderboard(round))


def _leaderboard(round: str):
    with admin_tx() as c:
        if round == "final":
            if not (session(c, 1)["results_published"] and session(c, 2)["results_published"]):
                return {"published": False, "rows": []}
            data = scoring.combined(c)
            if data is None:
                return {"published": False, "rows": [], "note": "Combined scoring has not been configured"}
        else:
            n = int(round)
            if not session(c, n)["results_published"]:
                return {"published": False, "rows": []}
            data = scoring.compute_scores(c, n)
        keep = ("rank", "team_number", "name", "total", "report", "code", "manual", "round1_total", "round2_total")
        return {"published": True, "round": round, "rows": [{k: t[k] for k in keep if k in t} for t in data]}
