create extension if not exists pgcrypto;

alter table public.profiles
  add column if not exists team_access_version integer not null default 0,
  add column if not exists team_access_blocked boolean not null default false,
  add column if not exists team_access_verified_at timestamptz;

create table if not exists public.team_access_state (
  id integer primary key default 1 check (id = 1),
  enabled boolean not null default false,
  current_version integer not null default 1,
  updated_at timestamptz not null default now()
);

insert into public.team_access_state (id, enabled, current_version)
values (1, false, 1)
on conflict (id) do nothing;

create table if not exists public.team_access_secrets (
  version integer primary key,
  code_hash text not null,
  created_at timestamptz not null default now()
);

alter table public.team_access_state enable row level security;
alter table public.team_access_secrets enable row level security;

drop policy if exists "Authenticated users can read team access state" on public.team_access_state;
create policy "Authenticated users can read team access state"
  on public.team_access_state for select
  to authenticated
  using (true);
