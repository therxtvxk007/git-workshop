-- A local stand-in for the parts of Supabase's `auth` schema the migrations
-- depend on.
--
-- This exists so the security model can be *executed* rather than asserted.
-- `supabase/tests/01_rls_test.sql` applies the real migrations on top of this
-- shim and then tries to do the things the policies are supposed to forbid.
-- It is a test fixture and is never applied to a real project.

create schema if not exists auth;

create table if not exists auth.users (
  id                  uuid primary key default gen_random_uuid(),
  email               text unique,
  raw_user_meta_data  jsonb not null default '{}'::jsonb
);

-- Supabase resolves the caller from the JWT. Locally we read the same GUC
-- PostgREST sets, so `set request.jwt.claim.sub` impersonates a user.
create or replace function auth.uid()
returns uuid
language sql
stable
as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
end
$$;

grant usage on schema public to anon, authenticated, service_role;
grant usage on schema auth to authenticated, service_role;
grant select on auth.users to authenticated, service_role;
