# Foundation review 001 — Codex report (ORIGINAL, UNEDITED)

Everything below the rule is exactly what Codex returned. Nothing has been
added, removed, softened or reordered. Claude Code's response to these
findings is a separate document (`FOUNDATION-REVIEW-001.md`) — do not edit
this file to reflect fixes; supersede it with a new review instead.

| | |
|---|---|
| Reviewed commit | `3a388f98762a59084efa6de3f64afe94ce8ce0dc` |
| Comparison base | `9826f61a6ccf998877fc333018b78b6b14bef466` (origin/main) |
| Reviewer | Codex CLI 0.153.4, model `gpt-6-astra`, ChatGPT auth |
| Session id | `01a0826c-0d1d-7923-ac5c-be30ecef8bb9` |
| Invocation | `codex exec -s workspace-write -c approval_policy="never"` |
| Worktree | `~/dev/bh2-foundation-review`, detached at the reviewed commit |
| Started / ended | 2026-09-08T19:08:34Z / 19:12:41Z (~4m07s) |
| Process exit | 0 |
| Verdict | **REQUEST-CHANGES** |

---

## 1. Reviewed commit

Reviewed detached HEAD **`3a388f98762a59084efa6de3f64afe94ce8ce0dc`** against **`9826f61a6ccf998877fc333018b78b6b14bef466`**, covering `7e01b8b`, `d60a46b`, and `3a388f9`.

Read `AGENTS.md` first, then the required documents, changed policy/harness files, and relevant backend implementations. No source edits, commits, pushes, deployments, network calls, or live/staging database connections. Final git status was clean.

## 2. Verification results

| Command | Outcome |
|---|---|
| `git rev-parse HEAD` | Exact reviewed SHA confirmed |
| `git status --short` / `git status --porcelain` | Clean before and after |
| `git log --oneline 9826f61..3a388f9` | Three specified commits |
| `git diff --stat 9826f61..3a388f9` | 22 changed files |
| `git diff --check 9826f61..3a388f9` | Passed |
| `env -u DATABASE_URL -u SUPABASE_DATABASE_URL SQLITE_DATABASE_URL='sqlite:///:memory:' npm_config_offline=true ./check.sh full` | **Passed:** 382 tests, 104 subtests, 20 warnings; five preflight traps passed; ESLint skipped |
| `env -u DATABASE_URL -u SUPABASE_DATABASE_URL SQLITE_DATABASE_URL='sqlite:///:memory:' .venv/bin/python -m pytest backend/tests/test_entitlement_defaults.py backend/tests/test_entitlement_reads.py backend/tests/test_schema_conformance.py -q` | **96 passed**, 19 warnings |
| `node --version`; `.venv/bin/python --version`; `.venv/bin/python -m ruff --version`; `.venv/bin/python -m pytest --version` | Node **22.22.2**, Python **3.12.14**, ruff **0.16.6**, pytest **9.1.1** |

Additional read-only verification used `cat`, `sed`, `nl`, `git diff`, `git ls-files`, and repository-wide `rg` searches for push rules, migration classification, old paths, gates, metering, invoice endpoints, Stripe writes, and `BH-001`.

Two `.venv/bin/python - <<'PY'` probes executed extracted repository code entirely in memory:

- **Stripe handler, mocked dependencies:** a deletion event carrying an old Pro price changed `business → pro`; delivering the identical event twice performed **two business writes**.
- **Accounting SELECT, SQLite fixtures:** querying Business A’s transaction returned **Business B’s category name** through a cross-business category reference.

These probes establish code behavior, not production exploitability.

## 3. Findings

### Confirmed

1. **MAJOR — CI can still report success without proving all required checks ran.**  
   `.github/workflows/ci.yml:71` checks only for explicit `SKIP ruff` and `SKIP pytest` strings. `check.sh:57` can skip the entire backend without emitting either; `check.sh:98` treats unavailable preflight as a successful skip. Locally, missing ruff/pytest also permits green.  
   **Fix:** make mandatory checks fail closed in `check.sh`; allow only explicitly optional ESLint skipping. Assert required successful steps rather than absence of two skip strings.

2. **MAJOR — The remote gate has coverage gaps and overstates equivalence.**  
   `.github/workflows/ci.yml:16` excludes feature-branch pushes before a PR exists. `scripts/preflight.sh:72` and `:88` compare against `origin/main`; on a push-to-main checkout that comparison is empty, so changed-file checks inspect nothing. Missing comparison refs also fail open.  
   **Fix:** trigger verification for builder branches, supply an event-appropriate comparison base, and fail when the base cannot be resolved. Correct `docs/CURRENT_STATE.md:77` until remote execution is evidenced.

3. **MAJOR — Runtime alignment is incomplete.**  
   `.github/workflows/ci.yml:32` and `:38` select Node 20/Python 3.11, versus verified local Node 22/Python 3.12. `frontend/client/package-lock.json:856` declares **Node ≥22** for Capacitor CLI. Backend dependencies remain largely unpinned in `requirements.txt:1`. Matching ruff/pytest alone does not establish equivalent environments.  
   **Fix:** align supported runtimes and dependency resolution, or explicitly test/document a compatibility matrix. The Node mismatch is confirmed; an actual CI installation failure is **not** established.

4. **MAJOR — Stripe correctness and deduplication claims are false.**  
   `docs/CURRENT_STATE.md:297` says tiers change only when prices change; `:381` says events are deduplicated. `backend/main.py:988` processes created, updated **and deleted** subscriptions identically, assigning the tier at `:1012` without testing for a price change. Event recording happens **after committed business mutations**, at `:1025`. Both problems were reproduced with the extracted handler.  
   **Fix:** correct the baseline and explicitly include price-change discrimination, stale/replayed events, and atomic deduplication in P0 Stripe acceptance criteria.

5. **MAJOR — Accounting contains an application-layer tenant-isolation defect omitted from the baseline.**  
   `backend/accounting.py:300` accepts `category_id` without verifying category ownership. At `:200`, the transaction query joins categories by ID alone; the tenant filter applies only to transactions. The local SQL probe returned B’s category metadata while querying A.  
   **Fix:** validate category ownership on create/update/bulk-update and scope category joins by business. Add a two-business regression test and record this under P0-9. Live constraint protection remains unverified.

6. **MAJOR — The proposed RLS evidence query cannot answer its stated question.**  
   `docs/PERMISSIONS_AND_TENANCY.md:25` returns table names, RLS flags, and policy counts. It does not inspect policy expressions, applicable roles/commands, table/column grants, or default privileges. One permissive policy can defeat isolation while looking satisfactory here.  
   **Fix:** expand P0-8’s evidence packet to include those properties and role-based negative tests. Policy counts are inventory, not isolation evidence.

7. **MAJOR — Entitlement acceptance criteria contradict the canonical plan matrix.**  
   `audits/ENTITLEMENT-SPEC.md:211` requires Starter rejection on every protected endpoint; `:541` explicitly requires quoting rejection. But `backend/auth.py:291` grants Starter quoting, accounting, email and Aria text chat. Also, `docs/RC1_SCOPE.md:50` calls board meetings ungated despite `backend/executive_meeting_api.py:51` and subsequent calls enforcing a server-side tier gate.  
   **Fix:** specify expected access per feature, subscription status and override. Describe board meetings as inconsistently gated, including missing canonical override/status handling.

8. **MAJOR — The founder decision introduces contradictory instructions and unchecked completion claims.**  
   `audits/ENTITLEMENT-SPEC.md:448` resolves MSC to Business and New Body to Pro, but `:469` still requires Business on both. At `:450` and `:455`, allowances and thresholds are described as already exercised/live, despite no backend metering implementation. Read-only scope also differs between `:301` and `:352`.  
   **Fix:** reconcile the acceptance criteria and distinguish decisions from implemented, observed behavior.

9. **MINOR — The old-path correction is incomplete: 032 is not established as a completed production record.**  
   `audits/032-PROD-RUNBOOK.md:366` retains `~/Documents/business-hero-2`. Its header records **staging rehearsal**, while `audits/live-schema-public.txt:479` and `:588` still show the non-null tax columns that 032 would change.  
   **Fix:** update the executable path or explicitly archive the runbook as superseded. Preserving historical 030a/031 commands is defensible; treating 032 the same way is unsupported by repository evidence.

10. **MINOR — Surviving policy and status inconsistencies undermine the “one source of truth” claim.**  
    `docs/OPERATIONS_AND_RELEASE.md:9` still says “Mike pushes,” although its immediate context is main, so this is ambiguous rather than an unequivocal feature-branch prohibition. `CLAUDE.md:39` instructs agents not to re-derive audit conclusions, conflicting with verification discipline. `docs/CURRENT_STATE.md:178` leaves the master-key consumer check open while `:452` closes it.  
    **Fix:** use the exact feature-branch/main rule consistently, qualify audit reuse by current evidence, and reconcile duplicated status statements.

11. **MAJOR — The new pre-push hook does not verify the actual pushed revision.**  
    `.githooks/pre-push:23` reads pushed SHAs only to detect deletion, then checks the current working directory at `:44`. Pushing another local ref, or testing with uncommitted fixes, can verify different content from the pushed commit.  
    **Fix:** restrict pushes to the verified clean HEAD or verify each pushed revision in isolation. Weaken `docs/DEVELOPMENT_WORKFLOW.md:97`’s absolute guarantee until this is enforced.

### Suspicions requiring further evidence

- The RC1 journey’s final “accounting sync” may imply outbound publication of locally created invoices. Inspected sync code is oriented toward importing provider data; no `create_invoice`/`push_invoice` implementation was found. Define the direction before treating this journey as covered.
- No production cross-tenant exploit or actual GitHub CI failure was demonstrated.

## 4. Entitlement vs tenant isolation

**Entitlement:** may this business use this feature?  
**Isolation:** may this caller access this business’s records?

The reviewed voice, chat, quoting and WhatsApp paths resolve authenticated business context. For example, `backend/realtime_voice.py:659` verifies the token and `:667` resolves membership; `backend/assistant_chat.py:475` checks active membership for a requested business. Their missing plan checks establish **entitlement/spend gaps**, not automatically cross-tenant access.

Receptionist settings and board meetings already have server-side gates, but inconsistent mechanisms. Missing metering, subscription-status enforcement, and customer-editable entitlement fields are monetisation/privilege risks.

Finding 5 is different: **another tenant’s category metadata can cross the application-layer boundary**. Adding `require_feature` would not repair it. Backend RLS cannot be assumed to rescue an elevated connection.

The single `require_feature("email")` call site and absence of executable metering references were confirmed.

## 5. CI enforcement judgement

The rewrite is a meaningful improvement: ruff is blocking, the shared full command runs, full history is fetched, and pipeline failure propagation is present.

It is **not yet an equivalent, comprehensive remote gate**:

- Feature pushes without PRs receive no run.
- PR events trigger checks; main pushes trigger checks after main changes.
- Changed-file preflight checks need an explicit event base.
- Mandatory skips remain possible.
- Runtime/dependency parity is unproven.
- Required branch protection cannot be established from workflow YAML.

## 6. RC1 boundary challenge

The contractor money journey is a coherent starting point, but its dependencies need correction:

- **P1-8 contains P0 tax behavior.** Non-registered-business VAT correctness is an explicit release criterion at `docs/RC1_SCOPE.md:254`; move that slice into the P0 money path.
- Define **subscription-status access alongside P0-1**, before applying gates everywhere. Placing it after metering encourages implementing the same access decisions twice.
- P0-3 must precede any claim that enforcement is effective.
- PDF/manual-invoice work may proceed independently, but both need the same entitlement, read-only and tax acceptance contract.
- Define accounting-sync direction and an actual quote/invoice export deliverable for unpaid customers.
- Full receptionist metering broadens the “smallest contractor edition”; retain it only with an explicit decision that receptionist service ships in RC1.

**BH-001 is absent from the reviewed tree.** If intended as P0-8, evidence gathering is the right first ticket—but use the expanded evidence requirements in finding 6. A concrete ticket packet is still needed.

## 7. UNVERIFIED

- Live/staging schemas, constraints, RLS, grants and applied migration state: database access prohibited.
- GitHub run results, branch protection and required checks: network prohibited.
- Clean CI installs and Node 20/Python 3.11 compatibility: not executed.
- Deployed behavior, Stripe delivery/coupons, Twilio caps/releases, Railway configuration and external-consumer claims: external access prohibited.
- Browser journeys and visual rendering: no browser execution performed.
- Production exploitability of finding 5: requires authorized constraint inspection and a controlled two-business integration test.

## 8. VERDICT

**REQUEST-CHANGES**

To reach approval: repair the CI/hook guarantees, reconcile the contradictory policies and entitlement decisions, correct unsupported baseline claims, and update RC1 tickets/dependencies to include the confirmed Stripe and isolation defects.

The foundation need not implement all RC1 work before approval. It must accurately identify that work and provide a trustworthy verification gate.