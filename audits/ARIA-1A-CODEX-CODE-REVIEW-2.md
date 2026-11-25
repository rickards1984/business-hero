# ARIA-1a — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 24 Nov 2026.

---

REQUEST CHANGES

Review-1 findings 1, 6 and 7 are fixed for their reported scenarios; 8 is fixed in `sort_pending`. Findings 2–5 and 9 remain partially resolved. Blocking issues below concern correctness and North Star P2/P8.

1. **Review 1 #1 — Fixed; regression tests cover the reported failures.**
   [inbox_sorting.py:147](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:147). **Original P1; no remaining blocker from sender identity alone.**
   Own-address messages, forwarded complaints, no-reply enquiries and auto-generated forms now reach classification. `test_sender_alone_never_hides_real_mail` proves those examples. Messages with additional bulk indicators still have the problem described next.

2. **Review 1 #2 — Partially fixed. P1, blocking: real financial mail still receives irreversible free classifications.**
   [inbox_sorting.py:126](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:126), [inbox_sorting.py:155](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:155).
   Promotion-labelled invoices, leading `£`, financial snippets and listed financial senders are covered by passing tests. But `pay` disappeared from the old money expression: **“Please pay today”**, from an unlisted supplier with `List-Unsubscribe`, becomes FYI/1. Reproduced. Likewise, a form message saying “Can you fix our roof?” with that header becomes FYI/1. Neither is reconsidered automatically.

   Spam also precedes the exemption: **“Invoice due” labelled SPAM becomes Junk**, even from a protected sender. Therefore the documented “always goes to the AI” guarantee remains false. Tests cover favourable examples, not these counterexamples.

3. **Review 1 #3 — Partially fixed. P1, blocking: an analysis entry point bypasses coordination.**
   [router.py:1273](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1273), [router.py:1300](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1300).
   Background sorting and empty-ID Sort now share the lock and conditional stamp. However, `/analyze` with explicit `message_ids` takes neither protection and updates classifications unconditionally. Run it while background sorting is awaiting the model: both pay, and the explicit-ID request can overwrite the background result.

   The SQLite lock/stamp tests cover the protected path only. The PostgreSQL test exercises basic exclusion, not this endpoint, exceptions or pool pressure; it was skipped here.

4. **Review 1 #4 — Partially fixed. P2, blocking: normalization still disagrees across SQL, status and rendered messages.**
   [inbox_sorting.py:62](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:62), [inbox_sorting.py:92](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:92), [router.py:759](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:759).
   The 26-value SQL corpus proves the original case/ordinary-space/hyphen examples on SQLite. It misses two discrepancies:

   - `"   "`, priority 5: Python/status and SQL say unsorted/not important, but the response serializer converts it to `"fyi"`; the frontend consequently marks it important.
   - `"\t"`, priority 5: Python strips it and says not important; SQL `trim()` leaves the tab and includes it as important. PostgreSQL’s default text `trim` has the same whitespace distinction.

   Both reproduced locally, including the actual frontend helper. NULL handling is correct. The frontend parity tests use canonical categories plus NULL/empty string; they do not test the serialized whitespace cases.

5. **Review 1 #5 — Partially fixed. P2, blocking: counts and navigation still describe different views.**
   [router.py:1333](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1333), [EmailsTab.tsx:80](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:80), [EmailsTab.tsx:201](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:201).
   Independent counts and the new unread query parameter fix the original happy path. Remaining concrete failures:

   - **Month means different periods:** status uses 30 days; the page subtracts one calendar month. On 24 November, a 24 October message can appear while its category count excludes it.
   - **Today uses different timezones:** status uses London; the page uses the browser’s timezone.
   - **An active sync poll retains the old `loadEmails` closure.** Start polling on All, then click Unread or Needs you. The old poll can replace the list with unfiltered messages while “Unread only” remains selected. `filteredEmails` does not reapply unread/category filters.
   - Counts refresh every minute, but the list does not. After background sorting completes, an already-selected category can retain an empty list beside a positive count.

   The status fixtures prove isolated counts. The UI test checks source strings, not rendered interactions, request ordering or polling.

6. **Review 1 #6 — Fixed for the reported overlap. Original P2, non-blocking.**
   [briefing_scheduler.py:301](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/briefing_scheduler.py:301).
   A running background sync now prevents timestamp advancement; the passing test demonstrates that scheduling resumes after busy clears. With the current single scheduler/event loop, this addresses the reported two-hour postponement.

   Hardening remains: timestamps represent task scheduling, not successful completion. An immediately failed full sync still postpones another full attempt. The check and task admission are also separate, although I found no second production caller creating a concrete new race.

7. **Review 1 #7 — Fixed for the prohibited-time calculation. Original P2, non-blocking.**
   [inbox_schedule.py:56](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_schedule.py:56), [EmailsTab.tsx:270](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:270).
   Passing tests prove Friday 18:55/18:50 becomes Monday 07:00 and preserve the permitted 19:00 check. Status now refreshes each minute. It remains an estimated opportunity: a busy scheduler can delay it. No rendered polling test establishes frontend freshness.

8. **Review 1 #8 — Fixed in the shared sorter; passing tests prove duplicate and partial-response handling. Original P2, non-blocking residual.**
   [inbox_sorting.py:288](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:288).
   Duplicate IDs count once; missing answers remain unsorted and set `failed`; out-of-batch answers are ignored. However, explicit-ID `/analyze` still counts raw returned analyses and lacks equivalent completeness reporting. A duplicate answer there can still inflate `analyzed_count`.

9. **Review 1 #9 — Partially fixed. P3, non-blocking: bulk-mail cost remains unmeasured and potentially substantial.**
   [inbox_sorting.py:126](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:126).
   The passing test proves only “Bank holiday offers” with a neutral preview. **“Statement-making savings” still matches `statement`** because a hyphen creates a word boundary. “Bank holiday offers” with **“Order now”** in its preview also reaches AI. Both reproduced.

   `account`, `order`, `quote`, `contract` and every message from the listed domains—including all `gov.uk` subdomains—override bulk filtering. Removing sender-only skips also sends generic automated notifications to AI. There is no representative corpus or measured keep rate from which to quantify the cost increase.

10. **P2, non-blocking hardening: lock handling assumes an Engine-bound session.**
    [inbox_sorting.py:181](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:181).
    `Session(bind=connection).get_bind()` returns a Connection; the installed SQLAlchemy Connection has no `.connect()`. Such a PostgreSQL session fails before sorting. A session configured only with per-model binds can also fail at argument-free `get_bind()`. Current production callers use the global Engine, so these are compatibility gaps rather than demonstrated production failures.

    Ordinary mid-pass exceptions execute the unlock and close `finally` blocks on the separate connection. The SQLite exception-release path was reproduced successfully. PostgreSQL exception cleanup is not tested; an unlock failure should invalidate the connection rather than risk returning a session-level lock to the pool.

11. **P2, non-blocking hardening: advisory locks consume scarce connections throughout AI calls.**
    [inbox_sorting.py:183](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:183), [router.py:1262](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1262).
    Each active business holds an extra connection for the entire pass. Sort now also retains its request session after looking up the business, and the worker needs connections for reads/stamps. Multiple slow classifications can exhaust the default 20-connection pool—or the configured maximum budget of 30—and time out unrelated requests.

    The lock connection also leaves its transaction open throughout the pass. A server timeout that terminates that connection would release its lock before classification finishes. No pool-pressure or connection-loss test covers either scenario.

12. **P3, non-blocking hardening: lock collisions and SQLite scope need explicit limits.**
    [inbox_sorting.py:185](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:185), [inbox_sorting.py:197](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:197).
    `hashtext` provides a 32-bit key: colliding businesses unnecessarily block each other and report busy. This delays work; it does not itself permit duplicate work or cross-tenant access.

    SQLite exclusion works within one process and releases on exceptions. Two processes sharing a SQLite file can still classify the same mail. The lock dictionary also retains every business key indefinitely. These limits are not covered by the existing same-process tests.

13. **P3, non-blocking hardening: normalization and minute polling add mailbox-sized work.**
    [inbox_sorting.py:92](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:92), [router.py:1369](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1369).
    The normalization expressions cannot directly use an ordinary category index, although business-scoping indexes remain usable. Status fetches every matching row and counts in Python; selecting All repeats that work every minute. Large mailboxes need query-plan and load evidence.

    Status’s INBOX restriction matches the page’s default list request. However, waiting/last-sorted remain business-wide, NULL received dates are excluded from ranged counts but accepted by the page, and counts cover more than the list’s 50-row limit. These distinctions are not tested together.

Verification: **109 passed, 1 skipped, 3 setup errors**. PostgreSQL was unavailable; the SQLite threaded test and two frontend tests required forbidden temporary-file writes. Additional in-memory Python/Node checks reproduced the cases above. `./check.sh` was not run because it writes compiled files; no full-suite or PostgreSQL verification is claimed. No files modified, committed or pushed.