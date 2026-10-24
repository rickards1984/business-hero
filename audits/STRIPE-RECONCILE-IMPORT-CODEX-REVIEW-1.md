# Stripe reconciliation import fix — Codex review 1

- Commit reviewed: 0afd8fb
- Model: gpt-6-astra · session 01a16f42-9186-7171-b2e9-8ac57f75ea5e · tokens used: 28,739
- Verdict: APPROVE

## Prompt

```
You are the independent reviewer for a RED (billing) fix in this repository. Do not commit, push, or modify files.
Review commit 0afd8fb on branch fix/stripe-reconcile-import (`git show 0afd8fb`).

Context: production's daily Stripe reconciliation (backend/services/stripe_reconciliation.py, run from a
scheduler thread via asyncio.to_thread in services/briefing_scheduler.py) failed with
"ImportError: cannot import name '_plan_item' from 'main' (/app/main.py)". It did a lazy `from main import ...`.
The fix moves _plan_item, _resolve_plan_from_price, _resolve_current_period_end and _epoch_to_utc into
backend/app/billing/plans.py, main.py re-imports them under the old names, and reconciliation calls plans.*.

Check:
1. The moved code is byte-for-byte equivalent in behaviour (webhook in main.py ~line 1110-1180 included).
2. No remaining caller or test relies on monkeypatching main._resolve_plan_from_price etc. in a way that now silently stops taking effect.
3. Whether the root-cause explanation (process not running as module `main`) is plausible, and whether any other lazy `from main import` (e.g. services/invoice_chase_helper.py) has the same production risk.
4. Run: .venv/bin/python -m pytest backend/tests/test_stripe_reconciliation.py backend/tests/test_stripe_webhook_correctness.py -q
Give a verdict APPROVE or REQUEST CHANGES with numbered findings (P1/P2/P3).
```

## Review (verbatim)

**APPROVE** commit `0afd8fb`. No blocking billing regression found. This serves the North Star’s correctness and stability prerequisites.

1. **P3 — Root cause remains unproven.** [railway.json](/Users/michaelrickards/dev/bh2-stripe-import/railway.json:7) and `Procfile` specify `uvicorn main:app`, which loads module `main`. Running as `__main__` could cause a second import, but does not alone explain missing helpers. A scheduler thread shares the process’s module cache. The extraction removes the problematic dependency; the new test proves independence from `main`, not the precise production cause.

2. **P3 — Pre-existing equivalent dependency in invoice chasing.** [invoice_chase_helper.py:51](/Users/michaelrickards/dev/bh2-stripe-import/backend/services/invoice_chase_helper.py:51) still lazily imports three functions from `main`. It has the same structural risk if module identity or availability differs; import failure returns a failed chase. Track separately.

Verified:
- All four helper ASTs match after normalizing renamed identifiers. The entire webhook AST is unchanged, including lines 1110–1180. Warning logger changes from `admin` to `app.billing.plans`.
- No remaining repository caller/test relies on patching the old helper names or `main.get_stripe_config`. The reconciliation fixture correctly patches `plans`; webhook tests use environment variables. Old aliases preserve direct calls, but no longer control nested helper lookups.
- **84 passed, 213 deprecation warnings.** Used the requested pytest selection with bytecode/cache writes disabled and `--capture=sys`, because default capture cannot create temporary files in this read-only environment.

No files modified, commits created, or pushes performed. Full `check.sh` and production recovery were not verified. Operational confirmation: the next daily reconciliation completes without the import error.