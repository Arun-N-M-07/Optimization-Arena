"""Shared REAL-Supabase 'arena' for the workspace/review/round-2 suites (files z1..z3 run in order).

Creates: admin, judge1 (assigned to team A), judge2 (unassigned), teams A and B with 2 members + a participant
each, three Round 1 questions with variants A/B (A->team A, B->team B), a Round 2 DUEL question; starts Round 1.
Judge provider is the MOCK (nothing is executed) and Gemini is replaced by a controllable fake unless a test
opts into the real model. Everything is deleted afterwards and both rounds are reset.
"""
import os
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import evaluation
from app.db import admin_tx
from app.gemini_eval import CriterionEval, EvalResponse
from app.main import app
from . import supa

HIDDEN = "HIDDEN-TEST-INPUT-4471"
REF = "REFERENCE-SOLUTION-SECRET-9921"
FAKE = {"mode": "ok", "calls": 0}


def fake_evaluator(ctx):
    FAKE["calls"] += 1
    if FAKE["mode"] == "fail":
        raise RuntimeError("simulated Gemini outage")
    marks = {"INEFFICIENCY": 4.0, "APPROACH": 3.5, "COMPLEXITY": 4.0, "TRADEOFFS": 3.0}
    return EvalResponse(criteria=[CriterionEval(criterion=k, marks=v, explanation=f"Reasoned explanation for {k.lower()}.") for k, v in marks.items()],
                        summary="Solid report overall.", needs_review=False, injection_suspected=False)


_TOK: dict = {}


def hdr(email):
    if email not in _TOK:
        _TOK[email] = supa.sign_in(email)
    return {"Authorization": f"Bearer {_TOK[email]}"}


class Arena(dict):
    def call(self, who, method, path, body=None, **kw):
        h = hdr(self[who]["email"]) if isinstance(who, str) else who
        if method in ("get", "delete"):
            return getattr(self["client"], method)(f"/api{path}", headers=h, **kw)
        return getattr(self["client"], method)(f"/api{path}", json=body, headers=h, **kw)


def _variant(label, cat, langs):
    return {"label": label, "description": f"Optimize this {cat} code ({label}).", "expected_behavior": "Same output.",
            "constraints": "n <= 1e5", "languages": list(langs), "original_code": {l: f"# slow {cat} {label} ({l})" for l in langs},
            "visible_tests": [{"input": "1", "expected_output": "1"}, {"input": "2", "expected_output": "2"}],
            "hidden_tests": [{"input": HIDDEN, "expected_output": "42"}],
            "reference_solution": {l: REF for l in langs}, "reference_concepts": "hash map", "expected_complexity": "O(n)"}


@pytest.fixture(scope="session")
def arena():
    os.environ["JUDGE_PROVIDER"] = "mock"
    evaluation.EVALUATOR = fake_evaluator
    a = Arena(client=TestClient(app), n1=random.randint(7000, 7499), n2=random.randint(7500, 7999), users=[])
    admin = supa.create_user("ADMIN")
    j1, j2 = supa.create_user("JUDGE"), supa.create_user("JUDGE")
    a.update(admin=admin, judge1=j1, judge2=j2)
    a["users"] += [admin, j1, j2]
    try:
        for key, num in (("ta", a["n1"]), ("tb", a["n2"])):
            t = a.call("admin", "post", "/admin/teams", {"team_number": num, "name": f"ZZ Team {num}"}).json()
            a[key] = t["id"]
            for m in ("One", "Two"):
                assert a.call("admin", "post", f"/admin/teams/{t['id']}/members", {"full_name": f"{num} {m}"}).status_code == 201
        for key, team in (("pa", "ta"), ("pb", "tb")):
            email = f"arena-test-{uuid.uuid4().hex[:10]}@example.com"
            r = a.call("admin", "post", "/admin/users", {"email": email, "password": supa.PASSWORD, "role": "PARTICIPANT", "team_id": a[team]})
            assert r.status_code == 201, r.text
            a[key] = {"id": r.json()["id"], "email": email}
            a["users"].append(a[key])
        for cat, langs in {"DSA": ("python", "cpp"), "OOP": ("java",), "DBMS": ("sql",)}.items():
            q = a.call("admin", "post", "/admin/questions", {"category": cat, "title": f"ZZTEST {cat}"}).json()
            a.call("admin", "patch", f"/admin/questions/{q['id']}/status", {"status": "PUBLISHED"})
            a[cat] = {"q": q["id"]}
            for lab in ("A", "B"):
                v = a.call("admin", "post", f"/admin/questions/{q['id']}/variants", _variant(lab, cat, langs)).json()
                assert a.call("admin", "patch", f"/admin/variants/{v['id']}/status", {"status": "PUBLISHED"}).status_code == 200
                a[cat][lab] = v["id"]
        for cat in ("DSA", "OOP", "DBMS"):
            for team, lab in (("ta", "A"), ("tb", "B")):
                assert a.call("admin", "put", f"/admin/teams/{a[team]}/assignments/{cat}", {"variant_id": a[cat][lab]}).status_code == 200
        d = a.call("admin", "post", "/admin/questions", {"category": "DUEL", "title": "ZZTEST DUEL"}).json()
        a.call("admin", "patch", f"/admin/questions/{d['id']}/status", {"status": "PUBLISHED"})
        dv = a.call("admin", "post", f"/admin/questions/{d['id']}/variants", _variant("D", "DUEL", ("python", "cpp"))).json()
        a.call("admin", "patch", f"/admin/variants/{dv['id']}/status", {"status": "PUBLISHED"})
        a["DUEL"] = {"q": d["id"], "D": dv["id"]}
        assert a.call("admin", "put", f"/admin/judges/{j1['id']}/teams", {"team_ids": [a["ta"]]}).status_code == 200
        r = a.call("admin", "post", "/admin/rounds/1/start", {"duration_minutes": 150})
        assert r.status_code == 200, r.text
        yield a
    finally:
        with admin_tx() as c:
            ids = [u["id"] for u in a["users"]]
            c.execute(text("delete from public.contest_announcements where message like 'ZZTEST %'"))
            c.execute(text("delete from public.teams where name like 'ZZ Team %'"))
            c.execute(text("delete from public.questions where title like 'ZZTEST %'"))
            c.execute(text("delete from public.audit_logs where actor_id = any(cast(:ids as uuid[]))"), {"ids": ids})
            c.execute(text("update public.contest_sessions set state = 'DRAFT', starts_at = null, ends_at = null, config = '{}'::jsonb, finalists_locked = false, results_published = false"))
        for u in a["users"]:
            supa.delete_user(u["id"])
        evaluation.EVALUATOR = __import__("app.gemini_eval", fromlist=["evaluate"]).evaluate
