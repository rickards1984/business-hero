# OUT-28a fast save — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 20 Nov 2026. Verdict APPROVE; both low findings acted on in the next commit.

---

APPROVE

1. **Low — [backend/outreach_manage.py:204](/Users/michaelrickards/dev/bh2-FASTSAVE/backend/outreach_manage.py:204): cards can appear absent for several minutes.** The frontend invalidates queries immediately after saving, potentially before replacement cards exist. An owner opening approvals during preparation can see an empty or partial list until the five-minute refresh or another refetch. Consider a preparation notice and a short follow-up refresh.

2. **Low — [backend/tests/test_outreach_edit_any_time.py:427](/Users/michaelrickards/dev/bh2-FASTSAVE/backend/tests/test_outreach_edit_any_time.py:427): the failure test can pass without exercising preparation.** Unlike the preceding test, it does not replace `get_session_context` or assert that `broken()` ran. If session creation fails first, the broad exception handler swallows that failure and the test still passes. Supply a controlled session context and assert preparation was reached and the context exited.

No blocking safety defect found: saving commits before scheduling; the task owns and closes its session, rolling back unfinished transactions on failure. Concurrent preparation remains protected by OUT-24’s business lock and final open-card check held through proposal commit. Interrupted preparation remains recoverable by the hourly pass.

Static review only; tests were not run. No files changed.