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
