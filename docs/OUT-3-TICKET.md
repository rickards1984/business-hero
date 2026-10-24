## TICKET OUT-3

**Outcome** Tenant-safe, approval-first outreach persistence for the core pilot, with Postgres tests reviewed before migration implementation.

**Current evidence** `docs/OUT-2-CONTRACTS.md` §5 specifies the schema and §6 F01/F02 specify tenant/authority boundaries; its final “AUTO owner's agreement” and “Independent review — Claude Code”, dated 19 October 2026, govern the split and test-first sequence. `backend/migrations/035_aria_actions.sql:80` currently permits only four non-outreach action types. `backend/migrations/007_email_accounts_messages.sql:9` creates accounts with no unique default index. `backend/services/metering.py:149` implements atomic generic meter increments, `:224` locks usage; no second monthly counter is authorised. `scripts/rls-local.sh` previously replayed through 033/030b only. These are checkout facts, not live catalogue evidence.

**Scope** Stage A changes only this packet, `backend/tests/test_outreach_schema_rls.py`, and `scripts/rls-local.sh`. Stage B, after Mike approves the tests and Claude reviews scope, writes **`backend/migrations/037_outreach_core.sql`**, with the 17 tables listed below, composite keys/FKs, CHECKs, indexes, RLS and minimum grants; extends the shared action-type CHECK and adds the audited default-account index. No migration SQL is written in Stage A. Authority metadata remains schema-versioned `aria_actions.payload` JSON, as AUTO agreed; no authority columns or second permission engine.

**Non-goals** No model registration/create_all, APIs, tools, provider access, sender rewrite, automatic grants, data import, billing/Stripe changes, production access, deployment, commit or push. Deferred schemas are explicitly listed below. No direct model client or external send. No reads under `~/.openclaw`.

**Dependencies** OUT-1 approved decisions; OUT-2 final owner agreement and binding review. Coordinate migration 037 with Claude's single AUTO queue before Stage B. AUTO-1 integration is reconciled before service work; AUTO-2 supplies complete inbox freshness to OUT-7. OUT-4 supplies tenant-scoped Aria read projections and grounding tests before any new dataset is exposed or populated by application features (North Star §8). OUT-13 remains a gate for real PII import/launch.

**Affected systems** Backend tests, local Supabase replay, future Postgres schema. No frontend or third-party behaviour changes in Stage A.

**Security & data risk** **RED**: schema, RLS, grants and action authority boundaries. This instruction authorises only the test-first Stage A. Mike reviews tests before any Stage B migration SQL. Independent Claude review required; staging rehearsal, bounded rollback, live catalogue verification and each production action remain separately authorised. Tests use synthetic data and rollback on loopback only.

**Acceptance criteria**

1. Exactly the listed 17 new tables; every table has UUID PK, non-null tenant FK, created/updated UTC timestamps and `UNIQUE(business_id,id)`. RLS enabled in the creation transaction; revoke default client grants first. Safe rows allow member SELECT only; no blanket platform-admin policy. Browser writes and all anon privileges denied, including column grants and inherited privileges. Backend needs no automatic TRUNCATE grant.
2. Composite references reject foreign tenants even on the elevated backend path. Mailbox/message, campaign/mailbox and enrolment/campaign/prospect/step identities are bound together, not merely independently tenant-valid. Parent campaign mailbox is immutable after dispatch. Polymorphic daily scope must equal its business or an owned email account.
3. Enumerations and count/score/cap bounds are enforced; reviewed count cannot exceed eligible count; approved compliance requires reviewer/date; claimed live outbound requires mailbox/action. One pending/active enrolment per prospect across campaigns, one suppression per versioned key, one operation per idempotency key, and all §5 parent/identity unique keys hold. Paused history and distinct tenants remain permitted.
4. `aria_actions` accepts `send_outreach` and `reply_outreach`, preserves all four old types and all existing statuses, and rejects unknown types. No migration updates/deletes invoice-chase payloads, settings, approval records or status. Stage B compares pre/post snapshots of synthetic legacy chase rows, including executing rows and NULL approvers. Stage A's coexistence test is not proof of migration preservation.
5. Monthly allowance is enforced solely through `services/metering` / `usage_meters`; usage events settle operations idempotently and daily aggregates enforce daily caps only. See flow below.
6. Default-account audit precedes cleanup/index; Mike chooses every ambiguous default. Zero defaults are reported, never repaired by recency; general sends later fail closed on missing defaults. Campaign mailbox remains explicit. No account is selected by creation/update time.
7. Replay appends 034/035 and optional 037 without changing historical indexes, expected-error traps or existing comments; pruning preserves their policies. Missing 037 does not skip the Postgres tests. With URL unset, tests skip cleanly in `check.sh`.

**Required tests** `backend/tests/test_outreach_schema_rls.py`: F01 actual authenticated A/B SELECT and anon/browser denial, elevated cross-tenant FK rejection; F02 database write/claim/authority forgery boundary; §5 RLS/grants, tenant parent keys, state/count bounds, identity/idempotency uniqueness, mailbox binding, default uniqueness and legacy action compatibility. Additional §5 portions of F04/F07/F09 are included where they are database invariants. Test docstrings identify their rule. F01 API/tool/worker ID checks and deferred integration/import IDs belong to OUT-4/5/10. F02 NULL-user registration, fresh grant/revision/expiry validation, per-kind settings merge, bespoke reply authority and revocation races are OUT-6/AUTO service tests, not JSON CHECKs; no claim that Stage A covers them. Reply-slot F17 belongs to OUT-7. Valid seed graphs are positive controls; negative tests require specific constraint SQLSTATE classes, not arbitrary database errors.

**Verification** Stage A: `PYTHONDONTWRITEBYTECODE=1 ./check.sh`, `bash -n scripts/rls-local.sh`, `git diff --check`. Claude, outside this sandbox: `scripts/rls-local.sh up`, then `scripts/rls-local.sh test`; targeted suite: `RLS_LOCAL_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54329/postgres PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_outreach_schema_rls.py -v`. Before 037, missing tables/keys and rejected outreach action types must be red, never skipped or xfailed. Stage B: the targeted suite must pass after replay; `./check.sh full` before any later push, independently reviewed RLS policy baseline update, staging parity/rollback and before/after chase preservation evidence. No Docker/Postgres/network execution in this sandbox.

**Likely files** Stage A: exactly the three scope files above. Stage B: `backend/migrations/037_outreach_core.sql`, dedicated production runbook and approved catalogue/policy evidence (separate scope approval).

**Builder** Codex.

**Reviewer** Claude Code (scope, test review, independent security review; Claude commits). Mike approves the RED tests and subsequent production actions.

**Branch** `ticket/OUT-3-outreach-schema`, isolated worktree `/Users/michaelrickards/dev/bh2-OUT-3`.

**Budget band** L for complete OUT-3; Stage A bounded to packet/tests/replay only.

**Max repair cycles** 3, then escalate.

**Completion evidence** `PYTHONDONTWRITEBYTECODE=1 ./check.sh` exited 0: TypeScript, Python compilation, Ruff and pytest passed; eslint skipped because no lint script exists. Final pytest result: 1,844 passed, 234 skipped (201 new OUT-3 cases), 220 subtests passed, 1,629 warnings. `bash -n scripts/rls-local.sh` and `git diff --check` passed. No Docker, Postgres, network, commit or push. The check created an empty untracked `data.db` absent at initial status; that zero-byte test artifact was removed. Only the three authorised files remain changed. No production/staging evidence claimed.

**Status** in review — Stage A only; Stage B awaits Mike's test approval.

**North Star** P4 (owner approval) and P9 (sealed business), Actions & permissions pillar; security, tenant isolation and correctness prerequisites. New data remains inactive until OUT-4's scoped tools ship.

### Exact creation list and deferrals

| New table | Browser SELECT | Purpose |
| --- | --- | --- |
| `outreach_brands` | Member only | Brand identity/default mailbox |
| `outreach_settings` | None | Pause/limits; safe summary via OUT-4 |
| `outreach_mailboxes` | None | Mailbox health/warm-up operational state |
| `outreach_prospects` | Member only | Shared tenant prospect identity |
| `outreach_evidence` | Member only | Sanitized bounded evidence only |
| `outreach_compliance` | Member only | Versioned LIA decisions |
| `outreach_campaigns` | Member only | Explicit campaign mailbox/versions |
| `outreach_batch_reviews` | None | Version-bound first-batch review records |
| `outreach_sequence_steps` | None | Versioned approved templates |
| `outreach_enrolments` | None | Prospect sequence state |
| `outreach_messages` | None | Sensitive payload/authority/provider ledger |
| `outreach_replies` | Member only | Sanitized reply classification and resolution |
| `outreach_suppressions` | None | Tenant-keyed suppression digests |
| `outreach_unsubscribe_tokens` | None | Stored token bindings, never plaintext |
| `outreach_dispatch_jobs` | None | Durable logical operation uniqueness |
| `outreach_daily_usage` | None | Locked business/mailbox daily caps |
| `outreach_usage_events` | None | Per-operation metering settlement ledger |

The review's core list has 16 tables; **the one justified addition is `outreach_usage_events`**, explicitly required by that same review's second condition as the ledger beneath generic meters. Keeping it with messages/dispatch/daily usage avoids untracked reservations and a second allowance counter. No other table moves forward. Sensitive messages and operational records stay backend-only; OUT-4 exposes redacted, bounded projections.

Deferred: OUT-5 `outreach_import_runs`, `outreach_import_items`; OUT-7 `outreach_knowledge`, `outreach_reply_slots`; OUT-10 `outreach_integrations`, `outreach_research_jobs`, `outreach_provider_usage`. Their optional FK columns on core tables are **omitted until their owning migration**, not added as unenforced UUID references. `knowledge_refs` is bounded versioned JSON pending OUT-7; it grants no authority. No import or provider feature is enabled by this schema.

Existing tables receive verified `UNIQUE(business_id,id)` keys where absent: **`email_accounts`, `aria_actions`, `email_outbox`, `email_messages`**. Mailbox-identity parent keys also include `(business_id,email_account_id,id)` where referenced by mailbox-bound children. Equivalent campaign/enrolment/step keys bind the multi-field relationships. `mailbox_id` always means `email_accounts.id`, not `outreach_mailboxes.id`.

Test fixture spellings resolve §5 shorthand for review: `campaign_version`, `fact_value`, `next_due_at`, `to_emails`, `cc_emails`, `payload_version`, `period_start`, `period_end`, `local_send_date`, `local_date`. They are proposed schema names, not claims about existing columns. Stage B must implement the approved contract or return a concrete discrepancy for review, never adapt tests to permit a weaker constraint. Enumerations left implicit by §5 need a complete agreed list in Stage B; current fixtures use `stage=new`, `state=pending/active/paused`, `kind=initial`, reply `resolution=pending`, and job `status=pending`.

### One monthly allowance source

OUT-4/6 extend the existing `services/metering` boundary using `usage_meters` tenant/meter/UK-calendar-period identity. `outreach_prospects_researched` counts completed evidence bundles (including no-fit) once; `outreach_emails_sent` counts accepted initial/follow-up/bespoke sends once. Entitlement provides 200 researched prospects / 500 accepted emails per business per month, shared across brands/mailboxes. No independent monthly totals in outreach settings, daily usage or event aggregation may authorise work. **[Superseded for emails by OUT-18 part C, 25 Oct 2026: the monthly email allowance is per brand — its daily limit × the month's UK weekdays — enforced from the brand's usage events; the business-wide sent/held meters remain for reporting and billing. See docs/OUT-18-TICKET.md.]**

The OUT-6 shared pre-claim hook locks the generic meter/reservation capacity with business/day/mailbox scope, records a unique event and claims the action in **one transaction**, with no intervening commit. Generic metering owns used/reserved/remaining allowance; the event ledger identifies and settles each reservation exactly once. Daily usage is solely a locked aggregate for mailbox/business day caps, reconciled from events. Definite pre-dispatch failure releases; acceptance commits once; unknown holds until reconciliation, never lease-expiry release. An unclaimed operation crossing month boundaries rebooks; dispatched work settles its original period. Provider credits/costs are separate and deferred to OUT-10. Founder exemptions are verified entitlement, never business-name rules. Exact service APIs and meter reservation names are OUT-6, not invented by this migration.

### Default-account runbook step — read-only audit first

Before the partial unique index is added, the separately authorised runbook confirms the project selector (production `oxblcmwhuwtobdhsfgyi`, rehearsal `gzcrsrqmygublveuzqyg`) and live schema. Then run this **read-only audit**, including businesses with no accounts:

```sql
SELECT b.id AS business_id,
       count(e.id) AS account_count,
       count(e.id) FILTER (WHERE e.is_default IS TRUE) AS default_count,
       coalesce(array_agg(e.id ORDER BY e.id)
                FILTER (WHERE e.is_default IS TRUE), '{}'::uuid[]) AS default_account_ids
FROM public.businesses AS b
LEFT JOIN public.email_accounts AS e ON e.business_id = b.id
GROUP BY b.id
HAVING count(e.id) FILTER (WHERE e.is_default IS TRUE) <> 1
ORDER BY b.id;
```

Archive results and Mike's explicit account-ID decisions. UUID ordering is display only, never selection. Zero defaults and multiple defaults need explicit disposition; no newest-account fallback. Cleanup writes are a separate RED action with before/after evidence. Re-run the audit before the index; unresolved duplicate defaults block it. A zero-default tenant can remain explicitly disconnected/blocked; an at-most-one partial index cannot guarantee exactly one. AUTO owns atomic set-default and the four sender fixes; this ticket does not rewrite them. Coordinate index ownership with Claude so it is added once, after the audit.

### Review gates and known verification limits

- Claude confirms the usage-events addition, test column spellings/implicit enums, 037 queue and default-index ownership before Stage B. Shared AUTO infrastructure must replace equivalent job storage if it has landed; no parallel scheduler is authorised.
- Replay now preserves 035/037 policies during ghost pruning. The existing `test_every_policy_matches_its_reviewed_definition` in `test_tenant_isolation_rls_path.py` pins **86 policies** and compares approved CSVs which do not include 035/037. It must fail until separately reviewed policy evidence is updated. These files are outside Stage A's allowed three-file scope; do not suppress that failure or prune legitimate new policies to make it pass.
- These tests run after replay. They do not prove 037 preserves pre-existing rows across execution. Stage B must seed representative invoice-chase actions/outbox rows before 037, snapshot complete rows/settings, apply it, and compare byte-for-byte logical values afterward; rehearse rollback against the same data.
- No real Postgres run occurred here. All new tests are expected to skip without `RLS_LOCAL_DATABASE_URL`; green `check.sh` therefore cannot prove constraints, RLS, replay success or schema compatibility. Claude runs and reviews the red suite before Mike's approval. No app behaviour changed: Mike opens this packet and the test file for the RED test review; there is nothing new to click in the app.

- Additional replay discrepancy for Claude: `scripts/rls-local-expected-errors.txt:11–12` tolerates 007 finding the 006 `email_outbox` table already present and missing `email_account_id`. Confirm the replay's final shape against the live-catalogue evidence before Stage B adds mailbox/outbox composite keys. The outbox-reference test deliberately requires the current `EmailOutbox` model's mailbox-bound columns; it does not hide missing columns with a skip or dynamically weaken its seed. Any baseline repair is outside this three-file Stage A and must be reviewed separately.

### Claude's scope review of Stage A — 19 October 2026

- **Scope.** Codex changed only its three files. I renumbered the migration from 036 to **037**: 036 is AUTO-2's `chase_replies`, and there is one queue. The replay now applies 036 and 037 whenever each exists, and `rls-local.sh test` runs every `test_*rls*.py` suite.
- **Ran on Postgres, outside the sandbox.** I ran `scripts/rls-local.sh up`, which replays 034 and 035 with every expected error matched exactly. Then:
  - the outreach suite is **red as intended** (42 failed, 37 passed, 154 errors), with every failure due to missing 037 objects;
  - the tenant isolation suite failed only on 035's `aria_actions_member_read`, as Codex predicted.
- **Baseline fix (Claude, a separate commit).** I added that policy to `audits/BH-003-rls-policies-post-july.csv`, with its provenance, and raised the pinned count to 87. The isolation suite is now 32/32 green.
- **For Stage B:**
  - build the new `UNIQUE(business_id,id)` keys on live tables (especially `email_messages`) with `CREATE UNIQUE INDEX CONCURRENTLY`, then `ADD CONSTRAINT … USING INDEX`, so syncing never blocks;
  - run the default-account audit query before the partial unique index, as the ticket says.

### Claude's review of Stage B — 19 October 2026

Codex built the following:
- `037_outreach_core.sql`;
- `audits/037-PROD-RUNBOOK.md`;
- six policy renderings;
- the reconcile step that brings the replay's `email_outbox` to the live-dump shape (repair cycle 1).

**I ran it all on the local Supabase Postgres replay, outside the sandbox:**
- **Replay:** 141 expected errors, every count exact, with 037 applied cleanly.
- **Tests:** `test_outreach_schema_rls.py` plus `test_tenant_isolation_rls_path.py` gave **233 passed**. Every approved Stage A test passes, and the isolation suite pins **93** reviewed policies; Codex's six renderings match `pg_policies` exactly.
- **Test fix:** one harness fix in the Stage A test file. Its seed helper `add(name, **values)` collided with tables that have a `name` column, so it is now `add(name, /, **values)`. No test's meaning changed.
- **Re-paste:** the whole file pasted again exits 0, with "already exists, skipping" notices only.
- **Rollback:** both STEP 9 blocks run, giving 0 outreach tables, 87 policies, the original 4-type `aria_actions_type_chk`, no `out3` keys and no outreach functions. That matches the before-state exactly.
- **Security read:**
  - `authenticated` gets SELECT only, on six tables, through member policies;
  - `service_role` gets no TRUNCATE;
  - neither trigger function is SECURITY DEFINER, and both pin `search_path`;
  - every table revokes from anon and authenticated first.

**Still open before production (in the runbook):**
- STEP 0's key and duplicate checks. Staging's email tables have no primary keys (found by the 036 rehearsal).
- The default-account audit gate.
- Migration 036 (AUTO-2) runs first.
