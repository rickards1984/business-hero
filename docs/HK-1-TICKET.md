# HK-1: housekeeping before daily use

**Tier:** AMBER. It touches the voice billing hand-off and alert email, but there is no schema change and no production SQL. **Builder:** Claude. **Reviewer:** Codex.

## 1. A production-only import bug: WhatsApp chases and profit alerts never sent

- **What went wrong:** production loads `backend/main.py` through the root shim as the module `backend_main`; the name `main` belongs to the shim. Two lazy imports used `from main import …`, so they imported the shim and failed:
  - **`services/invoice_chase_helper.py`:** the WhatsApp "send chase" action always replied "Couldn't send the chase email automatically".
  - **`services/profit_guard.send_alert`:** the cost alarm and kill-switch emails could never send (they were logged only).
- **Why nothing caught it:** tests import `backend/main.py` as `main`, so none of them saw it.
- **Fix:** `services/backend_main.backend_main()` finds the module by its file, under whatever name it was loaded.
- **Tests (`test_backend_main.py`):**
  - no backend code imports `main` by name;
  - the resolver finds the module as production loads it, with the shim owning `main`;
  - both callers use the resolver.
  - The guard and the caller tests fail on the old code.

## 2. The flaky voice test (`test_a_session_is_metered_once_from_the_aria_voice_source`)

- **Not reproduced:** 3 full-suite runs and 24 parallel runs were all clean. The recorded failures happened while Codex was running alongside, so the machine was under load.
- **Two plausible causes, both fixed:**
  - **The accrual was started late.** It was started as `ensure_future(to_thread(_record))`, so the worker thread was only submitted when that task first ran; an event loop torn down straight after (a test client closing, or a deploy) could lose the accrual, leaving the session to heartbeat recovery. It's now `run_in_executor` with the copied context, submitted immediately. This protects production billing too.
  - **The test's wait was too short.** It now waits up to 15 s instead of 5 s; a passing test returns at once.

## 3. Preflight TRAP 4 over-match

- **Problem:** "models.py changed" matched any path containing `models.py`, blocking unrelated pushes (OUT-19 H). It also missed a new SQLModel table declared outside `models.py`.
- **Now it flags:**
  - exactly `backend/models.py`; or
  - an added `table=True` line in any backend Python file.
- **Fixture-repo tests:** two false positives, two real cases. Three of the four fail on the old check.

## 4. Light mode: the loading bars were invisible

- **Problem:** the home cards' `.skeleton` drew `--glass-bg` (near-white in light mode) with a white highlight on white cards, so the cards looked frozen while loading. Dark mode was fine.
- **Fix:**
  - `--skeleton-base` and `--skeleton-highlight` tokens, grey in light mode and unchanged in dark;
  - `.bh-skeleton` uses the same tokens;
  - `.skeleton` is `display: block`, so a `<span>` keeps its height.

## Not in HK-1 (each needs its own ticket)

- **The outreach `prepare` scan** (OUT-8 note 2): every open card is scanned per enrolment. The right fix is a partial expression index on `aria_actions (business_id, (payload->>'enrolment_id')) WHERE action_type='send_outreach'`. That is a production migration (RED, from a runbook), needed only **before the pilot cap of 5 is lifted**. The cap is still in place.
- **OUT-13 retention:** retention, subject rights and redaction. A RED ticket of its own, needed before real personal-data import or launch.

## Codex review 1 (`audits/HK-1-CODEX-REVIEW-1.md`, 1 × P1, 1 × P2) → fixed

1. **P1: the resolver still returned the shim in production.** The root `main.py` executed the backend module without registering it, so nothing in `sys.modules` pointed at `backend/main.py`. The first test hid this by registering it by hand.
   - The shim now registers `sys.modules["backend_main"]` before executing it.
   - The resolver also follows the shim's `backend_main` attribute.
   - A test runs the **real root `main.py`** against a stub backend, as production does, and it fails on the old shim and resolver.
2. **P2: TRAP 4 could PASS wrongly.** With `pipefail`, `grep -q` closing early made the writer's SIGPIPE read as "no match", and a failed patch diff left it at "no change".
   - Here-strings replace the pipes.
   - A failed diff counts as a model change.
   - Test files are excluded from the `table=True` scan, since a test may hold it as text; a fixture test covers this.

## Codex review 2 (`audits/HK-1-CODEX-REVIEW-2.md`, targeted) → APPROVE

No P1 or P2. Railway's `uvicorn main:app` start is unaffected. Codex checked the TRAP 4 fix by reading it (its sandbox can't run the fixture tests); the fixture tests pass here.
