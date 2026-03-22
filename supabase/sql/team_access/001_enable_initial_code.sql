-- Generates the first shared team access code, stores only its bcrypt hash,
-- enables the gate, and returns the plain code once in the query result.
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
upsert_secret as (
  insert into public.team_access_secrets (version, code_hash)
  select 1, crypt(g.plain_code, gen_salt('bf'))
  from generated g
  on conflict (version) do update
  set code_hash = excluded.code_hash,
      created_at = now()
  returning version
),
updated as (
  update public.team_access_state
  set enabled = true,
      current_version = 1,
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
