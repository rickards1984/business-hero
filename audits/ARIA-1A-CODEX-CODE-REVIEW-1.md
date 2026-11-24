# ARIA-1a — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 24 Nov 2026.

---

REQUEST CHANGES

Reviewed commit `1677b16` against `HEAD~1`. Findings 1–5 are blocking; 6–9 are hardening.

1. **P1 — Blocking: automated senders and own-address mail can contain real enquiries or complaints.** [inbox_sorting.py:106](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:106), [inbox_sorting.py:121](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:121)
   A booking form’s `no-reply@…` message titled “New enquiry” becomes FYI/1. So does a contact plugin sending from the business’s address, or the owner forwarding “Fwd: Complaint” into their business mailbox. These messages receive `ai_analyzed_at`, disappear from Important and are never reconsidered automatically. Reproduced locally. Sender identity alone is insufficient evidence that an incoming message needs no attention.

2. **P1 — Blocking: the money exemption does not deliver its stated protection.** [inbox_sorting.py:85](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:85), [inbox_sorting.py:110](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:110)
   Three concrete failures:
   - A genuine invoice labelled `CATEGORY_PROMOTIONS` becomes Junk before the money check.
   - “£750 received” from a no-reply sender becomes FYI: the leading `\b` cannot match before `£` at the beginning of the subject.
   - Bank/HMRC/GoCardless notices titled “Action required”, “Your account” or “Your mandate has been cancelled” have no matching money keyword; financial content in the snippet is ignored.

   The first two were reproduced. Current tests cover favourable subjects and explicitly preserve the promotions override; they do not establish “money is never filtered away”.

3. **P1 — Blocking: concurrent sorting pays twice and overwrites completed classifications.** [inbox_sorting.py:156](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:156), [inbox_sorting.py:132](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:132)
   Background sorting and Sort now can select the same unsorted rows. There is no claim/lock, and `_stamp` does not require `ai_analyzed_at IS NULL`. I reproduced two passes classifying one message: the second stored Complaint, then the first overwrote it with FYI. Both reported success and both invoked classification. The process-local sync flag also cannot protect two app instances. Use coordination shared by every sorting entry point; a conditional update alone would prevent overwrites but not duplicate AI spending.

4. **P2 — Blocking: Python, SQL filters and displayed categories disagree.** [inbox_sorting.py:69](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:69), [router.py:790](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:790)
   `normalise` accepts case, spaces and hyphens; `stored_values` and `IMPORTANT_SQL` compare exact lowercase strings. Consequently:
   - `Finance`, priority 2: displayed as Money and important in Python, excluded by SQL.
   - `Action Required`, priority 2: same disagreement.
   - `Junk`, priority 5: excluded in Python but included by SQL.

   PostgreSQL’s text comparisons preserve this mismatch. Unknown values displayed as FYI also disappear under the FYI filter. NULL categories are consistently excluded from importance, but empty-string/high-priority values disagree with the frontend’s falsy-category handling. Tests exercise normalization separately, while SQL parity and TS parity omit these cases.

5. **P2 — Blocking: category navigation makes other categories falsely show zero.** [EmailsTab.tsx:359](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:359), [EmailsTab.tsx:492](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:492)
   Counts come from the already server-filtered, maximum-50-message list. Select Junk and “Needs you”, “New enquiries” and every other category become zero even when those messages exist. Additionally, clicking Unread selects All without applying an unread filter; clicking Needs you includes read important mail. These cards do not represent the counts or views their labels promise. Test the rendered interactions, including switching categories with important unread mail elsewhere.

6. **P2 — Non-blocking hardening: a skipped full sync postpones read-state refresh for another two hours.** [briefing_scheduler.py:300](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/briefing_scheduler.py:300)
   The scheduler advances `_last_email_sync` before the overlap guard accepts the run. If a quick run is still processing businesses when a full run becomes due, the full run is skipped but recorded as scheduled. Subsequent quick checks skip known Gmail IDs, leaving their read/unread state stale until another full interval. Record an accepted/completed full run separately, or retain a pending full refresh. The guard’s `finally` correctly releases it on ordinary exceptions.

7. **P2 — Non-blocking hardening: “next check” can advertise a time when checks are prohibited.** [inbox_schedule.py:46](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_schedule.py:46)
   At Friday 18:55, with the last check at 18:50, `next_check` returns Friday 19:05; `due` refuses that time. The actual next opportunity is Monday morning. Reproduced locally. Normalize the calculated candidate into the permitted window. The frontend also fetches this status only on mount or Sort now, so its advertised next check can remain in the past.

8. **P2 — Non-blocking hardening: duplicate and incomplete model answers produce misleading success counts.** [service.py:410](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/service.py:410), [inbox_sorting.py:194](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:194)
   Batch membership is checked, but uniqueness and completeness are not. Returning the same message twice stamps it twice and reports two sorted messages; reproduced with one database row. Returning only one of ten messages leaves nine waiting with `failed=False`. Deduplicate accepted IDs and report incomplete batches explicitly. Add duplicate, missing-ID and partial-response tests.

9. **P3 — Non-blocking hardening: broad money matching sends obvious newsletters to paid classification.** [inbox_sorting.py:85](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:85)
   A mailing-list message titled “Bank holiday offers” bypasses the free filters; reproduced locally. Prefix matches also catch words such as “statement-making”. Preserve conservative handling of ambiguous financial messages, but add a false-keep corpus before claiming newsletters cost nothing.

Other checks: GET `/sorting` has authentication, the router’s email entitlement dependency and business-scoped queries. The synchronous message-list endpoint contains no `await`; its async authentication dependency is compatible with FastAPI. Sort now opens its own worker-thread session, and classification attribution reaches the business’s `classify` ledger purpose. Microsoft continues using its delta cursor; ignoring `skip_ids` there preserves change refreshes.

I found no concrete default-model routing incompatibility involving `max_chain`, OpenAI-only paths or fine-tuned environment overrides. Quote chat’s `chat_params` returns no temperature or token-limit fields for `gpt-6.1-sol`. Its request is compatible with the documented [model capabilities](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and [Chat Completions parameters](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create); no live paid request was made.

Gmail’s single-page 50-message fetch and default-account-only background sync are existing limitations, not new regressions. They still prevent claiming every connected mailbox and every overnight message is covered. Live quota behaviour was not verified.

Verification: **88 sorting/schedule tests passed**, plus in-memory reproductions above. The broader run had **120 passes and 52 setup errors** because model tests require writable temporary directories. PostgreSQL integration, frontend execution and `./check.sh` were not run. No files changed, committed or pushed.