# BH-001 — the live RLS, policy and grant state of production

**Source:** six read-only CSV exports from the Supabase SQL editor against
project **`oxblcmwhuwtobdhsfgyi`**, committed beside this file as
`audits/BH-001-prod-Q*-2026-09-24.csv`, parsed as CSV (never grepped — policy
expressions contain commas; `AGENTS.md` §3.10).

**Status: RLS coverage is no longer unknown.** `docs/CURRENT_STATE.md` §4 and
`audits/AUDIT-2026-07-04.md` Appendix B both described a database with ~30
RLS-off tables. That is no longer what production looks like. The headline:

| Question | Answer |
|---|---|
| Does `authenticated` still hold UPDATE on `businesses`? | **Not at table level.** Column level is **unverified — Q4's export is truncated.** See §3. |
| Is every table RLS-enabled with policies referencing `is_business_member`? | **Effectively yes**, with two documented exceptions and ten benign self-scoped/catalogue policies. See §2. |
| Anything that reorders RC1? | **Yes — one item.** Two **views** carry `SELECT` for `anon` and cannot have RLS. See §5. |

---

## 1 · Q1 — the census

58 tables in `public`. **56 have RLS on with at least one policy.** The other
two are both fine, and each for a different reason:

| Table | State | Verdict |
|---|---|---|
| `zz_033_flags_backup` | **RLS off** | Safe. `033_entitlement.sql:1142` revoked `anon` and `authenticated` outright, and Q3 confirms neither holds any grant on it. RLS off matters only where a grant exists (`AGENTS.md` §3.8). It is 033's rollback route, deliberately retained (033 STEP 26). |
| `stripe_events` | **RLS on, zero policies** | Correct by design. RLS on with no policy denies everyone on the client path, and `030a_pre_billing_security.sql` SECTION 4 did exactly that — dropped the member policy and revoked both client roles — so the webhook's idempotency ledger is backend-only. Q3 confirms no grants. A member could otherwise delete a row and replay a processed webhook, or forge an `event_id` so a real cancellation was skipped. |

`rls_forced` is false everywhere. That matters only for table owners, and the
owner here is `postgres`, which is the backend's own connection — it is
*supposed* to bypass RLS (`AGENTS.md` §4).

**No table is RLS-off with a client-role grant.** That is the invariant that
matters, and production holds it.

---

## 2 · Q2 — what the policies actually say

**87 policies, and Q1's per-table counts sum to exactly 87, so this export is
complete.** 77 of them gate on membership (`is_business_member`, a
`business_members` subquery, or `is_platform_admin` / `platform_admins`).

The other ten are each justified:

| Policy | Why it does not reference membership |
|---|---|
| `business_members.users_view_own` (SELECT) | The membership table cannot gate on membership without recursion. Scoped to `user_id = auth.uid() OR invited_email = auth.email()`. |
| `business_members.users_link_self` (UPDATE) | An invitee accepting an invite, `user_id IS NULL` and their own email. **Safe only alongside 030a's two-column grant** (`user_id`, `accepted_at`) — with a table-wide UPDATE this becomes a cross-tenant pivot. Q4 must confirm that grant; see §3. |
| `platform_admins.platform_admins_read_own` (SELECT) | `user_id = auth.uid()`. Self-scoped. |
| `profiles.{select,insert,update}_own` | `id = auth.uid()`. Self-scoped. |
| `accounting_providers_public_read`, `plan_definitions_public_read`, `automation_rule_templates_member_read` | `USING (true)` on **catalogue** tables — no `business_id` column, nothing tenant-specific. |
| `support_articles_public_read` (anon) | `is_published = true`. A published help article. |

**Three `USING (true)` policies exist and all three are catalogues.** None is
on a table with a `business_id`.

**No INSERT or UPDATE policy anywhere lacks a `WITH_CHECK`** — so there is no
table a tenant can write into and then not read back, which was the specific
trap the ticket asked about.

**SEC-02 and SEC-03 are closed in production.** The July 2026 audit's two
CRITICALs were `USING (true) FOR ALL` policies with no role restriction on
`xero_connections` and `accounting_connections` — the tables holding OAuth
token ciphertext. Neither `xero_connections_service_policy` nor
`accounting_connections_service` appears in this export. Both tables now carry
only `*_member_access` with `is_business_member(...) OR is_platform_admin(...)`
on both `USING` and `WITH CHECK`.

### 2.1 · Production matches the migration-defined state exactly

Compared against the local Supabase replay built by
`scripts/rls-local.sh` (BH-003, PR #9), which replays this repository's
migrations and prunes the pre-baseline ghost policies against the 5 July 2026
capture:

```
prod: 87 policies   local (replay + prune): 87
byte-identical definitions: 87
in prod, absent locally: 0      local only, absent in prod: 0
RLS-enabled / policy-count differences across 58 tables: 0
businesses table grants: identical for anon, authenticated, postgres, service_role
```

**This is the single most useful result in the ticket.** It means the BH-003
RLS harness is a faithful model of production's policy and RLS state, so its
green run now supports a claim about production and not merely about the
migration files — closing the gap that file's own docstring and `UNCOVERED`
registry flagged. It also independently confirms the prune step was right:
the 24 ghost policies it drops are genuinely absent from production.

It does **not** extend to grants beyond `businesses` (Q3 is truncated), to
constraints (no CSV covers them), or to views (§5).

---

## 3 · Q4 and Q3 — TRUNCATED. Must be re-run.

**Both exports stop at exactly 100 data rows.**

- **Q4 (column privileges)** covers only `accounting_categories` through
  `accounting_transactions` — five tables of 58. **`businesses` is not in it
  at all.**
- **Q3 (table grants)** stops alphabetically at `support_stats`, so
  `support_tickets`, `tasks`, `usage_meters`, `whatsapp_*`, `xero_connections`
  and `zz_033_flags_backup` are missing.

Q1, Q2, Q5 and Q6 are complete (Q2 verified against Q1's counts; Q6 is a
single-table query).

**This is the trap the ticket was written to avoid, and it nearly worked.**
Read naively, Q4 says *no column of `businesses` is UPDATE-able by
`authenticated`* — which reads as "the paywall hole is already closed". It
says no such thing: the query never reached the table.

**What Q6 does establish:** `authenticated` holds
`DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE` on `businesses` and
**no table-level UPDATE**. That is consistent with `033_entitlement.sql`
SECTION 5 having run, which replaced the table-level UPDATE with a
**26-column list** that still contains `plan_tier`, `is_active`,
`feature_flags`, `limits` and `subscription_status`. Column grants are
invisible to `role_table_grants`; only `column_privileges` sees them.

**So the paywall hole (RC1 P0-3) is neither confirmed nor refuted by this
packet.** The one query that settles it is 30 seconds of work:

```sql
-- Q4b — THE DECISIVE QUERY FOR P0-3. Run it and send the result.
SELECT privilege_type,
       count(*) AS columns,
       string_agg(column_name, ', ' ORDER BY column_name) AS cols
  FROM information_schema.column_privileges
 WHERE table_schema = 'public' AND table_name = 'businesses'
   AND grantee = 'authenticated'
 GROUP BY privilege_type ORDER BY privilege_type;
```

**EXPECT, if 033 ran as recorded:** `UPDATE | 26 | api_key, brand_color, …`
including `plan_tier`, `is_active`, `feature_flags`, `limits`,
`subscription_status`, and excluding `metered_usage_enabled` and
`monthly_spend_cap_gbp`. That is what the local replay and staging both show,
and it is the state `audits/030b-PROD-RUNBOOK.md` STEP 0 expects.

If the 26 columns are there, **030b Release 2 is ready to run and P0-3 is
open.** If UPDATE returns zero rows, someone has already revoked it and that
runbook's STEP 4 ("prove the hole exists before closing it") would stop —
which is the correct outcome, and the runbook says so.

Re-run Q3 and Q4 in full as well. To avoid the truncation: the Supabase editor
exports what the grid holds, so either add an explicit high `LIMIT`, or split
by table prefix, or use the aggregate form above which returns one row per
privilege instead of one per column.

---

## 4 · Q5 — what a new table inherits

```
public | r (table) | postgres        | anon=arwdDxtm, authenticated=arwdDxtm, service_role=arwdDxtm
public | r (table) | supabase_admin  | anon=arwdDxtm, authenticated=arwdDxtm, service_role=arwdDxtm
```

`arwdDxtm` is SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER —
**everything**. So the `create_all()` trap (`AGENTS.md` §3.3) is **confirmed
live, in production, as written**: a new SQLModel class creates a table with
RLS **off** and full privileges for `anon` and `authenticated`, which means a
publicly readable and writable table from the moment the process boots.

It is not theoretical and it is not historical. It is the current default, and
it applies to the next model anyone adds. The only reason the database is
currently clean is that someone went and fixed every table by hand
(029, 030a).

**This deserves a ticket of its own:**
`ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;`
would make the trap fail safe instead of fail open — new tables would arrive
unreachable rather than public, and adding a grant would become a deliberate
act. It is one statement, it is RED, and it needs its own rehearsal because it
changes what every future migration and every `create_all()` produces.

---

## 5 · THE ONE THING THAT REORDERS RC1 — two views, readable by `anon`

Q3 lists two objects that are **not tables**:

```
receptionist_call_stats   anon -> DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
                 authenticated -> DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
support_stats             anon -> DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
```

Both appear in the 3 Sep 2026 schema dump (`audits/live-schema-public.txt`)
and **no migration in this repository creates either**. Both exist on staging,
where their definitions are:

```sql
-- receptionist_call_stats
SELECT business_id, count(*) FILTER (WHERE source = 'receptionist') AS total_receptionist_calls,
       today_calls, this_week_calls, handled_calls, transferred_calls,
       voicemail_calls, missed_calls, avg_duration_seconds, last_receptionist_call
  FROM calls GROUP BY business_id;

-- support_stats
SELECT open_tickets, awaiting_admin, in_progress, awaiting_reply, resolved_total,
       ai_resolved_total, created_today, resolved_today, ai_resolution_rate
  FROM support_conversations;          -- platform-wide, no business_id
```

**Why this is a finding, and why BH-001's own Q1 cannot see it:**

1. **A view cannot have RLS.** `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` is
   not a thing for views. Q1 filters `relkind = 'r'` — tables only — so both
   views are absent from the 58-table census and from every RLS count in this
   packet.
2. **A view runs with its OWNER's privileges** unless it was created with
   `security_invoker = on` (PostgreSQL 15+). On staging both are owned by
   `postgres` with no options set. `postgres` owns `calls`, and an owner
   bypasses RLS on their own tables.
3. **So `receptionist_call_stats` returns every business's rows to whoever can
   read the view** — and `anon` can. `anon` is the public key shipped in the
   frontend bundle.

**Severity.** `receptionist_call_stats` is grouped **by `business_id`**, so it
discloses, per tenant, to anyone on the internet holding a key that ships in
the JavaScript: the business's UUID, its total receptionist call volume,
today's and this week's counts, how many calls were handled, transferred, sent
to voicemail and **missed**, the average call duration, and the timestamp of
the most recent call. That is a per-customer operational profile. It is the
same class of finding as BH-002 (the accounting-category leak), reachable
without authenticating at all.

`support_stats` has no `business_id` — it is a platform-wide aggregate, so it
leaks our own support volumes rather than a customer's data. Lower severity,
same root cause, same fix.

The write privileges (`INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`) are noise:
both views aggregate with `GROUP BY` or bare aggregates, so neither is
auto-updatable and writes through them fail. **The `SELECT` is the leak.**

### 5.1 · The one check that confirms it in production

Read-only, and it is the only thing between "very likely" and "certain":

```sql
SELECT c.relname,
       pg_get_userbyid(c.relowner)                            AS owner,
       coalesce(array_to_string(c.reloptions, ','), '(none)')  AS options,
       has_table_privilege('anon', c.oid, 'SELECT')           AS anon_can_select
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('v','m')
 ORDER BY 1;
```

- `options` containing `security_invoker=on` → **no leak**; the view runs as
  the caller and `calls`' RLS applies. Record it and close this finding.
- `options` `(none)` and `owner` `postgres` → **leak confirmed**, as staging.

### 5.2 · The fix, when you want it

Either revoke (`REVOKE ALL ON public.receptionist_call_stats FROM anon,
authenticated;` — the backend reads as `postgres` and is unaffected), or set
`ALTER VIEW ... SET (security_invoker = on);` so the base tables' RLS applies
to the caller. Revoking is the stronger and simpler of the two. **Check
whether the frontend reads either view first** — if it does, `security_invoker`
is the option that keeps the page working. Both are RED; this file does not
change them.

### 5.3 · Why the ticket missed it, and what to change

BH-001's Q1 was written as `relkind = 'r'`. Nothing in the packet asks about
views, so nothing in the packet could have found this — it surfaced only
because Q3 lists relations by name and two of them turned out not to be
tables. **The census query in `scripts/rls-local.sh` has carried a `Q1b` views
section since BH-003 for exactly this reason; BH-001's own SQL should adopt
it.**

---

## 6 · What this packet still does not establish

- **Constraints.** No CSV covers `pg_constraint`. In particular the UNIQUE on
  `stripe_events.event_id`, which BH-006's webhook de-duplication depends on
  under concurrent delivery, is **unverified in production** — migration 010
  declares it, but `models.py` declares that field `index=True`, so whether it
  exists depends on which created the table. `audits/BH-006-PROD-RUNBOOK.md`
  STEP 2 is the read that settles it.
- **Column grants on 53 of 58 tables**, including `businesses` and
  `business_members` (§3). The `business_members` two-column UPDATE grant that
  makes `users_link_self` safe is among them.
- **Whether any policy is *effective*.** These are static rules. Executed
  two-tenant negative tests are BH-003 (PR #9), and they now stand on the
  policy equivalence established in §2.1.
- **`storage` and `auth` schemas.** `public` only.
- **Functions.** No SECURITY DEFINER inventory. Staging has one
  client-callable (`public.whoami`, read-only identity); production is
  unconfirmed.

---

## 7 · Recommended order after this

1. **Run Q4b (§3).** Thirty seconds, and it decides whether 030b Release 2
   runs tonight.
2. **Run the views check (§5.1).** One query. If it confirms, the view fix
   goes ahead of the remaining RC1 items — it is an unauthenticated
   cross-tenant read.
3. **Re-run Q3 and Q4 in full.**
4. Then `030b` Release 2 (PR #10) and BH-003 (PR #9) as already queued.
5. Raise the default-privileges ticket (§4) so the `create_all()` trap fails
   safe.
