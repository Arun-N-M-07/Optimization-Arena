-- Core schema for The Optimization Arena.
-- Writes happen through the FastAPI backend (secret key / service role, bypasses RLS).
-- RLS below only governs what browsers using the publishable key may READ.

create type public.app_role as enum ('PARTICIPANT', 'ADMIN', 'JUDGE');
create type public.question_category as enum ('DSA', 'OOP', 'DBMS', 'DUEL');
create type public.publish_status as enum ('DRAFT', 'PUBLISHED', 'ARCHIVED');
create type public.submission_kind as enum ('RUN', 'DRAFT', 'FINAL');
create type public.judge_outcome as enum (
  'PENDING', 'ACCEPTED', 'WRONG_ANSWER', 'COMPILATION_ERROR', 'RUNTIME_ERROR',
  'TIME_LIMIT_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'SYSTEM_ERROR');
create type public.report_status as enum (
  'DRAFT', 'SUBMITTED', 'EVALUATION_PENDING', 'EVALUATED', 'REVIEWED');
create type public.contest_state as enum (
  'DRAFT', 'SCHEDULED', 'RUNNING', 'PAUSED', 'ENDED', 'RESULTS_PUBLISHED');

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;

-- ---------- identity ----------
create table public.teams (
  id uuid primary key default gen_random_uuid(),
  team_number integer not null unique check (team_number > 0),
  name text not null check (length(trim(name)) > 0),
  is_active boolean not null default true,
  is_finalist boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger teams_touch before update on public.teams
  for each row execute function public.touch_updated_at();

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  role public.app_role not null default 'PARTICIPANT',
  team_id uuid references public.teams(id) on delete set null,
  created_at timestamptz not null default now(),
  -- only participants belong to a team
  check (team_id is null or role = 'PARTICIPANT')
);
create index profiles_team_idx on public.profiles(team_id);

create table public.team_members (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  user_id uuid references auth.users(id) on delete set null,
  full_name text not null check (length(trim(full_name)) > 0),
  email text,
  created_at timestamptz not null default now(),
  unique (team_id, email)
);
create index team_members_team_idx on public.team_members(team_id);

create or replace function public.enforce_team_size() returns trigger
language plpgsql as $$
begin
  if (select count(*) from public.team_members where team_id = new.team_id) >= 3 then
    raise exception 'A team can have at most 3 members';
  end if;
  return new;
end $$;
create trigger team_members_max before insert on public.team_members
  for each row execute function public.enforce_team_size();

-- Helpers used by RLS (security definer so policies don't recurse into profiles).
create or replace function public.current_app_role() returns public.app_role
language sql stable security definer set search_path = public as
$$ select role from public.profiles where id = auth.uid() $$;

create or replace function public.current_team_id() returns uuid
language sql stable security definer set search_path = public as
$$ select team_id from public.profiles where id = auth.uid() $$;

create or replace function public.is_staff() returns boolean
language sql stable security definer set search_path = public as
$$ select coalesce(public.current_app_role() in ('ADMIN', 'JUDGE'), false) $$;

-- ---------- question bank ----------
create table public.questions (
  id uuid primary key default gen_random_uuid(),
  round smallint not null check (round in (1, 2)),
  category public.question_category not null,
  title text not null,
  difficulty text not null default 'EASY' check (difficulty in ('EASY', 'MEDIUM')),
  status public.publish_status not null default 'DRAFT',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((round = 1 and category <> 'DUEL') or (round = 2 and category = 'DUEL'))
);
create trigger questions_touch before update on public.questions
  for each row execute function public.touch_updated_at();

-- Participant-visible content of one variant of a question.
create table public.question_variants (
  id uuid primary key default gen_random_uuid(),
  question_id uuid not null references public.questions(id) on delete cascade,
  label text not null,                       -- e.g. 'A', 'B', 'C'
  description text not null,
  expected_behavior text not null,
  constraints text not null default '',
  languages text[] not null check (cardinality(languages) > 0),
  original_code jsonb not null default '{}'::jsonb,   -- {language: source}
  visible_tests jsonb not null default '[]'::jsonb,   -- [{input, expected_output}]
  status public.publish_status not null default 'DRAFT',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (question_id, label)
);
create trigger question_variants_touch before update on public.question_variants
  for each row execute function public.touch_updated_at();

-- Server-only: hidden tests, reference solution, private evaluation notes.
-- RLS enabled with NO policies => unreachable from any browser key.
create table public.question_private (
  variant_id uuid primary key references public.question_variants(id) on delete cascade,
  hidden_tests jsonb not null default '[]'::jsonb,
  reference_solution jsonb not null default '{}'::jsonb,
  reference_concepts text not null default '',
  expected_complexity text not null default ''
);

create table public.question_assignments (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  variant_id uuid not null references public.question_variants(id) on delete restrict,
  category public.question_category not null,
  locked boolean not null default false,
  assigned_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  unique (team_id, category)               -- one variant per category per team
);
create index question_assignments_variant_idx on public.question_assignments(variant_id);

-- ---------- submissions & reports ----------
create table public.submissions (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  variant_id uuid not null references public.question_variants(id),
  submitted_by uuid references auth.users(id),
  language text not null,
  code text not null check (length(code) <= 200000),
  kind public.submission_kind not null,
  idempotency_key text,
  created_at timestamptz not null default now(),      -- server clock is the only clock
  unique (team_id, idempotency_key)
);
create index submissions_team_variant_idx on public.submissions(team_id, variant_id, created_at desc);

create table public.execution_results (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null references public.submissions(id) on delete cascade,
  outcome public.judge_outcome not null default 'PENDING',
  passed_visible integer,
  total_visible integer,
  passed_hidden integer,                    -- counts only; never hidden content
  total_hidden integer,
  runtime_ms integer,
  memory_kb integer,
  safe_message text,                        -- participant-facing feedback
  provider text,
  created_at timestamptz not null default now()
);
create index execution_results_submission_idx on public.execution_results(submission_id);

create table public.autopsy_reports (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  variant_id uuid not null references public.question_variants(id),
  submission_id uuid references public.submissions(id),
  version integer not null default 1 check (version > 0),
  inefficiency text not null default '',
  approach text not null default '',
  complexity text not null default '',
  tradeoffs text not null default '',
  status public.report_status not null default 'DRAFT',
  submitted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (team_id, variant_id, version),
  check (status = 'DRAFT' or submitted_at is not null)
);
create trigger autopsy_reports_touch before update on public.autopsy_reports
  for each row execute function public.touch_updated_at();

-- Submitted report content is immutable.
create or replace function public.freeze_submitted_report() returns trigger
language plpgsql as $$
begin
  if old.status <> 'DRAFT' and (
       new.inefficiency is distinct from old.inefficiency or
       new.approach is distinct from old.approach or
       new.complexity is distinct from old.complexity or
       new.tradeoffs is distinct from old.tradeoffs or
       new.submission_id is distinct from old.submission_id) then
    raise exception 'Submitted reports are immutable; create a new version';
  end if;
  return new;
end $$;
create trigger autopsy_reports_freeze before update on public.autopsy_reports
  for each row execute function public.freeze_submitted_report();

create table public.report_evaluations (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.autopsy_reports(id) on delete cascade,
  source text not null check (source in ('AI', 'JUDGE')),
  status text not null default 'PENDING' check (status in ('PENDING', 'COMPLETED', 'FAILED')),
  model text,
  eval_version integer not null default 1,
  attempts integer not null default 0,
  needs_review boolean not null default false,
  error text,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
-- At most one in-flight/completed AI evaluation per report+version: no duplicate scoring.
create unique index report_evaluations_ai_unique
  on public.report_evaluations(report_id, eval_version) where source = 'AI';

create table public.evaluation_criteria (
  id uuid primary key default gen_random_uuid(),
  evaluation_id uuid not null references public.report_evaluations(id) on delete cascade,
  criterion text not null check (criterion in
    ('INEFFICIENCY', 'APPROACH', 'COMPLEXITY', 'TRADEOFFS')),
  marks numeric(4,1) not null check (marks >= 0),
  max_marks numeric(4,1) not null default 5 check (max_marks = 5),
  explanation text not null check (length(trim(explanation)) > 0),
  evidence text,
  check (marks <= max_marks),
  unique (evaluation_id, criterion)
);

-- ---------- scoring, contest, audit ----------
create table public.score_adjustments (
  id uuid primary key default gen_random_uuid(),
  team_id uuid not null references public.teams(id) on delete cascade,
  report_id uuid references public.autopsy_reports(id),
  criterion text,
  previous_marks numeric(5,1) not null,
  new_marks numeric(5,1) not null,
  reason text not null check (length(trim(reason)) > 0),
  adjusted_by uuid not null references auth.users(id),
  created_at timestamptz not null default now()
);

create table public.contest_sessions (
  id uuid primary key default gen_random_uuid(),
  round smallint not null unique check (round in (1, 2)),
  state public.contest_state not null default 'DRAFT',
  starts_at timestamptz,
  ends_at timestamptz,
  config jsonb not null default '{}'::jsonb,   -- problem, languages, scoring, optional mechanics (off by default)
  finalists_locked boolean not null default false,
  results_published boolean not null default false,
  updated_at timestamptz not null default now(),
  check (ends_at is null or starts_at is null or ends_at > starts_at)
);
create trigger contest_sessions_touch before update on public.contest_sessions
  for each row execute function public.touch_updated_at();
insert into public.contest_sessions (round) values (1), (2);

create table public.contest_announcements (
  id uuid primary key default gen_random_uuid(),
  round smallint check (round in (1, 2)),
  message text not null check (length(trim(message)) > 0),
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);

create table public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid references auth.users(id),
  action text not null,
  entity text not null,
  entity_id text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index audit_logs_created_idx on public.audit_logs(created_at desc);

-- ---------- Row Level Security (read paths for browser keys) ----------
alter table public.profiles enable row level security;
alter table public.teams enable row level security;
alter table public.team_members enable row level security;
alter table public.questions enable row level security;
alter table public.question_variants enable row level security;
alter table public.question_private enable row level security;          -- no policies on purpose
alter table public.question_assignments enable row level security;
alter table public.submissions enable row level security;
alter table public.execution_results enable row level security;
alter table public.autopsy_reports enable row level security;
alter table public.report_evaluations enable row level security;        -- scores served by backend only
alter table public.evaluation_criteria enable row level security;       -- scores served by backend only
alter table public.score_adjustments enable row level security;
alter table public.contest_sessions enable row level security;
alter table public.contest_announcements enable row level security;
alter table public.audit_logs enable row level security;

create policy profiles_self on public.profiles for select to authenticated
  using (id = auth.uid() or public.current_app_role() = 'ADMIN');
create policy teams_own on public.teams for select to authenticated
  using (id = public.current_team_id() or public.is_staff());
create policy team_members_own on public.team_members for select to authenticated
  using (team_id = public.current_team_id() or public.is_staff());

create policy questions_assigned on public.questions for select to authenticated
  using (public.is_staff() or (status = 'PUBLISHED' and exists (
    select 1 from public.question_variants v
    join public.question_assignments a on a.variant_id = v.id
    where v.question_id = questions.id and a.team_id = public.current_team_id())));
create policy variants_assigned on public.question_variants for select to authenticated
  using (public.is_staff() or (status = 'PUBLISHED' and exists (
    select 1 from public.question_assignments a
    where a.variant_id = question_variants.id and a.team_id = public.current_team_id())));
create policy assignments_own on public.question_assignments for select to authenticated
  using (team_id = public.current_team_id() or public.is_staff());

create policy submissions_own on public.submissions for select to authenticated
  using (team_id = public.current_team_id() or public.is_staff());
create policy execution_results_own on public.execution_results for select to authenticated
  using (exists (select 1 from public.submissions s where s.id = submission_id
    and (s.team_id = public.current_team_id() or public.is_staff())));
create policy reports_own on public.autopsy_reports for select to authenticated
  using (team_id = public.current_team_id() or public.is_staff());

create policy evaluations_staff on public.report_evaluations for select to authenticated
  using (public.is_staff());
create policy criteria_staff on public.evaluation_criteria for select to authenticated
  using (public.is_staff());
create policy adjustments_staff on public.score_adjustments for select to authenticated
  using (public.is_staff());
create policy audit_admin on public.audit_logs for select to authenticated
  using (public.current_app_role() = 'ADMIN');

create policy sessions_read on public.contest_sessions for select to anon, authenticated using (true);
create policy announcements_read on public.contest_announcements for select to anon, authenticated using (true);

-- New auth users get a PARTICIPANT profile; roles are only elevated by the backend.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, email, full_name)
  values (new.id, new.email, coalesce(new.raw_user_meta_data->>'full_name', ''));
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Lock helper functions down; they are only meant for policy evaluation.
revoke execute on function public.current_app_role(), public.current_team_id(), public.is_staff() from public, anon;
grant execute on function public.current_app_role(), public.current_team_id(), public.is_staff() to authenticated;
revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.enforce_team_size() from public, anon, authenticated;
revoke execute on function public.freeze_submitted_report() from public, anon, authenticated;
