-- Drafts, immutable submissions, judge assignment, manual scores, evaluation fields,
-- judge-scoped RLS, realtime publication.

create table public.judge_assignments (
  judge_id uuid not null references auth.users(id) on delete cascade,
  team_id uuid not null references public.teams(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (judge_id, team_id)
);
create index judge_assignments_team_idx on public.judge_assignments(team_id);

-- helper: which teams may the caller see?
create or replace function public.can_see_team(tid uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select tid is not null and (
    tid = public.current_team_id()
    or public.current_app_role() = 'ADMIN'
    or (public.current_app_role() = 'JUDGE' and exists (
          select 1 from public.judge_assignments j where j.judge_id = auth.uid() and j.team_id = tid)));
$$;

revoke execute on function public.can_see_team(uuid) from public, anon;
grant execute on function public.can_see_team(uuid) to authenticated;

create table public.code_drafts (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  variant_id uuid not null references public.question_variants(id) on delete cascade,
  language text not null,
  code text not null check (length(code) <= 200000),
  updated_by uuid references auth.users(id) on delete set null,
  updated_at timestamptz not null default now(),
  unique (team_id, variant_id, language)
);

create table public.manual_scores (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  round smallint not null check (round in (1, 2)),
  component text not null check (length(trim(component)) > 0),   -- e.g. 'viva', 'bonus', 'round2_score'
  marks numeric(6,1) not null,
  max_marks numeric(6,1) not null check (max_marks > 0),
  reason text not null check (length(trim(reason)) > 0),
  entered_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  check (marks >= 0 and marks <= max_marks),
  unique (team_id, round, component)
);

-- Submitted code is immutable (updates rejected; deletes only via cascade from team removal).
create or replace function public.reject_submission_update() returns trigger
language plpgsql set search_path = public as $$
begin raise exception 'Submissions are immutable'; end $$;
create trigger submissions_immutable before update on public.submissions
  for each row execute function public.reject_submission_update();
revoke execute on function public.reject_submission_update() from public, anon, authenticated;

-- ---------- evaluation fields ----------
alter table public.report_evaluations
  add column started_at timestamptz,
  add column summary text,
  add column comment text,
  add column approved_at timestamptz,
  add column approved_by uuid references auth.users(id) on delete set null;
-- Only judge/admin reviews can be approved.
alter table public.report_evaluations add constraint report_evaluations_approval_source
  check (approved_at is null or source = 'JUDGE');
create index report_evaluations_report_idx on public.report_evaluations(report_id, created_at desc);

-- ---------- RLS ----------
alter table public.judge_assignments enable row level security;
alter table public.code_drafts enable row level security;
alter table public.manual_scores enable row level security;

-- Judges may only see assigned teams. RESTRICTIVE policies are ANDed with the existing permissive
-- ones, so participants/admins are unaffected and no existing policy is dropped or weakened.
create policy judge_scope on public.teams as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or public.can_see_team(id));
create policy judge_scope on public.team_members as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or public.can_see_team(team_id));
create policy judge_scope on public.question_assignments as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or public.can_see_team(team_id));
create policy judge_scope on public.submissions as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or public.can_see_team(team_id));
create policy judge_scope on public.autopsy_reports as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or public.can_see_team(team_id));
create policy judge_scope on public.score_adjustments as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or public.can_see_team(team_id));
create policy judge_scope on public.execution_results as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or exists (
    select 1 from public.submissions s where s.id = submission_id and public.can_see_team(s.team_id)));
create policy judge_scope on public.report_evaluations as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or exists (
    select 1 from public.autopsy_reports r where r.id = report_id and public.can_see_team(r.team_id)));
create policy judge_scope on public.evaluation_criteria as restrictive for select to authenticated
  using (public.current_app_role() is distinct from 'JUDGE' or exists (
    select 1 from public.report_evaluations e join public.autopsy_reports r on r.id = e.report_id
    where e.id = evaluation_id and public.can_see_team(r.team_id)));

create policy drafts_own on public.code_drafts for select to authenticated
  using (team_id = public.current_team_id() or public.current_app_role() = 'ADMIN');
create policy manual_scores_staff on public.manual_scores for select to authenticated
  using (public.is_staff() and public.can_see_team(team_id));
create policy judge_assignments_self on public.judge_assignments for select to authenticated
  using (judge_id = auth.uid() or public.current_app_role() = 'ADMIN');

-- ---------- realtime ----------
do $$
declare t text;
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    foreach t in array array['contest_sessions', 'contest_announcements', 'submissions', 'execution_results'] loop
      if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
        execute format('alter publication supabase_realtime add table public.%I', t);
      end if;
    end loop;
  end if;
end $$;
