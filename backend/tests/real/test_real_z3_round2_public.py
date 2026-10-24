"""REAL Postgres+Auth: round lifecycle, finalists, Round 2, publication, public leaderboard, announcements, audit, exports."""
import httpx
import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import admin_tx
from .conftest import FAKE, HIDDEN, REF, hdr

pytestmark = pytest.mark.real_supabase


def _sql(sql, **p):
    with admin_tx() as c:
        return c.execute(text(sql), p).scalar()


def test_public_leaderboard_is_hidden_until_published(arena):
    c = arena["client"]
    assert c.get("/api/public/leaderboard?round=1").json() == {"published": False, "rows": []}
    assert c.get("/api/public/leaderboard?round=2").json() == {"published": False, "rows": []}
    assert c.get("/api/public/leaderboard?round=final").json()["published"] is False
    assert c.get("/api/public/leaderboard?round=9").status_code == 422
    assert arena.call("admin", "post", "/admin/rounds/1/publish", {"published": True}).status_code == 409      # round still running


def test_finalists_and_round2_need_round1_to_end(arena):
    assert arena.call("admin", "put", "/admin/finalists", {"team_ids": [arena["ta"]]}).status_code == 409
    assert arena.call("admin", "post", "/admin/rounds/2/start").status_code == 409
    assert arena.call("pa", "post", "/admin/rounds/1/end").status_code == 403


def test_announcements(arena):
    c = arena["client"]
    assert arena.call("pa", "post", "/admin/announcements", {"message": "ZZTEST hack"}).status_code == 403
    a = arena.call("admin", "post", "/admin/announcements", {"message": "ZZTEST lunch at 12:30", "round": 1})
    assert a.status_code == 201
    st = c.get("/api/public/state").json()
    assert any(x["message"] == "ZZTEST lunch at 12:30" for x in st["announcements"]) and st["server_now"]
    assert st["rounds"]["1"]["state"] == "RUNNING"
    assert arena.call("admin", "delete", f"/admin/announcements/{a.json()['id']}").status_code == 204
    assert arena.call("admin", "post", "/admin/announcements", {"message": ""}).status_code == 422


def test_end_round1_stops_submissions_and_publishes_results(arena):
    r = arena.call("admin", "post", "/admin/rounds/1/end")
    assert r.status_code == 200 and r.json()["state"] == "ENDED"
    assert arena.call("admin", "post", "/admin/rounds/1/end").status_code == 409
    v = arena["va"]["DSA"]
    assert arena.call("pa", "post", f"/participant/variants/{v}/submit", {"language": "python", "code": "late"}).status_code == 409
    assert arena.call("admin", "put", "/admin/teams/%s/manual-scores" % arena["ta"], {"round": 1, "component": "viva", "marks": 8, "max_marks": 10, "reason": "post-round correction"}).status_code == 200
    r = arena.call("admin", "post", "/admin/rounds/1/publish", {"published": True})
    assert r.status_code == 200 and r.json()["results_published"] is True and r.json()["state"] == "RESULTS_PUBLISHED"
    body = arena["client"].get("/api/public/leaderboard?round=1")
    data = body.json()
    assert data["published"] is True
    top = next(x for x in data["rows"] if x["team_number"] == arena["n1"])
    assert top["rank"] == 1 and top["total"] == 23.5
    # public data never carries identities or internals
    for banned in ("email", "team_id", "last_final_at", "reason", HIDDEN, REF):
        assert banned not in body.text
    assert "@" not in body.text


def test_released_marks_are_visible_only_to_the_owning_team(arena):
    a = arena.call("pa", "get", "/participant/results").json()
    assert a["released"] is True
    dsa = next(i for i in a["items"] if i["category"] == "DSA")
    assert dsa["total"] == 15.5 and len(dsa["criteria"]) == 4 and dsa["comment"] == "Great complexity analysis"
    assert next(i for i in a["items"] if i["category"] == "DBMS")["total"] == 0           # unreviewed report earns nothing yet
    b = arena.call("pb", "get", "/participant/results").json()
    assert all(i["total"] == 0 for i in b["items"]) and "Great complexity" not in str(b)


def test_finalist_selection_lock_and_round2_requirements(arena):
    assert arena.call("admin", "put", "/admin/finalists", {"team_ids": ["00000000-0000-0000-0000-000000000000"]}).status_code == 422
    assert arena.call("admin", "post", "/admin/finalists/lock").status_code == 409            # none selected
    f = arena.call("admin", "get", "/admin/finalists").json()
    mine = {t["team_number"]: t for t in f["teams"]}
    assert mine[arena["n1"]]["round1_total"] == 23.5 and mine[arena["n1"]]["rank"] == 1
    assert arena.call("admin", "put", "/admin/finalists", {"team_ids": [arena["ta"]]}).status_code == 200
    assert arena.call("admin", "post", "/admin/rounds/2/start").status_code == 409            # not locked
    assert arena.call("admin", "post", "/admin/finalists/lock").status_code == 200
    assert arena.call("admin", "put", "/admin/finalists", {"team_ids": [arena["ta"], arena["tb"]]}).status_code == 409
    assert arena.call("admin", "post", "/admin/rounds/2/start").status_code == 409            # no problem configured


def test_round2_config_validation_and_unofficial_mechanics_stay_off(arena):
    cfg = {"duration_minutes": 60, "variant_id": arena["vb"]["DSA"]}
    assert arena.call("admin", "put", "/admin/rounds/2/config", cfg).status_code == 422                       # a Round 1 problem
    assert arena.call("admin", "put", "/admin/rounds/2/config", {"power_ups_enabled": True}).status_code == 422
    assert arena.call("admin", "put", "/admin/rounds/2/config", {"viva_enabled": True}).status_code == 422
    assert arena.call("admin", "put", "/admin/rounds/2/config", {"surprise": 1}).status_code == 422
    r = arena.call("admin", "put", "/admin/rounds/2/config", {"duration_minutes": 60, "variant_id": arena["DUEL"]["D"], "code_points_per_question": 50})
    assert r.status_code == 200 and r.json()["config"]["duration_minutes"] == 60


def test_round2_only_finalists_same_problem_and_server_deadline(arena):
    r = arena.call("admin", "post", "/admin/rounds/2/start")
    assert r.status_code == 200 and r.json()["state"] == "RUNNING"
    mins = _sql("select extract(epoch from (ends_at - starts_at)) / 60 from public.contest_sessions where round = 2")
    assert round(float(mins)) == 60
    qa = arena.call("pa", "get", "/participant/questions").json()
    duel = next(q for q in qa["questions"] if q["category"] == "DUEL")
    assert duel["variant_id"] == arena["DUEL"]["D"] and qa["rounds"]["2"]["state"] == "RUNNING"
    qb = arena.call("pb", "get", "/participant/questions").json()
    assert all(q["category"] != "DUEL" for q in qb["questions"])                            # non-finalist: no Round 2 access
    D = arena["DUEL"]["D"]
    assert arena.call("pb", "put", f"/participant/variants/{D}/draft", {"language": "python", "code": "x"}).status_code == 404
    assert arena.call("pb", "post", f"/participant/variants/{D}/submit", {"language": "python", "code": "x"}).status_code == 404
    assert arena.call("pa", "put", f"/participant/variants/{D}/draft", {"language": "python", "code": "print(1)"}).status_code == 200
    s = arena.call("pa", "post", f"/participant/variants/{D}/submit", {"language": "python", "code": "print(1)"})
    assert s.status_code == 201 and s.json()["result"]["is_mock"] is True
    assert arena.call("pa", "put", f"/participant/variants/{D}/report", {"inefficiency": "x"}).status_code == 422     # no reports in Round 2
    assert arena.call("admin", "put", "/admin/rounds/2/config", {"duration_minutes": 30}).status_code == 409                # frozen once started
    assert arena.call("admin", "put", "/admin/rounds/2/config", {"variant_id": arena["vb"]["DSA"]}).status_code in (409, 422)
    # the server clock decides the deadline, whatever the browser says
    with admin_tx() as c:
        c.execute(text("update public.contest_sessions set ends_at = starts_at + interval '1 millisecond' where round = 2"))
    late = arena.call("pa", "post", f"/participant/variants/{D}/submit", {"language": "python", "code": "print(2)"})
    assert late.status_code == 409
    assert arena.call("pa", "get", "/participant/questions").json()["rounds"]["2"]["state"] == "ENDED"


def test_round2_scoring_publication_and_combined_board(arena):
    assert arena.call("admin", "post", "/admin/rounds/2/publish", {"published": True}).status_code == 200      # ended by the deadline
    # mock judge results never earn code points; only manual/real results score
    b = arena.call("admin", "get", "/admin/leaderboard?round=2").json()["rows"]
    assert [r["team_number"] for r in b] == [arena["n1"]] and b[0]["code"] == 0 and b[0]["total"] == 0
    assert arena.call("admin", "put", f"/admin/teams/{arena['ta']}/manual-scores", {"round": 2, "component": "round2_score", "marks": 40, "max_marks": 100, "reason": "Judged by panel"}).status_code == 200
    pub = arena["client"].get("/api/public/leaderboard?round=2").json()
    assert pub["published"] and [r["team_number"] for r in pub["rows"]] == [arena["n1"]] and pub["rows"][0]["total"] == 40
    fin = arena["client"].get("/api/public/leaderboard?round=final").json()
    assert fin["published"] is False and "not been configured" in fin["note"]                                  # no invented formula
    assert arena.call("admin", "put", "/admin/rounds/2/config", {"final": {"round1_weight": 1, "round2_weight": 0.5}, "duration_minutes": 60, "variant_id": arena["DUEL"]["D"], "code_points_per_question": 50}).status_code == 200
    fin = arena["client"].get("/api/public/leaderboard?round=final").json()
    assert fin["published"] and fin["rows"][0]["total"] == round(23.5 * 1 + 40 * 0.5, 1) == 43.5
    assert arena.call("admin", "get", "/admin/leaderboard?round=final").status_code == 200


def test_unpublish_hides_results_again(arena):
    assert arena.call("admin", "post", "/admin/rounds/1/publish", {"published": False}).status_code == 200
    assert arena["client"].get("/api/public/leaderboard?round=1").json()["published"] is False
    assert arena.call("pa", "get", "/participant/results").json()["released"] is False
    arena.call("admin", "post", "/admin/rounds/1/publish", {"published": True})


def test_audit_log_and_exports_are_admin_only(arena):
    log = arena.call("admin", "get", "/admin/audit?limit=300").json()
    actions = {e["action"] for e in log}
    assert {"round.start", "round.end", "report.review", "assignment.set", "finalists.lock", "score.manual", "round.publish"} <= actions
    assert all("password" not in str(e["details"]).lower() for e in log)
    for who in ("pa", "judge1"):
        assert arena.call(who, "get", "/admin/audit").status_code == 403
        assert arena.call(who, "get", "/admin/export/leaderboard.csv").status_code == 403
    csv_ = arena.call("admin", "get", "/admin/export/leaderboard.csv?round=1")
    assert csv_.status_code == 200 and csv_.text.splitlines()[0] == "rank,team_number,team_name,report,code,manual,total" and str(arena["n1"]) in csv_.text
    sub = arena.call("admin", "get", "/admin/export/submissions.csv?round=1")
    assert sub.status_code == 200 and "team_number" in sub.text.splitlines()[0]
    subs = arena.call("admin", "get", "/admin/submissions?round=1").json()
    assert {r["team_number"] for r in subs} == {arena["n1"], arena["n2"]} and HIDDEN not in str(subs)
