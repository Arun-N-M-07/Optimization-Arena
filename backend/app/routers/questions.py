import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ..auth import CurrentUser, require_roles
from ..db import admin_tx, audit, map_db_error, one, rows

router = APIRouter(prefix="/api/admin", tags=["admin: questions"])
admin = require_roles("ADMIN")

LANGUAGES = {
    "DSA": {"c", "cpp", "java", "python"},
    "OOP": {"cpp", "java", "python"},
    "DBMS": {"sql"},
    "DUEL": {"c", "cpp", "java", "python"},
}


class QuestionIn(BaseModel):
    category: str = Field(pattern="^(DSA|OOP|DBMS|DUEL)$")
    title: str = Field(min_length=1, max_length=200)
    difficulty: str = Field(default="EASY", pattern="^(EASY|MEDIUM)$")


class TestCase(BaseModel):
    input: str = Field(max_length=20000)
    expected_output: str = Field(max_length=20000)


class VariantIn(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1)
    expected_behavior: str = Field(min_length=1)
    constraints: str = ""
    languages: list[str] = Field(min_length=1)
    original_code: dict[str, str] = {}
    visible_tests: list[TestCase] = []
    # server-only
    hidden_tests: list[TestCase] = []
    reference_solution: dict[str, str] = {}
    reference_concepts: str = ""
    expected_complexity: str = ""

    @model_validator(mode="after")
    def _languages_match_code(self):
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("Duplicate languages")
        extra = set(self.original_code) - set(self.languages)
        if extra:
            raise ValueError(f"original_code has languages that are not offered: {sorted(extra)}")
        return self


class StatusIn(BaseModel):
    status: str = Field(pattern="^(DRAFT|PUBLISHED|ARCHIVED)$")


VARIANT_COLS = """v.id, v.question_id, v.label, v.description, v.expected_behavior, v.constraints, v.languages,
  v.original_code, v.visible_tests, v.status, p.hidden_tests, p.reference_solution,
  p.reference_concepts, p.expected_complexity"""


def _variant(c, variant_id) -> dict:
    v = one(c, f"select {VARIANT_COLS} from public.question_variants v "
               "left join public.question_private p on p.variant_id = v.id where v.id = :id", id=str(variant_id))
    if not v:
        raise HTTPException(404, "Variant not found")
    return v


@router.post("/questions", status_code=201)
def create_question(body: QuestionIn, user: CurrentUser = Depends(admin)):
    try:
        with admin_tx() as c:
            q = one(c, "insert into public.questions (round, category, title, difficulty) "
                       "values (case when cast(:cat as text) = 'DUEL' then 2 else 1 end, cast(:cat as public.question_category), :t, :d) returning *",
                    cat=body.category, t=body.title.strip(), d=body.difficulty)
            audit(c, user, "question.create", "question", q["id"], body.model_dump())
            return q
    except DBAPIError as e:
        raise map_db_error(e)


@router.get("/questions")
def list_questions(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        qs = rows(c, "select * from public.questions order by category, created_at")
        vs = rows(c, f"select {VARIANT_COLS} from public.question_variants v "
                     "left join public.question_private p on p.variant_id = v.id order by v.label")
        for q in qs:
            q["variants"] = [v for v in vs if v["question_id"] == q["id"]]
        return qs


@router.post("/questions/{question_id}/variants", status_code=201)
def create_variant(question_id: UUID, body: VariantIn, user: CurrentUser = Depends(admin)):
    try:
        with admin_tx() as c:
            q = one(c, "select category::text as category from public.questions where id = :id", id=str(question_id))
            if not q:
                raise HTTPException(404, "Question not found")
            bad = set(body.languages) - LANGUAGES[q["category"]]
            if bad:
                raise HTTPException(422, f"Languages not allowed for {q['category']}: {sorted(bad)}")
            v = one(c, """insert into public.question_variants
                   (question_id, label, description, expected_behavior, constraints, languages, original_code, visible_tests)
                   values (:q, :l, :d, :e, :c, :langs, cast(:oc as jsonb), cast(:vt as jsonb)) returning id""",
                    q=str(question_id), l=body.label.strip(), d=body.description, e=body.expected_behavior,
                    c=body.constraints, langs=body.languages, oc=json.dumps(body.original_code),
                    vt=json.dumps([t.model_dump() for t in body.visible_tests]))
            c.execute(text(
                """insert into public.question_private (variant_id, hidden_tests, reference_solution, reference_concepts, expected_complexity)
                   values (:v, cast(:h as jsonb), cast(:r as jsonb), :rc, :ec)"""),
                {"v": str(v["id"]), "h": json.dumps([t.model_dump() for t in body.hidden_tests]),
                 "r": json.dumps(body.reference_solution), "rc": body.reference_concepts, "ec": body.expected_complexity})
            audit(c, user, "variant.create", "variant", v["id"], {"question": str(question_id), "label": body.label})
            return _variant(c, v["id"])
    except DBAPIError as e:
        raise map_db_error(e)


@router.patch("/questions/{question_id}/status")
def set_question_status(question_id: UUID, body: StatusIn, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        q = one(c, "update public.questions set status = cast(:s as public.publish_status) where id = :id returning *",
                s=body.status, id=str(question_id))
        if not q:
            raise HTTPException(404, "Question not found")
        audit(c, user, "question.status", "question", question_id, {"status": body.status})
        return q


@router.patch("/variants/{variant_id}/status")
def set_variant_status(variant_id: UUID, body: StatusIn, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        v = _variant(c, variant_id)
        if body.status == "PUBLISHED":
            missing = [l for l in v["languages"] if not v["original_code"].get(l, "").strip()]
            if missing:
                raise HTTPException(422, f"Cannot publish: missing original code for {missing}")
            if not v["hidden_tests"]:
                raise HTTPException(422, "Cannot publish: at least one hidden test is required")
        if body.status != "PUBLISHED" and one(c, "select 1 as x from public.question_assignments where variant_id = :v and locked", v=str(variant_id)):
            raise HTTPException(409, "Variant is in locked assignments and cannot be unpublished")
        c.execute(text(
            "update public.question_variants set status = cast(:s as public.publish_status) where id = :id"),
            {"s": body.status, "id": str(variant_id)})
        audit(c, user, "variant.status", "variant", variant_id, {"status": body.status})
        return _variant(c, variant_id)
