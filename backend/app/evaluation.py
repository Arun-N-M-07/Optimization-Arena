"""Evaluation job lifecycle: create -> claim -> call Gemini -> persist. Safe to retry; never double-scores."""
import json
import logging
import threading
import time

from sqlalchemy import text

from . import gemini_eval
from .config import get_settings
from .db import admin_tx, one, rows

log = logging.getLogger("arena.evaluation")

MAX_ATTEMPTS = 6
RUN_PENDING_LIMIT = 20            # jobs one admin press may attempt
RUN_PENDING_WORKERS = 4           # evaluated in parallel inside one request
RUN_PENDING_BUDGET_SECONDS = 250  # a press stops STARTING jobs that could not finish by then; vercel.json allows 300 s per request
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
    return _run_job(evaluation_id)[0]


def _run_job(evaluation_id) -> tuple[str, bool]:
    """(status, claimed). claimed is False when this call did no work because another worker holds the job or it is already done."""
    with admin_tx() as c:
        claimed = one(c, """update public.report_evaluations set status = 'PENDING', started_at = now(), attempts = attempts + 1
                            where id = :id and source = 'AI' and attempts < :max
                              and (status = 'FAILED' or (status = 'PENDING' and (started_at is null or started_at < now() - interval '5 minutes')))
                            returning report_id""", id=str(evaluation_id), max=MAX_ATTEMPTS)
        if not claimed:
            cur = one(c, "select status from public.report_evaluations where id = :id", id=str(evaluation_id))
            return (cur["status"] if cur else "MISSING"), False
        ctx = _load_context(c, claimed["report_id"])
    try:
        result = EVALUATOR(ctx)
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        with admin_tx() as c:
            c.execute(text("update public.report_evaluations set status = 'FAILED', error = :e where id = :id"),
                      {"e": msg, "id": str(evaluation_id)})
        return "FAILED", True
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
    return "COMPLETED", True


# A job is eligible when it failed (and has attempts left) or its claim is stale (the process that held it died).
_ELIGIBLE = """source = 'AI' and attempts < :m
              and (status = 'FAILED' or (status = 'PENDING' and (started_at is null or started_at < now() - interval '5 minutes')))"""


def _clock() -> float:
    return time.monotonic()


def _eligible_ids(limit: int) -> list[str]:
    with admin_tx() as c:
        return [str(r["id"]) for r in rows(c, f"select id from public.report_evaluations where {_ELIGIBLE} order by created_at limit :l",
                                           m=MAX_ATTEMPTS, l=limit)]


def count_eligible() -> int:
    with admin_tx() as c:
        return one(c, f"select count(*) as n from public.report_evaluations where {_ELIGIBLE}", m=MAX_ATTEMPTS)["n"]


def run_pending(limit: int = 20, budget_seconds: float | None = None, workers: int = 1) -> dict:
    """Evaluate eligible jobs; returns {evaluation_id: status} for the jobs this call attempted.

    No budget (the long-lived worker): every selected job runs, sequentially, exactly as before.
    With `budget_seconds` (a serverless request with a hard time limit): a job is STARTED only if a worst-case evaluation
    (gemini_eval.WORST_CASE_SECONDS) would still finish inside the budget, and up to `workers` jobs run in parallel. Jobs that were
    not started are untouched (still eligible), so nothing is lost or duplicated; run it again to continue. Claiming is an atomic
    UPDATE in run_job, so overlapping calls (several admins, the worker) can never evaluate or score a job twice."""
    queue = _eligible_ids(limit)
    out: dict[str, str] = {}
    if budget_seconds is None and workers <= 1:
        for i in queue:
            out[i] = run_job(i)
        return out
    deadline = None if budget_seconds is None else _clock() + budget_seconds
    lock = threading.Lock()

    def drain():
        while True:
            with lock:
                if not queue or (deadline is not None and _clock() + gemini_eval.WORST_CASE_SECONDS > deadline):
                    return
                i = queue.pop(0)
            try:
                st, claimed = _run_job(i)
                if not claimed:
                    st = "SKIPPED"                      # someone else (another press, the worker) owns or finished it: not our work
            except Exception as e:                       # one bad job (e.g. a DB blip) must not abandon the others
                log.error("evaluation %s failed unexpectedly: %s", i[:8], type(e).__name__)
                st = "ERROR"
            with lock:
                out[i] = st
    threads = [threading.Thread(target=drain, name=f"eval-{n}") for n in range(max(1, workers))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return out


def evaluation_view(conn, evaluation_id) -> dict | None:
    e = one(conn, "select * from public.report_evaluations where id = :id", id=str(evaluation_id))
    if e:
        e["criteria"] = rows(conn, "select criterion, marks, max_marks, explanation, evidence from public.evaluation_criteria where evaluation_id = :id order by criterion", id=str(evaluation_id))
        e["total"] = sum(float(c["marks"]) for c in e["criteria"])
    return e
