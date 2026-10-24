from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, require_roles
from ..db import admin_tx, one, rows, user_tx
from ..rounds import VISIBLE_STATES, session

router = APIRouter(prefix="/api/participant", tags=["participant"])
participant = require_roles("PARTICIPANT")


def _slim(s: dict) -> dict:
    return {"state": s["state"], "starts_at": s["starts_at"], "ends_at": s["ends_at"], "results_published": s["results_published"]}


@router.get("/team")
def my_team(user: CurrentUser = Depends(participant)):
    if not user.team_id:
        raise HTTPException(404, "Your account is not linked to a team yet")
    with user_tx(user) as c:  # RLS applies: only the caller's own team row is visible
        t = one(c, "select id, team_number, name, is_finalist from public.teams where id = :id", id=str(user.team_id))
        if not t:
            raise HTTPException(404, "Team not found")
        t["members"] = rows(c, "select id, full_name from public.team_members where team_id = :id order by created_at", id=str(user.team_id))
        return t


@router.get("/questions")
def my_questions(user: CurrentUser = Depends(participant)):
    """Assigned questions (rounds 1 and 2). A round's content stays hidden until that round has started."""
    if not user.team_id:
        raise HTTPException(404, "Your account is not linked to a team yet")
    with user_tx(user) as c:
        sess = {n: session(c, n) for n in (1, 2)}
        # Explicit column list: only participant-safe fields, and question_private is never joined.
        qs = rows(c, """select q.round, a.category::text as category, q.id as question_id, q.title, q.difficulty,
                               v.id as variant_id, v.label, v.description, v.expected_behavior, v.constraints,
                               v.languages, v.original_code, v.visible_tests,
                               (select count(*) from public.submissions s where s.variant_id = v.id and s.team_id = a.team_id and s.kind = 'FINAL') as finals,
                               (select r.status::text from public.autopsy_reports r where r.variant_id = v.id and r.team_id = a.team_id
                                order by r.version desc limit 1) as report_status
                        from public.question_assignments a
                        join public.question_variants v on v.id = a.variant_id
                        join public.questions q on q.id = v.question_id
                        where a.team_id = :t order by q.round, a.category""", t=str(user.team_id))
        qs = [q for q in qs if sess[q["round"]]["state"] in VISIBLE_STATES]
        return {"server_now": sess[1]["server_now"], "round": _slim(sess[1]),
                "rounds": {str(n): _slim(s) for n, s in sess.items()}, "questions": qs}
