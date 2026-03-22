-- Turns off the shared team access gate globally without changing the current version.
update public.team_access_state
set enabled = false,
    updated_at = now()
where id = 1
returning enabled, current_version, updated_at;
