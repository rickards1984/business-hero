# 030b Release 2 — Codex reviews (ORIGINAL, UNEDITED)

| | Review 1 |
|---|---|
| Commit | `23a5bf0` (tree identical to `1b141b2`) |
| Session | `01a0b634-ca67-7c31-9d5b-a3b662258b3a` |
| Tokens reported | 86,674 |
| Verdict | REQUEST-CHANGES — 6 items, all taken |

Reviewer: Codex CLI 0.153.4, `gpt-5.6-sol`, ChatGPT auth, sandboxed to the
worktree, read-only, no database, no network. Ran STEP 3's grep and its own
searches for RPCs, REST URLs and non-literal table names independently.

What changed in response, by item: (1) STEP 0 gained 0d/0e/0f — effective
column privileges via `has_column_privilege`, client-callable SECURITY
DEFINER functions mentioning `businesses`, views over `businesses` —
each with EXPECT from staging and a STOP IF; STEP 7 now tests all five
entitlement columns. (2) STEP 3 is four checks: multi-line chains, every
`.rpc(`, raw `rest/v1/businesses`, non-literal `.from(`. (3) The RLS
suite and `scripts/rls-local.sh` are on PR #9's branch; the runbook and
migration now say so instead of implying `main`. (4) ROLLBACK 1 and 2 are
executable SQL in the runbook. (5) STEP 7's ad hoc GRANT is gone —
stop, save, compare, report; STEP 9 requires evidence of causation before
any rollback. (6) Section 2 requires Mike's explicit approval in so many
words; STEP 0 stops on any UPDATE column set other than exactly the 26.

---

## REVIEW 1 — 23a5bf0

I reviewed commit `23a5bf0` against parent `fb80454`. The current branch HEAD is `1b141b2`, but its tree is identical to `23a5bf0`. No database connection, edits, or `check.sh` run.

1. SQL correctness

Section 1’s direct-table protection is correct:

- `REVOKE INSERT, UPDATE` removes both table-level and column-level privileges, covering all five sensitive columns ([030b_release2_revoke.sql:71](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/030b_release2_revoke.sql:71)).
- Dropping `biz_update_if_owner` removes the now-unreachable owner policy ([030b_release2_revoke.sql:73](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/030b_release2_revoke.sql:73)).
- The remaining admin `ALL` policy does not help an ordinary owner, and without an UPDATE grant even a platform admin cannot update directly through PostgREST.

Repository inspection found no alternate writer:

- The only frontend RPC is `whoami` ([DebugPanel.tsx:45](/Users/michaelrickards/dev/bh2-030b-release2/frontend/client/src/components/DebugPanel.tsx:45)); its SECURITY DEFINER body only returns identity data ([028_baseline_live_state.sql:460](/Users/michaelrickards/dev/bh2-030b-release2/supabase/migrations/028_baseline_live_state.sql:460)).
- The other repository SECURITY DEFINER functions are read-only membership/admin checks.
- No SQL view is defined in the repository.
- No stored function in the repository writes `businesses`.
- The four literal frontend `from('businesses')` calls are reads.

However, the runbook does not prove that the live database lacks a drifted SECURITY DEFINER RPC, granted updatable view, PUBLIC/inherited column privilege, or another live-only bypass. Repository files are explicitly non-authoritative for live state. For this RED migration, that is a blocking verification gap.

2. Rollback correctness

The rollback’s 26 columns exactly match 033 Section 5 ([033_entitlement.sql:718](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/033_entitlement.sql:718), [030b_release2_revoke.sql:116](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/030b_release2_revoke.sql:116)). It correctly excludes `metered_usage_enabled` and `monthly_spend_cap_gbp`.

The recreated policy is equivalent to the original definition at 028 lines 597–601 ([028_baseline_live_state.sql:597](/Users/michaelrickards/dev/bh2-030b-release2/supabase/migrations/028_baseline_live_state.sql:597), [030b_release2_revoke.sql:124](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/030b_release2_revoke.sql:124)).

Ordering is safe:

- Apply order is revoke, then drop. The intermediate state still has the policy but no grant.
- Rollback restores the grant before the policy. During that interval, RLS deny-by-default prevents an ordinary owner from updating; only the existing platform-admin policy can authorize a write.
- If executed as one transaction, no intermediate state is externally visible.

Operationally, though, `ROLLBACK 1` is only commented SQL. Instructions such as [030b-PROD-RUNBOOK.md:251](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:251) say to paste it from the migration file, but literally pasting the block executes nothing. A RED rollback should be present as executable SQL in the runbook.

3. Runbook and STOP IF review

There are several unsafe or incomplete instructions:

- STEP 6 can falsely pass in a bad state. Its `column_privileges` query filters `grantee='authenticated'` ([030b-PROD-RUNBOOK.md:226](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:226)). A PUBLIC or inherited UPDATE privilege on, for example, `is_active` could remain while 1b returns zero. STEP 7 tests only `plan_tier` and `feature_flags`, not all five sensitive columns.
- STEP 7 instructs an ad hoc production `GRANT SELECT` if SELECT fails ([030b-PROD-RUNBOOK.md:289](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:289)). Section 1 cannot remove SELECT; that result means unexpected state or concurrent change. The correct instruction is stop and investigate against the snapshot, not improvise another RED mutation.
- STEP 9 asserts that failures in checks 3–6 mean a write still uses the anon-key path and orders rollback ([030b-PROD-RUNBOOK.md:333](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:333)). Those checks could fail for unrelated backend, authentication, or deployment reasons. It should stop, preserve evidence, and roll back only when the revoke is confirmed causal.
- STEP 6 says to roll back and then “re-run this step” while simultaneously expecting STEP 0 values ([030b-PROD-RUNBOOK.md:247](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:247)). STEP 6’s written EXPECT is the post-apply state, so the instruction is internally inconsistent.

The staging record supports the grant/policy apply, role tests, idempotency, and rollback comparisons ([030b-STAGING-REHEARSAL.md:14](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-STAGING-REHEARSAL.md:14)). It does not establish live RPC/view absence or browser behavior, although the record itself does not claim that it ran the browser smoke tests.

There is also a false repository claim: both the migration and STEP 10 refer to `backend/tests/test_tenant_isolation_rls_path.py` and four strict xfails ([030b_release2_revoke.sql:24](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/030b_release2_revoke.sql:24), [030b-PROD-RUNBOOK.md:340](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:340)). That file does not exist. Neither does `scripts/rls-local.sh`, which STEP 10 instructs the operator to run.

4. Table-wide versus 26-column UPDATE

The 26-column grant is correct per migration 033. `docs/CURRENT_STATE.md` is stale where it says “table-wide UPDATE” ([CURRENT_STATE.md:338](/Users/michaelrickards/dev/bh2-030b-release2/docs/CURRENT_STATE.md:338)).

The runbook safely handles both known possibilities:

- It expects the 26-column state.
- If production still has table-level UPDATE, STEP 0 explicitly stops because the supplied rollback would not restore that pre-state ([030b-PROD-RUNBOOK.md:103](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:103)).

It should similarly state explicitly that any smaller or otherwise different UPDATE column set is also a stop; the current detailed STOP list only names “more than 26” and the two forbidden columns, although the global EXPECT rule implies exact matching.

5. Optional Section 2

The technical separation is clean. Applying only Section 1 closes the INSERT/UPDATE hole while leaving DELETE, TRUNCATE, and REFERENCES unchanged. The migration and runbook explicitly state that skipping Section 2 leaves the spec’s “SELECT and TRIGGER only” VERIFY unmet ([030b_release2_revoke.sql:57](/Users/michaelrickards/dev/bh2-030b-release2/backend/migrations/030b_release2_revoke.sql:57), [030b-PROD-RUNBOOK.md:296](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:296)).

Because Section 2 is an additional RED production grant change, “Decide before pasting” is insufficient. It must say not to apply Section 2 without Mike’s explicit approval for that action.

6. Frontend pre-check

I ran STEP 3 exactly. It produced no output, exit status 1 as expected.

I also searched separately for:

- All frontend `.from(...)` calls: no dynamic table argument was found.
- All frontend `.rpc(...)` calls: only `whoami`.
- REST paths containing `rest/v1/businesses`: none.
- Multiline literal `from('businesses') … update/insert/upsert/delete` chains: none.

Thus the current repository has no client-side write to `businesses`.

But STEP 3’s grep is not adequate evidence: it only sees a mutation when `from('businesses')` happens to fall within four preceding context lines, and it does not search RPCs, direct REST calls, aliases, or dynamic table names ([030b-PROD-RUNBOOK.md:153](/Users/michaelrickards/dev/bh2-030b-release2/audits/030b-PROD-RUNBOOK.md:153)).

VERDICT: REQUEST-CHANGES

1. Add live, read-only pre-checks for effective `authenticated`/PUBLIC/inherited INSERT and UPDATE privileges on every `businesses` column, callable SECURITY DEFINER functions/RPCs that can reach `businesses`, and granted writable views depending on `businesses`. Extend post-apply role verification to all five sensitive columns.
2. Replace STEP 3’s four-line-context grep with explicit checks covering multiline direct writes, every `.rpc(` call, direct PostgREST URLs, and non-literal `.from(...)` arguments.
3. Remove or correct the claims about the nonexistent `test_tenant_isolation_rls_path.py`, its four xfails, and nonexistent `scripts/rls-local.sh`; add the promised regression test/harness before relying on them.
4. Put executable, directly pasteable `ROLLBACK 1` SQL and an unambiguous rollback verification sequence in the runbook.
5. Replace STEP 7’s ad hoc `GRANT SELECT` and STEP 9’s unconditional causal diagnosis with stop-and-investigate instructions grounded in the saved before-snapshot.
6. Require Mike’s explicit approval before optional Section 2 is applied, and explicitly STOP for any production UPDATE grant shape that differs from the exact 26-column snapshot—not only larger grants.