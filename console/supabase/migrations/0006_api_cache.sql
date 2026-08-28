-- Response cache for the engine's read endpoints.
--
-- The cache is keyed by (endpoint, request_hash, snapshot_hash). Including the
-- snapshot in the key is the whole point: a response computed against one
-- snapshot must never be served for another, or the console will show numbers
-- from one cutoff under the label of a different one.

create table public.api_response_cache (
  id             uuid primary key default gen_random_uuid(),
  endpoint       text not null,
  request_hash   text not null,
  snapshot_hash  text not null,
  response_hash  text not null,
  payload        jsonb not null,
  retrieved_at   timestamptz not null default now(),
  expires_at     timestamptz not null,
  unique (endpoint, request_hash, snapshot_hash),
  constraint expiry_after_retrieval check (expires_at > retrieved_at)
);

alter table public.api_response_cache enable row level security;

-- Readable by the workspace, writable only by the service role that fronts the
-- engine. A browser that can write the cache can poison every other analyst's
-- view of the data.
create policy api_cache_select on public.api_response_cache
  for select to authenticated
  using (public.can_read_workspace() and expires_at > now());

revoke all on public.api_response_cache from anon, authenticated;
grant select on public.api_response_cache to authenticated;

create index api_cache_expiry_idx on public.api_response_cache (expires_at);

create or replace function public.purge_expired_api_cache()
returns integer
language sql
volatile
security definer
set search_path = public, pg_temp
as $$
  with deleted as (
    delete from public.api_response_cache where expires_at <= now() returning 1
  )
  select count(*)::integer from deleted;
$$;
