"""REAL Supabase project + REAL Postgres (via SQLAlchemy) + REAL Auth tokens.

Covers teams -> questions -> variants -> assignments, cross-team isolation, and
hidden-test privacy, both through the API and directly under Postgres RLS.
Everything created here is removed in teardown and Round 1 is reset to DRAFT.
Tests run in file order and share state on purpose (they walk the competition flow).
"""
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import CurrentUser
from app.db import admin_tx, get_engine, user_tx
from app.main import app
from . import supa

pytestmark = pytest.mark.real_supabase

HIDDEN = "SECRET-HIDDEN-INPUT-7731"
REF = "SECRET-REFERENCE-SOLUTION-9182"
S: dict = {}  # shared state across ordered tests


_TOKENS: dict = {}


def hdr(email):
    if email not in _TOKENS:
        _TOKENS[email] = supa.sign_in(email)
    return {"Authorization": f"Bearer {_TOKENS[email]}"}


@pytest.fixture(scope="module")
def world():
    client = TestClient(app)
    n1, n2 = random.randint(9000, 9499), random.randint(9500, 9999)
    admin = supa.create_user("ADMIN")
    judge = supa.create_user("JUDGE")
    stranger = supa.create_user("PARTICIPANT")  # participant with no team
    S.update(client=client, n1=n1, n2=n2, admin=admin, judge=judge, stranger=stranger, users=[admin, judge, stranger],
             ah=hdr(admin["email"]))
    yield S
    # ---- teardown: remove everything this module created, reset Round 1 ----
    with admin_tx() as c:
        ids = [u["id"] for u in S["users"]]
        c.execute(text("delete from public.teams where team_number in (:a, :b)"), {"a": n1, "b": n2})
        c.execute(text("delete from public.questions where title like 'ZZTEST %'"))
        c.execute(text("delete from public.audit_logs where actor_id = any(cast(:ids as uuid[]))"), {"ids": ids})
        c.execute(text("update public.contest_sessions set state='DRAFT', starts_at=null, ends_at=null where round=1"))
    for u in S["users"]:
        supa.delete_user(u["id"])


def post(world, path, body=None, h=None, method="post"):
    return getattr(world["client"], method)(f"/api{path}", json=body, headers=h or world["ah"])


# ---------------- teams ----------------
def test_participant_and_judge_cannot_use_admin_apis(world):
    for who in ("stranger", "judge"):
        h = hdr(world[who]["email"])
        assert world["client"].get("/api/admin/teams", headers=h).status_code == 403
        assert world["client"].post("/api/admin/teams", json={"team_number": 1, "name": "x"}, headers=h).status_code == 403


def test_admin_creates_teams_and_numbers_are_unique(world):
    a = post(world, "/admin/teams", {"team_number": world["n1"], "name": "ZZ Alpha"})
    b = post(world, "/admin/teams", {"team_number": world["n2"], "name": "ZZ Beta"})
    assert a.status_code == 201 and b.status_code == 201
    assert post(world, "/admin/teams", {"team_number": world["n1"], "name": "Dup"}).status_code == 409
    world["ta"], world["tb"] = a.json()["id"], b.json()["id"]
    assert a.json()["eligible"] is False  # no members yet


def test_member_limits_min_two_for_eligibility_max_three(world):
    ta = world["ta"]
    r = post(world, f"/admin/teams/{ta}/members", {"full_name": "A One"})
    assert r.status_code == 201 and r.json()["eligible"] is False  # 1 member: not eligible
    r = post(world, f"/admin/teams/{ta}/members", {"full_name": "A Two"})
    assert r.json()["eligible"] is True
    post(world, f"/admin/teams/{ta}/members", {"full_name": "A Three"})
    assert post(world, f"/admin/teams/{ta}/members", {"full_name": "A Four"}).status_code == 409  # DB trigger
    members = world["client"].get("/api/admin/teams", headers=world["ah"]).json()
    mine = next(t for t in members if t["id"] == ta)
    assert mine["member_count"] == 3
    gone = world["client"].delete(f"/api/admin/teams/{ta}/members/{mine['members'][2]['id']}", headers=world["ah"])
    assert gone.status_code == 200 and gone.json()["member_count"] == 2
    # team B: two members
    for n in ("B One", "B Two"):
        post(world, f"/admin/teams/{world['tb']}/members", {"full_name": n})


def test_accounts_link_participants_to_teams(world):
    for key, team in (("pa", "ta"), ("pb", "tb")):
        email = f"arena-test-{uuid.uuid4().hex[:10]}@example.com"
        r = post(world, "/admin/users", {"email": email, "password": supa.PASSWORD, "role": "PARTICIPANT", "team_id": world[team]})
        assert r.status_code == 201, r.text
        world[key] = {"id": r.json()["id"], "email": email}
        world["users"].append(world[key])
    # participant without team is rejected; team on a judge is rejected
    assert post(world, "/admin/users", {"email": "x1@example.com", "password": supa.PASSWORD, "role": "PARTICIPANT"}).status_code == 422
    assert post(world, "/admin/users", {"email": "x2@example.com", "password": supa.PASSWORD, "role": "JUDGE", "team_id": world["ta"]}).status_code == 422


# ---------------- questions & variants ----------------
def _variant(label, cat="DSA", langs=("python",), hidden=True):
    return {"label": label, "description": f"Optimize this {cat} code ({label}).", "expected_behavior": "Same output.",
            "constraints": "n <= 1e5", "languages": list(langs),
            "original_code": {l: f"# slow {l}" for l in langs},
            "visible_tests": [{"input": "1", "expected_output": "1"}],
            "hidden_tests": [{"input": HIDDEN, "expected_output": "42"}] if hidden else [],
            "reference_solution": {l: REF for l in langs}, "reference_concepts": "hash map", "expected_complexity": "O(n)"}


def test_question_and_variant_management(world):
    cats = {"DSA": ("python", "cpp"), "OOP": ("java",), "DBMS": ("sql",)}
    for cat, langs in cats.items():
        q = post(world, "/admin/questions", {"category": cat, "title": f"ZZTEST {cat}"})
        assert q.status_code == 201
        qid = q.json()["id"]
        va = post(world, f"/admin/questions/{qid}/variants", _variant("A", cat, langs))
        vb = post(world, f"/admin/questions/{qid}/variants", _variant("B", cat, langs))
        assert va.status_code == 201 and vb.status_code == 201, va.text
        assert post(world, f"/admin/questions/{qid}/variants", _variant("A", cat, langs)).status_code == 409  # duplicate label
        world[cat] = {"q": qid, "A": va.json()["id"], "B": vb.json()["id"]}
    # language rules per category
    bad = post(world, f"/admin/questions/{world['OOP']['q']}/variants", _variant("C", "OOP", ("c",)))
    assert bad.status_code == 422
    # publishing needs hidden tests
    noh = post(world, f"/admin/questions/{world['DSA']['q']}/variants", _variant("C", "DSA", ("python",), hidden=False))
    r = post(world, f"/admin/variants/{noh.json()['id']}/status", {"status": "PUBLISHED"}, method="patch")
    assert r.status_code == 422


def test_cannot_assign_unpublished(world):
    r = post(world, f"/admin/teams/{world['ta']}/assignments/DSA", {"variant_id": world["DSA"]["A"]}, method="put")
    assert r.status_code == 422


def test_publish_everything(world):
    for cat in ("DSA", "OOP", "DBMS"):
        assert post(world, f"/admin/questions/{world[cat]['q']}/status", {"status": "PUBLISHED"}, method="patch").status_code == 200
        for lab in ("A", "B"):
            r = post(world, f"/admin/variants/{world[cat][lab]}/status", {"status": "PUBLISHED"}, method="patch")
            assert r.status_code == 200 and r.json()["status"] == "PUBLISHED"


# ---------------- assignments ----------------
def test_assignment_rules_and_matrix(world):
    put = lambda team, cat, v: post(world, f"/admin/teams/{world[team]}/assignments/{cat}", {"variant_id": world[cat][v]}, method="put")
    # wrong category
    assert post(world, f"/admin/teams/{world['ta']}/assignments/OOP", {"variant_id": world["DSA"]["A"]}, method="put").status_code == 422
    # incomplete -> cannot lock
    assert put("ta", "DSA", "A").status_code == 200
    r = post(world, "/admin/assignments/lock")
    assert r.status_code == 409 and r.json()["detail"]["problems"]
    # change before start is allowed
    assert put("ta", "DSA", "B").status_code == 200 and put("ta", "DSA", "A").status_code == 200
    for cat, v in (("OOP", "A"), ("DBMS", "A")):
        assert put("ta", cat, v).status_code == 200
    for cat in ("DSA", "OOP", "DBMS"):
        assert put("tb", cat, "B").status_code == 200
    m = world["client"].get("/api/admin/assignments", headers=world["ah"]).json()
    ta = next(t for t in m["teams"] if t["id"] == world["ta"])
    assert ta["complete"] and ta["assignments"]["DSA"]["label"] == "A"
    assert m["round_state"] in ("DRAFT", "SCHEDULED")


def test_persisted_in_real_database(world):
    with admin_tx() as c:
        n = c.execute(text("select count(*) from public.question_assignments where team_id in (:a, :b)"),
                      {"a": world["ta"], "b": world["tb"]}).scalar()
        a = c.execute(text("select count(*) from public.audit_logs where actor_id = :u and action like 'assignment.%'"),
                      {"u": world["admin"]["id"]}).scalar()
    assert n == 6 and a >= 6  # 6 live rows, plus audit entries for each change (including replaced ones)


# ---------------- participant visibility BEFORE the round ----------------
def test_participant_sees_own_team_only_and_no_questions_before_start(world):
    ha, hb = hdr(world["pa"]["email"]), hdr(world["pb"]["email"])
    ta = world["client"].get("/api/participant/team", headers=ha).json()
    tb = world["client"].get("/api/participant/team", headers=hb).json()
    assert ta["team_number"] == world["n1"] and tb["team_number"] == world["n2"]
    assert {m["full_name"] for m in ta["members"]} == {"A One", "A Two"}
    assert world["client"].get("/api/participant/questions", headers=ha).json()["questions"] == []
    assert world["client"].get("/api/participant/team", headers=hdr(world["stranger"]["email"])).status_code == 404
    assert world["client"].get("/api/participant/team", headers=world["ah"]).status_code == 403  # admins use admin API


# ---------------- start round: lock + visibility ----------------
def test_start_requires_valid_state_then_locks(world):
    # Another active team with 0 members would block start; ours are fine. Start the round.
    other_active = None
    with admin_tx() as c:  # temporarily deactivate unrelated pre-existing teams so the test is hermetic
        pre = [r[0] for r in c.execute(text("select id from public.teams where is_active and team_number not in (:a,:b)"), {"a": world["n1"], "b": world["n2"]})]
        if pre:
            c.execute(text("update public.teams set is_active=false where id = any(cast(:ids as uuid[]))"), {"ids": pre})
    world["deactivated"] = pre
    try:
        r = post(world, "/admin/rounds/1/start", {"duration_minutes": 150})
        assert r.status_code == 200 and r.json()["state"] == "RUNNING"
    finally:
        with admin_tx() as c:
            if world["deactivated"]:
                c.execute(text("update public.teams set is_active=true where id = any(cast(:ids as uuid[]))"), {"ids": world["deactivated"]})
    # locked: assignment changes and membership changes now rejected
    assert post(world, f"/admin/teams/{world['ta']}/assignments/DSA", {"variant_id": world["DSA"]["B"]}, method="put").status_code == 409
    assert post(world, f"/admin/teams/{world['ta']}/members", {"full_name": "Late"}).status_code == 409
    assert world["client"].delete(f"/api/admin/teams/{world['ta']}/assignments/DSA", headers=world["ah"]).status_code == 409
    assert post(world, f"/admin/variants/{world['DSA']['A']}/status", {"status": "DRAFT"}, method="patch").status_code == 409


def test_participants_see_only_their_assigned_questions_and_no_private_data(world):
    ha, hb = hdr(world["pa"]["email"]), hdr(world["pb"]["email"])
    ra = world["client"].get("/api/participant/questions", headers=ha)
    rb = world["client"].get("/api/participant/questions", headers=hb)
    qa, qb = ra.json()["questions"], rb.json()["questions"]
    assert [q["category"] for q in qa] == ["DSA", "OOP", "DBMS"] and len(qb) == 3
    assert {q["label"] for q in qa} == {"A"} and {q["label"] for q in qb} == {"B"}
    assert {q["variant_id"] for q in qa}.isdisjoint({q["variant_id"] for q in qb})
    for resp in (ra, rb):
        assert HIDDEN not in resp.text and REF not in resp.text
        for banned in ("hidden_tests", "reference_solution", "reference_concepts", "expected_complexity"):
            assert banned not in resp.text
    assert world["client"].get("/api/participant/questions", headers=hdr(world["stranger"]["email"])).status_code == 404


# ---------------- RLS directly in Postgres ----------------
def _as(user_id, team_id=None):
    return CurrentUser(id=uuid.UUID(user_id), email=None, role="PARTICIPANT", team_id=uuid.UUID(team_id) if team_id else None)


def test_rls_cross_team_isolation_and_private_tables(world):
    a = _as(world["pa"]["id"], world["ta"])
    with user_tx(a) as c:
        assert [r[0] for r in c.execute(text("select team_number from public.teams"))] == [world["n1"]]
        assert c.execute(text("select count(*) from public.team_members")).scalar() == 2
        assert c.execute(text("select count(*) from public.question_assignments")).scalar() == 3
        vis = {str(r[0]) for r in c.execute(text("select id from public.question_variants"))}
        assert vis == {world[k]["A"] for k in ("DSA", "OOP", "DBMS")}      # never the B variants
        assert c.execute(text("select count(*) from public.question_private")).scalar() == 0   # hidden tests
        assert c.execute(text("select count(*) from public.audit_logs")).scalar() == 0
        assert c.execute(text("select count(*) from public.profiles")).scalar() == 1            # only self
    # writes are impossible for participants even via SQL
    for sql in ("insert into public.teams (team_number, name) values (99999, 'x')",
                "update public.question_assignments set locked = false",
                "delete from public.question_assignments"):
        with pytest.raises(Exception):
            with user_tx(a) as c:
                res = c.execute(text(sql))
                if res.rowcount == 0:
                    raise RuntimeError("no rows affected")  # RLS filtered the write: treat as blocked
    with user_tx(_as(world["stranger"]["id"])) as c:  # no team -> sees nothing
        for t in ("teams", "team_members", "question_assignments", "question_variants", "question_private"):
            assert c.execute(text(f"select count(*) from public.{t}")).scalar() == 0, t


def test_rls_publishable_key_cannot_read_private_data(world):
    import httpx
    from app.config import get_settings
    s = get_settings()
    h = {"apikey": s.supabase_publishable_key}
    for t in ("question_private", "teams", "question_assignments", "question_variants", "audit_logs"):
        r = httpx.get(f"{s.supabase_url}/rest/v1/{t}?select=*", headers=h, timeout=15)
        assert r.status_code in (200, 401, 403) and (r.status_code != 200 or r.json() == []), t
    # a logged-in participant going straight at PostgREST still can't see hidden tests or other teams
    h = {"apikey": s.supabase_publishable_key, "Authorization": hdr(world["pa"]["email"])["Authorization"]}
    assert httpx.get(f"{s.supabase_url}/rest/v1/question_private?select=*", headers=h, timeout=15).json() == []
    teams = httpx.get(f"{s.supabase_url}/rest/v1/teams?select=team_number", headers=h, timeout=15).json()
    assert teams == [{"team_number": world["n1"]}]


def test_session_state_does_not_leak_between_pooled_requests(world):
    with get_engine().connect() as c:
        assert c.execute(text("select current_user")).scalar() == "postgres"
        assert c.execute(text("select current_setting('request.jwt.claims', true)")).scalar() in (None, "")
