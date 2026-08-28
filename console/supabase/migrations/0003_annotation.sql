-- Blinded two-reviewer annotation.
--
-- Blinding is enforced here, in the database, not in the client. A reviewer can
-- read a peer's review of a task only once their own review row exists. If that
-- rule lived in React, "blinded" would mean "blinded unless you open the
-- network tab", which is not blinded.

create type public.review_decision as enum ('accept', 'correct', 'reject');
create type public.task_state      as enum ('pending', 'in_review', 'submitted', 'adjudicated', 'disputed');

create table public.annotation_assignments (
  id             uuid primary key default gen_random_uuid(),
  task_id        text not null,
  forecast_id    text not null,
  snapshot_hash  text not null check (length(trim(snapshot_hash)) > 0),
  cutoff_at      timestamptz not null,
  reviewer_id    uuid not null references auth.users (id) on delete cascade,
  state          public.task_state not null default 'pending',
  assigned_at    timestamptz not null default now(),
  due_at         timestamptz not null,
  unique (task_id, reviewer_id)
);

comment on column public.annotation_assignments.forecast_id is
  'Engine-side identifier. Forecasts are never canonical in this database; this
   is a pointer, not a copy.';

create table public.annotation_reviews (
  id             uuid primary key default gen_random_uuid(),
  task_id        text not null,
  reviewer_id    uuid not null references auth.users (id) on delete cascade,
  decision       public.review_decision not null,
  -- The reviewer's own probability, only meaningful for 'correct'.
  corrected_probability numeric(6,5) check (corrected_probability between 0 and 1),
  rationale      text not null check (length(trim(rationale)) >= 20),
  evidence_ids   text[] not null default '{}',
  -- Whether the machine suggestion was visible when this review was written.
  saw_suggestion boolean not null default false,
  time_spent_seconds integer check (time_spent_seconds >= 0),
  submitted_at   timestamptz not null default now(),
  unique (task_id, reviewer_id),
  constraint corrected_probability_required_for_correct
    check (decision <> 'correct' or corrected_probability is not null)
);

comment on table public.annotation_reviews is
  'Immutable. There is deliberately no UPDATE or DELETE policy: a reviewer who
   can edit a submitted review after seeing a peer''s can manufacture agreement,
   and an annotation set whose history can be rewritten is not evidence of
   anything. Corrections are made by adjudication, which is a new row.';

create table public.annotation_adjudications (
  id              uuid primary key default gen_random_uuid(),
  task_id         text not null unique,
  adjudicator_id  uuid not null references auth.users (id),
  decision        public.review_decision not null,
  final_probability numeric(6,5) check (final_probability between 0 and 1),
  rationale       text not null check (length(trim(rationale)) >= 20),
  disputed_review_ids uuid[] not null default '{}',
  adjudicated_at  timestamptz not null default now()
);

alter table public.annotation_assignments   enable row level security;
alter table public.annotation_reviews       enable row level security;
alter table public.annotation_adjudications enable row level security;

-- Assignments: your own, or everything if you adjudicate.
create policy assignments_select on public.annotation_assignments
  for select to authenticated
  using (reviewer_id = auth.uid() or public.is_administrator());

create policy assignments_admin_write on public.annotation_assignments
  for all to authenticated
  using (public.is_administrator())
  with check (public.is_administrator());

-- A reviewer may move only their own task between workflow states.
create policy assignments_update_own_state on public.annotation_assignments
  for update to authenticated
  using (reviewer_id = auth.uid() and public.has_role(auth.uid(), 'reviewer'))
  with check (reviewer_id = auth.uid());

-- The unblinding predicate.
--
-- SECURITY DEFINER is not optional here. The obvious way to write the blinding
-- rule -- an EXISTS subquery over annotation_reviews inside annotation_reviews'
-- own SELECT policy -- makes Postgres evaluate the policy to evaluate the
-- policy, and the first read fails with "infinite recursion detected in policy".
-- A definer function reads the table with RLS bypassed, which breaks the cycle
-- while answering exactly one question: has this user already submitted?
create or replace function public.has_submitted_review(_task_id text, _user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.annotation_reviews
    where task_id = _task_id and reviewer_id = _user_id
  );
$$;

-- THE BLINDING POLICY.
--
-- Read your own review always. Read a peer's review on the same task only once
-- your own row exists. Administrators see everything, because adjudication is
-- impossible otherwise.
create policy reviews_select_blinded on public.annotation_reviews
  for select to authenticated
  using (
    reviewer_id = auth.uid()
    or public.is_administrator()
    or public.has_submitted_review(task_id, auth.uid())
  );

create policy reviews_insert_own on public.annotation_reviews
  for insert to authenticated
  with check (
    reviewer_id = auth.uid()
    and public.has_role(auth.uid(), 'reviewer')
    and exists (
      select 1 from public.annotation_assignments a
      where a.task_id = annotation_reviews.task_id
        and a.reviewer_id = auth.uid()
    )
  );

-- No update policy and no delete policy. This is the immutability guarantee;
-- it is expressed as an absence on purpose. Adding one later should require
-- explaining, in a migration, why the annotation record needs to be rewritable.

create policy adjudications_select on public.annotation_adjudications
  for select to authenticated
  using (public.can_read_workspace());

create policy adjudications_admin_insert on public.annotation_adjudications
  for insert to authenticated
  with check (public.is_administrator());

revoke all on public.annotation_assignments, public.annotation_reviews,
              public.annotation_adjudications
  from anon, authenticated;
grant select, insert, update, delete on public.annotation_assignments to authenticated;
grant select, insert on public.annotation_reviews to authenticated;   -- no update/delete, ever
grant select, insert on public.annotation_adjudications to authenticated;

create index assignments_reviewer_idx on public.annotation_assignments (reviewer_id, state, due_at);
create index reviews_task_idx on public.annotation_reviews (task_id);

-- Inter-reviewer agreement, computed where the rows are rather than by shipping
-- every review to the browser.
create or replace function public.task_review_agreement(_task_id text)
returns table (reviews_submitted integer, decisions public.review_decision[], agreed boolean)
language sql
stable
security invoker            -- deliberately invoker: the blinding policy applies
set search_path = public, pg_temp
as $$
  select
    count(*)::integer,
    array_agg(decision order by submitted_at),
    count(distinct decision) = 1
  from public.annotation_reviews
  where task_id = _task_id;
$$;

grant execute on function public.task_review_agreement(text) to authenticated;
grant execute on function public.has_submitted_review(text, uuid) to authenticated;
