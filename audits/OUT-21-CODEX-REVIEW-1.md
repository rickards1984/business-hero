# OUT-21 — Codex review 1 (preserved verbatim)

Three findings; **changes requested**.

1. **High — exception logs can expose contact data.** [outreach_research.py:1325](/Users/michaelrickards/dev/bh2-OUT-21/backend/services/outreach_research.py:1325) logs unrestricted exception text. SQLAlchemy errors from `_store` can include INSERT parameters containing contact names and emails; the production engine does not enable `hide_parameters`. Confirmed with a synthetic `StatementError`. Preserve stack locations and exception type, but redact exception messages, parameters and chained exceptions before logging.

2. **Medium — missing-key refusal still leaves no owner-visible summary.** [outreach_research.py:964](/Users/michaelrickards/dev/bh2-OUT-21/backend/services/outreach_research.py:964) returns before saving the summary. `run_due` logs that return but only persists a failure summary for exceptions. An already-launched business with the missing key therefore keeps an empty or stale summary, and its day is already claimed. Persist the refusal and test its visibility through `status()`.

3. **Medium — malformed URLs can still discard a paid search’s candidates.** [outreach_research.py:533](/Users/michaelrickards/dev/bh2-OUT-21/backend/services/outreach_research.py:533) accepts a matching hostname such as `https://studio1.example:bad/team`. `fetch_page` subsequently reads `parts.port` outside its exception handler, raising `ValueError`. This aborts the entire candidate batch before storage. The new handler makes it visible, but valid candidates are still lost. Treat malformed ports and redirect URLs as candidate verification failures; test using the real fetch adapter.

No regression identified in spend settlement, search-claim release, or the once-per-day claim. Verification failures occur after spend settlement commits.

Read-only review completed; no files changed. Full tests and `check.sh` were not run because they write files; only read-only inspection and synthetic in-memory probes were performed.