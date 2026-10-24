"""Participant coding workspace: drafts, run, submit, history, Autopsy Report, released results."""
import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .. import evaluation
from ..auth import CurrentUser, require_roles
from ..db import admin_tx, audit, map_db_error, one, rows, user_tx
from ..judge_provider import MAX_CODE_CHARS, JudgeRequest, TestCase, get_provider, run_safely
from ..rounds import require_open, session

router = APIRouter(prefix="/api/participant", tags=["participant: workspace"])
participant = require_roles("PARTICIPANT")

SECTION_MAX = 4000
SECTION_MIN_TO_SUBMIT = 30
RUN_BURST_LIMIT = 6        # run attempts per team per 10 seconds


class CodeIn(BaseModel):
    language: str = Field(min_length=1, max_length=20)
    code: str = Field(max_length=MAX_CODE_CHARS)


class ReportIn(BaseModel):
    inefficiency: str = Field(default="", max_length=SECTION_MAX)
    approach: str = Field(default="", max_length=SECTION_MAX)
    complexity: str = Field(default="", max_length=SECTION_MAX)
    tradeoffs: str = Field(default="", max_length=SECTION_MAX)


def _team(user: CurrentUser) -> str:
    if not user.team_id:
        raise HTTPException(404, "Your account is not linked to a team yet")
    return str(user.team_id)


def _assigned(conn, team_id: str, variant_id: UUID) -> dict:
    """The caller's team must hold an assignment for this published variant. 404 (not 403) hides existence."""
    v = one(conn, """select v.id, v.languages, v.visible_tests, q.round, q.category::text as category
                     from public.question_assignments a
                     join public.question_variants v on v.id = a.variant_id
                     join public.questions q on q.id = v.question_id
                     where a.team_id = :t and a.variant_id = :v and v.status = 'PUBLISHED' and q.status = 'PUBLISHED'""",
            t=team_id, v=str(variant_id))
    if not v:
        raise HTTPException(404, "Question not found")
    return v


def _check_language(v: dict, language: str):
    if language not in v["languages"]:
        raise HTTPException(422, f"Language must be one of {v['languages']}")


def _result_view(row: dict | None) -> dict | None:
    if not row:
        return None
    keys = ("outcome", "passed_visible", "total_visible", "passed_hidden", "total_hidden", "runtime_ms", "memory_kb", "safe_message", "provider")
    out = {k: row.get(k) for k in keys}
    out["is_mock"] = row.get("provider") == "mock"
    return out


# ---------------- drafts ----------------
@router.get("/variants/{variant_id}/drafts")
def get_drafts(variant_id: UUID, user: CurrentUser = Depends(participant)):
    team = _team(user)
    with user_tx(user) as c:   # RLS: only the caller's team drafts are visible
        d = rows(c, "select language, code, updated_at from public.code_drafts where variant_id = :v and team_id = :t",
                 v=str(variant_id), t=team)
        return {"drafts": {r["language"]: {"code": r["code"], "updated_at": r["updated_at"]} for r in d}}


@router.put("/variants/{variant_id}/draft")
def save_draft(variant_id: UUID, body: CodeIn, user: CurrentUser = Depends(participant)):
    team = _team(user)
    try:
        with admin_tx() as c:
            v = _assigned(c, team, variant_id)
            _check_language(v, body.language)
            require_open(c, v["round"])
            r = one(c, """insert into public.code_drafts (team_id, variant_id, language, code, updated_by)
                          values (:t, :v, :l, :c, :u)
                          on conflict (team_id, variant_id, language)
                          do update set code = excluded.code, updated_by = excluded.updated_by, updated_at = now()
                          returning updated_at""", t=team, v=str(variant_id), l=body.language, c=body.code, u=str(user.id))
            return {"saved": True, "updated_at": r["updated_at"]}
    except DBAPIError as e:
        raise map_db_error(e)


# ---------------- run / submit ----------------
def _judge_and_store(team: str, user: CurrentUser, variant_id: UUID, body: CodeIn, kind: str, key: str | None) -> dict:
    with admin_tx() as c:
        v = _assigned(c, team, variant_id)
        _check_language(v, body.language)
        require_open(c, v["round"])
        if kind == "RUN":
            n = one(c, "select count(*) as n from public.submissions where team_id = :t and kind = 'RUN' and created_at > now() - interval '10 seconds'", t=team)["n"]
            if n >= RUN_BURST_LIMIT:
                raise HTTPException(429, "Too many run attempts; wait a few seconds")
        sub = one(c, """insert into public.submissions (team_id, variant_id, submitted_by, language, code, kind, idempotency_key)
                        values (:t, :v, :u, :l, :c, cast(:k as public.submission_kind), :ik)
                        on conflict (team_id, idempotency_key) do nothing returning id, created_at""",
                  t=team, v=str(variant_id), u=str(user.id), l=body.language, c=body.code, k=kind, ik=key)
        if not sub:   # duplicate request: return the original outcome, do not re-judge or re-store
            old = one(c, """select s.id, s.created_at, s.kind::text as kind from public.submissions s
                            where s.team_id = :t and s.idempotency_key = :ik""", t=team, ik=key)
            res = one(c, "select * from public.execution_results where submission_id = :s order by created_at desc limit 1", s=str(old["id"]))
            return {"submission_id": old["id"], "kind": old["kind"], "created_at": old["created_at"], "duplicate": True, "result": _result_view(res)}
        hidden = []
        if kind == "FINAL":
            p = one(c, "select hidden_tests from public.question_private where variant_id = :v", v=str(variant_id))
            hidden = (p or {}).get("hidden_tests") or []
        visible = v["visible_tests"] or []
    tests = [TestCase(**t) for t in visible] + [TestCase(**t) for t in hidden]
    res = run_safely(get_provider(), JudgeRequest(language=body.language, code=body.code, tests=tests))
    nv = len(visible)
    pv = min(res.passed, nv) if res.outcome != "SYSTEM_ERROR" else None
    ph = max(res.passed - nv, 0) if (hidden and res.outcome != "SYSTEM_ERROR") else None
    with admin_tx() as c:
        c.execute(text("""insert into public.execution_results (submission_id, outcome, passed_visible, total_visible, passed_hidden,
                          total_hidden, runtime_ms, memory_kb, safe_message, provider)
                          values (:s, cast(:o as public.judge_outcome), :pv, :tv, :ph, :th, :rt, :mk, :m, :p)"""),
                  {"s": str(sub["id"]), "o": res.outcome, "pv": pv, "tv": nv, "ph": ph, "th": len(hidden) if hidden else None,
                   "rt": res.runtime_ms, "mk": res.memory_kb, "m": res.message, "p": res.provider})
    return {"submission_id": sub["id"], "kind": kind, "created_at": sub["created_at"], "duplicate": False,
            "result": {"outcome": res.outcome, "passed_visible": pv, "total_visible": nv, "passed_hidden": ph,
                       "total_hidden": len(hidden) if hidden else None, "runtime_ms": res.runtime_ms, "memory_kb": res.memory_kb,
                       "safe_message": res.message, "provider": res.provider, "is_mock": res.is_mock}}


@router.post("/variants/{variant_id}/run")
def run_code(variant_id: UUID, body: CodeIn, user: CurrentUser = Depends(participant),
             idempotency_key: Annotated[str | None, Header(max_length=100)] = None):
    return _judge_and_store(_team(user), user, variant_id, body, "RUN", idempotency_key)


@router.post("/variants/{variant_id}/submit", status_code=201)
def submit_code(variant_id: UUID, body: CodeIn, user: CurrentUser = Depends(participant),
                idempotency_key: Annotated[str | None, Header(max_length=100)] = None):
    return _judge_and_store(_team(user), user, variant_id, body, "FINAL", idempotency_key)


@router.get("/variants/{variant_id}/submissions")
def history(variant_id: UUID, user: CurrentUser = Depends(participant)):
    team = _team(user)
    with user_tx(user) as c:  # RLS-scoped
        subs = rows(c, """select s.id, s.kind::text as kind, s.language, s.code, s.created_at,
                                 e.outcome::text as outcome, e.passed_visible, e.total_visible, e.passed_hidden, e.total_hidden,
                                 e.runtime_ms, e.safe_message, e.provider
                          from public.submissions s
                          left join lateral (select * from public.execution_results r where r.submission_id = s.id
                                             order by r.created_at desc limit 1) e on true
                          where s.variant_id = :v and s.team_id = :t order by s.created_at desc limit 100""", v=str(variant_id), t=team)
        for s in subs:
            s["is_mock"] = s["provider"] == "mock"
        return {"submissions": subs}


# ---------------- Autopsy Report ----------------
def _latest_report(c, team: str, variant_id: UUID, lock: bool = False) -> dict | None:
    # lock=True serialises concurrent writers on the report row (same lock order everywhere: report, then evaluation)
    return one(c, f"""select id, version, status::text as status, inefficiency, approach, complexity, tradeoffs,
                            submission_id, submitted_at, updated_at
                     from public.autopsy_reports where team_id = :t and variant_id = :v order by version desc limit 1 {'for update' if lock else ''}""",
               t=team, v=str(variant_id))


@router.get("/variants/{variant_id}/report")
def get_report(variant_id: UUID, user: CurrentUser = Depends(participant)):
    team = _team(user)
    with user_tx(user) as c:
        r = _latest_report(c, team, variant_id)
        return {"report": r, "limits": {"max": SECTION_MAX, "min_to_submit": SECTION_MIN_TO_SUBMIT}}


@router.put("/variants/{variant_id}/report")
def save_report(variant_id: UUID, body: ReportIn, user: CurrentUser = Depends(participant)):
    team = _team(user)
    try:
        with admin_tx() as c:
            v = _assigned(c, team, variant_id)
            if v["round"] != 1:
                raise HTTPException(422, "Autopsy Reports exist only for Round 1 questions")
            require_open(c, 1)
            cur = _latest_report(c, team, variant_id, lock=True)
            if cur and cur["status"] != "DRAFT":
                raise HTTPException(409, "This report was already submitted. Create an amendment to change it.")
            if cur:
                c.execute(text("update public.autopsy_reports set inefficiency=:a, approach=:b, complexity=:c, tradeoffs=:d where id=:id"),
                          {"a": body.inefficiency, "b": body.approach, "c": body.complexity, "d": body.tradeoffs, "id": str(cur["id"])})
            else:
                c.execute(text("""insert into public.autopsy_reports (team_id, variant_id, version, inefficiency, approach, complexity, tradeoffs)
                                  values (:t, :v, 1, :a, :b, :c, :d)"""),
                          {"t": team, "v": str(variant_id), "a": body.inefficiency, "b": body.approach, "c": body.complexity, "d": body.tradeoffs})
            return {"report": _latest_report(c, team, variant_id)}
    except DBAPIError as e:
        raise map_db_error(e)


@router.post("/variants/{variant_id}/report/submit")
def submit_report(variant_id: UUID, background: BackgroundTasks, user: CurrentUser = Depends(participant)):
    team = _team(user)
    with admin_tx() as c:
        v = _assigned(c, team, variant_id)
        if v["round"] != 1:
            raise HTTPException(422, "Autopsy Reports exist only for Round 1 questions")
        require_open(c, 1)
        cur = _latest_report(c, team, variant_id, lock=True)
        if not cur:
            raise HTTPException(422, "Write the report first")
        if cur["status"] != "DRAFT":
            return {"report": cur, "already_submitted": True}     # idempotent
        short = [k for k in ("inefficiency", "approach", "complexity", "tradeoffs") if len(cur[k].strip()) < SECTION_MIN_TO_SUBMIT]
        if short:
            raise HTTPException(422, {"message": f"Each section needs at least {SECTION_MIN_TO_SUBMIT} characters", "sections": short})
        code = one(c, "select id from public.submissions where team_id = :t and variant_id = :v and kind = 'FINAL' order by created_at desc limit 1",
                   t=team, v=str(variant_id))
        if not code:
            raise HTTPException(422, "Submit your optimized code before submitting the report")
        c.execute(text("""update public.autopsy_reports set status = 'SUBMITTED', submitted_at = now(), submission_id = :s where id = :id"""),
                  {"s": str(code["id"]), "id": str(cur["id"])})
        job = evaluation.ensure_job(c, cur["id"])
        c.execute(text("update public.autopsy_reports set status = 'EVALUATION_PENDING' where id = :id"), {"id": str(cur["id"])})
        audit(c, user, "report.submit", "report", cur["id"], {"variant": str(variant_id), "version": cur["version"]})
        report = _latest_report(c, team, variant_id)
    if job:
        # background (default): runs after the response. inline: runs inside the request (use on serverless hosts that
        # freeze work after the response). manual: an admin triggers it. A failure never blocks the participant.
        mode = os.getenv("EVALUATION_MODE", "background")
        if mode == "inline":
            try:
                evaluation.run_job(job)
            except Exception:
                pass
            with admin_tx() as c:
                report = _latest_report(c, team, variant_id)
        elif mode == "background":
            background.add_task(evaluation.run_job, job)
        # worker / manual: the persisted PENDING job is processed by the worker process or by an admin
    return {"report": report, "already_submitted": False}


@router.post("/variants/{variant_id}/report/amend", status_code=201)
def amend_report(variant_id: UUID, user: CurrentUser = Depends(participant)):
    """New version copying the last submitted one; the old version stays untouched."""
    team = _team(user)
    try:
        with admin_tx() as c:
            _assigned(c, team, variant_id)
            require_open(c, 1)
            cur = _latest_report(c, team, variant_id, lock=True)
            if not cur or cur["status"] == "DRAFT":
                raise HTTPException(409, "Nothing to amend")
            c.execute(text("""insert into public.autopsy_reports (team_id, variant_id, version, inefficiency, approach, complexity, tradeoffs)
                              values (:t, :v, :n, :a, :b, :c, :d)"""),
                      {"t": team, "v": str(variant_id), "n": cur["version"] + 1, "a": cur["inefficiency"], "b": cur["approach"],
                       "c": cur["complexity"], "d": cur["tradeoffs"]})
            return {"report": _latest_report(c, team, variant_id)}
    except DBAPIError as e:
        raise map_db_error(e)


# ---------------- released results ----------------
@router.get("/results")
def my_results(user: CurrentUser = Depends(participant)):
    team = _team(user)
    with admin_tx() as c:     # explicit team scoping; marks are only ever released through this path
        s1 = session(c, 1)
        if not s1["results_published"]:
            return {"released": False, "items": []}
        items = rows(c, """
            with latest as (select distinct on (variant_id) id, variant_id, version, status::text as status from public.autopsy_reports
                            where team_id = :t and status <> 'DRAFT' order by variant_id, version desc),
            rev as (select distinct on (report_id) id, report_id, comment from public.report_evaluations
                    where source = 'JUDGE' and approved_at is not null order by report_id, approved_at desc)
            select q.title, q.category::text as category, v.label, l.version, rev.id as review_id, rev.comment
            from public.question_assignments a join public.question_variants v on v.id = a.variant_id
            join public.questions q on q.id = v.question_id
            left join latest l on l.variant_id = v.id left join rev on rev.report_id = l.id
            where a.team_id = :t and q.round = 1 order by a.category""", t=team)
        for it in items:
            it["criteria"] = rows(c, "select criterion, marks, max_marks, explanation from public.evaluation_criteria where evaluation_id = :e order by criterion",
                                  e=str(it["review_id"])) if it["review_id"] else []
            it["total"] = sum(float(x["marks"]) for x in it["criteria"])
            it["review_id"] = None
        return {"released": True, "items": items}
