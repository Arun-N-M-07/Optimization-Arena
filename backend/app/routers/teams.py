from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ..auth import CurrentUser, SupabaseGateway, get_gateway, require_roles
from ..db import admin_tx, audit, map_db_error, one, rows

router = APIRouter(prefix="/api/admin", tags=["admin: teams"])
admin = require_roles("ADMIN")

MIN_MEMBERS = 2


class TeamIn(BaseModel):
    team_number: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)


class MemberIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = None


class AccountIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(default="", max_length=100)
    role: str = Field(default="PARTICIPANT", pattern="^(PARTICIPANT|JUDGE|ADMIN)$")
    team_id: UUID | None = None


def team_view(conn, team_id: UUID | None = None) -> list[dict]:
    q = """
      select t.id, t.team_number, t.name, t.is_active, t.is_finalist,
             coalesce(json_agg(json_build_object('id', m.id, 'full_name', m.full_name, 'email', m.email)
                      order by m.created_at) filter (where m.id is not null), '[]') as members
      from public.teams t left join public.team_members m on m.team_id = t.id
      {where} group by t.id order by t.team_number"""
    out = rows(conn, q.format(where="where t.id = :id" if team_id else ""), **({"id": str(team_id)} if team_id else {}))
    for t in out:
        t["member_count"] = len(t["members"])
        t["eligible"] = t["is_active"] and t["member_count"] >= MIN_MEMBERS
    return out


@router.post("/teams", status_code=201)
def create_team(body: TeamIn, user: CurrentUser = Depends(admin)):
    try:
        with admin_tx() as c:
            t = one(c, "insert into public.teams (team_number, name) values (:n, :name) returning id",
                    n=body.team_number, name=body.name.strip())
            audit(c, user, "team.create", "team", t["id"], body.model_dump())
            return team_view(c, t["id"])[0]
    except DBAPIError as e:
        raise map_db_error(e)


@router.get("/teams")
def list_teams(user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        return team_view(c)


@router.post("/teams/{team_id}/members", status_code=201)
def add_member(team_id: UUID, body: MemberIn, user: CurrentUser = Depends(admin)):
    try:
        with admin_tx() as c:
            if not one(c, "select 1 as x from public.teams where id = :id for update", id=str(team_id)):
                raise HTTPException(404, "Team not found")
            if one(c, "select 1 as x from public.question_assignments where team_id = :id and locked", id=str(team_id)):
                raise HTTPException(409, "Assignments are locked; membership can no longer change")
            m = one(c, "insert into public.team_members (team_id, full_name, email) values (:t, :n, :e) returning id",
                    t=str(team_id), n=body.full_name.strip(), e=body.email)
            audit(c, user, "member.add", "team", team_id, {"member": str(m["id"])})
            return team_view(c, team_id)[0]
    except DBAPIError as e:
        raise map_db_error(e)


@router.delete("/teams/{team_id}/members/{member_id}")
def remove_member(team_id: UUID, member_id: UUID, user: CurrentUser = Depends(admin)):
    with admin_tx() as c:
        if one(c, "select 1 as x from public.question_assignments where team_id = :id and locked", id=str(team_id)):
            raise HTTPException(409, "Assignments are locked; membership can no longer change")
        gone = one(c, "delete from public.team_members where id = :m and team_id = :t returning id",
                   m=str(member_id), t=str(team_id))
        if not gone:
            raise HTTPException(404, "Member not found on this team")
        audit(c, user, "member.remove", "team", team_id, {"member": str(member_id)})
        return team_view(c, team_id)[0]


@router.post("/users", status_code=201)
def create_account(body: AccountIn, user: CurrentUser = Depends(admin),
                   gateway: SupabaseGateway = Depends(get_gateway)):
    """Create a Supabase Auth account and set its role/team. Passwords never touch our DB."""
    if body.role == "PARTICIPANT" and not body.team_id:
        raise HTTPException(422, "Participants must belong to a team")
    if body.role != "PARTICIPANT" and body.team_id:
        raise HTTPException(422, "Only participants belong to a team")
    uid = gateway.create_auth_user(body.email, body.password, body.full_name)
    try:
        with admin_tx() as c:
            c.execute(text("update public.profiles set role = cast(:r as public.app_role), team_id = :t where id = :id"),
                      {"r": body.role, "t": str(body.team_id) if body.team_id else None, "id": uid})
            audit(c, user, "account.create", "profile", uid, {"role": body.role, "team_id": str(body.team_id) if body.team_id else None})
    except DBAPIError as e:
        gateway.delete_auth_user(uid)
        raise map_db_error(e)
    return {"id": uid, "email": body.email, "role": body.role, "team_id": body.team_id}
