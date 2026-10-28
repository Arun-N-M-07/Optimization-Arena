"""What a participant is told about their report's evaluation. HTTP 200 on submit means only "saved"; the response and the RLS-protected
GET must say whether the evaluation is pending, delayed (failed, will be retried) or complete, and must never leak marks or errors."""
import json

import pytest
from fastapi.testclient import TestClient

from app import evaluation
from app.auth import CurrentUser, current_user
from app.gemini_eval import CriterionEval, EvalResponse
from app.main import app

SECRETS = ("RuntimeError", "simulated", "Traceback", "marks", "explanation", "attempts", "error", "criteria", "summary")


class Model:
    def __init__(self):
        self.mode, self.calls = "ok", 0

    def __call__(self, ctx):
        self.calls += 1
        if self.mode == "fail":
            raise RuntimeError("simulated Gemini outage with internal detail")
        return EvalResponse(criteria=[CriterionEval(criterion=k, marks=4.0, explanation=f"Reasoned explanation for {k.lower()}.")
                                      for k in ("INEFFICIENCY", "APPROACH", "COMPLEXITY", "TRADEOFFS")], summary="ok")


@pytest.fixture
def env(db_url, use_db, monkeypatch, world):
    use_db(db_url, EVALUATION_MODE="inline")
    model = Model()
    monkeypatch.setattr(evaluation, "EVALUATOR", model)
    state = {"user": CurrentUser(world["participant"], "p@example.test", "PARTICIPANT", world["team"])}
    app.dependency_overrides[current_user] = lambda: state["user"]
    yield model, state, world
    app.dependency_overrides.clear()


H = {"Authorization": "Bearer x"}


def submit(w):
    return TestClient(app).post(f"/api/participant/variants/{w['variant']}/report/submit", headers=H)


def get_report(w):
    return TestClient(app).get(f"/api/participant/variants/{w['variant']}/report", headers=H)


def assert_nothing_leaks(resp):
    body = json.dumps({k: v for k, v in resp.json()["report"].items() if k not in ("inefficiency", "approach", "complexity", "tradeoffs")})
    for word in SECRETS:
        assert word not in body, f"{word!r} leaked to the participant: {body}"


def test_a_draft_has_no_evaluation_state(env):
    model, state, w = env
    assert get_report(w).json()["report"]["evaluation_state"] is None


def test_gemini_failure_http_200_but_the_participant_is_told_evaluation_is_delayed(env, raw):
    model, state, w = env
    model.mode = "fail"
    r = submit(w)
    assert r.status_code == 200                                               # saved...
    rep = r.json()["report"]
    assert rep["status"] == "EVALUATION_PENDING" and rep["evaluation_state"] == "DELAYED"      # ...but explicitly NOT evaluated
    assert_nothing_leaks(r)
    g = get_report(w)                                                         # the page the participant reloads (RLS read path)
    assert g.json()["report"]["evaluation_state"] == "DELAYED" and g.json()["report"]["status"] == "EVALUATION_PENDING"
    assert_nothing_leaks(g)
    again = submit(w).json()                                                  # re-pressing submit is harmless and reports the same truth
    assert again["already_submitted"] is True and again["report"]["evaluation_state"] == "DELAYED" and model.calls == 1


def test_success_is_reported_complete_only_when_it_really_completed(env):
    model, state, w = env
    r = submit(w)
    assert r.json()["report"]["status"] == "EVALUATED" and r.json()["report"]["evaluation_state"] == "COMPLETE"
    assert get_report(w).json()["report"]["evaluation_state"] == "COMPLETE"
    assert_nothing_leaks(r)


def test_queued_for_a_worker_or_manual_run_is_pending_not_complete(env, monkeypatch):
    model, state, w = env
    monkeypatch.setenv("EVALUATION_MODE", "worker")                          # job persisted, nobody has run it yet
    r = submit(w)
    assert r.json()["report"]["evaluation_state"] == "PENDING" and model.calls == 0
    assert get_report(w).json()["report"]["evaluation_state"] == "PENDING"


def test_state_follows_the_admin_retry_from_delayed_to_complete(env):
    model, state, w = env
    model.mode = "fail"
    submit(w)
    assert get_report(w).json()["report"]["evaluation_state"] == "DELAYED"
    model.mode = "ok"
    state["user"] = CurrentUser(w["admin"], "a@example.test", "ADMIN", None)
    report_id = TestClient(app).get(f"/api/admin/evaluations", headers=H).json()[0]["report_id"]
    assert TestClient(app).post(f"/api/admin/reports/{report_id}/evaluate", headers=H).json()["status"] == "COMPLETED"
    state["user"] = CurrentUser(w["participant"], "p@example.test", "PARTICIPANT", w["team"])
    assert get_report(w).json()["report"]["evaluation_state"] == "COMPLETE"


def test_another_team_cannot_read_the_report_or_its_state(env, raw):
    model, state, w = env
    submit(w)
    other_team = raw.execute("insert into public.teams (team_number, name) values ((select max(team_number) + 1 from public.teams), 'LT other') returning id").fetchone()[0]
    uid = raw.execute("insert into auth.users (email) values ('other@example.test') returning id").fetchone()[0]
    raw.execute("update public.profiles set team_id = %s where id = %s", (other_team, uid))
    try:
        state["user"] = CurrentUser(uid, "other@example.test", "PARTICIPANT", other_team)
        other = get_report(w)                                                # lookups are scoped to the caller's team: nothing to see
        assert other.status_code == 200 and other.json()["report"] is None and "evaluation_state" not in json.dumps(other.json())
    finally:
        raw.execute("delete from public.teams where id = %s", (other_team,))
        raw.execute("delete from auth.users where id = %s", (uid,))
