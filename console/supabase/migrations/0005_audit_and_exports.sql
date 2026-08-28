-- Append-only audit log with a hash chain, and the export register.
--
-- An audit table that administrators can UPDATE is a log of what somebody was
-- willing to leave in it. Two mechanisms make that harder here:
--
--   1. No UPDATE or DELETE policy exists, and the grants match.
--   2. Each row carries `prev_hash` and `entry_hash`, computed by a trigger
--      over the row's own content. Deleting or rewriting a row out of band
--      breaks the chain, and `public.verify_audit_chain()` will say where.
--
-- The chain does not make tampering impossible — a superuser can do anything —
-- it makes tampering *detectable*, which is the achievable property.

create table public.audit_events (
  id            bigint generated always as identity primary key,
  actor_id      uuid references auth.users (id),
  actor_role    public.app_role,
  action        text not null check (length(trim(action)) > 0),
  resource_type text not null,
  resource_id   text,
  -- Cutoff and snapshot are recorded on every event: "who approved this" is
  -- only answerable together with "against which data".
  cutoff_at     timestamptz,
  snapshot_hash text,
  detail        jsonb not null default '{}'::jsonb,
  occurred_at   timestamptz not null default now(),
  prev_hash     text,
  entry_hash    text not null default ''
);

create or replace function public.audit_chain_link()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  previous text;
begin
  select entry_hash into previous
  from public.audit_events
  order by id desc
  limit 1;

  new.prev_hash := previous;
  new.actor_id  := coalesce(new.actor_id, auth.uid());
  new.entry_hash := encode(
    digest(
      coalesce(previous, '') ||
      coalesce(new.actor_id::text, '') ||
      new.action || new.resource_type ||
      coalesce(new.resource_id, '') ||
      coalesce(new.snapshot_hash, '') ||
      new.detail::text ||
      new.occurred_at::text,
      'sha256'),
    'hex');
  return new;
end;
$$;

create trigger audit_events_chain
  before insert on public.audit_events
  for each row execute function public.audit_chain_link();

create or replace function public.verify_audit_chain()
returns table (id bigint, ok boolean, reason text)
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
  row record;
  expected text;
  previous text := null;
begin
  for row in select * from public.audit_events order by id loop
    expected := encode(
      digest(
        coalesce(previous, '') ||
        coalesce(row.actor_id::text, '') ||
        row.action || row.resource_type ||
        coalesce(row.resource_id, '') ||
        coalesce(row.snapshot_hash, '') ||
        row.detail::text ||
        row.occurred_at::text,
        'sha256'),
      'hex');

    if row.prev_hash is distinct from previous then
      return query select row.id, false, 'prev_hash does not match the preceding entry';
    elsif row.entry_hash <> expected then
      return query select row.id, false, 'entry_hash does not match the row contents';
    else
      return query select row.id, true, null::text;
    end if;

    previous := row.entry_hash;
  end loop;
end;
$$;

create table public.export_records (
  id            uuid primary key default gen_random_uuid(),
  actor_id      uuid not null references auth.users (id) on delete cascade,
  export_name   text not null,
  format        text not null check (format in ('csv', 'json')),
  row_count     integer not null check (row_count >= 0),
  cutoff_at     timestamptz not null,
  snapshot_hash text not null,
  data_mode     text not null check (data_mode in ('live', 'synthetic')),
  is_hypothetical boolean not null default false,
  filters       jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

comment on table public.export_records is
  'Every export is registered. When a spreadsheet turns up somewhere it should
   not be, this is how its cutoff, snapshot and filters get reconstructed.';

alter table public.audit_events   enable row level security;
alter table public.export_records enable row level security;

create policy audit_select on public.audit_events
  for select to authenticated
  using (public.can_read_workspace());

create policy audit_insert on public.audit_events
  for insert to authenticated
  with check (public.can_read_workspace() and (actor_id is null or actor_id = auth.uid()));

-- No update policy. No delete policy. Append-only means append-only.

create policy exports_select on public.export_records
  for select to authenticated
  using (actor_id = auth.uid() or public.is_administrator());

create policy exports_insert_own on public.export_records
  for insert to authenticated
  with check (actor_id = auth.uid());

revoke all on public.audit_events, public.export_records from anon, authenticated;
grant select, insert on public.audit_events to authenticated;
grant select, insert on public.export_records to authenticated;
grant execute on function public.verify_audit_chain() to authenticated;

create index audit_events_occurred_idx on public.audit_events (occurred_at desc);
create index audit_events_resource_idx on public.audit_events (resource_type, resource_id);
