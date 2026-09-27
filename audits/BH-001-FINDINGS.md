# BH-001 — the live RLS, policy and grant state of production

**Source:** six read-only CSV exports from the Supabase SQL editor against
project **`oxblcmwhuwtobdhsfgyi`**, committed beside this file as
`audits/BH-001-prod-Q*-2026-09-24.csv`, parsed as CSV (never grepped — policy
expressions contain commas; `AGENTS.md` §3.10).

**Status: the POLICY inventory is complete and clean. GRANT coverage is not,
and three access findings came out of the data that the ticket's own queries
were not designed to surface.** P0-8 asked "what is the live RLS, policy and
grant state" — two of those three are answered.

| Question | Answer |
|---|---|
| Does `authenticated` still hold UPDATE on `businesses`? | **Not at table level** (Q6, complete). Column level is **unverified — Q4's export is truncated.** §3 |
| Is every table RLS-enabled with policies referencing `is_business_member`? | **Yes for 56 of 58 tables**, and the two exceptions are each correct. But "referencing" is not "enforcing" — see §2 and §6. |
| Anything that reorders RC1? | **Three things.** Two views readable by `anon` (§5); inactive members still reading `calls` and `tasks` (§6.1); `TRUNCATE` granted to `anon` on 46 tables (§6.2). |

**A note on how this file is written.** Codex's review of its first version
found five claims that went further than the CSVs support, and two findings
sitting in the data that the first version missed entirely. Both classes are
corrected below, and where evidence is absent it now says so rather than
reasoning from the migration files — `AGENTS.md` §3.4 exists because this
repository has made that mistake before.

---

## 1 · Q1 — the census

58 tables in `public`. **56 have RLS on with at least one policy.** The other
two:

| Table | State | Verdict |
|---|---|---|
| `zz_033_flags_backup` | **RLS off** | **Grants UNVERIFIED.** `033_entitlement.sql:1142` revokes `anon` and `authenticated`, but a migration file is not evidence of live state, and this table sorts **beyond Q3's truncation point** (`support_stats`), so the grant export does not cover it. If those revokes did not land, an RLS-off table holding a snapshot of every business's `plan_tier` and `feature_flags` is client-readable. **One query settles it — §3.1.** |
| `stripe_events` | **RLS on, zero policies** | Correct by design, and this one IS evidenced: the table sorts *inside* Q3's covered range and appears nowhere in it, so `anon` and `authenticated` hold no direct grant. RLS on with no policy denies the client path outright, which is what `030a` SECTION 4 did — dropped the member policy and revoked both client roles. A member could otherwise delete a row and replay a processed webhook, or forge an `event_id` so a real cancellation was skipped. |

`rls_forced` is false on all 58. That matters only for table owners. **Q1 does
not export ownership**, so the natural next sentence — "and the owner is
`postgres`, which is supposed to bypass RLS" — is inference from
`AGENTS.md` §4, not from this packet.

**The invariant I want to claim here is "no table is RLS-off while a client
role holds a grant", and I cannot claim it yet.** It holds for every table Q3
covers. `zz_033_flags_backup` is the one table that is both RLS-off and
outside Q3's range, which is an unfortunate coincidence rather than a
conclusion.

---

## 2 · Q2 — what the policies actually say

**87 policies. Q1's per-table counts sum to 87, and Codex independently
confirmed every per-table count matches, not merely the total — so this export
is complete.**

**77 policies REFERENCE `is_business_member`, a `business_members` subquery,
`is_platform_admin` or `platform_admins`.** The first version of this file said
those 77 "gate on membership". That is a text match, not a semantic claim, and
at least one of the 77 does not require membership at all:
`support_articles_member_read` is `(is_published = true) OR
is_platform_admin(auth.uid())` — a published help article, readable by any
authenticated user. Correct behaviour; wrong description.

The ten that reference neither:

| Policy | Why |
|---|---|
| `business_members.users_view_own` (SELECT) | The membership table cannot gate on membership without recursion. `user_id = auth.uid() OR invited_email = auth.email()`. |
| `business_members.users_link_self` (UPDATE) | An invitee accepting an invite. **See §6.3 — it does not pin the new `user_id`.** |
| `platform_admins.platform_admins_read_own` (SELECT) | `user_id = auth.uid()`. |
| `profiles.{select,insert,update}_own` | `id = auth.uid()`. |
| `accounting_providers_public_read`, `plan_definitions_public_read`, `automation_rule_templates_member_read` | `USING (true)` on catalogue tables. |
| `support_articles_public_read` (anon) | `is_published = true`. |

**Three `USING (true)` policies, all on catalogue tables.** That none of those
three tables has a `business_id` column is true, and it comes from the schema
dump — Q2 cannot establish it.

**On `WITH CHECK`:** the first version claimed no INSERT or UPDATE policy
anywhere lacks one. That was wrong twice over, and the way it was wrong is
worth recording because it is the CSV trap this ticket was written to avoid.
The export writes a NULL `with_check_expression` as the **literal string
`null`**, so a check for "empty" matched nothing and the claim looked
confirmed. Handling the sentinel, there is exactly one:
`businesses."Platform admins can manage all businesses"` is `ALL` with no
explicit `WITH CHECK`. **That is not a defect** — PostgreSQL falls back to the
`USING` expression for the check — and the inherited packet's framing ("writes
are not constrained") is wrong for this case. The real statement is: no policy
here permits a write it cannot also authorise.

**SEC-02 and SEC-03 are closed as POLICY DEFECTS.** The July audit's two
CRITICALs were `USING (true) FOR ALL` with no role restriction on
`xero_connections` and `accounting_connections`. Neither policy appears in this
export; both tables now carry only `*_member_access` with
`is_business_member(...) OR is_platform_admin(...)` on both sides. That is the
policy fixed. It is **not** a statement that the token ciphertext in those
tables is confidential — see §6.4.

### 2.1 · Production's policy TEXT matches the migration-defined replay

Compared against the local Supabase replay built by `scripts/rls-local.sh`
(BH-003, PR #9, census committed at `5e1aaf7`):

```
prod: 87 policies   local (replay + prune): 87
identical after normalisation: 87   (command, roles, permissive, USING, WITH CHECK)
in prod, absent locally: 0      local only, absent in prod: 0
RLS-enabled / policy-count across all 58 tables: 0 differences
businesses table grants: identical for all four roles
```

Normalisation, stated so it can be argued with: whitespace collapsed, roles
sorted, the export's literal `null` mapped to SQL NULL. Codex reproduced the
comparison independently and confirmed `permissive` matches too. **Not
"byte-identical"** — identical after that normalisation. Whitespace collapsing
is not generally safe, because it also rewrites quoted literals; no production
literal here contains runs of whitespace, but the raw captures are committed so
the comparison can be redone strictly.

**What this licenses, narrowly.** BH-003's RLS suite runs against the replay.
Because the replay's policy *text* and RLS state match production's, a green
run there supports a claim about production's **policy text** — which is more
than "the migration files say so", and is the gap that suite's own docstring
flagged.

**What it does not license, and Codex's example is the decisive one.**
Identical calls to `is_business_member()` do not establish identical *function
bodies*, security settings, ownership or execute privileges — and `030a`
changed membership behaviour **without changing a single policy expression**.
Two databases can therefore match on all 87 policies and still behave
differently. Also outside the comparison: grants beyond `businesses` (Q3
truncated), column grants (Q4 truncated), constraints (no export), views (the
replay creates none — §5), role attributes and membership, and the `auth` and
`storage` schemas. **BH-003 supports production conclusions subject to those
dependencies, not unconditionally.**

---

## 3 · Q3 and Q4 — TRUNCATED. Must be re-run.

**Both exports stop at exactly 100 data rows.**

- **Q4 (column privileges)** ends mid-table at
  `accounting_transactions.amount / authenticated`. Five tables appear; four
  are complete and the fifth is partial, so **54 of 58 tables lack complete
  column-grant coverage**. **`businesses` does not appear at all.**
- **Q3 (table grants)** ends at `support_stats / anon`. Everything sorting
  after it is missing: `support_tickets`, `tasks`, `usage_meters`,
  `whatsapp_*`, `xero_connections`, `zz_033_flags_backup`.

Q1, Q2, Q5 and Q6 are complete (Q2 verified against Q1's counts row by row;
Q6 is a single-table query).

**This is the trap the ticket was written to avoid, and it nearly worked.**
Read naively, Q4 says *no column of `businesses` is UPDATE-able by
`authenticated`* — which reads as "the paywall hole is already closed". It says
no such thing: the query never reached the table.

**What Q6 does establish:** `authenticated` holds
`DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE` on `businesses` and
**no table-level UPDATE** — consistent with `033` SECTION 5 having replaced the
table grant with a **26-column list** that still contains `plan_tier`,
`is_active`, `feature_flags`, `limits` and `subscription_status`. Column grants
are invisible to `role_table_grants`.

**So RC1 P0-3 is neither confirmed nor refuted by this packet.**

### 3.1 · The three queries that close the gaps

```sql
-- Q4b — THE DECISIVE QUERY FOR P0-3. Aggregated, so the 100-row limit
-- cannot truncate it.
SELECT privilege_type, count(*) AS columns,
       string_agg(column_name, ', ' ORDER BY column_name) AS cols
  FROM information_schema.column_privileges
 WHERE table_schema = 'public' AND table_name = 'businesses'
   AND grantee = 'authenticated'
 GROUP BY privilege_type ORDER BY privilege_type;

-- Q3b — the grants Q3 could not reach, including the RLS-off table.
SELECT table_name, grantee,
       string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
  FROM information_schema.role_table_grants
 WHERE table_schema = 'public' AND grantee IN ('anon','authenticated')
   AND table_name > 'support_stats'
 GROUP BY table_name, grantee ORDER BY table_name, grantee;

-- Q3c — business_members' column grants, which §6.3 turns on.
SELECT privilege_type, count(*) AS columns,
       string_agg(column_name, ', ' ORDER BY column_name) AS cols
  FROM information_schema.column_privileges
 WHERE table_schema = 'public' AND table_name = 'business_members'
   AND grantee = 'authenticated'
 GROUP BY privilege_type ORDER BY privilege_type;
```

**EXPECT — Q4b, if 033 ran as recorded:** `UPDATE | 26 | …` including
`plan_tier`, `is_active`, `feature_flags`, `limits`, `subscription_status`, and
excluding `metered_usage_enabled` and `monthly_spend_cap_gbp`. That is what the
local replay and staging both show, and what `audits/030b-PROD-RUNBOOK.md`
STEP 0 expects.

If the 26 columns are there, **030b Release 2 is ready and P0-3 is open.** If
UPDATE returns nothing, it has already been revoked — and Q4b cannot say by
whom or when, so check the git log and the runbook's own records before
concluding Release 2 has run.

**EXPECT — Q3b:** `zz_033_flags_backup` absent (033's revokes landed). If it
appears with any privilege, §1's finding is live.

**EXPECT — Q3c:** `UPDATE | 2 | accepted_at, user_id` — 030a's narrowing. If it
shows the whole table, §6.3 becomes a cross-tenant membership pivot.

Re-run Q3 and Q4 in full as well. The editor exports what the grid holds, so
either aggregate (as above), split by table prefix, or add an explicit high
`LIMIT`.

---

## 4 · Q5 — what a new table inherits, and the remedy that does not work

```
public | r (tables)    | postgres        | anon=arwdDxtm, authenticated=arwdDxtm, service_role=arwdDxtm
public | r (tables)    | supabase_admin  | anon=arwdDxtm, authenticated=arwdDxtm, service_role=arwdDxtm
public | S (sequences) | postgres        | anon=rwU, authenticated=rwU, service_role=rwU
public | S (sequences) | supabase_admin  | anon=rwU, authenticated=rwU, service_role=rwU
public | f (functions) | postgres        | anon=X, authenticated=X, service_role=X
public | f (functions) | supabase_admin  | anon=X, authenticated=X, service_role=X
```

`arwdDxtm` is SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
**and MAINTAIN** (`m`, PostgreSQL 17) — the first version's decoding omitted
MAINTAIN. So the **`create_all()` trap is confirmed live**: a new SQLModel
class creates a table with RLS **off** and full privileges for `anon` and
`authenticated`, publicly readable and writable from the moment the process
boots — **when the creating role is `postgres` or `supabase_admin`**, which
covers both the backend connection and the dashboard.

`create_all()` runs at every boot (`AGENTS.md` §3.3), so this is the current
default and applies to the next model anyone adds.

**Two corrections to the first version's remedy**, both Codex's:

1. `ALTER DEFAULT PRIVILEGES … REVOKE …` **only changes defaults for the role
   that executes it.** Q5 shows two creator roles, so the statement must name
   them:

   ```sql
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres, supabase_admin
     IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
   ```

   Whether the runbook's connection may alter `supabase_admin`'s defaults is
   itself something to establish before writing that runbook.
2. **Sequences (`rwU`) and functions (`X`) have client-role defaults too**, and
   a TABLES-only revoke leaves both. A new sequence is writable by `anon`; a
   new function is executable by `anon`. Worth interpreting; not proven
   exploitable here.

This changes **future** objects only — existing grants are untouched, which is
why it is additive and still RED. The first version added "the database is
currently clean only because someone fixed every table by hand"; that is
removed, because §1 and §3 show grant coverage is incomplete and §6 shows it
is not clean.

---

## 5 · Two views readable by `anon`, which cannot carry RLS

Q3 lists two objects that are **not in Q1's 58 tables**:

```
receptionist_call_stats   anon -> DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
                 authenticated -> DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
support_stats             anon -> DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
```

Both appear in the 3 Sep 2026 schema dump and **no migration in this repository
creates either.** The `anon` SELECT grant is established by Q3, from
production.

**Why Q1 could not see this:** Q1 filters `relkind = 'r'`. A view cannot have
RLS enabled on it, and an ordinary view's access to its base tables normally
runs with the **view owner's** privileges unless it was created with
`security_invoker = on` (PostgreSQL 15+). An owner who owns the base table
bypasses that table's RLS.

**What is NOT established by this packet, and the first version overstated
it.** These CSVs carry no view definitions, owners, `reloptions`, dependencies,
or `INSTEAD OF` triggers. The definitions the first version quoted came from
**staging**, and staging cannot establish what production's views return. So
the honest statement is: **two views are client-readable, they cannot be
protected by RLS, and on staging they aggregate `calls` and
`support_conversations` with `receptionist_call_stats` grouped by
`business_id`. If production's definitions match staging's, `anon` can read
every tenant's receptionist call profile** — counts, missed calls, average
duration, last call — with a key that ships in the frontend bundle. That is the
same class of exposure as BH-002, without authenticating.

`support_stats` has no `business_id` on staging: a platform-wide aggregate, so
it would leak our own support volumes rather than a customer's data.

The write grants are **probably** inert: an aggregating view is not
automatically updatable. But an `INSTEAD OF` trigger or rule can make one
writable, and none of that is exported — so "writes fail" is not evidenced
either. `TRUNCATE` does not apply to ordinary views at all.

### 5.1 · The query that settles it

Read-only:

```sql
SELECT c.relname,
       c.relkind,                                              -- v or m
       pg_get_userbyid(c.relowner)                    AS owner,
       coalesce(array_to_string(c.reloptions, ','), '(none)') AS options,
       has_table_privilege('anon', c.oid, 'SELECT')   AS anon_can_select,
       pg_get_viewdef(c.oid, true)                    AS definition
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('v','m')
 ORDER BY 1;

-- and, for each view returned, what it reads and whether any of that is
-- itself SECURITY DEFINER:
SELECT DISTINCT dependent.relname AS view_name, base.relname AS reads,
       base.relrowsecurity       AS base_has_rls
  FROM pg_depend d
  JOIN pg_rewrite r  ON r.oid = d.objid
  JOIN pg_class dependent ON dependent.oid = r.ev_class
  JOIN pg_class base ON base.oid = d.refobjid
 WHERE dependent.relkind IN ('v','m') AND base.relkind = 'r'
   AND dependent.oid <> base.oid
 ORDER BY 1, 2;

SELECT n.nspname||'.'||p.proname AS func, p.prosecdef AS security_definer,
       pg_get_userbyid(p.proowner) AS owner
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND (has_function_privilege('anon', p.oid, 'EXECUTE')
        OR has_function_privilege('authenticated', p.oid, 'EXECUTE'))
 ORDER BY 1;
```

Reading it: `options` containing `security_invoker=on` means the view runs as
the caller and the base table's RLS applies — **but check the third query
anyway**, because an invoker view can still call a SECURITY DEFINER function.
`(none)` plus an owner who owns the base table means the exposure is real. A
`relkind` of `m` is a materialized view, which holds its own copy of the rows
and is not affected by base-table RLS at read time at all. And read
`pg_get_viewdef` rather than trusting the staging definitions quoted above.

### 5.2 · The fix, when confirmed

`REVOKE ALL ON public.receptionist_call_stats, public.support_stats FROM anon,
authenticated;` — the backend reads as `postgres` and is unaffected. Or
`ALTER VIEW … SET (security_invoker = on)`, which keeps the view usable by a
member while applying the base table's RLS. **Check whether the frontend reads
either view first**; if it does, `security_invoker` is the option that keeps
the page working. Both RED; nothing here changes them.

### 5.3 · What to change in the ticket

BH-001's Q1 was written `relkind = 'r'`, so nothing in the packet could have
found this. `scripts/rls-local.sh census` has carried a views section since
BH-003 for exactly this reason, and BH-001's own SQL should adopt it.

---

## 6 · Findings that came out of the data, not the questions

The first version of this file did not contain §6.1–§6.4. All four are in the
CSVs; Codex found the first two by reading the data independently.

### 6.1 · Inactive members can still read `calls` and `tasks`

Q2 shows **two permissive SELECT policies on each of `calls` and `tasks`**:

| Table | Policy | Requires `bm.is_active`? |
|---|---|---|
| `calls` | `Members can select calls for their businesses` | **No** |
| `calls` | `calls_select_if_member` | Yes |
| `tasks` | `Members can select tasks for their businesses` | **No** |
| `tasks` | `tasks_select_if_member` | Yes |

**PostgreSQL combines permissive policies with OR**, so the newer, stricter
policy cannot narrow the older one. A `business_members` row with
`is_active = false` satisfies the broader policy, and the member reads the
tenant's calls and tasks.

Concretely: **a member who has been deactivated — an employee who left — can
still read that business's call records and tasks** through the anon key, for
as long as their `business_members` row exists. `business_members.users_view_own`
also lets them see their own inactive membership, so the row is discoverable.

Evidence quality differs between the two: Q3 confirms `authenticated` holds
SELECT on `calls`; `tasks` sorts beyond Q3's truncation, so its grant is
unverified (Q3b above covers it).

These two policies are `028_baseline_live_state.sql`'s captured live state —
the duplicates its own header flags as "no consolidation of the duplicate
policies on businesses/tasks/calls … cleanup is a separate, later migration".
That cleanup never happened. **Dropping the two `is_active`-less policies is a
small RED migration and it is the highest-value one in this file** — one
`DROP POLICY` each, and the stricter policy is already there to take over.

### 6.2 · `TRUNCATE` is granted to `anon` on 46 tables, and RLS does not constrain it

Q3, within its covered range: `TRUNCATE` is held by **`anon` on 46 tables** and
**`authenticated` on 48** (plus the views, where it does not apply). Q6
independently confirms it on `businesses`; Q3 shows it on `business_members`.

**PostgreSQL excludes `TRUNCATE` and `REFERENCES` from row-level security.**
RLS filters rows for SELECT/INSERT/UPDATE/DELETE; `TRUNCATE` is a table-level
operation and a policy cannot restrict it. So for these tables, the row
policies that this file spends §2 confirming are **not the second gate** —
there is no second gate.

**This is not a demonstrated exploit.** PostgREST does not expose `TRUNCATE`,
and reaching it needs an executable SQL or RPC route that has not been shown to
exist. What it does mean is that the reassurance "broad grants are fine because
RLS is the gate" (`AGENTS.md` §3.8) **does not hold for TRUNCATE**, and the
grant is real authority sitting on the public key. `030a` revoked
`INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES` from `anon` on three tables; the
same revoke has not been applied to the other 46. Worth its own ticket, and
worth stating separately from reachability.

### 6.3 · `users_link_self` does not pin the new `user_id`

```
USING       (invited_email = auth.email()) AND (user_id IS NULL)
WITH CHECK  (invited_email = auth.email())
```

The `USING` clause restricts which row may be updated — an unclaimed invite
addressed to the caller. The `WITH CHECK` constrains the row *after* the
update, and it checks only the email. **It never requires the new `user_id` to
be `auth.uid()`.** So the policy permits claiming your own invitation on behalf
of an arbitrary UUID.

030a's two-column grant (`user_id`, `accepted_at`) is what stops this being
worse — the tenant and role cannot be changed — but it does not make the policy
"link *self*". Whether anything else prevents it (a trigger, a FK to
`auth.users`, a constraint) is not in these exports. Q3c above confirms the
grant is still two columns; the policy's `WITH CHECK` should gain
`AND user_id = auth.uid()` regardless, since that is what its name claims.

### 6.4 · `oauth_tokens` is member-accessible, which contradicts the July audit

`audits/AUDIT-2026-07-04.md` Appendix B lists `oauth_tokens` under "Enabled +
correct" as **`(deny-auth)`**. Today Q2 shows
`oauth_tokens_member_access`, `ALL`, `{authenticated}`,
`is_business_member(...) OR is_platform_admin(...)`, and Q3 shows `anon` and
`authenticated` both holding SELECT/INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES.
The July capture's `deny_authenticated_oauth_tokens` policy is **not** in
production's 87.

So the table went from "no authenticated access at all" to "any member of the
owning business has full access to its OAuth token rows". That may well be
deliberate — some feature presumably needs it — but it is a material change
from the documented security posture and it is the table holding third-party
access tokens. It should be stated and owned, not absorbed into "56 tables have
member policies". **This is also why §2's SEC-02/SEC-03 closure is scoped to
"those policy defects are gone" rather than "token confidentiality is
verified".**

---

## 7 · What this packet still does not establish

- **Column grants on 54 of 58 tables** (§3), including `businesses` — P0-3 —
  and `business_members` (§6.3).
- **Table grants for everything sorting after `support_stats`** (§3),
  including the RLS-off `zz_033_flags_backup` (§1).
- **Constraints.** No export covers `pg_constraint`. The UNIQUE on
  `stripe_events.event_id`, which BH-006's webhook de-duplication depends on
  under concurrent delivery, is unverified in production —
  `audits/BH-006-PROD-RUNBOOK.md` STEP 2 is that read.
- **Helper function bodies, ownership and security settings** — the §2.1 limit
  that matters most, since every membership policy is a call into one.
- **View definitions, owners and options** (§5).
- **Whether any policy is EFFECTIVE.** These are static rules. Executed
  two-tenant negative tests are BH-003 (PR #9), subject to §2.1's limits.
- **Ownership of anything** (§1), and role attributes or role membership.
- **`storage` and `auth` schemas**, and `public` sequences and functions (§4).

---

## 8 · Recommended order

1. **Q4b (§3.1).** Thirty seconds, and it decides whether 030b Release 2 runs.
2. **The views check (§5.1).** If it confirms, that fix goes ahead of the rest
   — it is an unauthenticated cross-tenant read.
3. **Drop the two `is_active`-less policies on `calls` and `tasks` (§6.1).**
   Two `DROP POLICY` statements, the stricter policies already exist, and until
   it runs a deactivated member keeps reading.
4. **Q3b and Q3c (§3.1)**, then re-run Q3 and Q4 in full.
5. Then `030b` Release 2 (PR #10) and BH-003 (PR #9) as queued.
6. Raise tickets for: the default-privileges change (§4), the `anon` TRUNCATE
   revoke (§6.2), `users_link_self`'s `WITH CHECK` (§6.3), and a decision on
   `oauth_tokens` member access (§6.4).
