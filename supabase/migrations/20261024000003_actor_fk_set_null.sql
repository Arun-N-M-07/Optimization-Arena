-- Deleting an account must not be blocked by (or erase) the history it created.
-- Keep the rows, drop the pointer.
alter table public.audit_logs drop constraint audit_logs_actor_id_fkey,
  add constraint audit_logs_actor_id_fkey foreign key (actor_id) references auth.users(id) on delete set null;
alter table public.question_assignments drop constraint question_assignments_assigned_by_fkey,
  add constraint question_assignments_assigned_by_fkey foreign key (assigned_by) references auth.users(id) on delete set null;
alter table public.submissions drop constraint submissions_submitted_by_fkey,
  add constraint submissions_submitted_by_fkey foreign key (submitted_by) references auth.users(id) on delete set null;
alter table public.report_evaluations drop constraint report_evaluations_created_by_fkey,
  add constraint report_evaluations_created_by_fkey foreign key (created_by) references auth.users(id) on delete set null;
alter table public.contest_announcements drop constraint contest_announcements_created_by_fkey,
  add constraint contest_announcements_created_by_fkey foreign key (created_by) references auth.users(id) on delete set null;
