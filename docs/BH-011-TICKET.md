## TICKET BH-011 — finish server-side plan enforcement (RC1 P0-1)

**Outcome**  Every paid feature is refused AT THE API to a business whose
plan does not include it, through ONE mechanism — not by hiding buttons.

**Current evidence** (counted on `main` at `237348f`, 9 Oct 2026)
| File | Routes | Gate today |
|---|---|---|
| `backend/quoting_api.py` | 15 | **none** (`quoting`) |
| `backend/whatsapp_briefing_api.py` | 7 | **none** (`whatsapp`) |
| `backend/accounting.py` | 13 | **none** (`accounting`) |
| `backend/booking_api.py` | 3 | **none** (`calendar_booking`) |
| `backend/receptionist_api.py` | 14 | hand-rolled `_require_receptionist_flag` (`:306`) |
| `backend/executive_meeting_api.py` | 17 | second mechanism `services/tier_gating.require_tier_feature` (`board_meetings`), which still documents the removed `paused` tier |
Already gated by the canonical mechanism: email (`app/email/router.py:64`),
Aria chat/TTS (`main.py` `_assert_ai_access`), voice (`realtime_voice.py`),
invoice PDF (BH-009). `docs/CURRENT_STATE.md` §5; `RC1_SCOPE.md` P0-1;
`audits/ENTITLEMENT-SPEC.md` PART B and PART D.

**Serves**  RC1 P0-1 (security/money prerequisite: paid AI and paid
features are currently gated only in the browser).

**Scope — STAGE 1 (this run): tests and design only. RED (entitlement).**
Mike reviews the tests before implementation.
1. `backend/tests/test_plan_enforcement.py`: for EVERY route in the six
   files above, a test that a business without the feature is refused
   (403, nothing written, no provider called) and one with it is not
   refused by the gate. Enumerate routes from the routers themselves, so a
   route added later without a gate fails the suite. Strict xfail
   (`raises=` a specific exception type, as in BH-009) for the new behaviour.
2. A test that `require_tier_feature` and `_require_receptionist_flag`
   are gone (no call sites) once folded into `auth.require_feature` /
   `assert_feature_access`, and that the canonical feature names are used
   (`auth.CANONICAL_FEATURES`; board meetings = `board_meetings`).
3. `docs/BH-011-DESIGN.md`: the per-route mapping (route → feature),
   EXCEPTIONS with reasons (e.g. Twilio/WhatsApp inbound webhooks
   authenticated by signature, OAuth callbacks, read-only exports DECISION 3
   permits, any admin route), how read-only accounts behave per route
   (`auth.READ_ONLY_PERMITTED_FEATURES`), and the receptionist's existing
   stopgap flag on MSC/New Body (033 STEP 21) — does folding the gate in
   change what those two businesses can do?

**Sequencing**  Stage 2 (implementation) touches `quoting_api.py`, which
BH-010 (manual invoices) also changes. Stage 2 starts after BH-010 merges.
Stage 1 only adds files.

**Non-goals**  Metering (P0-2). Changing which tiers get which features
(`auth.PLAN_FEATURE_DEFAULTS` is Mike's). Frontend.

**Builder** Codex  **Reviewer** Claude Code  **Branch** `ticket/BH-011-plan-enforcement`
**Budget band** L  **Max repair cycles** 3
**Status** in progress — stage 1 (tests first)


## Stage 1 delivery — 9 October 2026

**Stage status** In review — Stage 1 tests/design complete; Mike reviews the
behaviour contract and Claude Code reviews the tests/design. Stage 2 is not
started or authorised by this completion entry and waits for BH-010 to merge.
The original ticket text above is retained.

**Delivered** `backend/tests/test_plan_enforcement.py` and
`docs/BH-011-DESIGN.md`. Discovery covers all 78 registered routes, including
nine admin routes omitted from the headline counts (the board admin route
was already counted). Tests cover per-route feature refusals and passage,
Starter defaults, explicit grants/denials, paid/read-only statuses, admin and
public exceptions, signed/forged WhatsApp webhooks, access-check metadata,
founder stopgap compatibility, legacy gate removal and canonical vocabulary.
New behaviour uses strict, exception-specific xfail. Runtime code is unchanged.

**Acceptance for this stage** Tests and mapping are reviewable; new routes fail
an unmarked inventory assertion; denied requests must have no domain I/O;
allowed requests prove gate passage only. Every exception and the limits of
that proof are documented. No real database or provider is used by these tests.

**Decisions awaiting Mike** Compound quote-action feature requirements;
downgrade/history retention versus whole-feature denial; denied signed webhook
403 versus a no-effects 200 acknowledgement. Full wording and evidence are in
the design. No current production access state was asserted for MSC/New Body.

**What Mike should click** Nothing changes in the UI in Stage 1. Review the
plain-English behaviour contract and open questions in the design. The design
lists the browser smoke checks for separately approved Stage 2 implementation.
`check.sh` does not establish visual, end-to-end or live-provider behaviour.

## Completion evidence

Interpreter: `/Users/michaelrickards/dev/business-hero-2/.venv/bin/python`
(the pre-existing worktree `.venv` symlink resolves there).

Targeted command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_plan_enforcement.py -q --tb=short`

```text
450 passed, 126 xfailed, 27 warnings in 3.02s
```

Verification command: `PYTHONDONTWRITEBYTECODE=1 npm_config_cache="$PWD/.npm-cache" npm_config_offline=true ./check.sh`

Exit code **0**. Exact check output:

```text
------------------------------------------------------------
  FRONTEND
------------------------------------------------------------
  PASS  tsc --noEmit
  SKIP  eslint  (no lint script in package.json)
------------------------------------------------------------
  BACKEND
------------------------------------------------------------
  PASS  python syntax (py_compile)
        All checks passed!
  PASS  ruff
            business.last_stripe_event_at = datetime.utcnow()
        
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_replayed_checkout_applies_once
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_checkout_is_recorded_in_the_audit_table
          /Users/michaelrickards/dev/bh2-BH-011/backend/main.py:1040: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
            business.last_stripe_event_at = datetime.utcnow()
        
        backend/tests/test_tenant_isolation_backend_path.py: 180 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default datetime adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)
        
        backend/tests/test_tenant_isolation_backend_path.py: 120 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default date adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)
        
        backend/tests/test_tenant_isolation_backend_path.py: 55 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default date converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()
        
        backend/tests/test_tenant_isolation_backend_path.py: 60 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default timestamp converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()
        
        -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
        1213 passed, 33 skipped, 126 xfailed, 812 warnings, 220 subtests passed in 8.64s
  PASS  pytest
------------------------------------------------------------
  4 passed   0 failed   1 skipped
  Green. Safe to proceed.
------------------------------------------------------------
```

Frontend dependencies were reused via an ignored worktree-local symlink to the
existing `business-hero-2/frontend/client/node_modules`; nothing was installed.
Temporary check logs/cache were removed after copying this evidence. No
implementation changes, network requests, production actions, commits or pushes.
Fast mode was requested and run; preflight/full was not run because no push is
being made. Existing warnings and skipped tests remain visible in the output.

---

## Stage 1 review — Claude Code (reviewer), 9 October 2026

Read the design note and the test approach in full. The route inventory is
derived from the routers and compared with an explicit list, so a new route
without a decision fails; xfails catch only the two named contract
exceptions; domain I/O is a hard sentinel, so "allowed" means the gate was
passed, nothing more — stated as such. **No defects; ready for Mike.**

One thing the design rightly could not settle, now partly settled:
**MSC and New Body's effective access.** Aria chat is gated by the same
canonical `assert_feature_access`, and Mike's Aria test on **New Body**
passed on 9 Oct, so New Body resolves to FULL access and folding the
receptionist gate changes nothing for it. **MSC is not verified** — one
Aria message on MSC, or one read-only query, settles it before Stage 2.

**CORRECTION (same day):** the paragraph above is wrong. Platform admins
bypass `_assert_ai_access` entirely, and Mike's account administers the
platform, so his Aria test proves nothing about New Body's access. Neither
business is verified. The read-only query in the design note's decisions
section settles both.

---

## Stage 2 — implementation (unblocked 10 Oct 2026: BH-010 merged)

Mike approved the Stage 1 tests and the decisions recorded in
`docs/BH-011-DESIGN.md` § "Decisions — Mike, 9 October 2026". The branch is
rebased onto `main` at `252d849` (BH-009 and BH-010 merged).

Build exactly the design, with these decision-driven changes:
1. **Downgrade history (decision 2):** define the history routes explicitly
   (board meetings + their messages/action items/goals; receptionist calls
   and stats; WhatsApp messages) as READ-ONLY readable when the feature is
   absent from the PLAN, refused when an admin set the flag explicitly
   `false` or the business is suspended. Tests first for both sides.
2. **Signed WhatsApp webhook, business without `whatsapp` (decision 3):**
   empty 200 with NO effects (no logging, no pending-action lookup or
   execution, no reply). Change the Stage 1 tests that encode 403 to match,
   and say so in Completion evidence.
3. Remove xfail markers as tests pass; fold `require_tier_feature` and
   `_require_receptionist_flag` into the canonical mechanism and delete them.
4. **MSC:** decision 2026-10-10 — the fix for MSC's suspended state is the
   Stripe founder coupon (DECISION 4), done by Mike. Folding the gate in must
   not be blocked on it, and must not special-case MSC.

Rules as before: no network, no production, no migration, no git
commit/push. Finish with `./check.sh full` and record the output.

**Status** in progress — stage 2 (implementation)


## Stage 2 Completion evidence

**Status** in review — implementation and local verification complete;
Claude Code review pending. No commit or push. The existing uncommitted Stage 2
instructions above were preserved. Serves RC1 P0-1, the North Star
security/money prerequisite.

**Implemented** Canonical gates in the six routers, compound quote-action
requirements, seven explicit retained-history exceptions, accounting AI GET
read-only refusal, and signed WhatsApp entitlement checks before any message
logging/action lookup/reply (denied business: empty 200). Deleted the tier-gate
module and receptionist helper. Access-check uses canonical access and keeps
advanced access/settings restricted to business/beta. Unknown feature names
fail closed. PLAN_FEATURE_DEFAULTS is unchanged (verified by AST comparison).
No frontend, migrations, production access, network requests, commits or pushes.
MSC has no special case; Mike's founder-coupon action remains separate.

**Tests first — observed before implementation**

Command (using the required interpreter):
`PYTHONDONTWRITEBYTECODE=1 /Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_plan_enforcement.py -q --tb=short`

```text
40 failed, 501 passed, 105 xfailed, 27 warnings in 3.55s
```

Each new decision test had failing cases in that run:

* `test_decision_history_is_retained_but_admin_denial_wins`: 63 cases across
  the seven named history routes, active/unpaid/canceled and no restriction /
  explicit false / suspension. 24 failed first: 18 missing history permissions
  and six WhatsApp admin-denial/suspension failures. Other cases already passed.
* `test_decision_starter_signed_webhook_acknowledges_without_effects`: both
  numbered-action and ordinary-message cases failed first by reaching logging.
* `test_decision_access_metadata_preserves_advanced_tiers`: Starter explicit
  grant and Business explicit denial failed first; the other three tier cases
  already passed. Response shape and advanced restriction are asserted.
* Updated Stage 1 `test_signed_webhook_denied_before_logging_action_or_reply`:
  all six cases failed first against the approved empty-200/no-effects contract.
  The original 403 expectation was deliberately replaced per decision 3.
* Updated Stage 1 Starter route matrix: six newly retained receptionist/board
  history reads failed first. WhatsApp history already passed before gating.

The remaining Stage 1 denied-feature, read-only, explicit-grant, metadata,
unknown-feature and legacy-gate assertions passed after implementation (105
strict XPASS results), then their markers were removed. `READ_ALLOWED` and the
Starter route matrix now include the seven explicitly approved history reads;
explicit false still denies all of them. No other Stage 1 permission expectation
was relaxed. Route inventory remains 78 and is not marked or bypassed.

**Additional regression coverage** The 24-case
`test_gate_checks_the_same_business_as_the_handler` failed first against the
initial dependency implementation, then passed after accounting/receptionist
used `assert_feature_access` on their existing resolved business. This avoids
checking a query-selected business while operating on a different one. Added
four advanced-settings filtering cases and two preview-before-cache cases;
these preservation tests passed when introduced, rather than being claimed as
new failing decision tests.

Final targeted result:

```text
676 passed, 24 warnings in 3.03s
```

**Full-suite repair** The first full check found 28 older-test failures:
accounting FakeBusiness fixtures lacked subscription fields, and seven
entitlement-read tests still called the now-deleted receptionist helper.
Updated `test_accounting_tenant_isolation.py` and
`test_tenant_isolation_backend_path.py` with active Starter business attributes;
updated `test_entitlement_reads.py` to call the canonical receptionist assertion
with an active synthetic business. No tenant-isolation assertion was removed
or weakened and no gate was mocked. Targeted rerun: 56 passed, 425 warnings.
The second full check passed.

**Verification command** (all temporary/cache paths kept inside this worktree;
pre-existing `.venv` and node_modules symlinks reused, no installs):

```bash
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.bh011-tmp" npm_config_cache="$PWD/.npm-cache" npm_config_offline=true ./check.sh full
```

Exit code **0**. Exact final check output:

```text
------------------------------------------------------------
  FRONTEND
------------------------------------------------------------
  PASS  tsc --noEmit
  SKIP  eslint  (no lint script in package.json)
------------------------------------------------------------
  BACKEND
------------------------------------------------------------
  PASS  python syntax (py_compile)
        All checks passed!
  PASS  ruff
            business.last_stripe_event_at = datetime.utcnow()
        
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_replayed_checkout_applies_once
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_checkout_is_recorded_in_the_audit_table
          /Users/michaelrickards/dev/bh2-BH-011/backend/main.py:1048: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
            business.last_stripe_event_at = datetime.utcnow()
        
        backend/tests/test_tenant_isolation_backend_path.py: 180 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default datetime adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)
        
        backend/tests/test_tenant_isolation_backend_path.py: 120 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default date adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)
        
        backend/tests/test_tenant_isolation_backend_path.py: 55 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default date converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()
        
        backend/tests/test_tenant_isolation_backend_path.py: 60 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default timestamp converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()
        
        -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
        1557 passed, 33 skipped, 809 warnings, 220 subtests passed in 9.36s
  PASS  pytest
------------------------------------------------------------
  PREFLIGHT (deploy traps)
------------------------------------------------------------
        
        TRAP 1 — requirements.txt sync
          PASS  every backend dep is present in root requirements.txt
        
        TRAP 2 — trailing newline on requirements.txt
          PASS  trailing newline present
        
        TRAP 3 — repo location
          PASS  repo is outside CloudStorage/Dropbox
        
        TRAP 4 — create_all() RLS drift warning
          PASS  no models.py changes on this branch
                comparison base: origin/main
        
        TRAP 5 — secret scan on staged/changed files
          PASS  no secret patterns in changed files
        
        PREFLIGHT PASSED — safe to push.
        
  PASS  preflight
------------------------------------------------------------
  5 passed   0 failed   1 skipped
  Green. Safe to proceed.
------------------------------------------------------------
```

Supplemental checks: `git -c core.whitespace=cr-at-eol diff --check -- backend docs/BH-011-DESIGN.md` passed
(WhatsApp's existing CRLF endings preserved; the verbatim check transcript above
retains its whitespace-only output lines); no frontend/migration changes;
PLAN_FEATURE_DEFAULTS AST unchanged; the preflight secret-pattern scan was
also applied to all uncommitted changed files and passed. Preflight traps 4/5
compare committed/staged paths, so that supplemental check matters here.
Temporary scripts/logs/cache were removed after recording this evidence.

**Unverified / review boundary** This is local synthetic request and unit-test
verification. Gate passage is not a full provider/database operation. No browser,
end-to-end, live Twilio, production founder-state or phone-callback smoke test was
run; background-job/call-site audit remains outside this six-router ticket.
Existing skips and deprecation warnings remain. Claude Code still reviews the
implementation; the builder is not approving this RED change.

**What Mike should click when reviewing behaviour in an authorised test setup**
Open Quotes and Accounting on Starter; view retained board/WhatsApp/receptionist
history after downgrade, then try settings, new meetings, sends and previews
(refused). Repeat with an explicit false or suspension (history refused). For
unpaid/canceled, view/download an existing quote and try editing/sending or
accounting AI insights (refused). These manual checks were not run here.

---

## Stage 2 review — Claude Code (reviewer), 10 October 2026

**Verdict: ACCEPT.** Read the full diff.

- `auth.py`: `assert_feature_access` refuses unknown feature names (every
  real caller uses a canonical name — checked by search); `retained_history`
  lets the seven designated history GETs pass a plan omission but never an
  explicit admin `false` or suspension (Mike's decision 2);
  `/v1/accounting/ai-insights` joins the side-effecting GETs refused to
  read-only accounts.
- Six routers gated through `require_feature`; quote convert/email/WhatsApp
  require both features (decision 1); legacy `require_tier_feature` and
  `_require_receptionist_flag` deleted, `services/tier_gating.py` removed.
- Signed WhatsApp webhook: entitlement asserted after tenant resolution and
  BEFORE the inbound log line, logging or any action; a denied business gets
  an empty 200 (decision 3).
- Changes to pre-existing tests are legitimate, not weakening: two fakes gain
  the access fields the gate now reads; the receptionist gate test targets the
  canonical gate with the same plan/flag outcomes asserted.

Not verified by tests — for Mike's click test: how AI Hub's Receptionist,
Booking and CEO Briefing tabs render for a plan WITHOUT those features (they
now receive 403s; the Dashboard's WhatsApp-config call already swallows its
error). Not a defect in this ticket; a Starter-account look is the check.
