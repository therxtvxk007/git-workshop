-- Scenario sessions.
--
-- Scenarios live in their own tables with their own identifiers. Nothing here
-- can be joined into a forecast listing by accident, because the isolation the
-- console promises has to be structural: "we filter hypotheticals out in the
-- query" is one forgotten WHERE clause away from a scenario appearing in an
-- alert list.

create table public.scenario_sessions (
  id              uuid primary key default gen_random_uuid(),
  owner_id        uuid not null references auth.users (id) on delete cascade,
  name            text not null check (length(trim(name)) between 1 and 120),
  forecast_id     text not null,
  district_name   text not null,
  event_family    text not null,
  baseline_probability numeric(6,5) not null check (baseline_probability between 0 and 1),
  cutoff_at       timestamptz not null,
  snapshot_hash   text not null check (length(trim(snapshot_hash)) > 0),
  -- Not defaulted and not nullable: every row must assert what it is.
  is_hypothetical boolean not null default true check (is_hypothetical),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.scenario_inputs (
  id              uuid primary key default gen_random_uuid(),
  session_id      uuid not null references public.scenario_sessions (id) on delete cascade,
  feature         text not null,
  label           text not null,
  baseline_value  numeric not null,
  hypothetical_value numeric not null,
  created_at      timestamptz not null default now(),
  unique (session_id, feature)
);

alter table public.scenario_sessions enable row level security;
alter table public.scenario_inputs   enable row level security;

create policy scenario_sessions_owner on public.scenario_sessions
  for all to authenticated
  using (owner_id = auth.uid() or public.is_administrator())
  with check (owner_id = auth.uid() and public.can_read_workspace());

create policy scenario_inputs_owner on public.scenario_inputs
  for all to authenticated
  using (exists (
    select 1 from public.scenario_sessions s
    where s.id = scenario_inputs.session_id
      and (s.owner_id = auth.uid() or public.is_administrator())
  ))
  with check (exists (
    select 1 from public.scenario_sessions s
    where s.id = scenario_inputs.session_id and s.owner_id = auth.uid()
  ));

revoke all on public.scenario_sessions, public.scenario_inputs from anon, authenticated;
grant select, insert, update, delete on public.scenario_sessions to authenticated;
grant select, insert, update, delete on public.scenario_inputs to authenticated;

create index scenario_sessions_owner_idx on public.scenario_sessions (owner_id, updated_at desc);
