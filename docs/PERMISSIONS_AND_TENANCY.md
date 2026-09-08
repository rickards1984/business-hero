# Permissions and tenancy — STUB, and one open question

**Status: stub, blocked on evidence.**

Analysis is in `docs/CURRENT_STATE.md` §4. The essential points:

- Backend bypasses RLS; isolation is application-layer `WHERE business_id`
- Frontend uses the anon key and is subject to RLS
- Admin and customer are the **same** Postgres role (`authenticated`), and
  grants are evaluated before RLS — so a column grant to an admin is a grant
  to every customer
- `authenticated` retains table-wide UPDATE on `businesses` until `030b`
  Release 2 lands (`docs/RC1_SCOPE.md` P0-3)

## The open question — RC1 P0-8

**Live RLS, policy and grant state is UNKNOWN.** The July 2026 audit listed
~30 tables with RLS off (`audits/AUDIT-2026-07-04.md` Appendix B). Three
migrations have landed since. The schema dump carries no policy data.

**This cannot be answered from the repository.** It needs a read-only
evidence packet against `oxblcmwhuwtobdhsfgyi`. The query below is the
**inventory** half — table, RLS flag, policy count — and review 001 finding 6
is right that inventory is not isolation evidence: a single permissive
`USING (true)` policy satisfies a non-zero count while defeating isolation
entirely. P0-8 is not satisfied by this query alone. It must also capture:

- **policy expressions** — `pg_policy.polqual` and `polwithcheck`, not just
  the count
- **which roles and commands** each policy applies to (`polroles`, `polcmd`)
- **table and column grants** for `anon` and `authenticated`
  (`information_schema.role_table_grants`), since RLS is only the second gate
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
