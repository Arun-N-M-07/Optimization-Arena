"""Judge/admin review of Autopsy Reports. Judges only reach teams assigned to them."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text

from ..auth import CurrentUser, require_roles
from ..db import admin_tx, audit, one, rows

router = APIRouter(prefix="/api/judge", tags=["judge"])
reviewer = require_roles("JUDGE", "ADMIN")
CRITERIA = ("INEFFICIENCY", "APPROACH", "COMPLEXITY", "TRADEOFFS")


class CriterionIn(BaseModel):
    criterion: str
    marks: float = Field(ge=0, le=5)
    explanation: str = Field(min_length=5, max_length=2000)

    @field_validator("marks")
    @classmethod
    def _half(cls, v):
        if round(v * 2) != v * 2:
            raise ValueError("Marks must be in steps of 0.5")
        return v


class ReviewIn(BaseModel):
    criteria: list[CriterionIn]
    comment: str = Field(default="", max_length=3000)
    approve: bool = True

    @model_validator(mode="after")
    def _four(self):
        if sorted(c.criterion for c in self.criteria) != sorted(CRITERIA):
            raise ValueError("Provide each of the four criteria exactly once")
        return self


def bump(conn):
    """Touch contest sessions so Realtime subscribers refetch scores/leaderboards."""
    conn.execute(text("update public.contest_sessions set updated_at = now()"))


def _authorize_team(conn, user: CurrentUser, team_id) -> None:
    if user.role == "ADMIN":
        return
    if not one(conn, "select 1 as x from public.judge_assignments where judge_id = :j and team_id = :t", j=str(user.id), t=str(team_id)):
        raise HTTPException(404, "Report not found")      # 404: do not reveal existence of unassigned teams


def team_allowed(conn, user: CurrentUser, team_id) -> None:
    _authorize_team(conn, user, team_id)


@router.get("/queue")
def queue(user: CurrentUser = Depends(reviewer)):
    scope = "" if user.role == "ADMIN" else "and exists (select 1 from public.judge_assignments j where j.judge_id = :j and j.team_id = r.team_id)"
    with admin_tx() as c:
        return {"items": rows(c, f"""
            with latest as (select distinct on (team_id, variant_id) * from public.autopsy_reports
                            where status <> 'DRAFT' order by team_id, variant_id, version desc)
            select r.id as report_id, r.version, r.status::text as report_status, r.submitted_at,
                   t.team_number, t.name as team_name, q.title, q.category::text as category,
                   (select e.status from public.report_evaluations e where e.report_id = r.id and e.source = 'AI' limit 1) as ai_status,
                   (select e.needs_review from public.report_evaluations e where e.report_id = r.id and e.source = 'AI' limit 1) as needs_review,
                   exists (select 1 from public.report_evaluations e where e.report_id = r.id and e.source = 'JUDGE' and e.approved_at is not null) as approved
            from latest r join public.teams t on t.id = r.team_id
            join public.question_variants v on v.id = r.variant_id join public.questions q on q.id = v.question_id
            where true {scope} order by approved, needs_review desc nulls last, r.submitted_at""", j=str(user.id))}


@router.get("/reports/{report_id}")
def detail(report_id: UUID, user: CurrentUser = Depends(reviewer)):
    with admin_tx() as c:
        r = one(c, """select r.id, r.team_id, r.version, r.status::text as status, r.inefficiency, r.approach, r.complexity, r.tradeoffs,
                             r.submitted_at, r.submission_id, t.team_number, t.name as team_name,
                             q.title, q.category::text as category, v.description, v.expected_behavior, v.constraints,
                             v.original_code, p.reference_concepts, p.expected_complexity
                      from public.autopsy_reports r join public.teams t on t.id = r.team_id
                      join public.question_variants v on v.id = r.variant_id join public.questions q on q.id = v.question_id
                      left join public.question_private p on p.variant_id = v.id where r.id = :id""", id=str(report_id))
        if not r:
            raise HTTPException(404, "Report not found")
        _authorize_team(c, user, r["team_id"])
        r["submission"] = one(c, """select s.id, s.language, s.code, s.created_at, e.outcome::text as outcome, e.passed_visible, e.total_visible,
                                           e.passed_hidden, e.total_hidden, e.safe_message, e.provider
                                    from public.submissions s left join lateral (select * from public.execution_results x where x.submission_id = s.id
                                         order by x.created_at desc limit 1) e on true where s.id = :id""", id=str(r["submission_id"])) if r["submission_id"] else None
        evs = rows(c, "select * from public.report_evaluations where report_id = :id order by created_at", id=str(report_id))
        for e in evs:
            e["criteria"] = rows(c, "select criterion, marks, max_marks, explanation, evidence from public.evaluation_criteria where evaluation_id = :e order by criterion", e=str(e["id"]))
            e["total"] = sum(float(x["marks"]) for x in e["criteria"])
        r["evaluations"] = evs
        r["history"] = rows(c, """select a.created_at, a.criterion, a.previous_marks, a.new_marks, a.reason, u.email as by
                                  from public.score_adjustments a left join auth.users u on u.id = a.adjusted_by
                                  where a.report_id = :id order by a.created_at""", id=str(report_id))
        return r


@router.post("/reports/{report_id}/review", status_code=201)
def review(report_id: UUID, body: ReviewIn, user: CurrentUser = Depends(reviewer)):
    with admin_tx() as c:
        r = one(c, "select team_id, status::text as status from public.autopsy_reports where id = :id for update", id=str(report_id))
        if not r:
            raise HTTPException(404, "Report not found")
        _authorize_team(c, user, r["team_id"])
        if r["status"] == "DRAFT":
            raise HTTPException(409, "Report has not been submitted")
        ai = one(c, "select id from public.report_evaluations where report_id = :id and source = 'AI' and status = 'COMPLETED' limit 1", id=str(report_id))
        prev = {x["criterion"]: float(x["marks"]) for x in rows(c, "select criterion, marks from public.evaluation_criteria where evaluation_id = :e", e=str(ai["id"]))} if ai else {}
        ev = one(c, """insert into public.report_evaluations (report_id, source, status, comment, created_by, completed_at, approved_at, approved_by, eval_version)
                       values (:r, 'JUDGE', 'COMPLETED', :cm, :u, now(), case when :ap then now() end, case when :ap then cast(:u as uuid) end,
                               (select coalesce(max(eval_version), 0) + 1 from public.report_evaluations where report_id = :r and source = 'JUDGE'))
                       returning id""", r=str(report_id), cm=body.comment, u=str(user.id), ap=body.approve)
        for cr in body.criteria:
            c.execute(text("insert into public.evaluation_criteria (evaluation_id, criterion, marks, max_marks, explanation) values (:e, :c, :m, 5, :x)"),
                      {"e": str(ev["id"]), "c": cr.criterion, "m": cr.marks, "x": cr.explanation})
            if cr.criterion in prev and prev[cr.criterion] != cr.marks:     # every override is recorded with its reason
                c.execute(text("""insert into public.score_adjustments (team_id, report_id, criterion, previous_marks, new_marks, reason, adjusted_by)
                                  values (:t, :r, :c, :p, :n, :why, :u)"""),
                          {"t": str(r["team_id"]), "r": str(report_id), "c": cr.criterion, "p": prev[cr.criterion], "n": cr.marks,
                           "why": cr.explanation, "u": str(user.id)})
        if body.approve:
            c.execute(text("update public.autopsy_reports set status = 'REVIEWED' where id = :id"), {"id": str(report_id)})
        audit(c, user, "report.review", "report", report_id,
              {"approve": body.approve, "overrides": [k for k in prev if any(x.criterion == k and x.marks != prev[k] for x in body.criteria)],
               "total": sum(x.marks for x in body.criteria)})
        bump(c)
        return {"evaluation_id": ev["id"], "total": sum(x.marks for x in body.criteria), "approved": body.approve}
