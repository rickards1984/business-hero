# RCP-2 — Codex code review 1 (verbatim)

- **Reviewer:** Codex CLI (`codex exec --sandbox read-only`), model `gpt-6-astra`
- **Session:** `01a1d770-03a1-7d92-af77-8f75270e9d94`, 34,992 tokens
- **Verdict:** APPROVE, with one nit (the admin-link fallback), fixed with a test.

---

1. **NIT — [backend/services/receptionist_numbers.py:483](/Users/michaelrickards/dev/bh2-RCP2/backend/services/receptionist_numbers.py:483): Incorrect admin-link fallback.** When `APP_BASE_URL` is unset, the email links to `PUBLIC_BASE_URL/admin`. That variable identifies the API host, so it won’t open the frontend dashboard. Use `FRONTEND_URL`/`APP_BASE_URL`, otherwise retain the plain dashboard instruction. Add a fallback test.

No blocking findings. The alert is scheduled after persistence, skipped on refusal, runs in a worker thread, and catches exceptions. The recipient comes only from `PROFIT_ALERT_TO`; request data cannot override it. The body contains relevant provisioning details without credentials. £50, included setup, self-setup and absent optional fields format correctly.

Verification: **791 tests passed**, including the plan-enforcement harness and both endpoint alert tests. Additional read-only probes confirmed threading, formatting and exception handling. Removing scheduling or delivery would fail the corresponding assertions. Full `check.sh` and database-backed tests weren’t run because they write files. No files modified; nothing committed or pushed.

VERDICT: APPROVE