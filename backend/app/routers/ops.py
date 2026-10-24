"""Admin operations: rounds, finalists, judges, announcements, monitoring, scores, audit, exports."""
import csv
import io
import json
import os
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .. import evaluation, pubcache, scoring
from ..auth import CurrentUser, require_roles
from ..db import admin_tx, audit, map_db_error, one, rows
from ..rounds import session
from .review import bump, team_allowed

router = APIRouter(prefix="/api/admin", tags=["admin: operations"])
admin = require_roles("ADMIN")
scorer = require_roles("ADMIN", "JUDGE")


# ---------------- rounds ----------------
class FinalWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")
    round1_weight: float | None = Field(default=None, ge=0, le=100)
    round2_weight: float | None = Field(default=None, ge=0, le=100)


class RoundConfig(BaseModel):
    """Everything optional and conservative: unspecified official rules stay disabled."""
    model_config = ConfigDict(extra="forbid")
    code_points_per_question: float = Field(default=0, ge=0, le=1000)
    tiebreak: Literal["none", "earliest_final_submission"] = "none"
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    variant_id: UUID | None = None           # Round 2 common problem
    final: FinalWeights | None = None         # combined leaderboard weights (Round 2 config)
    power_ups_enabled: Literal[False] = False  # optional mechanics are not implemented; cannot be enabled
    viva_enabled: Literal[False] = False


def _view(r: dict) -> dict:
    pubcache.changed()
    return {k: r[k] for k in ("round", "state", "starts_at", "ends_at", "server_now", "results_published", "finalists_locked", "config")}


@router.get("/rounds")
def get_rounds(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        return [_view(session(c, n)) for n in (1, 2)]


@router.put("/rounds/{rnd}/config")
def set_config(rnd: int, body: RoundConfig, user: CurrentUser = Depends(admin)):
    if rnd not in (1, 2):
        raise HTTPException(404, "No such round")
    with admin_tx() as c:
        s = session(c, rnd, lock=True)
        existing = s["config"] or {}
        frozen = s["state"] not in ("DRAFT", "SCHEDULED")
        if frozen:   # the problem and duration cannot change once started; resending the same values is fine
            for f in ("variant_id", "duration_minutes"):
                if f in body.model_fields_set and str(getattr(body, f)) != str(existing.get(f)):
                    raise HTTPException(409, "The problem and duration are frozen once the round has started")
        if body.variant_id:
            v = one(c, """select q.round, v.status::text as vs, q.status::text as qs from public.question_variants v
                          join public.questions q on q.id = v.question_id where v.id = :v""", v=str(body.variant_id))
            if not v or v["round"] != rnd or v["vs"] != "PUBLISHED" or v["qs"] != "PUBLISHED":
                raise HTTPException(422, "variant_id must be a published question for this round")
        cfg = json.loads(body.model_dump_json(exclude_none=True))
        if frozen:
            cfg.update({f: existing[f] for f in ("variant_id", "duration_minutes") if f in existing})
        c.execute(text("update public.contest_sessions set config = cast(:c as jsonb) where round = :r"), {"c": json.dumps(cfg), "r": rnd})
        audit(c, user, "round.config", "round", rnd, cfg)
        return _view(session(c, rnd))


@router.post("/rounds/{rnd}/end")
def end_round(rnd: int, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        s = session(c, rnd, lock=True)
        if s["stored_state"] != "RUNNING":
            raise HTTPException(409, "Round is not running")
        c.execute(text("update public.contest_sessions set state = 'ENDED', ends_at = least(ends_at, now()) where round = :r"), {"r": rnd})
        audit(c, user, "round.end", "round", rnd)
        return _view(session(c, rnd))


class PublishIn(BaseModel):
    published: bool


@router.post("/rounds/{rnd}/publish")
def publish(rnd: int, body: PublishIn, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        s = session(c, rnd, lock=True)
        if s["state"] not in ("ENDED", "RESULTS_PUBLISHED"):
            raise HTTPException(409, "Results can only be published after the round has ended")
        c.execute(text("update public.contest_sessions set results_published = :p, state = case when :p then 'RESULTS_PUBLISHED' else 'ENDED' end::public.contest_state where round = :r"),
                  {"p": body.published, "r": rnd})
        audit(c, user, "round.publish", "round", rnd, {"published": body.published})
        return _view(session(c, rnd))


@router.post("/rounds/2/start")
def start_round2(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        s1, s2 = session(c, 1), session(c, 2, lock=True)
        if s1["state"] not in ("ENDED", "RESULTS_PUBLISHED"):
            raise HTTPException(409, "Round 1 must have ended first")
        if s2["state"] not in ("DRAFT", "SCHEDULED"):
            raise HTTPException(409, "Round 2 has already started")
        if not s2["finalists_locked"]:
            raise HTTPException(409, "Lock the finalists first")
        vid = (s2["config"] or {}).get("variant_id")
        if not vid:
            raise HTTPException(409, "Configure the Round 2 problem first")
        v = one(c, "select q.category::text as category, v.status::text as vs from public.question_variants v join public.questions q on q.id = v.question_id where v.id = :v", v=vid)
        if not v or v["category"] != "DUEL" or v["vs"] != "PUBLISHED":
            raise HTTPException(409, "The Round 2 problem must be a published DUEL question")
        # Same problem, constraints, tests and deadline for every finalist: one assignment row each, locked.
        n = c.execute(text("""insert into public.question_assignments (team_id, variant_id, category, locked, assigned_by)
                              select id, :v, 'DUEL', true, :u from public.teams where is_active and is_finalist
                              on conflict (team_id, category) do nothing"""), {"v": vid, "u": str(user.id)}).rowcount
        minutes = int((s2["config"] or {}).get("duration_minutes") or 60)
        c.execute(text("update public.contest_sessions set state = 'RUNNING', starts_at = now(), ends_at = now() + make_interval(mins => :m) where round = 2"), {"m": minutes})
        audit(c, user, "round.start", "round", 2, {"finalists": n, "duration_minutes": minutes})
        return _view(session(c, 2))


# ---------------- finalists ----------------
class FinalistsIn(BaseModel):
    team_ids: list[UUID]


@router.get("/finalists")
def finalists(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        r1 = {t["team_id"]: t for t in scoring.compute_scores(c, 1)}
        teams = rows(c, "select id, team_number, name, is_finalist, (select count(*) from public.team_members m where m.team_id = t.id) as members from public.teams t where is_active order by team_number")
        for t in teams:
            sc = r1.get(str(t["id"]), {})
            t.update(round1_total=sc.get("total", 0), rank=sc.get("rank"), reports_reviewed=sc.get("reports_reviewed", 0), reports_total=sc.get("reports_total", 0))
        return {"locked": session(c, 2)["finalists_locked"], "round1_state": session(c, 1)["state"], "teams": teams}


@router.put("/finalists")
def set_finalists(body: FinalistsIn, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        s2 = session(c, 2, lock=True)
        if s2["finalists_locked"]:
            raise HTTPException(409, "Finalists are locked")
        if session(c, 1)["state"] not in ("ENDED", "RESULTS_PUBLISHED"):
            raise HTTPException(409, "Round 1 must have ended before selecting finalists")
        ids = [str(i) for i in body.team_ids]
        ok = one(c, "select count(*) as n from public.teams where is_active and id = any(cast(:ids as uuid[]))", ids=ids)["n"]
        if ok != len(set(ids)):
            raise HTTPException(422, "Every finalist must be an existing active team (team numbers carry over from Round 1)")
        c.execute(text("update public.teams set is_finalist = (id = any(cast(:ids as uuid[])))"), {"ids": ids})
        audit(c, user, "finalists.set", "round", 2, {"team_ids": ids})
        return {"finalists": len(set(ids))}


@router.post("/finalists/lock")
def lock_finalists(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        n = one(c, "select count(*) as n from public.teams where is_finalist and is_active")["n"]
        if n == 0:
            raise HTTPException(409, "Select at least one finalist")
        c.execute(text("update public.contest_sessions set finalists_locked = true where round = 2"))
        audit(c, user, "finalists.lock", "round", 2, {"count": n})
        return {"locked": True, "finalists": n}


# ---------------- users & judges ----------------
@router.get("/users")
def users(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        return rows(c, """select p.id, p.email, p.full_name, p.role::text as role, p.team_id, t.team_number
                          from public.profiles p left join public.teams t on t.id = p.team_id order by p.role, t.team_number, p.email""")


class JudgeTeamsIn(BaseModel):
    team_ids: list[UUID]


@router.get("/judges")
def judges(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        js = rows(c, "select id, email, full_name from public.profiles where role = 'JUDGE' order by email")
        for j in js:
            j["team_ids"] = [str(r["team_id"]) for r in rows(c, "select team_id from public.judge_assignments where judge_id = :j", j=str(j["id"]))]
            j["pending"] = one(c, """select count(*) as n from public.autopsy_reports r join public.judge_assignments a on a.team_id = r.team_id and a.judge_id = :j
                                     where r.status in ('EVALUATION_PENDING', 'EVALUATED')""", j=str(j["id"]))["n"]
        return js


@router.put("/judges/{judge_id}/teams")
def assign_judge(judge_id: UUID, body: JudgeTeamsIn, user: CurrentUser = Depends(admin)):
    try:
        with admin_tx() as c:
            if not one(c, "select 1 as x from public.profiles where id = :j and role = 'JUDGE'", j=str(judge_id)):
                raise HTTPException(404, "Judge not found")
            c.execute(text("delete from public.judge_assignments where judge_id = :j"), {"j": str(judge_id)})
            for t in set(body.team_ids):
                c.execute(text("insert into public.judge_assignments (judge_id, team_id) values (:j, :t)"), {"j": str(judge_id), "t": str(t)})
            audit(c, user, "judge.assign", "profile", judge_id, {"team_ids": [str(t) for t in set(body.team_ids)]})
            return {"assigned": len(set(body.team_ids))}
    except DBAPIError as e:
        raise map_db_error(e)


# ---------------- announcements ----------------
class AnnouncementIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    round: Literal[1, 2] | None = None


@router.post("/announcements", status_code=201)
def announce(body: AnnouncementIn, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        a = one(c, "insert into public.contest_announcements (round, message, created_by) values (:r, :m, :u) returning id, round, message, created_at",
                r=body.round, m=body.message.strip(), u=str(user.id))
        audit(c, user, "announcement.create", "announcement", a["id"], {"round": body.round})
        pubcache.changed()
        return a


@router.delete("/announcements/{aid}", status_code=204)
def delete_announcement(aid: UUID, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        if not one(c, "delete from public.contest_announcements where id = :i returning id", i=str(aid)):
            raise HTTPException(404, "Announcement not found")
        audit(c, user, "announcement.delete", "announcement", aid)
        pubcache.changed()


# ---------------- monitoring ----------------
@router.get("/submissions")
def submissions(round: int = 1, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        return rows(c, """
            select t.team_number, t.name as team_name, q.title, q.category::text as category, v.label,
                   (select count(*) from public.submissions s where s.team_id = a.team_id and s.variant_id = a.variant_id and s.kind = 'FINAL') as finals,
                   (select count(*) from public.code_drafts d where d.team_id = a.team_id and d.variant_id = a.variant_id) as drafts,
                   f.created_at as last_final_at, e.outcome::text as outcome, e.provider,
                   rp.status::text as report_status
            from public.question_assignments a join public.teams t on t.id = a.team_id
            join public.question_variants v on v.id = a.variant_id join public.questions q on q.id = v.question_id
            left join lateral (select * from public.submissions s where s.team_id = a.team_id and s.variant_id = a.variant_id and s.kind = 'FINAL' order by created_at desc limit 1) f on true
            left join lateral (select * from public.execution_results x where x.submission_id = f.id order by created_at desc limit 1) e on true
            left join lateral (select status from public.autopsy_reports r where r.team_id = a.team_id and r.variant_id = a.variant_id order by version desc limit 1) rp on true
            where q.round = :r order by t.team_number, a.category""", r=round)


@router.get("/evaluations")
def evaluations(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        return rows(c, """
            with latest as (select distinct on (team_id, variant_id) * from public.autopsy_reports where status <> 'DRAFT' order by team_id, variant_id, version desc)
            select r.id as report_id, t.team_number, q.title, r.status::text as report_status,
                   e.id as evaluation_id, e.status as ai_status, e.attempts, e.error, e.needs_review, e.model,
                   exists (select 1 from public.report_evaluations j where j.report_id = r.id and j.source = 'JUDGE' and j.approved_at is not null) as approved
            from latest r join public.teams t on t.id = r.team_id join public.question_variants v on v.id = r.variant_id
            join public.questions q on q.id = v.question_id
            left join public.report_evaluations e on e.report_id = r.id and e.source = 'AI' order by t.team_number, q.category""")


@router.post("/reports/{report_id}/evaluate")
def queue_evaluation(report_id: UUID, background: BackgroundTasks, user: CurrentUser = Depends(admin)):
    """Create (if missing) and retry the AI evaluation. Idempotent; never creates a second AI record."""
    with admin_tx() as c:
        r = one(c, "select status::text as status from public.autopsy_reports where id = :i", i=str(report_id))
        if not r or r["status"] == "DRAFT":
            raise HTTPException(404, "Submitted report not found")
        evaluation.ensure_job(c, report_id)
        ev = one(c, "select id, status, attempts from public.report_evaluations where report_id = :r and source = 'AI'", r=str(report_id))
        audit(c, user, "evaluation.retry", "report", report_id)
    background.add_task(evaluation.run_job, ev["id"])
    return {"evaluation_id": ev["id"], "status": ev["status"]}


@router.post("/evaluations/run-pending")
def run_pending(user: CurrentUser = Depends(admin)):
    return evaluation.run_pending()


# ---------------- manual scores (viva, bonus, round 2 judging) ----------------
class ManualScoreIn(BaseModel):
    round: Literal[1, 2]
    component: str = Field(min_length=1, max_length=50)
    marks: float = Field(ge=0)
    max_marks: float = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)


@router.put("/teams/{team_id}/manual-scores")
def manual_score(team_id: UUID, body: ManualScoreIn, user: CurrentUser = Depends(scorer)):
    if body.marks > body.max_marks:
        raise HTTPException(422, "marks cannot exceed max_marks")
    try:
        with admin_tx() as c:
            team_allowed(c, user, team_id)
            prev = one(c, "select marks, max_marks from public.manual_scores where team_id = :t and round = :r and component = :c",
                       t=str(team_id), r=body.round, c=body.component)
            c.execute(text("""insert into public.manual_scores (team_id, round, component, marks, max_marks, reason, entered_by)
                              values (:t, :r, :c, :m, :x, :why, :u)
                              on conflict (team_id, round, component) do update set marks = excluded.marks, max_marks = excluded.max_marks,
                                reason = excluded.reason, entered_by = excluded.entered_by"""),
                      {"t": str(team_id), "r": body.round, "c": body.component, "m": body.marks, "x": body.max_marks, "why": body.reason, "u": str(user.id)})
            if prev:
                c.execute(text("""insert into public.score_adjustments (team_id, criterion, previous_marks, new_marks, reason, adjusted_by)
                                  values (:t, :c, :p, :n, :why, :u)"""),
                          {"t": str(team_id), "c": f"manual:{body.component}", "p": prev["marks"], "n": body.marks, "why": body.reason, "u": str(user.id)})
            audit(c, user, "score.manual", "team", team_id, {**body.model_dump(), "previous": float(prev["marks"]) if prev else None})
            bump(c)
            return {"saved": True}
    except DBAPIError as e:
        raise map_db_error(e)


# ---------------- leaderboard, audit, exports ----------------
def _board(c, which: str) -> list[dict]:
    if which == "final":
        data = scoring.combined(c)
        if data is None:
            raise HTTPException(409, "Combined scoring is not configured (set both weights in Round 2 settings)")
        return data
    if which not in ("1", "2"):
        raise HTTPException(422, "round must be 1, 2 or final")
    return scoring.compute_scores(c, int(which))


@router.get("/leaderboard")
def admin_leaderboard(round: str = "1", user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        return {"round": round, "rows": [{**t, "last_final_at": t["last_final_at"]} for t in _board(c, round)]}


@router.get("/audit")
def audit_log(limit: int = 100, offset: int = 0, user: CurrentUser = Depends(admin)):
    limit = max(1, min(limit, 500))
    with admin_tx() as c:
        return rows(c, """select a.created_at, a.action, a.entity, a.entity_id, a.details, u.email as actor
                          from public.audit_logs a left join auth.users u on u.id = a.actor_id
                          order by a.created_at desc limit :l offset :o""", l=limit, o=max(offset, 0))


def _csv(name: str, header: list[str], data: list[list]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for row in data:
        # neutralise spreadsheet formula injection
        w.writerow([("'" + str(x)) if isinstance(x, str) and x[:1] in "=+-@" else x for x in row])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/export/leaderboard.csv")
def export_leaderboard(round: str = "1", user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        d = _board(c, round)
    return _csv(f"leaderboard-{round}", ["rank", "team_number", "team_name", "report", "code", "manual", "total"],
                [[t["rank"], t["team_number"], t["name"], t["report"], t["code"], t["manual"], t["total"]] for t in d])


@router.get("/export/submissions.csv")
def export_submissions(round: int = 1, user: CurrentUser = Depends(admin)):
    d = submissions(round, user)
    return _csv(f"submissions-round-{round}", ["team_number", "team_name", "category", "question", "variant", "finals", "last_final_at", "outcome", "provider", "report_status"],
                [[r["team_number"], r["team_name"], r["category"], r["title"], r["label"], r["finals"], r["last_final_at"], r["outcome"], r["provider"], r["report_status"]] for r in d])


# ---------------- operations / monitoring ----------------
@router.get("/ops/status")
def ops_status(user: CurrentUser = Depends(admin)):
    """What an operator needs on competition day: is the DB healthy, is evaluation keeping up, which risky modes are on."""
    t0 = time.perf_counter()
    with admin_tx() as c:
        c.execute(text("select 1"))
        db_ms = round((time.perf_counter() - t0) * 1000)
        ev = one(c, """select count(*) filter (where status = 'PENDING') as pending, count(*) filter (where status = 'FAILED') as failed,
                              count(*) filter (where status = 'COMPLETED') as completed,
                              coalesce(extract(epoch from now() - min(created_at) filter (where status in ('PENDING', 'FAILED')))::int, 0) as oldest_waiting_seconds
                       from public.report_evaluations where source = 'AI'""")
        errors = rows(c, "select error, count(*) as n from public.report_evaluations where source = 'AI' and status = 'FAILED' group by error order by n desc limit 5")
        recent = one(c, "select count(*) as n from public.audit_logs where created_at > now() - interval '10 minutes'")
    judge = os.getenv("JUDGE_PROVIDER", "disabled")
    return {"database_ms": db_ms, "evaluations": ev, "evaluation_errors": errors, "admin_actions_last_10_min": recent["n"],
            "judge_provider": judge, "judge_is_real": judge == "judge0", "evaluation_mode": os.getenv("EVALUATION_MODE", "background"),
            "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
            "warnings": [w for w in (
                "Code execution is NOT real: results are not correctness verdicts." if judge != "judge0" else None,
                f"{ev['failed']} AI evaluation(s) failed; retry from Round 1 → Report evaluations." if ev["failed"] else None,
                f"AI evaluations have waited {ev['oldest_waiting_seconds']//60} min." if ev["oldest_waiting_seconds"] > 600 else None,
                "Evaluation mode is 'worker' but no recent completions; check the worker service." if os.getenv("EVALUATION_MODE") == "worker" and ev["pending"] and ev["oldest_waiting_seconds"] > 120 else None) if w]}
