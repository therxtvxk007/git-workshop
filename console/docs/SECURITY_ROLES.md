# Roles, policies and what actually enforces them

Every rule in this document is enforced by Postgres. The React components that
hide buttons and gate routes are a courtesy — they prevent an unpleasant error
message, they do not prevent the action. If the client had a bug tomorrow, the
database would still refuse.

`supabase/tests/01_rls_test.sql` attempts thirteen violations of these rules
against a real Postgres and fails the run if any succeeds. Run it before
trusting anything below.

## Roles

| Role | Can |
| --- | --- |
| `viewer` | Read the workspace: forecasts, evidence, backtests, data health, models, audit |
| `reviewer` | Everything above, plus claim and submit blinded annotation reviews |
| `analyst` | Everything above, plus create and export scenarios |
| `administrator` | Everything above, plus grant/revoke roles, adjudicate disputes, read all reviews and exports |

Roles are additive and a user may hold several. `administrator` satisfies every
check.

## Roles live in their own table

`public.user_roles`, never a column on `public.profiles`.

This is the most important decision in the schema. A `profiles.role` column is
editable by the row's owner under any sane profile policy, which means a user
can promote themselves to administrator by updating their own profile. Splitting
the table makes that impossible to express: `profiles` is presentation data that
authorisation never reads, and `user_roles` is writable only by administrators.

Checks go through a `SECURITY DEFINER` function:

```sql
create or replace function public.has_role(_user_id uuid, _role public.app_role)
returns boolean language sql stable security definer
set search_path = public, pg_temp
as $$ select exists (select 1 from public.user_roles
                     where user_id = _user_id and role = _role); $$;
```

`search_path` is pinned. A definer function with a mutable search path is a
privilege-escalation primitive.

New sign-ups get a profile and exactly `viewer`, created by a trigger on
`auth.users`. Elevation is a deliberate administrative act, never a side effect
of registering.

## Blinding

A reviewer may read a peer's review of a task **only once their own review row
exists**:

```sql
create policy reviews_select_blinded on public.annotation_reviews
  for select to authenticated
  using (
    reviewer_id = auth.uid()
    or public.is_administrator()
    or public.has_submitted_review(task_id, auth.uid())
  );
```

`has_submitted_review` is `SECURITY DEFINER`, and that is not incidental. The
obvious way to write this rule — an `EXISTS` subquery over `annotation_reviews`
inside `annotation_reviews`' own `SELECT` policy — makes Postgres evaluate the
policy in order to evaluate the policy. The first version of this schema did
exactly that and every read failed with `infinite recursion detected in policy`.
The RLS test caught it. A definer function reads the table with RLS bypassed and
answers one question: has this user already submitted?

The serving API must not send the model's opinion to a blinded reviewer either.
See `docs/API_INTEGRATION.md`.

## Immutability

`public.annotation_reviews` has **no `UPDATE` policy and no `DELETE` policy**,
and the grants match:

```sql
grant select, insert on public.annotation_reviews to authenticated;
```

The absence is the guarantee. A reviewer who can edit a submitted review after
seeing a peer's can manufacture agreement, and an annotation set whose history
can be rewritten is not evidence of anything. Corrections happen through
adjudication, which appends a new row alongside the originals; neither review is
altered.

Adding an update policy later should require explaining, in a migration, why the
annotation record needs to be rewritable.

## Append-only audit with a hash chain

`public.audit_events` has no `UPDATE` or `DELETE` policy. Each row also carries
`prev_hash` and `entry_hash`, computed by a `BEFORE INSERT` trigger over the
row's own content and its predecessor's hash. The client cannot supply either: a
caller that chooses its own chain link can forge a consistent-looking history.

`public.verify_audit_chain()` recomputes the chain and reports the first broken
link. This does not make tampering impossible — a superuser can do anything —
it makes tampering **detectable**, which is the achievable property. The test
suite deletes a row as a superuser and asserts that verification catches it.

Reads are not audited. Audited actions are: submitting a review, adjudicating,
raising a dispute, exporting, saving a scenario, and granting or revoking a
role. An audit log that records every page view buries the entries that matter.

## Scenario isolation

Scenarios live in `scenario_sessions` and `scenario_inputs`, with

```sql
is_hypothetical boolean not null default true check (is_hypothetical)
```

The check constraint means the column cannot be set to false at all. Isolation
is structural rather than a filter, because "we exclude hypotheticals in the
query" is one forgotten `WHERE` clause away from a scenario appearing in an
alert list. Scenario rows are private to their owner, cannot be joined into a
forecast listing, cannot produce an alert, and every export of one is
watermarked in both its filename and its header block.

## Explicit grants

Every table is `revoke all ... from anon, authenticated` followed by the exact
grants it needs. Relying on a blanket grant plus RLS means one forgotten
`enable row level security` exposes a whole table. Assertion 10 of the RLS test
fails the build if any table in `public` lacks RLS.

## Local mode

With no `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`, the console uses
`LocalCloudBackend`: browser storage, reproducing these rules faithfully enough
to demonstrate the workflow.

**It secures nothing.** Everything it holds is editable from devtools in about
four seconds. The top bar shows a `local storage` chip whenever it is active,
and the sign-in page says so explicitly. Use it to click through the workflow
before standing up a database; never as a deployment.

## Running the policy tests

```bash
createdb console_test
psql -d console_test -v ON_ERROR_STOP=1 -f supabase/tests/00_local_auth_shim.sql
for f in supabase/migrations/*.sql; do
  psql -d console_test -v ON_ERROR_STOP=1 -f "$f"
done
psql -d console_test -v ON_ERROR_STOP=1 -f supabase/tests/01_rls_test.sql
```

The shim supplies the parts of Supabase's `auth` schema the migrations depend
on, so the policies can be executed rather than asserted. It is a test fixture
and is never applied to a real project.
