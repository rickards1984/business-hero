# Permissions and tenancy — STUB, and one open question

**Status: stub, blocked on evidence.**

Analysis is in `docs/CURRENT_STATE.md` §4. The essential points:

- Backend bypasses RLS; isolation is application-layer `WHERE business_id`
- Frontend uses the anon key and is subject to RLS
- Admin and customer are the **same** Postgres role (`authenticated`), and
  grants are evaluated before RLS — so a column grant to an admin is a grant
  to every customer
- `authenticated` holds **no table-level UPDATE** on `businesses` (BH-001 Q6,
  24 Sep 2026). `033` SECTION 5 replaced it with a **26-column grant** that
  still contains `plan_tier`, `is_active`, `feature_flags`, `limits` and
  `subscription_status` — the same hole, one layer down, and invisible to
  `role_table_grants`. **The column grant itself is unverified in production**
  (BH-001's column export was truncated before reaching the table), so P0-3 is
  open-pending-one-query, not confirmed. `audits/BH-001-FINDINGS.md` §3.1

## RC1 P0-8 — policy inventory COMPLETE; grant coverage INCOMPLETE (24 Sep 2026)

**Live RLS and policy state is established. Grant state is not, and three
access findings came out of the data.** P0-8 asked for RLS, policy *and* grant
state; two of the three are answered. Full interpretation, including what is
still unverified, in **`audits/BH-001-FINDINGS.md`**. Six read-only exports from
`oxblcmwhuwtobdhsfgyi`, committed as `audits/BH-001-prod-Q*-2026-09-24.csv`;
full interpretation in **`audits/BH-001-FINDINGS.md`**. Summary:

- **58 tables; 56 have RLS on with at least one policy.** The two that do not
  are both correct — `zz_033_flags_backup` (RLS off, but no grant to `anon` or
  `authenticated`, so unreachable) and `stripe_events` (RLS on with zero
  policies, which is deny-all on the client path and exactly what `030a`
  SECTION 4 did on purpose).
- **No table Q3 covers is RLS-off while a client role holds a grant.** The one
  RLS-off table, `zz_033_flags_backup`, sorts *beyond* Q3's truncation point,
  so its grants are **unverified** — the invariant cannot yet be stated
  database-wide (FINDINGS §1).
- **87 policies, complete** (every per-table count matches Q1, not just the
  total). 77 **reference** `is_business_member` / `business_members` /
  `is_platform_admin` — which is a text match, not proof of enforcement: one of
  the 77 (`support_articles_member_read`) requires no membership at all. The
  remaining ten are self-scoped on `auth.uid()`, catalogue reads, or a
  published-article read — enumerated in FINDINGS §2.
- **Three `USING (true)` policies exist; all three are on catalogue tables
  with no `business_id`.** Review 001 finding 6 was right that a permissive
  `true` defeats isolation while satisfying a count — so each one was checked
  individually, and none is on a tenant table.
- **One policy has no explicit `WITH CHECK`** —
  `businesses."Platform admins can manage all businesses"`, which is `ALL`, and
  PostgreSQL falls back to its `USING` expression, so it is not a defect. (The
  first reading of this said "none", because the export writes NULL as the
  literal string `null`.) No policy permits a write it cannot also authorise.
- **The July audit's SEC-02 and SEC-03 are closed.** The `USING (true) FOR ALL`
  policies on `xero_connections` and `accounting_connections` — the OAuth token
  tables — are gone from production.
- **Production's policy TEXT matches the migration-defined local replay**
  BH-003's RLS suite runs against — 87 of 87 on command, roles, permissive,
  `USING` and `WITH CHECK`, identical after documented normalisation; zero
  differences across all 58 tables. Evidence:
  `audits/BH-001-prod-vs-local-policy-diff.txt`. **Text equivalence is not
  behavioural equivalence:** every membership policy is a call into
  `is_business_member()`, and `030a` changed that function's behaviour without
  changing one policy expression. FINDINGS §2.1 states the limits.

### Three access findings from the data (FINDINGS §6)

1. **Inactive members can still read `calls` and `tasks`.** Each table carries
   two permissive SELECT policies, and the older one omits `bm.is_active`.
   Permissive policies OR together, so the stricter one cannot narrow it: a
   deactivated member — an employee who left — keeps reading. Two `DROP POLICY`
   statements fix it; the stricter policies already exist.
2. **`TRUNCATE` is granted to `anon` on 46 tables** and `authenticated` on 48.
   **RLS does not constrain `TRUNCATE`**, so for those tables the row policies
   are not a second gate. No exposed route to it is known; the grant is still
   real authority on the public key.
3. **`oauth_tokens` is member-accessible**, where the July audit recorded it
   `deny-auth`. Any member of the owning business has `ALL` on its OAuth token
   rows. Possibly deliberate; materially different from the documented posture.

### Still open, and the two that matter

1. **Column grants are unverified.** The Q3 and Q4 exports were both truncated
   at 100 rows, and Q4 never reached `businesses` — so **whether
   `authenticated` still holds 033's 26-column UPDATE grant (RC1 P0-3, the
   paywall hole) is unresolved.** Q6 shows no *table-level* UPDATE, which is
   consistent with 033 having converted it to a column list; `role_table_grants`
   cannot see column grants. FINDINGS §3 has the one query that settles it.
2. **Two views are readable by `anon` and cannot carry RLS.**
   `receptionist_call_stats` groups by `business_id`, so it plausibly discloses
   per-tenant call volumes to anyone holding the public anon key. The inventory
   query below filters `relkind = 'r'` and **cannot see views** — which is why
   it took until now to find. FINDINGS §5 has the confirming query and the fix.
3. Constraints are covered by no export, including the UNIQUE on
   `stripe_events.event_id` that BH-006's de-duplication depends on.

**The `create_all()` trap is confirmed live.** Q5: default privileges in
`public` grant everything (`arwdDxtm`) to `anon` and `authenticated`, so a new
SQLModel class ships a publicly readable *and writable* table. FINDINGS §4 has
the one-statement change that makes it fail safe.

---

## The inventory query, and why inventory is not enough

Kept because it is still the right first query, and because its limits are
what the findings above turn on. **It answers the inventory half only** —
table, RLS flag, policy count — and review 001 finding 6 is right that
inventory is not isolation evidence: a single permissive `USING (true)` policy
satisfies a non-zero count while defeating isolation entirely. It is also
`relkind = 'r'`, so **it cannot see the two views in §2 above.** P0-8 needed
all of this too:

- **policy expressions** — `pg_policy.polqual` and `polwithcheck`, not just
  the count
- **which roles and commands** each policy applies to (`polroles`, `polcmd`)
- **table grants** for `anon` and `authenticated`
  (`information_schema.role_table_grants`), since RLS is only the second gate
- **column grants**, collected separately from
  `information_schema.column_privileges` — `role_table_grants` does not carry
  them, and a column-level grant can expose a field on a table whose
  table-level grant looks clean
- **default privileges** (`pg_default_acl`), which decide what a *new* table
  gets — the `create_all()` trap
- **negative tests executed as each role**: authenticate as business A and
  attempt to read business B, and record the failure

Start with the inventory:

```sql
SELECT c.relname AS table_name,
       c.relrowsecurity AS rls_enabled,
       count(p.polname) AS policies
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_policy p ON p.polrelid = c.oid
 WHERE n.nspname = 'public' AND c.relkind = 'r'
 GROUP BY 1, 2
 ORDER BY c.relrowsecurity, 1;
```

Until it is answered, no honest statement about tenant isolation is
possible, and **this document must not claim one.**

**Also absent:** any automated tenant-isolation test, on either path
(`docs/RC1_SCOPE.md` P0-9). Roles beyond owner/member/platform-admin are
undesigned; the compliance module will need a portal-style user type that
does not exist (`audits/COMPLIANCE-MODULE-BRIEF.md` D5).
