-- Executable proof of the security model.
--
-- Every block below tries to do something a policy is supposed to prevent, and
-- fails the run if it succeeds. Read it as the answer to "how do you know
-- blinding works?" — not "we wrote a policy", but "here is the escalation
-- attempt, and here is it being refused".
--
-- Run with:
--   psql -v ON_ERROR_STOP=1 -f supabase/tests/00_local_auth_shim.sql
--   psql -v ON_ERROR_STOP=1 -f supabase/migrations/*.sql
--   psql -v ON_ERROR_STOP=1 -f supabase/tests/01_rls_test.sql

\set ON_ERROR_STOP on

-- Fixture users. The trigger on auth.users gives each one a profile and the
-- lowest role, so the assertions below start from a realistic state.
insert into auth.users (id, email, raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111', 'admin@example.invalid',    '{"display_name":"Admin"}'),
  ('22222222-2222-2222-2222-222222222222', 'reviewer-a@example.invalid','{"display_name":"Reviewer A"}'),
  ('33333333-3333-3333-3333-333333333333', 'reviewer-b@example.invalid','{"display_name":"Reviewer B"}'),
  ('44444444-4444-4444-4444-444444444444', 'viewer@example.invalid',    '{"display_name":"Viewer"}');

update public.user_roles set role = 'administrator'
  where user_id = '11111111-1111-1111-1111-111111111111';
insert into public.user_roles (user_id, role) values
  ('22222222-2222-2222-2222-222222222222', 'reviewer'),
  ('33333333-3333-3333-3333-333333333333', 'reviewer');

create or replace function pg_temp.act_as(_user uuid) returns void
language plpgsql as $$
begin
  perform set_config('request.jwt.claim.sub', _user::text, false);
end $$;

create or replace function pg_temp.check(_label text, _condition boolean) returns void
language plpgsql as $$
begin
  if not _condition then
    raise exception 'FAILED: %', _label;
  end if;
  raise notice 'ok: %', _label;
end $$;

-- 1. Sign-up grants `viewer`, never anything higher.
do $$
declare n integer;
begin
  select count(*) into n from public.user_roles
   where user_id = '44444444-4444-4444-4444-444444444444' and role = 'viewer';
  perform pg_temp.check('a new sign-up receives exactly the viewer role', n = 1);
  select count(*) into n from public.user_roles
   where user_id = '44444444-4444-4444-4444-444444444444' and role <> 'viewer';
  perform pg_temp.check('a new sign-up receives no other role', n = 0);
end $$;

-- 2. A viewer cannot promote themselves. This is the escalation the separate
--    user_roles table exists to prevent.
do $$
declare escalated boolean := false;
begin
  perform pg_temp.act_as('44444444-4444-4444-4444-444444444444');
  set local role authenticated;
  begin
    insert into public.user_roles (user_id, role)
      values ('44444444-4444-4444-4444-444444444444', 'administrator');
    escalated := true;
  exception when insufficient_privilege or check_violation then
    escalated := false;
  end;
  reset role;
  perform pg_temp.check('a viewer cannot grant themselves administrator', not escalated);
end $$;

-- 3. Blinding. Reviewer A submits; reviewer B must not be able to read it until
--    B has submitted their own.
insert into public.annotation_assignments (task_id, forecast_id, snapshot_hash, cutoff_at, reviewer_id, due_at)
values
  ('task_demo_1', 'fc_demo_1', 'sha256:demo', '2026-01-15T00:00:00Z', '22222222-2222-2222-2222-222222222222', '2026-01-22T00:00:00Z'),
  ('task_demo_1', 'fc_demo_1', 'sha256:demo', '2026-01-15T00:00:00Z', '33333333-3333-3333-3333-333333333333', '2026-01-22T00:00:00Z');

do $$
declare visible integer;
begin
  -- Reviewer A submits.
  perform pg_temp.act_as('22222222-2222-2222-2222-222222222222');
  set local role authenticated;
  insert into public.annotation_reviews (task_id, reviewer_id, decision, rationale)
    values ('task_demo_1', '22222222-2222-2222-2222-222222222222', 'accept',
            'The two independent sources agree and the base rate supports it.');
  reset role;

  -- Reviewer B, before submitting, sees nothing.
  perform pg_temp.act_as('33333333-3333-3333-3333-333333333333');
  set local role authenticated;
  select count(*) into visible from public.annotation_reviews where task_id = 'task_demo_1';
  reset role;
  perform pg_temp.check('a reviewer cannot read a peer review before submitting their own', visible = 0);

  -- Reviewer B submits, and the peer review becomes visible.
  perform pg_temp.act_as('33333333-3333-3333-3333-333333333333');
  set local role authenticated;
  insert into public.annotation_reviews (task_id, reviewer_id, decision, corrected_probability, rationale)
    values ('task_demo_1', '33333333-3333-3333-3333-333333333333', 'correct', 0.34,
            'One of the supporting reports is a rewrite of the other, so support is thinner.');
  select count(*) into visible from public.annotation_reviews where task_id = 'task_demo_1';
  reset role;
  perform pg_temp.check('after submitting, a reviewer sees both reviews', visible = 2);
end $$;

-- 4. A submitted review is immutable, even to its own author.
do $$
declare mutated boolean := false;
begin
  perform pg_temp.act_as('22222222-2222-2222-2222-222222222222');
  set local role authenticated;
  begin
    update public.annotation_reviews set decision = 'reject'
      where reviewer_id = '22222222-2222-2222-2222-222222222222';
    mutated := found;
  exception when insufficient_privilege then
    mutated := false;
  end;
  begin
    delete from public.annotation_reviews
      where reviewer_id = '22222222-2222-2222-2222-222222222222';
    mutated := mutated or found;
  exception when insufficient_privilege then
    null;
  end;
  reset role;
  perform pg_temp.check('a submitted review cannot be edited or deleted by its author', not mutated);
end $$;

-- 5. A reviewer cannot review a task they were not assigned.
do $$
declare inserted boolean := false;
begin
  perform pg_temp.act_as('22222222-2222-2222-2222-222222222222');
  set local role authenticated;
  begin
    insert into public.annotation_reviews (task_id, reviewer_id, decision, rationale)
      values ('task_not_mine', '22222222-2222-2222-2222-222222222222', 'accept',
              'Trying to review a task that was never assigned to me.');
    inserted := true;
  exception when insufficient_privilege or check_violation then
    inserted := false;
  end;
  reset role;
  perform pg_temp.check('a reviewer cannot review an unassigned task', not inserted);
end $$;

-- 6. A private saved view is invisible to another analyst; a shared one is not.
do $$
declare visible integer;
begin
  perform pg_temp.act_as('22222222-2222-2222-2222-222222222222');
  set local role authenticated;
  insert into public.saved_views (owner_id, name, route, cutoff_at, snapshot_hash, is_shared)
    values ('22222222-2222-2222-2222-222222222222', 'My unrest watchlist', '/', '2026-01-15T00:00:00Z', 'sha256:demo', false);
  insert into public.saved_views (owner_id, name, route, cutoff_at, snapshot_hash, is_shared)
    values ('22222222-2222-2222-2222-222222222222', 'Team flood view', '/', '2026-01-15T00:00:00Z', 'sha256:demo', true);
  reset role;

  perform pg_temp.act_as('33333333-3333-3333-3333-333333333333');
  set local role authenticated;
  select count(*) into visible from public.saved_views;
  reset role;
  perform pg_temp.check('another analyst sees the shared view and not the private one', visible = 1);
end $$;

-- 7. A scenario row must assert that it is hypothetical.
do $$
declare accepted boolean := false;
begin
  begin
    insert into public.scenario_sessions
      (owner_id, name, forecast_id, district_name, event_family, baseline_probability,
       cutoff_at, snapshot_hash, is_hypothetical)
    values ('22222222-2222-2222-2222-222222222222', 'sneaky', 'fc_demo_1', 'Patna', 'flood',
            0.4, '2026-01-15T00:00:00Z', 'sha256:demo', false);
    accepted := true;
  exception when check_violation then
    accepted := false;
  end;
  perform pg_temp.check('a scenario session cannot be stored as non-hypothetical', not accepted);
end $$;

-- 8. The audit chain verifies, and detects an out-of-band deletion.
do $$
declare bad integer;
begin
  perform pg_temp.act_as('11111111-1111-1111-1111-111111111111');
  set local role authenticated;
  insert into public.audit_events (action, resource_type, resource_id, snapshot_hash, detail)
    values ('review.submit', 'annotation_review', 'task_demo_1', 'sha256:demo', '{"decision":"accept"}'),
           ('export.create', 'export', 'ranked-districts', 'sha256:demo', '{"format":"csv"}'),
           ('role.grant',    'user_role', '44444444-4444-4444-4444-444444444444', 'sha256:demo', '{"role":"analyst"}');
  reset role;

  select count(*) into bad from public.verify_audit_chain() where not ok;
  perform pg_temp.check('an untouched audit chain verifies', bad = 0);

  -- Superuser tampering: exactly the case the chain is meant to expose.
  delete from public.audit_events where action = 'export.create';
  select count(*) into bad from public.verify_audit_chain() where not ok;
  perform pg_temp.check('deleting an audit row is detected by the chain', bad > 0);
end $$;

-- 9. An audit event cannot be appended in somebody else's name.
do $$
declare forged boolean := false;
begin
  perform pg_temp.act_as('44444444-4444-4444-4444-444444444444');
  set local role authenticated;
  begin
    insert into public.audit_events (actor_id, action, resource_type)
      values ('11111111-1111-1111-1111-111111111111', 'role.grant', 'user_role');
    forged := true;
  exception when insufficient_privilege or check_violation then
    forged := false;
  end;
  reset role;
  perform pg_temp.check('an audit event cannot be attributed to another user', not forged);
end $$;

-- 10. Every table in `public` has RLS enabled. A new table added without it is
--     the most likely way this model gets quietly undone.
do $$
declare unprotected text;
begin
  select string_agg(c.relname, ', ') into unprotected
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity;
  perform pg_temp.check(
    'every table in public has row level security enabled (found: ' || coalesce(unprotected, 'none') || ')',
    unprotected is null);
end $$;

\echo 'ALL RLS ASSERTIONS PASSED'
