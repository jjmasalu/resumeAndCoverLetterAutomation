select
  s.enabled,
  s.current_version,
  s.updated_at,
  count(sec.*) as stored_versions
from public.team_access_state s
left join public.team_access_secrets sec on true
where s.id = 1
group by s.enabled, s.current_version, s.updated_at;
