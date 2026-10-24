"""REAL Postgres+Auth: AI job reliability, judge scoping, review/override audit, scoring, concurrency, RLS."""
import concurrent.futures as cf
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import evaluation
from app.auth import CurrentUser
from app.config import get_settings
from app.db import admin_tx, user_tx
from app.main import app
from .conftest import FAKE, HIDDEN, REF, hdr
from .test_real_z1_workspace import SECTIONS

pytestmark = pytest.mark.real_supabase
CRIT = ("INEFFICIENCY", "APPROACH", "COMPLEXITY", "TRADEOFFS")


def _review(marks, approve=True, comment="ok"):
    return {"criteria": [{"criterion": c, "marks": m, "explanation": f"Marks for {c.lower()} after reading the report."} for c, m in zip(CRIT, marks)],
            "comment": comment, "approve": approve}


def _count(sql, **p):
    with admin_tx() as c:
        return c.execute(text(sql), p).scalar()


def _submit_report(arena, who, variant, lang, code="print('ok')"):
    assert arena.call(who, "post", f"/participant/variants/{variant}/submit", {"language": lang, "code": code}).status_code == 201
    assert arena.call(who, "put", f"/participant/variants/{variant}/report", SECTIONS).status_code == 200
    return arena.call(who, "post", f"/participant/variants/{variant}/report/submit")


def test_gemini_outage_never_blocks_report_submission_and_retry_is_idempotent(arena):
    v = arena["va"]["DBMS"]
    FAKE["mode"] = "fail"
    try:
        r = _submit_report(arena, "pa", v, "sql", "select 1")
        assert r.status_code == 200                                    # participant is not blocked
    finally:
        FAKE["mode"] = "ok"
    rep = arena.call("pa", "get", f"/participant/variants/{v}/report").json()["report"]
    assert rep["status"] == "EVALUATION_PENDING"
    ev = arena.call("admin", "get", "/admin/evaluations").json()
    mine = next(e for e in ev if e["report_id"] == rep["id"])
    assert mine["ai_status"] == "FAILED" and mine["attempts"] == 1 and "simulated" in mine["error"]
    calls = FAKE["calls"]
    assert arena.call("admin", "post", f"/admin/reports/{rep['id']}/evaluate").status_code == 200       # retry
    assert arena.call("admin", "post", f"/admin/reports/{rep['id']}/evaluate").status_code == 200       # retry again: must not re-score
    assert FAKE["calls"] == calls + 1
    ev = arena.call("admin", "get", "/admin/evaluations").json()
    mine = next(e for e in ev if e["report_id"] == rep["id"])
    assert mine["ai_status"] == "COMPLETED" and mine["attempts"] == 2
    assert _count("select count(*) from public.report_evaluations where report_id = :r and source = 'AI'", r=rep["id"]) == 1
    assert _count("select count(*) from public.evaluation_criteria c join public.report_evaluations e on e.id = c.evaluation_id where e.report_id = :r", r=rep["id"]) == 4
    arena["report_dbms"] = rep["id"]


def test_concurrent_duplicate_requests_create_one_record(arena):
    v = arena["vb"]["OOP"]
    tok = hdr(arena["pb"]["email"])["Authorization"]

    def submit(_):
        c = TestClient(app)
        return c.post(f"/api/participant/variants/{v}/submit", json={"language": "java", "code": "class Once {}"},
                      headers={"Authorization": tok, "Idempotency-Key": "race-1"}).status_code
    with cf.ThreadPoolExecutor(5) as ex:
        codes = list(ex.map(submit, range(5)))
    assert set(codes) == {201}
    assert _count("select count(*) from public.submissions where variant_id = :v and kind = 'FINAL'", v=v) == 1
    assert arena.call("pb", "put", f"/participant/variants/{v}/report", SECTIONS).status_code == 200

    def rsubmit(_):
        return TestClient(app).post(f"/api/participant/variants/{v}/report/submit", headers={"Authorization": tok}).status_code
    with cf.ThreadPoolExecutor(5) as ex:
        assert set(ex.map(rsubmit, range(5))) == {200}
    rid = arena.call("pb", "get", f"/participant/variants/{v}/report").json()["report"]["id"]
    assert _count("select count(*) from public.report_evaluations where report_id = :r and source = 'AI'", r=rid) == 1
    arena["report_pb_oop"] = rid


def test_team_b_also_has_a_dsa_report(arena):
    r = _submit_report(arena, "pb", arena["vb"]["DSA"], "python")
    assert r.status_code == 200
    arena["report_pb_dsa"] = arena.call("pb", "get", f"/participant/variants/{arena['vb']['DSA']}/report").json()["report"]["id"]


# ---------------- judge scoping ----------------
def test_judge_sees_only_assigned_teams(arena):
    q1 = arena.call("judge1", "get", "/judge/queue").json()["items"]
    assert {i["team_number"] for i in q1} == {arena["n1"]} and len(q1) == 2
    assert arena.call("judge2", "get", "/judge/queue").json()["items"] == []
    q_admin = arena.call("admin", "get", "/judge/queue").json()["items"]
    assert {i["team_number"] for i in q_admin} == {arena["n1"], arena["n2"]}
    # cannot open another team's report: 404 not 403, so existence is not revealed
    assert arena.call("judge1", "get", f"/judge/reports/{arena['report_pb_dsa']}").status_code == 404
    assert arena.call("judge2", "get", f"/judge/reports/{arena['report_dsa']}").status_code == 404
    assert arena.call("judge1", "post", f"/judge/reports/{arena['report_pb_dsa']}/review", _review([5, 5, 5, 5])).status_code == 404
    for who in ("pa", "pb"):
        assert arena.call(who, "get", "/judge/queue").status_code == 403


def test_judge_detail_has_ai_assessment_but_no_hidden_tests_or_reference_solution(arena):
    r = arena.call("judge1", "get", f"/judge/reports/{arena['report_dsa']}")
    assert r.status_code == 200
    d = r.json()
    assert d["submission"]["code"] and d["inefficiency"] == SECTIONS["inefficiency"]
    ai = next(e for e in d["evaluations"] if e["source"] == "AI")
    assert ai["total"] == 14.5 and ai["model"] and len(ai["criteria"]) == 4        # 4+3.5+4+3, summed by the backend
    assert HIDDEN not in r.text and REF not in r.text


def test_review_validation_override_audit_and_status(arena):
    rid = arena["report_dsa"]
    path = f"/judge/reports/{rid}/review"
    assert arena.call("judge1", "post", path, _review([6, 3, 4, 3])).status_code == 422                 # above the 5-mark cap
    assert arena.call("judge1", "post", path, _review([4.3, 3, 4, 3])).status_code == 422               # not a half-mark step
    bad = _review([4, 3, 4, 3]); bad["criteria"].pop()
    assert arena.call("judge1", "post", path, bad).status_code == 422                                   # criterion missing
    assert arena.call("pa", "post", path, _review([5, 5, 5, 5])).status_code == 403
    assert _count("select count(*) from public.report_evaluations where report_id = :r and source = 'JUDGE'", r=rid) == 0
    r = arena.call("judge1", "post", path, _review([5, 3.5, 4, 3], comment="Great complexity analysis"))
    assert r.status_code == 201 and r.json()["total"] == 15.5 and r.json()["approved"] is True        # AI said 4.0 for INEFFICIENCY: override
    adj = _count("select count(*) from public.score_adjustments where report_id = :r and criterion = 'INEFFICIENCY' and previous_marks = 4 and new_marks = 5 and length(reason) > 4", r=rid)
    assert adj == 1
    assert _count("select count(*) from public.score_adjustments where report_id = :r", r=rid) == 1    # only the changed criterion
    assert _count("select count(*) from public.audit_logs where action = 'report.review' and entity_id = :r", r=rid) == 1
    d = arena.call("judge1", "get", f"/judge/reports/{rid}").json()
    assert d["status"] == "REVIEWED" and len(d["history"]) == 1
    assert [e["source"] for e in d["evaluations"]] == ["AI", "JUDGE"]                                   # AI evaluation is preserved


def test_official_score_is_computed_by_backend_from_approved_reviews_only(arena):
    rows = arena.call("admin", "get", "/admin/leaderboard?round=1").json()["rows"]
    a = next(r for r in rows if r["team_number"] == arena["n1"])
    b = next(r for r in rows if r["team_number"] == arena["n2"])
    assert a["report"] == 15.5 and a["reports_reviewed"] == 1 and a["reports_total"] == 3           # out of the 3 assigned reports; DBMS is submitted but unreviewed, OOP not reviewed
    assert b["report"] == 0 and a["rank"] == 1 and b["rank"] == 2
    assert arena.call("pa", "get", "/admin/leaderboard").status_code == 403
    assert arena.call("judge1", "get", "/admin/leaderboard").status_code == 403


def test_manual_scores_judge_scope_validation_and_audit(arena):
    body = {"round": 1, "component": "viva", "marks": 7, "max_marks": 10, "reason": "Defended trade-offs well"}
    assert arena.call("judge1", "put", f"/admin/teams/{arena['ta']}/manual-scores", body).status_code == 200
    assert arena.call("judge1", "put", f"/admin/teams/{arena['tb']}/manual-scores", body).status_code == 404     # not assigned
    assert arena.call("judge1", "put", f"/admin/teams/{arena['ta']}/manual-scores", {**body, "marks": 11}).status_code == 422
    assert arena.call("pa", "put", f"/admin/teams/{arena['ta']}/manual-scores", body).status_code == 403
    assert arena.call("judge1", "put", f"/admin/teams/{arena['ta']}/manual-scores", {**body, "marks": 8, "reason": "Revised after review"}).status_code == 200
    a = next(r for r in arena.call("admin", "get", "/admin/leaderboard?round=1").json()["rows"] if r["team_number"] == arena["n1"])
    assert a["manual"] == 8 and a["total"] == 23.5
    assert _count("select count(*) from public.score_adjustments where team_id = :t and criterion = 'manual:viva' and previous_marks = 7 and new_marks = 8", t=arena["ta"]) == 1


def test_participants_cannot_see_marks_before_release(arena):
    assert arena.call("pa", "get", "/participant/results").json()["released"] is False
    for who, t in (("pa", arena["ta"]), ("pb", arena["tb"])):
        with user_tx(CurrentUser(id=uuid.UUID(arena[who]["id"]), email=None, role="PARTICIPANT", team_id=uuid.UUID(t))) as c:
            for tbl in ("report_evaluations", "evaluation_criteria", "score_adjustments", "manual_scores", "audit_logs"):
                assert c.execute(text(f"select count(*) from public.{tbl}")).scalar() == 0, tbl


# ---------------- RLS in Postgres for judges / direct API abuse ----------------
def _judge(arena, who):
    return CurrentUser(id=uuid.UUID(arena[who]["id"]), email=None, role="JUDGE", team_id=None)


def test_rls_judge_is_limited_to_assigned_teams(arena):
    with user_tx(_judge(arena, "judge1")) as c:
        assert {r[0] for r in c.execute(text("select team_number from public.teams"))} == {arena["n1"]}
        assert {str(r[0]) for r in c.execute(text("select team_id from public.submissions"))} == {arena["ta"]}
        assert {str(r[0]) for r in c.execute(text("select team_id from public.autopsy_reports"))} == {arena["ta"]}
        assert c.execute(text("select count(*) from public.question_private")).scalar() == 0            # judges never get hidden tests via RLS
        assert c.execute(text("select count(*) from public.audit_logs")).scalar() == 0
    with user_tx(_judge(arena, "judge2")) as c:
        for tbl in ("teams", "submissions", "autopsy_reports", "report_evaluations", "execution_results", "question_assignments", "team_members"):
            assert c.execute(text(f"select count(*) from public.{tbl}")).scalar() == 0, tbl


def test_participants_cannot_write_through_postgrest(arena):
    s = get_settings()
    h = {"apikey": s.supabase_publishable_key, **hdr(arena["pa"]["email"]), "Content-Type": "application/json", "Prefer": "return=minimal"}
    v = arena["va"]["DSA"]
    ins = httpx.post(f"{s.supabase_url}/rest/v1/submissions", headers=h, timeout=20,
                     json={"team_id": arena["ta"], "variant_id": v, "language": "python", "code": "bypass", "kind": "FINAL"})
    assert ins.status_code in (401, 403)                        # no INSERT policy: the deadline logic cannot be bypassed
    d = httpx.post(f"{s.supabase_url}/rest/v1/code_drafts", headers=h, timeout=20, json={"team_id": arena["ta"], "variant_id": v, "language": "python", "code": "x"})
    assert d.status_code in (401, 403)
    up = httpx.patch(f"{s.supabase_url}/rest/v1/autopsy_reports?id=eq.{arena['report_dsa']}", headers=h, timeout=20, json={"inefficiency": "HACKED"})
    assert up.status_code in (200, 204, 401, 403)
    assert _count("select inefficiency from public.autopsy_reports where id = :r", r=arena["report_dsa"]) == SECTIONS["inefficiency"]     # unchanged
    sc = httpx.patch(f"{s.supabase_url}/rest/v1/manual_scores?team_id=eq.{arena['ta']}", headers=h, timeout=20, json={"marks": 10})
    assert _count("select marks from public.manual_scores where team_id = :t and component = 'viva'", t=arena["ta"]) == 8
    assert sc.status_code in (200, 204, 401, 403)


def test_invalid_tokens_and_malformed_requests(arena):
    c = arena["client"]
    v = arena["va"]["DSA"]
    assert c.get("/api/participant/questions").status_code == 401
    assert c.get("/api/participant/questions", headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.e30.expired"}).status_code == 401
    assert c.post(f"/api/participant/variants/{v}/submit", content=b"{not json", headers={**hdr(arena["pa"]["email"]), "Content-Type": "application/json"}).status_code == 422
    assert c.post(f"/api/participant/variants/not-a-uuid/submit", json={"language": "python", "code": "x"}, headers=hdr(arena["pa"]["email"])).status_code == 422
    assert arena.call("pa", "get", "/admin/users").status_code == 403
    assert arena.call("judge1", "post", "/admin/rounds/1/end").status_code == 403
