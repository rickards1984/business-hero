# BH-001 — Codex review (ORIGINAL, UNEDITED)

| | Review 1 |
|---|---|
| Commit | `c83abc8` (on `main` @ `fe672a2`) |
| Session | `01a0d518-615a-7aa1-bfb0-207ffdb533d9` |
| Tokens reported | 88,069 |
| Verdict | REQUEST-CHANGES — 9 items, all taken |

Reviewer: Codex CLI 0.153.4, `gpt-5.6-sol`, ChatGPT auth, read-only, no
database. It parsed all six exports independently with Python's `csv` module
and reproduced the prod-vs-local comparison against BH-003's committed census.

**It found two access findings the first version missed entirely**, and both
are now §6.1 and §6.2 of the findings:

1. **Inactive members can still read `calls` and `tasks`.** Each table carries
   two permissive SELECT policies and the older one omits `bm.is_active`.
   Permissive policies OR together, so the stricter policy cannot narrow it —
   a deactivated member keeps reading. Verified against Q2.
2. **`TRUNCATE` is granted to `anon` on 46 tables**, and PostgreSQL excludes
   `TRUNCATE` from row-level security. So for those tables the row policies
   this report spends a section confirming are not a second gate.

**And it caught five claims that went past the evidence**, the worst being
mine about the RLS-off table: I wrote that Q3 confirms no client grant on
`zz_033_flags_backup`, and `zz` sorts BEYOND Q3's truncation point, so the
export cannot say that. The headline invariant built on it is now qualified.

It also corrected: "byte-identical" (it is identical after documented
normalisation, and text equivalence is not behavioural equivalence — 030a
changed what membership means without changing any policy text, which is the
decisive counterexample); "77 gate on membership" (a text match — one of the
77 requires no membership); "no policy lacks a WITH CHECK" (one does, and my
check missed it because the export writes NULL as the literal string `null` —
the CSV trap this very ticket warns about); the default-privileges remedy
(`ALTER DEFAULT PRIVILEGES` without `FOR ROLE` changes only the executing
role's defaults, and Q5 shows two creator roles, plus sequence and function
defaults a TABLES-only revoke leaves behind); and 53 → 54 tables lacking
COMPLETE column coverage, since Q4's fifth table is partial.

Two further residual findings it asked for are now §6.3 and §6.4:
`users_link_self` never pins the new `user_id` to `auth.uid()`, and
`oauth_tokens` is member-accessible where the July audit recorded it
`deny-auth`.

Every item was verified against the CSVs before being accepted.

---

## REVIEW 1 — c83abc8

Reviewed `main..HEAD` at `c83abc8`, parsing all six exports with Python’s `csv` module. No database connections, file edits, or `check.sh` runs.

The core census is accurate, but several safety conclusions exceed the evidence, and the report misses material findings.

| Claim | Independent result |
|---|---|
| 58 tables; 56 with RLS and policies | Correct. One RLS-off table; one RLS-on table without policies. All `rls_forced` flags are false. |
| 87 policies; Q1 counts sum to 87 | Correct. **Every per-table count also matches Q2**, not just the total. |
| 77 membership policies; ten exceptions | The ten named exceptions are correct as a **text classification**. “77 gate on membership” overstates what those expressions require. |
| Three `USING(true)` policies | Correct: the three identified catalogue SELECT policies. Absence of `business_id` is schema evidence, not something Q2 establishes. |
| No INSERT/UPDATE policy lacks WITH CHECK | Correct for the four explicit INSERT and six explicit UPDATE policies. Incomplete when considering `ALL` policies; the read-back conclusion does not follow. |
| SEC-02/SEC-03 closed | The specific unrestricted policies are gone, and the reported replacement definitions are correct. This establishes removal of those policy defects, not verified token confidentiality. |
| Q3/Q4 truncation | Both contain exactly 100 records. Q3 ends at `support_stats / anon`; Q4 ends at `accounting_transactions.amount / authenticated`. Neither resolves the missing `businesses` column grants. |
| Q6 grants | Accurately reported, including authenticated `TRUNCATE` and absence of table-level UPDATE. |
| Local equivalence | Independently reproduced against BH-003’s committed census at `5e1aaf7`: 87 normalized policy matches, including `permissive`; all 58 inventory records and Q6 grants match. This is **catalogue-text equivalence**, not demonstrated behavioural equivalence. |

**VERDICT: REQUEST-CHANGES**

1. **Withdraw the unsupported “rollback table is safe” and database-wide invariant claims.**  
   [FINDINGS §1](/Users/michaelrickards/dev/bh2-BH-001-census/audits/BH-001-FINDINGS.md:27) says Q3 confirms no grants on `zz_033_flags_backup`. It cannot: that table sorts beyond the truncated export. Migration 033 is historical intent, not current production evidence. Mark its grants—and therefore “no RLS-off table has a client-role grant”—unverified.

   `stripe_events` is different: it sorts **inside** Q3’s covered range and is absent, supporting absence of the queried direct grants. Its RLS-on/zero-policy state is independently established. Also qualify the assertion that every table is owned by `postgres`: Q1 does not export ownership.

2. **Add the missed inactive-member access finding.**  
   Q2 contains both:
   - `calls."Members can select calls for their businesses"` without `bm.is_active`, alongside `calls_select_if_member` with it.
   - `tasks."Members can select tasks for their businesses"` without `bm.is_active`, alongside `tasks_select_if_member` with it.

   All four are permissive. The broader policy therefore allows a matching **inactive** membership to satisfy SELECT; the newer policy cannot narrow it. `business_members.users_view_own` also permits users to see their own inactive membership. Q3 confirms authenticated SELECT on `calls`; `tasks` grants remain outside its range. Record the policy defect for both, distinguishing that grant-evidence difference. PostgreSQL combines permissive policies with OR. [PostgreSQL RLS documentation](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

3. **Narrow the conclusion drawn from the successful local comparison.**  
   [§2.1](/Users/michaelrickards/dev/bh2-BH-001-census/audits/BH-001-FINDINGS.md:71) should say **identical after documented normalization**, not byte-identical. Role sorting is appropriate here, and mapping the export’s exact null sentinel is reasonable. Unconditional whitespace collapsing is unsafe generally because it also changes quoted literals and identifiers; the observed production literals do not reveal such a collision, but retain raw captures or use SQL-aware normalization.

   Include `permissive` explicitly in the comparison contract—I checked it and it matches—and pin the local evidence commit and capture.

   Most importantly, identical calls to `is_business_member()` or `is_platform_admin()` do not establish identical function bodies, security settings, ownership, or execution privileges. Migration 030a actually changes membership behaviour **without changing policy text**, demonstrating this exact gap. Add helper functions, role attributes/membership, and referenced-object definitions to the equivalence limitations. Existing limits concerning grants, constraints, views, and auth/storage are appropriate, but insufficient. BH-003 supports production conclusions only subject to these unresolved dependencies.

4. **Keep the views finding urgent but conditional, and strengthen its confirming query.**  
   [§5](/Users/michaelrickards/dev/bh2-BH-001-census/audits/BH-001-FINDINGS.md:184) correctly reproduces anon SELECT for both objects; authenticated grants are also captured for `receptionist_call_stats`. The general owner/invoker explanation is substantially correct: ordinary views have no independent table RLS, and underlying permissions/RLS normally use the view owner.

   However, production definitions, owners, options, dependencies, and write triggers/rules are absent from these CSVs. The staging evidence cannot establish that production returns every tenant’s aggregates. The shown SQL is abbreviated, not executable view-definition evidence; label it accordingly.

   The §5.1 query is valid and genuinely read-only, but **not sufficient** for its binary “confirmed/closed” conclusions. Add `relkind` and `pg_get_viewdef`, then inspect underlying relations/functions and their security properties. An invoker view can still call a SECURITY DEFINER function; an owner-context view can contain its own filtering. Materialized views also need separate treatment.

   Aggregates prevent **automatic** updatability, but INSTEAD OF triggers/rules can permit INSERT/UPDATE/DELETE. Therefore “writes fail” needs evidence; TRUNCATE is separately inapplicable to ordinary views. The proposed severity ordering is reasonable **if the stated production definitions and exposure are confirmed**. [PostgreSQL CREATE VIEW documentation](https://www.postgresql.org/docs/current/sql-createview.html)

5. **Add the missed RLS-independent grants finding.**  
   Q3 shows `TRUNCATE` on **46 ordinary tables for anon and 48 for authenticated**. Q6 independently confirms authenticated TRUNCATE on `businesses`; Q3 also shows it on `business_members`. These privileges are not constrained by RLS.

   This does **not** prove an unauthenticated HTTP truncation exploit: an executable SQL/RPC route, constraints, and other prerequisites matter. It does invalidate treating all broad grants as harmless whenever row policies exist. Record the database authority and unresolved reachability separately. [PostgreSQL explicitly excludes TRUNCATE and REFERENCES from RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

6. **Correct the default-privileges remedy and ACL interpretation.**  
   [§4](/Users/michaelrickards/dev/bh2-BH-001-census/audits/BH-001-FINDINGS.md:157) correctly identifies dangerous defaults for tables created in `public` by **both** `postgres` and `supabase_admin`. But the proposed statement changes defaults only for the executing role.

   The remedy must explicitly cover the intended creator roles, for example:

   ```sql
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres, supabase_admin
     IN SCHEMA public
     REVOKE ALL ON TABLES FROM anon, authenticated;
   ```

   Its execution authority must be established in the separate runbook. Calling this RED and a separate ticket is correct. It changes future objects, not existing grants. [PostgreSQL default-privileges documentation](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html)

   Also, `arwdDxtm` includes **MAINTAIN (`m`)**, omitted from the report’s decoding. Q5 additionally shows public-schema sequence privileges and function EXECUTE defaults for both client roles; table-default revocation does not address those. Record them as additional exposure surfaces requiring interpretation, not proven exploits. Remove “the database is currently clean” and qualify the boot-time conclusion by the actual object-creating role. [PostgreSQL privilege definitions](https://www.postgresql.org/docs/current/ddl-priv.html)

7. **Correct the policy classification and WITH CHECK inference.**  
   [§2](/Users/michaelrickards/dev/bh2-BH-001-census/audits/BH-001-FINDINGS.md:41) counts 77 expressions containing membership/admin references. But `support_articles_member_read` permits published articles **without** membership or admin status. Say “77 reference these mechanisms,” or classify actual predicates separately.

   `businesses."Platform admins can manage all businesses"` is `ALL` with a NULL explicit WITH CHECK. That is not automatically unsafe: PostgreSQL falls back to its USING expression. Conversely, merely having a WITH CHECK does not establish that a resulting row is readable. Remove that implication and correct the inherited packet explanation of NULL checks. [PostgreSQL policy semantics](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)

8. **Record two further access findings instead of calling the remaining policies benign.**  
   Q2’s `business_members.users_link_self` checks the invite email but never requires the new `user_id = auth.uid()`. Even the intended two-column grant would permit assigning the pending membership to another UUID, subject to constraints/triggers not exported. The grant mitigates changing tenant/role; it does not prove “link self.” Record this residual concern separately from the known cross-tenant pivot.

   Also, Appendix B describes `oauth_tokens` as “deny-auth,” whereas Q2 now gives authenticated members an `ALL` policy and Q3 supplies SELECT/INSERT/UPDATE/DELETE. This is a material difference from the historical security description. Describe member access to token rows and whether it is intended; do not silently subsume it under healthy coverage.

9. **Retain P0-3 as unresolved, refine Q4b’s scope, and reconcile the documentation.**  
   [§3](/Users/michaelrickards/dev/bh2-BH-001-census/audits/BH-001-FINDINGS.md:98) is right: **no other CSV settles the entitlement-column UPDATE question**. Q4b is valid, read-only, and sufficient to inspect the named direct authenticated column grants without the 100-row problem. It is not, by itself, proof of all effective access paths or readiness to execute Release 2. An absent UPDATE result does not establish who revoked it or when.

   Q4 covers four complete table prefixes and only two columns of its fifth table. Consequently, **54 tables lack complete column-grant coverage**, not merely 53.

   Apply the corrections throughout both edited docs. In particular, [PERMISSIONS_AND_TENANCY.md:12](/Users/michaelrickards/dev/bh2-BH-001-census/docs/PERMISSIONS_AND_TENANCY.md:12) still asserts table-wide authenticated UPDATE, directly contradicted by Q6. Replace “P0-8 ANSWERED” with a status acknowledging that policy inventory is complete while grant coverage and the identified safety questions remain incomplete.