"""Evaluation job lifecycle: create -> claim -> call Gemini -> persist. Safe to retry; never double-scores."""
import json

from sqlalchemy import text

from . import gemini_eval
from .config import get_settings
from .db import admin_tx, one, rows

MAX_ATTEMPTS = 6
EVALUATOR = gemini_eval.evaluate   # replaced in tests


def ensure_job(conn, report_id) -> str | None:
    """Idempotent: the partial unique index guarantees one AI evaluation per report+version."""
    r = one(conn, """insert into public.report_evaluations (report_id, source, status, model, eval_version)
                     values (:r, 'AI', 'PENDING', :m, :v) on conflict do nothing returning id""",
            r=str(report_id), m=get_settings().gemini_model, v=gemini_eval.EVAL_VERSION)
    return str(r["id"]) if r else None


def _load_context(conn, report_id) -> gemini_eval.EvalContext:
    r = one(conn, """select r.inefficiency, r.approach, r.complexity, r.tradeoffs, q.title, q.category::text as category,
                            v.description, v.expected_behavior, v.constraints, v.original_code, v.languages,
                            p.expected_complexity, p.reference_concepts, s.code, s.language
                     from public.autopsy_reports r
                     join public.question_variants v on v.id = r.variant_id
                     join public.questions q on q.id = v.question_id
                     left join public.question_private p on p.variant_id = v.id
                     left join public.submissions s on s.id = r.submission_id
                     where r.id = :id""", id=str(report_id))
    lang = r["language"] or r["languages"][0]
    return gemini_eval.EvalContext(
        title=r["title"], category=r["category"], description=r["description"], expected_behavior=r["expected_behavior"],
        constraints=r["constraints"], expected_complexity=r["expected_complexity"] or "",
        reference_concepts=r["reference_concepts"] or "", original_code=(r["original_code"] or {}).get(lang, ""),
        team_code=r["code"], language=r["language"], inefficiency=r["inefficiency"], approach=r["approach"],
        complexity=r["complexity"], tradeoffs=r["tradeoffs"])


def run_job(evaluation_id) -> str:
    """Returns the evaluation status after this call. Never raises for model/API problems."""
    with admin_tx() as c:
        claimed = one(c, """update public.report_evaluations set status = 'PENDING', started_at = now(), attempts = attempts + 1
                            where id = :id and source = 'AI' and attempts < :max
                              and (status = 'FAILED' or (status = 'PENDING' and (started_at is null or started_at < now() - interval '5 minutes')))
                            returning report_id""", id=str(evaluation_id), max=MAX_ATTEMPTS)
        if not claimed:
            cur = one(c, "select status from public.report_evaluations where id = :id", id=str(evaluation_id))
            return cur["status"] if cur else "MISSING"
        ctx = _load_context(c, claimed["report_id"])
    try:
        result = EVALUATOR(ctx)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        with admin_tx() as c:
            c.execute(text("update public.report_evaluations set status = 'FAILED', error = :e where id = :id"),
                      {"e": msg, "id": str(evaluation_id)})
        return "FAILED"
    with admin_tx() as c:
        c.execute(text("select 1 from public.autopsy_reports where id = (select report_id from public.report_evaluations where id = :id) for update"), {"id": str(evaluation_id)})
        for cr in result.criteria:
            c.execute(text("""insert into public.evaluation_criteria (evaluation_id, criterion, marks, max_marks, explanation, evidence)
                              values (:e, :c, :m, 5, :x, :ev) on conflict (evaluation_id, criterion) do nothing"""),
                      {"e": str(evaluation_id), "c": cr.criterion, "m": cr.marks, "x": cr.explanation, "ev": cr.evidence})
        summary = ("[Possible prompt injection detected] " if result.injection_suspected else "") + result.summary
        c.execute(text("""update public.report_evaluations set status = 'COMPLETED', completed_at = now(), error = null,
                          needs_review = :nr, summary = :s, model = :m where id = :id"""),
                  {"nr": result.needs_review or result.injection_suspected, "s": summary,
                   "m": get_settings().gemini_model, "id": str(evaluation_id)})
        c.execute(text("""update public.autopsy_reports set status = 'EVALUATED'
                          where id = (select report_id from public.report_evaluations where id = :id) and status = 'EVALUATION_PENDING'"""),
                  {"id": str(evaluation_id)})
    return "COMPLETED"


def run_pending(limit: int = 20) -> dict:
    with admin_tx() as c:
        ids = [str(r["id"]) for r in rows(c, """select id from public.report_evaluations where source = 'AI' and attempts < :m
              and (status = 'FAILED' or (status = 'PENDING' and (started_at is null or started_at < now() - interval '5 minutes')))
              order by created_at limit :l""", m=MAX_ATTEMPTS, l=limit)]
    out = {}
    for i in ids:
        out[i] = run_job(i)
    return out


def evaluation_view(conn, evaluation_id) -> dict | None:
    e = one(conn, "select * from public.report_evaluations where id = :id", id=str(evaluation_id))
    if e:
        e["criteria"] = rows(conn, "select criterion, marks, max_marks, explanation, evidence from public.evaluation_criteria where evaluation_id = :id order by criterion", id=str(evaluation_id))
        e["total"] = sum(float(c["marks"]) for c in e["criteria"])
    return e
