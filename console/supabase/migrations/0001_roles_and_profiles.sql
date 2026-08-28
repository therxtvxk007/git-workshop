-- Roles, profiles and the one function every other policy depends on.
--
-- The single most important decision in this file: roles live in their own
-- table, never on `profiles`. A `profiles.role` column is editable by the row's
-- owner under any sane profile policy, which means a user can promote
-- themselves to administrator by updating their own profile. Splitting the
-- table makes that impossible to express.

create extension if not exists pgcrypto;

create type public.app_role as enum ('administrator', 'analyst', 'reviewer', 'viewer');

create table public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  display_name  text not null check (length(trim(display_name)) between 1 and 120),
  organisation  text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.profiles is
  'Presentation data only. Authorisation never reads this table.';

create table public.user_roles (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users (id) on delete cascade,
  role        public.app_role not null,
  granted_by  uuid references auth.users (id),
  granted_at  timestamptz not null default now(),
  unique (user_id, role)
);

comment on table public.user_roles is
  'Authorisation source of truth. Writable only by administrators.';

-- SECURITY DEFINER so RLS policies can call it without recursing into
-- user_roles' own policies. `search_path` is pinned: a definer function with a
-- mutable search_path is a privilege-escalation primitive.
create or replace function public.has_role(_user_id uuid, _role public.app_role)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.user_roles
    where user_id = _user_id and role = _role
  );
$$;

create or replace function public.is_administrator()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select public.has_role(auth.uid(), 'administrator');
$$;

-- Analyst-or-better, the read bar for most of the console.
create or replace function public.can_read_workspace()
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select
    public.has_role(auth.uid(), 'administrator')
    or public.has_role(auth.uid(), 'analyst')
    or public.has_role(auth.uid(), 'reviewer')
    or public.has_role(auth.uid(), 'viewer');
$$;

alter table public.profiles  enable row level security;
alter table public.user_roles enable row level security;

create policy profiles_select_self_or_admin on public.profiles
  for select to authenticated
  using (id = auth.uid() or public.is_administrator());

create policy profiles_insert_self on public.profiles
  for insert to authenticated
  with check (id = auth.uid());

create policy profiles_update_self on public.profiles
  for update to authenticated
  using (id = auth.uid())
  with check (id = auth.uid());

-- A user may read which roles they hold; only an administrator may change them.
create policy user_roles_select_self_or_admin on public.user_roles
  for select to authenticated
  using (user_id = auth.uid() or public.is_administrator());

create policy user_roles_admin_write on public.user_roles
  for all to authenticated
  using (public.is_administrator())
  with check (public.is_administrator());

-- Explicit grants. Relying on a blanket grant to `authenticated` plus RLS means
-- one forgotten `enable row level security` exposes a whole table.
revoke all on public.profiles, public.user_roles from anon, authenticated;
grant select, insert, update on public.profiles to authenticated;
grant select on public.user_roles to authenticated;
grant insert, update, delete on public.user_roles to authenticated; -- gated by policy
grant execute on function public.has_role(uuid, public.app_role) to authenticated;
grant execute on function public.is_administrator() to authenticated;
grant execute on function public.can_read_workspace() to authenticated;

-- New sign-ups get a profile and the lowest role. Elevation is a deliberate
-- administrative act, never a side effect of registering.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1)));

  insert into public.user_roles (user_id, role)
  values (new.id, 'viewer')
  on conflict do nothing;

  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
