from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ..auth import CurrentUser, require_roles
from ..db import admin_tx, audit, map_db_error, one, rows

router = APIRouter(prefix="/api/admin", tags=["admin: assignments"])
admin = require_roles("ADMIN")
CATEGORIES = ("DSA", "OOP", "DBMS")
MIN_MEMBERS = 2
EDITABLE_STATES = ("DRAFT", "SCHEDULED")


class AssignIn(BaseModel):
    variant_id: UUID


class StartIn(BaseModel):
    duration_minutes: int = Field(default=150, ge=1, le=600)


def _round1(c, lock: bool = False) -> dict:
    return one(c, f"select state::text as state, starts_at, ends_at from public.contest_sessions where round = 1 {'for update' if lock else ''}")


def _require_editable(c):
    if _round1(c, lock=True)["state"] not in EDITABLE_STATES:
        raise HTTPException(409, "Round 1 has started; assignments can no longer change")


def _problems(c) -> list[str]:
    """Everything that stops assignments being locked. Empty list = ready."""
    out = []
    for t in rows(c, """select t.id, t.team_number, count(distinct m.id) as members, count(distinct a.category) as cats
                        from public.teams t left join public.team_members m on m.team_id = t.id
                        left join public.question_assignments a on a.team_id = t.id
                        where t.is_active group by t.id order by t.team_number"""):
        if t["members"] < MIN_MEMBERS:
            out.append(f"Team {t['team_number']} has {t['members']} member(s); at least {MIN_MEMBERS} required")
        if t["cats"] < len(CATEGORIES):
            out.append(f"Team {t['team_number']} has {t['cats']}/3 questions assigned")
    if not rows(c, "select 1 from public.teams where is_active limit 1"):
        out.append("There are no active teams")
    return out


@router.get("/assignments")
def matrix(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        teams = rows(c, """select t.id, t.team_number, t.name, t.is_active,
                           (select count(*) from public.team_members m where m.team_id = t.id) as member_count
                           from public.teams t order by t.team_number""")
        asg = rows(c, """select a.team_id, a.category::text as category, a.locked, a.variant_id, v.label, q.title
                         from public.question_assignments a join public.question_variants v on v.id = a.variant_id
                         join public.questions q on q.id = v.question_id""")
        by = {(a["team_id"], a["category"]): a for a in asg}
        for t in teams:
            t["assignments"] = {k: by.get((t["id"], k)) for k in CATEGORIES}
            t["complete"] = all(t["assignments"].values())
        return {"round_state": _round1(c)["state"], "locked": bool(asg) and all(a["locked"] for a in asg),
                "problems": _problems(c), "teams": teams}


@router.put("/teams/{team_id}/assignments/{category}")
def assign(team_id: UUID, category: str, body: AssignIn, user: CurrentUser = Depends(admin)):
    if category not in CATEGORIES:
        raise HTTPException(422, "Category must be DSA, OOP or DBMS")
    try:
        with admin_tx() as c:
            _require_editable(c)
            if not one(c, "select 1 as x from public.teams where id = :t and is_active", t=str(team_id)):
                raise HTTPException(404, "Active team not found")
            v = one(c, """select q.category::text as category, v.status::text as vs, q.status::text as qs
                          from public.question_variants v join public.questions q on q.id = v.question_id where v.id = :v""",
                    v=str(body.variant_id))
            if not v:
                raise HTTPException(404, "Variant not found")
            if v["category"] != category:
                raise HTTPException(422, f"That variant is a {v['category']} question, not {category}")
            if v["vs"] != "PUBLISHED" or v["qs"] != "PUBLISHED":
                raise HTTPException(422, "Only published questions and variants can be assigned")
            prev = one(c, "select variant_id from public.question_assignments where team_id = :t and category = cast(:c as public.question_category)",
                       t=str(team_id), c=category)
            c.execute(text("""insert into public.question_assignments (team_id, variant_id, category, assigned_by)
                              values (:t, :v, cast(:c as public.question_category), :by)
                              on conflict (team_id, category) do update set variant_id = excluded.variant_id,
                                assigned_by = excluded.assigned_by where not public.question_assignments.locked"""),
                      {"t": str(team_id), "v": str(body.variant_id), "c": category, "by": str(user.id)})
            audit(c, user, "assignment.set", "team", team_id,
                  {"category": category, "variant": str(body.variant_id), "previous": str(prev["variant_id"]) if prev else None})
            return {"team_id": team_id, "category": category, "variant_id": body.variant_id}
    except DBAPIError as e:
        raise map_db_error(e)


@router.delete("/teams/{team_id}/assignments/{category}", status_code=204)
def unassign(team_id: UUID, category: str, user: CurrentUser = Depends(admin)):
    if category not in CATEGORIES:
        raise HTTPException(422, "Category must be DSA, OOP or DBMS")
    with admin_tx() as c:
        _require_editable(c)
        gone = one(c, "delete from public.question_assignments where team_id = :t and category = cast(:c as public.question_category) and not locked returning variant_id",
                   t=str(team_id), c=category)
        if not gone:
            raise HTTPException(404, "No unlocked assignment to remove")
        audit(c, user, "assignment.remove", "team", team_id, {"category": category, "variant": str(gone["variant_id"])})


@router.post("/assignments/lock")
def lock(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        _require_editable(c)
        problems = _problems(c)
        if problems:
            raise HTTPException(409, {"message": "Assignments cannot be locked yet", "problems": problems})
        n = c.execute(text("update public.question_assignments set locked = true where not locked")).rowcount
        audit(c, user, "assignment.lock", "round", 1, {"rows": n})
        return {"locked": n}


@router.post("/rounds/1/start")
def start_round(body: StartIn = StartIn(), user: CurrentUser = Depends(admin)):
    """Starting Round 1 locks assignments (after the same validation) and sets server-side start/end."""
    with admin_tx() as c:
        _require_editable(c)
        problems = _problems(c)
        if problems:
            raise HTTPException(409, {"message": "Round 1 cannot start yet", "problems": problems})
        c.execute(text("update public.question_assignments set locked = true where not locked"))
        s = one(c, """update public.contest_sessions set state = 'RUNNING', starts_at = now(),
                      ends_at = now() + make_interval(mins => :m) where round = 1
                      returning state::text as state, starts_at, ends_at""", m=body.duration_minutes)
        audit(c, user, "round.start", "round", 1, {"duration_minutes": body.duration_minutes})
        return s
