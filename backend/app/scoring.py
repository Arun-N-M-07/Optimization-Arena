"""Official scoring. Everything is computed here from approved data; clients and Gemini never supply totals.

Round 1 total = approved report marks (judge-approved only) + code points (config, default 0, real
non-mock ACCEPTED only) + manual components. Round 2 total = code points (config) + manual components.
Combined ("final") only exists when both weights are configured. Nothing here invents official weights.
"""
import json
from decimal import Decimal

from sqlalchemy import text

from .db import one, rows
from .settings_check import REAL_JUDGES

DEFAULT_CONFIG = {"code_points_per_question": 0, "tiebreak": "none"}


def round_config(conn, rnd: int) -> dict:
    r = one(conn, "select config from public.contest_sessions where round = :r", r=rnd)
    return {**DEFAULT_CONFIG, **(r["config"] or {})}


def _f(x) -> float:
    return float(x) if isinstance(x, Decimal) else float(x or 0)


def compute_scores(conn, rnd: int) -> list[dict]:
    cfg = round_config(conn, rnd)
    cat_filter = "q.round = :r"
    teams = rows(conn, """select id, team_number, name from public.teams where is_active %s order by team_number""" %
                 ("and is_finalist" if rnd == 2 else ""))
    by = {str(t["id"]): {"team_id": str(t["id"]), "team_number": t["team_number"], "name": t["name"],
                         "report": 0.0, "reports_reviewed": 0, "reports_total": 0, "code": 0.0, "manual": 0.0,
                         "manual_items": [], "last_final_at": None} for t in teams}
    if rnd == 1:
        for r in rows(conn, """
            with latest as (select distinct on (team_id, variant_id) id, team_id from public.autopsy_reports
                            where status <> 'DRAFT' order by team_id, variant_id, version desc),
            rev as (select distinct on (report_id) id, report_id from public.report_evaluations
                    where source = 'JUDGE' and approved_at is not null order by report_id, approved_at desc)
            select l.team_id, (rev.id is not null) as reviewed,
                   coalesce((select sum(marks) from public.evaluation_criteria where evaluation_id = rev.id), 0) as marks
            from latest l left join rev on rev.report_id = l.id"""):
            t = by.get(str(r["team_id"]))
            if t:
                if r["reviewed"]:
                    t["reports_reviewed"] += 1
                    t["report"] += _f(r["marks"])
    if rnd == 1:   # approvals are shown out of the reports the team is expected to write (its assigned questions), not just those submitted
        for r in rows(conn, """select a.team_id, count(*) as n from public.question_assignments a join public.question_variants v on v.id = a.variant_id
                               join public.questions q on q.id = v.question_id where q.round = 1 group by a.team_id"""):
            t = by.get(str(r["team_id"]))
            if t:
                t["reports_total"] = r["n"]
    points = _f(cfg.get("code_points_per_question"))
    for r in rows(conn, """
        with fin as (select distinct on (s.team_id, s.variant_id) s.id, s.team_id, s.created_at
                     from public.submissions s join public.question_variants v on v.id = s.variant_id
                     join public.questions q on q.id = v.question_id
                     where s.kind = 'FINAL' and %s order by s.team_id, s.variant_id, s.created_at desc)
        select fin.team_id, fin.created_at,
               exists (select 1 from public.execution_results e where e.submission_id = fin.id
                       and e.outcome = 'ACCEPTED' and e.provider = any(:real)) as accepted
        from fin""" % cat_filter, r=rnd, real=sorted(REAL_JUDGES)):
        t = by.get(str(r["team_id"]))
        if t:
            if r["accepted"]:
                t["code"] += points
            if t["last_final_at"] is None or r["created_at"] > t["last_final_at"]:
                t["last_final_at"] = r["created_at"]
    for r in rows(conn, "select team_id, component, marks, max_marks from public.manual_scores where round = :r", r=rnd):
        t = by.get(str(r["team_id"]))
        if t:
            t["manual"] += _f(r["marks"])
            t["manual_items"].append({"component": r["component"], "marks": _f(r["marks"]), "max": _f(r["max_marks"])})
    for t in by.values():
        t["total"] = round(t["report"] + t["code"] + t["manual"], 1)
    return rank(list(by.values()), cfg.get("tiebreak", "none"))


def rank(items: list[dict], tiebreak: str) -> list[dict]:
    """Competition ranking (1,2,2,4). Optional tiebreak: earlier last FINAL submission wins."""
    def key(t):
        tb = t["last_final_at"].timestamp() if tiebreak == "earliest_final_submission" and t["last_final_at"] else float("inf")
        return (-t["total"], tb if tiebreak == "earliest_final_submission" else 0, t["team_number"])

    items.sort(key=key)
    prev, rk = None, 0
    for i, t in enumerate(items, 1):
        k = (t["total"], (t["last_final_at"] if tiebreak == "earliest_final_submission" else None))
        if k != prev:
            rk, prev = i, k
        t["rank"] = rk
    return items


def combined(conn) -> list[dict] | None:
    cfg2 = round_config(conn, 2)
    fin = cfg2.get("final") or {}
    w1, w2 = fin.get("round1_weight"), fin.get("round2_weight")
    if w1 is None or w2 is None:
        return None
    r1 = {t["team_id"]: t for t in compute_scores(conn, 1)}
    out = []
    for t in compute_scores(conn, 2):
        a = r1.get(t["team_id"], {}).get("total", 0)
        out.append({**t, "round1_total": a, "round2_total": t["total"], "total": round(a * w1 + t["total"] * w2, 1)})
    return rank(out, round_config(conn, 2).get("tiebreak", "none"))
