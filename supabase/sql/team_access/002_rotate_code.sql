-- Generates a fresh shared team access code, bumps the global version,
-- invalidates all previously verified users, and returns the new code once.
with generated as (
  select format(
    'TEAM-%s-%s-%s-%s',
    substr(raw, 1, 4),
    substr(raw, 5, 4),
    substr(raw, 9, 4),
    substr(raw, 13, 4)
  ) as plain_code
  from (
    select upper(encode(gen_random_bytes(8), 'hex')) as raw
  ) seed
),
next_version as (
  select current_version + 1 as version
  from public.team_access_state
  where id = 1
),
new_secret as (
  insert into public.team_access_secrets (version, code_hash)
  select n.version, crypt(g.plain_code, gen_salt('bf'))
  from next_version n
  cross join generated g
  returning version
),
updated as (
  update public.team_access_state
  set enabled = true,
      current_version = (select version from new_secret),
      updated_at = now()
  where id = 1
  returning enabled, current_version, updated_at
)
select
  g.plain_code as team_access_code,
  u.enabled,
  u.current_version,
  u.updated_at
from generated g
cross join updated u;
