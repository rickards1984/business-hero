# ARIA-1a — Codex code review 3 (verbatim)

Model gpt-6-astra, read-only sandbox, 24 Nov 2026.

---

REQUEST CHANGES

Blocking findings concern North Star P2/P8: incorrect counts and mail missing from the selected view. No new concrete PostgreSQL crash, duplicate-classification path or AI call blocking the event loop was found.

1. **P2 — Blocking: the first completed background sort never refreshes the list.** [EmailsTab.tsx:275](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:275)

   Open a newly connected mailbox, select Important while everything is unsorted, then let background sorting finish. `lastSortedRef.current` is null, so the null-to-timestamp transition does **not** reload messages. The reference then becomes that timestamp; subsequent unchanged polls also do nothing. The card can show important mail while the list remains empty until another interaction.

   Reproduced using the actual condition in Node: **zero reloads** across null → first timestamp → unchanged timestamp. The source-string test passes despite this defect. Distinguish “status not loaded yet” from “loaded, but nothing sorted yet”.

2. **P2 — Blocking: late status responses overwrite counts for the current period.** [EmailsTab.tsx:269](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:269)

   Select All time, then Today. If Today returns first and All time returns second, `setSorting(next)` installs All-time counts while Today remains selected. Nothing checks the response’s range or request generation. Incorrect counts remain until the next successful refresh.

   The new request counter protects only message-list successes. Tests do not exercise reordered status responses.

3. **P2 — Blocking: message request ordering remains incomplete.** [EmailsTab.tsx:160](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:160), [EmailsTab.tsx:307](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:307)

   Two concrete paths remain:

   - An old request fails after the current category request succeeds. Its unguarded `catch` clears the current list—and can set `hasEmailAccount=false`.
   - Start Sort now on All, then select Money while sorting runs. Completion calls the handler’s captured **old** `loadEmails()`. That request receives the newest counter despite requesting the old view. Reapplying Money locally cannot recover Money messages omitted from All’s 50-row response.

   The timer ref fixes ordinary sync polling, but not these paths. Guard error/finally mutations and use the current loader after awaited actions. Existing tests check strings, not these interactions.

4. **P2 — Non-blocking hardening: the new prompt’s accuracy is unmeasured.** [service.py:351](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/service.py:351), [service.py:400](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/service.py:400)

   Removing free classifications fixes the demonstrated deterministic loss of financial mail and enquiries. However, “reads every email” currently means subject plus **300 characters of snippet**, not the full email.

   A mailing-list form notification whose actual enquiry appears after that preview can still look like bulk mail; a financial newsletter containing “invoice/payment” language can look important. These are evaluation scenarios, not proven model regressions. Tests prove delivery to the classifier and inclusion of hints; they do **not** prove final categories or whether either error rate increased. A labelled corpus is needed before claiming classification quality.

5. **P3 — Non-blocking hardening: the 3p cost claim lacks usage evidence; throughput matters more for busy mailboxes.** [inbox_sorting.py:15](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:15), [ai_models.py:247](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/ai_models.py:247)

   GPT-6 Luna’s published standard rates are **$0.10/M input tokens and $0.50/M output tokens**. Ten emails in one ordinary request does not qualify for Batch API pricing. [Official model pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)

   Illustrative assumptions, not measured usage:

   - 200 input tokens and 100 billed output tokens per email: **$0.07/1,000 emails**, or **$1.54 for 22,000**.
   - The router expands this call’s 1,500-token setting to **6,000 completion tokens per ten-email batch**. At that ceiling, output alone costs **$0.30/1,000 emails**, before input, retries or fallback.
   - Thirty emails every fifteen minutes gives **120/hour**, approximately **1,470 per permitted weekday** with all 49 checks completed. A sustained 150/hour arrival rate grows the backlog; newest-first selection delays older mail.

   Already-sorted messages are not charged again every fifteen minutes. The increased cost is per newly classified email, plus failed/retried work. No measured token distribution supports the fixed sterling claim.

6. **P2/P3 — Non-blocking hardening: PostgreSQL changes look sound, but integration evidence remains incomplete.** [inbox_sorting.py:163](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:163), [router.py:1333](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1333)

   The separate autocommit connection is compatible with a **session-level** advisory lock: committing statements does not release it. Connection-bound sessions now obtain their engine, and unlock exceptions invalidate the connection. [PostgreSQL lock semantics](https://www.postgresql.org/docs/current/explicit-locking.html)

   The MD5-prefix → `bit(64)` → `bigint` expression supplies a signed 64-bit key. Collision probability is greatly reduced, not eliminated; the comment claiming businesses “never share one” is too strong.

   The grouped status query is valid PostgreSQL: `GROUP BY 1, 2, 3` groups the selected CASE expression itself. Collapsing priorities into below/above the importance threshold preserves the current counting rule. [PostgreSQL GROUP BY documentation](https://www.postgresql.org/docs/current/sql-select.html)

   Remaining failure scenarios: many simultaneous slow passes retain pool connections; losing the lock connection during an AI call can release exclusion before the worker finishes. No pool-pressure, connection-loss or unlock-failure integration test proves those cases. Both PostgreSQL tests were skipped here.

7. **P2 — Non-blocking compatibility change: explicit IDs no longer request re-analysis.** [router.py:1269](/Users/michaelrickards/dev/bh2-ARIA1/backend/app/email/router.py:1269), [inbox_sorting.py:261](/Users/michaelrickards/dev/bh2-ARIA1/backend/services/inbox_sorting.py:261)

   Naming an already-sorted message now produces no new analysis and returns `analyses=[]`. Thus a caller attempting to correct an old classification cannot do so through this endpoint.

   I found no repository UI caller passing explicit IDs or relying on returned analyses; both visible callers request unsorted work. This is therefore a contract change, not a demonstrated current UI blocker. Routing/locking tests cover named unsorted messages, but not this changed contract. Also, an explicit selection containing no pending rows returns `waiting=0` even if other business mail remains unsorted.

8. **Review-2 disposition — all thirteen points.**

   | Review-2 point | Fixed? | Do tests prove it? |
   |---|---|---|
   | **1 — Sender identity** | Yes, deterministic filtering removed. | Passing every-kind cases prove classifier admission. |
   | **2 — Real mail with bulk indicators** | Yes for the reported free-filter failures. | Passing cases cover “Please pay”, form enquiries and spam-labelled invoices; model accuracy remains unproved. |
   | **3 — Explicit-ID coordination** | Yes for the bypass. | Endpoint forwarding and shared-lock tests pass; PostgreSQL execution unverified. |
   | **4 — Normalization** | Yes for reported whitespace cases. | SQL/Python and serializer tests pass. Tabs now deliberately become FYI consistently, rather than unsorted. |
   | **5 — Counts/navigation** | **Partially.** Periods, timezone and timer closure improved. | Source assertions miss blocking findings 1–3 above. |
   | **6 — Skipped full sync** | Original fix retained. | Busy/resume test passes. Failed scheduled runs still postpone refresh: hardening. |
   | **7 — Next-check window** | Original fix retained. | Friday/Monday and permitted 19:00 tests pass. |
   | **8 — Duplicate/partial answers** | Yes, including removal of the separate explicit-ID implementation. | Shared-sorter duplicate and partial-response tests pass. |
   | **9 — Bulk cost** | Free-filter issue superseded; cost unmeasured. | No usage/cost corpus proves 3p/1,000. |
   | **10 — Connection-bound lock** | Implemented; unlock invalidation added. | Connection-bound PostgreSQL test exists but skipped; per-model-only binds remain unsupported. |
   | **11 — Connection pressure** | Partially: request transaction released; lock connection uses autocommit. | No pool-pressure or connection-loss test. |
   | **12 — Lock collisions/SQLite scope** | 64-bit key implemented; SQLite limitations unchanged. | PostgreSQL tests skipped; cross-process SQLite exclusion is not provided. |
   | **13 — Mailbox-sized status work** | Row transfer/counting improved through aggregation. | SQLite status fixtures pass; PostgreSQL execution/query-plan evidence absent. DB scans and list/count scope distinctions remain. |

Verification: **106 passed, 2 skipped, 1 setup error**. The error was the threaded SQLite test’s forbidden temporary-file creation. No rendered UI or live-model tests ran. `./check.sh` was not run because it writes compiled files. No files modified, committed or pushed.

For Mike’s final-cycle escalation, findings **1–3 are the blockers**; findings **4–7 are hardening or compatibility follow-ups**.