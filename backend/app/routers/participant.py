from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, require_roles
from ..db import one, rows, user_tx

router = APIRouter(prefix="/api/participant", tags=["participant"])
participant = require_roles("PARTICIPANT")

# Round 1 content becomes visible only once the round has started.
VISIBLE_STATES = ("RUNNING", "PAUSED", "ENDED", "RESULTS_PUBLISHED")


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
    if not user.team_id:
        raise HTTPException(404, "Your account is not linked to a team yet")
    with user_tx(user) as c:
        sess = one(c, "select state::text as state, starts_at, ends_at from public.contest_sessions where round = 1")
        if sess["state"] not in VISIBLE_STATES:
            return {"round": sess, "questions": []}
        # Explicit column list: only participant-safe fields, and question_private is never joined.
        qs = rows(c, """select a.category::text as category, q.id as question_id, q.title, q.difficulty,
                               v.id as variant_id, v.label, v.description, v.expected_behavior, v.constraints,
                               v.languages, v.original_code, v.visible_tests
                        from public.question_assignments a
                        join public.question_variants v on v.id = a.variant_id
                        join public.questions q on q.id = v.question_id
                        order by a.category""")
        return {"round": sess, "questions": qs}
