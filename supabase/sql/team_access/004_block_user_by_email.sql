-- Replace the placeholder email before running this in Supabase SQL editor.
with target as (
  select 'person@example.com'::text as email
),
updated as (
  update public.profiles p
  set team_access_blocked = true
  from target t
  where p.email = t.email
  returning p.id, p.email, p.team_access_blocked, p.team_access_version
)
select * from updated;
