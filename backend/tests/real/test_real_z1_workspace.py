"""REAL Postgres+Auth: drafts, run/submit, idempotency, immutability, deadlines, Autopsy Report lifecycle."""
import pytest
from sqlalchemy import text

from app.auth import CurrentUser
from app.db import admin_tx, user_tx
from .conftest import FAKE, HIDDEN, REF, hdr

pytestmark = pytest.mark.real_supabase


def _as(arena, who):
    import uuid
    return CurrentUser(id=uuid.UUID(arena[who]["id"]), email=None, role="PARTICIPANT",
                       team_id=uuid.UUID(arena["ta"] if who == "pa" else arena["tb"]))


def _set_deadline(minutes):
    """minutes < 0 means 'already over'. Always keeps ends_at > starts_at (a DB check) even if the round started seconds ago."""
    with admin_tx() as c:
        if minutes < 0:
            c.execute(text("update public.contest_sessions set ends_at = starts_at + interval '1 millisecond' where round = 1"))
        else:
            c.execute(text("update public.contest_sessions set ends_at = now() + make_interval(mins => :m) where round = 1"), {"m": minutes})


def test_questions_list_shows_own_variants_and_no_private_data(arena):
    r = arena.call("pa", "get", "/participant/questions")
    assert r.status_code == 200
    body = r.json()
    assert [q["label"] for q in body["questions"]] == ["A", "A", "A"] and body["server_now"]
    assert HIDDEN not in r.text and REF not in r.text
    arena["va"] = {q["category"]: q["variant_id"] for q in body["questions"]}
    arena["vb"] = {q["category"]: q["variant_id"] for q in arena.call("pb", "get", "/participant/questions").json()["questions"]}


def test_draft_save_restore_and_validation(arena):
    v = arena["va"]["DSA"]
    r = arena.call("pa", "put", f"/participant/variants/{v}/draft", {"language": "python", "code": "print('draft 1')"})
    assert r.status_code == 200 and r.json()["saved"]
    arena.call("pa", "put", f"/participant/variants/{v}/draft", {"language": "python", "code": "print('draft 2')"})   # upsert, not duplicate
    arena.call("pa", "put", f"/participant/variants/{v}/draft", {"language": "cpp", "code": "int main(){}"})
    d = arena.call("pa", "get", f"/participant/variants/{v}/drafts").json()["drafts"]
    assert d["python"]["code"] == "print('draft 2')" and d["cpp"]["code"] == "int main(){}"
    with admin_tx() as c:
        assert c.execute(text("select count(*) from public.code_drafts where variant_id = :v"), {"v": v}).scalar() == 2
    assert arena.call("pa", "put", f"/participant/variants/{v}/draft", {"language": "ruby", "code": "x"}).status_code == 422
    assert arena.call("pa", "put", f"/participant/variants/{v}/draft", {"language": "python", "code": "x" * 200_001}).status_code == 422
    assert arena.call("pa", "put", f"/participant/variants/{v}/draft", {"code": "x"}).status_code == 422          # malformed


def test_cross_team_isolation_for_drafts_and_variants(arena):
    va, vb = arena["va"]["DSA"], arena["vb"]["DSA"]
    # team B cannot read, write, run or submit against team A's variant; and A cannot against B's
    assert arena.call("pb", "get", f"/participant/variants/{va}/drafts").json()["drafts"] == {}
    for method, path in (("put", f"/participant/variants/{va}/draft"), ("post", f"/participant/variants/{va}/run"), ("post", f"/participant/variants/{va}/submit")):
        assert arena.call("pb", method, path, {"language": "python", "code": "steal"}).status_code == 404
    assert arena.call("pb", "get", f"/participant/variants/{va}/submissions").json()["submissions"] == []
    assert arena.call("pb", "get", f"/participant/variants/{va}/report").json()["report"] is None
    # RLS in Postgres itself: B's session sees none of A's drafts
    with user_tx(_as(arena, "pb")) as c:
        assert c.execute(text("select count(*) from public.code_drafts where team_id = :t"), {"t": arena["ta"]}).scalar() == 0
        assert c.execute(text("select count(*) from public.code_drafts")).scalar() == 0
    with user_tx(_as(arena, "pa")) as c:
        assert c.execute(text("select count(*) from public.code_drafts")).scalar() == 2
    assert vb != va


def test_run_uses_mock_judge_and_is_labelled(arena):
    v = arena["va"]["DSA"]
    r = arena.call("pa", "post", f"/participant/variants/{v}/run", {"language": "python", "code": "print(1)"})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["is_mock"] is True and res["provider"] == "mock" and "NOT executed" in res["safe_message"]
    assert res["total_hidden"] is None                         # a run never touches hidden tests
    wa = arena.call("pa", "post", f"/participant/variants/{v}/run", {"language": "python", "code": "# MOCK:WRONG_ANSWER"}).json()["result"]
    assert wa["outcome"] == "WRONG_ANSWER"


def test_run_burst_is_rate_limited(arena):
    v = arena["va"]["OOP"]
    with admin_tx() as c:      # simulate a burst already inside the 10-second window
        for _ in range(6):
            c.execute(text("insert into public.submissions (team_id, variant_id, language, code, kind) values (:t, :v, 'java', 'x', 'RUN')"), {"t": arena["ta"], "v": v})
    r = arena.call("pa", "post", f"/participant/variants/{v}/run", {"language": "java", "code": "class A{}"})
    assert r.status_code == 429
    with admin_tx() as c:      # clean up so later tests are unaffected
        c.execute(text("delete from public.submissions where team_id = :t and variant_id = :v and kind = 'RUN' and code = 'x'"), {"t": arena["ta"], "v": v})


def test_submit_final_is_idempotent_judged_and_immutable(arena):
    v = arena["va"]["DSA"]
    h = {**hdr(arena["pa"]["email"]), "Idempotency-Key": "k-final-1"}
    body = {"language": "python", "code": "print('final answer')"}
    r1 = arena["client"].post(f"/api/participant/variants/{v}/submit", json=body, headers=h)
    r2 = arena["client"].post(f"/api/participant/variants/{v}/submit", json=body, headers=h)       # double click / retry
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["submission_id"] == r2.json()["submission_id"] and r2.json()["duplicate"] is True and r1.json()["duplicate"] is False
    res = r1.json()["result"]
    assert res["total_hidden"] == 1 and res["is_mock"] and HIDDEN not in r1.text and REF not in r1.text   # counts only
    with admin_tx() as c:
        assert c.execute(text("select count(*) from public.submissions where variant_id = :v and kind = 'FINAL'"), {"v": v}).scalar() == 1
        assert c.execute(text("select count(*) from public.execution_results where submission_id = :s"), {"s": r1.json()["submission_id"]}).scalar() == 1
    # immutable: even the privileged role cannot edit a submission
    with pytest.raises(Exception, match="immutable"):
        with admin_tx() as c:
            c.execute(text("update public.submissions set code = 'tampered' where id = :s"), {"s": r1.json()["submission_id"]})
    hist = arena.call("pa", "get", f"/participant/variants/{v}/submissions").json()["submissions"]
    assert hist[0]["kind"] in ("FINAL", "RUN") and any(s["kind"] == "FINAL" and s["code"] == body["code"] for s in hist)
    arena["final_sub"] = r1.json()["submission_id"]


def test_submit_rejects_bad_language_and_provider_failure_is_system_error(arena, monkeypatch):
    v = arena["va"]["DSA"]
    assert arena.call("pa", "post", f"/participant/variants/{v}/submit", {"language": "java", "code": "x"}).status_code == 422
    import os
    monkeypatch.setenv("JUDGE_PROVIDER", "disabled")
    r = arena.call("pa", "post", f"/participant/variants/{v}/submit", {"language": "python", "code": "print(2)"})
    assert r.status_code == 201 and r.json()["result"]["outcome"] == "SYSTEM_ERROR" and r.json()["result"]["is_mock"] is False
    assert "not enabled" in r.json()["result"]["safe_message"]      # saved, but never misreported as WRONG_ANSWER


def test_deadline_is_enforced_by_server_clock(arena):
    v = arena["va"]["DSA"]
    _set_deadline(-1)                                               # the deadline passed a minute ago
    try:
        for method, path, body in (("put", f"/participant/variants/{v}/draft", {"language": "python", "code": "late"}),
                                   ("post", f"/participant/variants/{v}/run", {"language": "python", "code": "late"}),
                                   ("post", f"/participant/variants/{v}/submit", {"language": "python", "code": "late"}),
                                   ("put", f"/participant/variants/{v}/report", {"inefficiency": "late"})):
            r = arena.call("pa", method, path, body)
            assert r.status_code == 409 and "not open" in r.json()["detail"], (path, r.text)
        q = arena.call("pa", "get", "/participant/questions").json()
        assert q["round"]["state"] == "ENDED" and len(q["questions"]) == 3      # content stays readable after the end
    finally:
        _set_deadline(150)
    assert arena.call("pa", "put", f"/participant/variants/{v}/draft", {"language": "python", "code": "back"}).status_code == 200


# ---------------- Autopsy Report ----------------
SECTIONS = {"inefficiency": "The nested loops compare every pair of elements, giving quadratic work on large inputs.",
            "approach": "We replaced the inner scan with a hash set lookup so each element is visited once.",
            "complexity": "Original O(n^2) time, O(1) space. Optimized O(n) time, O(n) space for the set.",
            "tradeoffs": "We spend extra memory for the set; for tiny inputs the simple loop is just as fast and simpler."}


def test_report_requires_code_and_minimum_content(arena):
    v = arena["va"]["OOP"]            # OOP has no FINAL submission yet
    assert arena.call("pa", "put", f"/participant/variants/{v}/report", SECTIONS).status_code == 200
    r = arena.call("pa", "post", f"/participant/variants/{v}/report/submit")
    assert r.status_code == 422 and "Submit your optimized code" in r.text
    arena.call("pa", "put", f"/participant/variants/{v}/report", {**SECTIONS, "approach": "too short"})
    arena.call("pa", "post", f"/participant/variants/{v}/submit", {"language": "java", "code": "class Fast {}"})
    r = arena.call("pa", "post", f"/participant/variants/{v}/report/submit")
    assert r.status_code == 422 and r.json()["detail"]["sections"] == ["approach"]
    assert arena.call("pa", "put", f"/participant/variants/{v}/report", {"inefficiency": "x" * 4001}).status_code == 422
    assert arena.call("pa", "put", f"/participant/variants/{arena['vb']['OOP']}/report", SECTIONS).status_code == 404


def test_report_submit_triggers_ai_evaluation_and_is_immutable(arena):
    v = arena["va"]["DSA"]
    FAKE["calls"] = 0
    arena.call("pa", "put", f"/participant/variants/{v}/report", SECTIONS)
    r = arena.call("pa", "post", f"/participant/variants/{v}/report/submit")
    assert r.status_code == 200 and r.json()["already_submitted"] is False
    again = arena.call("pa", "post", f"/participant/variants/{v}/report/submit")      # duplicate request
    assert again.json()["already_submitted"] is True
    rep = arena.call("pa", "get", f"/participant/variants/{v}/report").json()["report"]
    assert rep["status"] == "EVALUATED" and FAKE["calls"] == 1   # fake ran once, in the background
    assert arena.call("pa", "put", f"/participant/variants/{v}/report", SECTIONS).status_code == 409
    with pytest.raises(Exception, match="immutable|Submitted reports"):
        with admin_tx() as c:
            c.execute(text("update public.autopsy_reports set approach = 'changed' where id = :i"), {"i": rep["id"]})
    with admin_tx() as c:
        assert c.execute(text("select count(*) from public.report_evaluations where report_id = :r and source = 'AI'"), {"r": rep["id"]}).scalar() == 1
    with admin_tx() as c:      # the report is bound to the LATEST final submission at submit time
        latest = c.execute(text("select id from public.submissions where team_id = :t and variant_id = :v and kind = 'FINAL' order by created_at desc limit 1"), {"t": arena["ta"], "v": v}).scalar()
    assert str(rep["submission_id"]) == str(latest)
    arena["report_dsa"] = rep["id"]
    # participants never see AI marks before release
    assert "marks" not in arena.call("pa", "get", f"/participant/variants/{v}/report").text
    assert arena.call("pa", "get", "/participant/results").json() == {"released": False, "items": []}


def test_amendment_creates_new_version_and_keeps_the_old(arena):
    v = arena["va"]["DSA"]
    r = arena.call("pa", "post", f"/participant/variants/{v}/report/amend")
    assert r.status_code == 201 and r.json()["report"]["version"] == 2 and r.json()["report"]["status"] == "DRAFT"
    with admin_tx() as c:
        assert c.execute(text("select count(*) from public.autopsy_reports where variant_id = :v and team_id = :t"), {"v": v, "t": arena["ta"]}).scalar() == 2
        c.execute(text("delete from public.autopsy_reports where variant_id = :v and team_id = :t and version = 2"), {"v": v, "t": arena["ta"]})
