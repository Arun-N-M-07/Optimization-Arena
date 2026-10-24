"""REAL Postgres: EVALUATION_MODE=worker keeps jobs persisted; the worker path is idempotent and crash-safe."""
import pytest
from sqlalchemy import text

from app import evaluation
from app.db import admin_tx
from .conftest import FAKE
from .test_real_z1_workspace import SECTIONS

pytestmark = pytest.mark.real_supabase


def _ev(report_id):
    with admin_tx() as c:
        r = c.execute(text("select id, status, attempts, started_at is not null from public.report_evaluations where report_id = :r and source = 'AI'"), {"r": report_id}).first()
        return dict(id=str(r[0]), status=r[1], attempts=r[2], claimed=r[3]) if r else None


def test_worker_mode_persists_the_job_and_the_worker_completes_it_exactly_once(arena, monkeypatch):
    monkeypatch.setenv("EVALUATION_MODE", "worker")
    v = arena["va"]["OOP"]
    assert arena.call("pa", "put", f"/participant/variants/{v}/report", SECTIONS).status_code == 200
    FAKE["calls"] = 0
    r = arena.call("pa", "post", f"/participant/variants/{v}/report/submit")
    assert r.status_code == 200
    rep = arena.call("pa", "get", f"/participant/variants/{v}/report").json()["report"]
    ev = _ev(rep["id"])
    assert rep["status"] == "EVALUATION_PENDING" and ev["status"] == "PENDING" and ev["attempts"] == 0 and FAKE["calls"] == 0   # persisted, nothing ran in the API
    out = evaluation.run_pending()
    assert out.get(ev["id"]) == "COMPLETED" and FAKE["calls"] == 1
    assert evaluation.run_pending().get(ev["id"]) is None                                              # nothing left to do
    assert evaluation.run_job(ev["id"]) == "COMPLETED" and FAKE["calls"] == 1                           # a duplicate trigger never rescores
    assert arena.call("pa", "get", f"/participant/variants/{v}/report").json()["report"]["status"] == "EVALUATED"
    arena["worker_report"] = rep["id"]


def test_a_job_whose_worker_crashed_is_recovered_but_a_live_claim_is_respected(arena):
    rid = arena["worker_report"]
    ev = _ev(rid)
    with admin_tx() as c:     # simulate: worker claimed the job a moment ago and is still working on it
        c.execute(text("delete from public.evaluation_criteria where evaluation_id = :e"), {"e": ev["id"]})
        c.execute(text("update public.report_evaluations set status = 'PENDING', started_at = now(), completed_at = null, attempts = 1 where id = :e"), {"e": ev["id"]})
    FAKE["calls"] = 0
    assert evaluation.run_pending().get(ev["id"]) is None and FAKE["calls"] == 0                        # live claim: not stolen
    with admin_tx() as c:     # ...and now the worker died 10 minutes ago
        c.execute(text("update public.report_evaluations set started_at = now() - interval '10 minutes' where id = :e"), {"e": ev["id"]})
    assert evaluation.run_pending().get(ev["id"]) == "COMPLETED" and FAKE["calls"] == 1                 # recovered after the stale-claim window
    with admin_tx() as c:
        assert c.execute(text("select count(*) from public.report_evaluations where report_id = :r and source = 'AI'"), {"r": rid}).scalar() == 1
        assert c.execute(text("select count(*) from public.evaluation_criteria where evaluation_id = :e"), {"e": ev["id"]}).scalar() == 4


def test_gemini_failures_are_retried_by_the_worker_and_exhaust_cleanly(arena):
    rid = arena["worker_report"]
    ev = _ev(rid)
    with admin_tx() as c:
        c.execute(text("delete from public.evaluation_criteria where evaluation_id = :e"), {"e": ev["id"]})
        c.execute(text("update public.report_evaluations set status = 'FAILED', error = 'simulated', started_at = now() - interval '1 hour', attempts = 2 where id = :e"), {"e": ev["id"]})
    FAKE["mode"] = "fail"
    try:
        assert evaluation.run_pending().get(ev["id"]) == "FAILED" and _ev(rid)["attempts"] == 3          # retried, failed again, still retryable
        with admin_tx() as c:
            c.execute(text("update public.report_evaluations set attempts = :m where id = :e"), {"m": evaluation.MAX_ATTEMPTS, "e": ev["id"]})
        FAKE["calls"] = 0
        assert evaluation.run_pending().get(ev["id"]) is None and FAKE["calls"] == 0                    # attempts exhausted: no hammering the API
    finally:
        FAKE["mode"] = "ok"
        with admin_tx() as c:
            c.execute(text("update public.report_evaluations set attempts = 0 where id = :e"), {"e": ev["id"]})
    assert evaluation.run_job(ev["id"]) == "COMPLETED"                                                   # an admin retry still works after exhaustion reset
