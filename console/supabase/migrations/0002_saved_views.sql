-- Saved filter sets.
--
-- A saved view stores the cutoff and snapshot it was created against. Reopening
-- a view built on an older snapshot and silently applying it to today's data
-- would show a different row set under the same name, so the UI compares the
-- two and says so.

create table public.saved_views (
  id             uuid primary key default gen_random_uuid(),
  owner_id       uuid not null references auth.users (id) on delete cascade,
  name           text not null check (length(trim(name)) between 1 and 120),
  route          text not null check (route ~ '^/'),
  filters        jsonb not null default '{}'::jsonb,
  cutoff_at      timestamptz not null,
  snapshot_hash  text not null check (length(trim(snapshot_hash)) > 0),
  is_shared      boolean not null default false,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (owner_id, name)
);

alter table public.saved_views enable row level security;

create policy saved_views_select on public.saved_views
  for select to authenticated
  using (owner_id = auth.uid() or (is_shared and public.can_read_workspace()));

create policy saved_views_insert_own on public.saved_views
  for insert to authenticated
  with check (owner_id = auth.uid() and public.can_read_workspace());

create policy saved_views_update_own on public.saved_views
  for update to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

create policy saved_views_delete_own on public.saved_views
  for delete to authenticated
  using (owner_id = auth.uid() or public.is_administrator());

revoke all on public.saved_views from anon, authenticated;
grant select, insert, update, delete on public.saved_views to authenticated;

create index saved_views_owner_idx on public.saved_views (owner_id, updated_at desc);
