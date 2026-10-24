-- Defense in depth: Supabase grants anon/authenticated full table privileges by default, leaving RLS as the only barrier.
-- The API writes with its own backend role; browser roles only ever READ (through RLS). Remove everything else.
-- Permission changes only: no table, column or data is touched.
revoke all on all tables in schema public from anon;
grant select on public.contest_sessions, public.contest_announcements to anon;       -- public round status + announcements (Realtime)
revoke insert, update, delete, truncate, references, trigger on all tables in schema public from authenticated;
