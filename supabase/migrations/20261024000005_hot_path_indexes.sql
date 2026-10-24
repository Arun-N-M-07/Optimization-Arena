-- Additive only: covering indexes for foreign keys on the hottest query paths.
create index if not exists submissions_variant_idx on public.submissions(variant_id);
create index if not exists autopsy_reports_variant_idx on public.autopsy_reports(variant_id);
create index if not exists autopsy_reports_submission_idx on public.autopsy_reports(submission_id);
create index if not exists code_drafts_variant_idx on public.code_drafts(variant_id);
create index if not exists score_adjustments_report_idx on public.score_adjustments(report_id);
create index if not exists score_adjustments_team_idx on public.score_adjustments(team_id);
