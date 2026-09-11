# BH-001 — Establish live RLS, policy and grant state

The ticket packet for RC1 **P0-8**, plus the exact read-only inspection for
Mike to run. Format per `AGENTS.md` §6.

**ID check:** `BH-001` is unused — no branch, no commit, no other document
claims it (`BH-000` is the template placeholder in `AGENTS.md`; `BH-004` is an
illustrative example in `docs/DEVELOPMENT_WORKFLOW.md`). BH-002 was numbered
first because the accounting leak was urgent; ticket numbers are identifiers,
not an order of work.

---

## TICKET  BH-001

| Field | Value |
|---|---|
| **Outcome** | The live RLS, policy and grant state of `oxblcmwhuwtobdhsfgyi` is known and written down, so that any statement about tenant isolation is evidence-backed rather than inferred. |
| **Current evidence** | `docs/CURRENT_STATE.md` §"RLS coverage — **unknown**"; `audits/AUDIT-2026-07-04.md` Appendix B lists ~30 tables with RLS off; three migrations have landed since and `audits/live-schema-public.txt` carries no policy data. `AGENTS.md` §3.4: migration files are not evidence of live state. |
| **Scope** | Run the read-only inspection below against production; commit the raw output to `audits/`; update `docs/PERMISSIONS_AND_TENANCY.md` and `docs/CURRENT_STATE.md` §4 to state what is actually true. |
| **Non-goals** | Changing any policy, grant or table. Enabling RLS anywhere. Fixing what the inspection finds — that is the follow-up ticket, scoped once the answer exists. No schema change of any kind. |
| **Dependencies** | None. This is the first ticket precisely because everything about isolation is currently inference. |
| **Affected systems** | Production database (read-only), plus two documents. No code. |
| **Security & data risk** | **RED** — it is production. Every statement is `SELECT` against catalog and `information_schema` views; nothing reads a customer row, and nothing writes. RED because of where it runs, not what it does. Per `AGENTS.md` §2, **Mike executes it**; no agent connects. |
| **Acceptance criteria** | ☐ Every query below has been run and its raw output saved. ☐ Every `public` table is classified: RLS on with policies / RLS on with none / RLS off. ☐ Every policy has its expression recorded, not just a count. ☐ Table **and** column grants to `anon` and `authenticated` are recorded. ☐ Default privileges are recorded. ☐ `docs/PERMISSIONS_AND_TENANCY.md` no longer says "unknown". ☐ Anything the inspection cannot answer is written down as still-unknown rather than assumed benign. |
| **Required tests** | None in this ticket — it changes no code. The negative tests belong to **BH-003** (below), which must not be folded in here. |
| **Verification** | `./check.sh full` for the documentation commit. The database evidence is the raw query output, committed verbatim. |
| **Likely files** | `audits/BH-001-live-rls-state.txt` (new), `docs/PERMISSIONS_AND_TENANCY.md`, `docs/CURRENT_STATE.md` §4. |
| **Builder** | Claude Code (documents only) — **Mike runs the queries.** |
| **Reviewer** | Codex |
| **Branch** | `ticket/BH-001-live-rls-state` |
| **Budget band** | S |
| **Max repair cycles** | 3 |
| **Completion evidence** | *(builder fills in)* |
| **Status** | **proposed** — awaiting Mike's approval and execution |

---

## The read-only production inspection

**For Mike to run.** Supabase SQL editor, project selector reading
**`oxblcmwhuwtobdhsfgyi`** — confirm that first (`AGENTS.md` §3.5: two
projects exist and staging is `gzcrsrqmygublveuzqyg`).

Every statement is a `SELECT` against `pg_catalog` / `information_schema`.
None reads a customer record. None writes. Safe to run at any time, including
during traffic.

Export each result **as CSV**, not by copying the grid — and per
`audits/033-PROD-RUNBOOK.md` STEP 24b, do not rebuild the CSV with `grep`:
policy expressions contain commas, and a naive line filter drops exactly the
rows that matter.

### Q1 — Inventory: which tables have RLS, and how many policies

```sql
SELECT c.relname                         AS table_name,
       c.relrowsecurity                  AS rls_enabled,
       c.relforcerowsecurity             AS rls_forced,
       count(p.polname)                  AS policy_count
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_policy p ON p.polrelid = c.oid
 WHERE n.nspname = 'public' AND c.relkind = 'r'
 GROUP BY 1, 2, 3
 ORDER BY c.relrowsecurity, c.relname;
```

**Purpose.** The census. **How to read it:** three categories, and the middle
one is the trap.

- `rls_enabled = false` → **publicly reachable** on the frontend path.
  `anon`/`authenticated` hold broad grants (`AGENTS.md` §3.8), and with RLS
  off there is no second gate. Every such table is a finding.
- `rls_enabled = true, policy_count = 0` → RLS on with no policy **denies
  everyone** on the anon path. Not a leak; a potential outage. It also means
  the frontend cannot be relying on this table.
- `rls_enabled = true, policy_count > 0` → **proves nothing yet.** Q2 decides.
- `rls_forced` matters for table owners, who otherwise bypass their own RLS.

### Q2 — What each policy actually says

```sql
SELECT c.relname                              AS table_name,
       p.polname                              AS policy_name,
       CASE p.polcmd WHEN 'r' THEN 'SELECT' WHEN 'a' THEN 'INSERT'
                     WHEN 'w' THEN 'UPDATE' WHEN 'd' THEN 'DELETE'
                     ELSE 'ALL' END           AS command,
       p.polpermissive                        AS permissive,
       COALESCE(
         (SELECT string_agg(r.rolname, ', ' ORDER BY r.rolname)
            FROM pg_roles r WHERE r.oid = ANY(p.polroles)),
         'PUBLIC')                            AS applies_to_roles,
       pg_get_expr(p.polqual,      p.polrelid) AS using_expression,
       pg_get_expr(p.polwithcheck, p.polrelid) AS with_check_expression
  FROM pg_policy p
  JOIN pg_class c     ON c.oid = p.polrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
 ORDER BY c.relname, p.polname;
```

**Purpose.** This is the query the old inventory-only version could not
answer, and the reason P0-8 was not satisfiable before. **How to read it:**

- `using_expression` of `true` — or anything not constraining
  `business_id` — is a policy that **satisfies a policy count while providing
  no isolation.** Treat as equivalent to RLS off.
- `with_check_expression` NULL on an INSERT/UPDATE policy means reads are
  constrained but **writes are not**: a tenant can write a row it will not be
  able to read back, including into another tenant's scope.
- `applies_to_roles = PUBLIC` applies to `anon` too.
- `permissive = false` (restrictive) policies AND together; permissive ones
  OR together — **one permissive `true` defeats every restrictive policy on
  the table.**
- Expect expressions referencing `auth.uid()` and a `business_members`
  lookup. An expression referencing only `auth.role()` is authentication, not
  tenancy.

### Q3 — Table grants (the gate evaluated *before* RLS)

```sql
SELECT table_name, grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
  FROM information_schema.role_table_grants
 WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
 GROUP BY table_name, grantee
 ORDER BY table_name, grantee;
```

**Purpose.** Grants are checked first; RLS only narrows what a grant already
allows. **How to read it:** `UPDATE` on `businesses` for `authenticated` is
the known open item (RC1 P0-3, `030b` Release 2) — it lets a customer edit
their own entitlement fields, so confirm whether it is still there. Any
`INSERT`/`UPDATE`/`DELETE` to `anon` is a finding on its own.

### Q4 — Column grants (not covered by Q3)

```sql
SELECT table_name, column_name, grantee,
       string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
  FROM information_schema.column_privileges
 WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')
 GROUP BY table_name, column_name, grantee
 ORDER BY table_name, column_name, grantee;
```

**Purpose.** `role_table_grants` does not carry column-level grants. **How to
read it:** a column grant on a table whose table-level grants look clean is
still a grant. Because admin and customer share the `authenticated` role
(`docs/CURRENT_STATE.md` §4), *a column granted for the admin UI is granted to
every customer.* Look hardest at `businesses` and `business_members`.

### Q5 — Default privileges (what a *new* table inherits)

```sql
SELECT n.nspname AS schema, d.defaclobjtype AS object_type,
       pg_get_userbyid(d.defaclrole) AS granted_by,
       d.defaclacl AS default_acl
  FROM pg_default_acl d
  LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
 ORDER BY 1, 2;
```

**Purpose.** `create_all()` runs at every boot and creates new tables with
**RLS off and default grants** (`AGENTS.md` §3.3). This says what "default
grants" means here. **How to read it:** if defaults grant to `anon` or
`authenticated`, then every new SQLModel class ships a publicly reachable
table, and the `create_all()` trap is not theoretical.

### Q6 — Does `businesses` still carry the open UPDATE grant?

```sql
SELECT grantee, privilege_type
  FROM information_schema.role_table_grants
 WHERE table_schema = 'public' AND table_name = 'businesses'
 ORDER BY grantee, privilege_type;
```

**Purpose.** Answers RC1 P0-3 directly, and it is the single most
consequential row in this packet. **How to read it:** `authenticated` +
`UPDATE` present means a customer can change their own `plan_tier` or
`feature_flags` directly, and **server-side entitlement enforcement is
defeated regardless of how good the gates are.** If present, P0-3 must
precede any claim that P0-1 is effective.

---

## What is NOT in this request, deliberately

Mike's instruction: anything needing writes or a test account is separate, and
runs in an isolated test environment — never against production.

**BH-003 — executed negative tests (not yet written).** The evidence packet
above is *static*: it says what the rules are, not what the database does when
someone tries. The negative tests — authenticate as business A, attempt to read
and write business B, record the refusal — need **two test businesses with real
auth sessions**, which means creating accounts and writing rows. They belong on
a staging or local Supabase instance (`gzcrsrqmygublveuzqyg`, or a local
`supabase start`), never on `oxblcmwhuwtobdhsfgyi`.

Folding them into BH-001 would turn a safe read into a production write. Kept
apart on purpose.

RC1 **P0-9** (the automated two-path isolation test) and **P0-9a** (the
confirmed accounting leak, fixed on `ticket/BH-002-accounting-category-isolation`)
are also separate tickets, for the same reason.
