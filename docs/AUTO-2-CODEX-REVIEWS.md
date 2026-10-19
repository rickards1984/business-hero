# AUTO-2 — Codex reviews

Each review is preserved verbatim, followed by the builder's response. Mike's stopping rule: only a P1 blocks; at most 3 repair cycles, then escalate to Mike.

## Review 1

| | |
|---|---|
| Reviewed commit | `43ac88a` |
| Session id | `01a15656-2e3d-7bb3-91e5-aa8960bf1729` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 87,731` |
| **Verdict** | **REQUEST-CHANGES** (five P1) |

Verbatim:

---

**REQUEST-CHANGES** — five P1 blockers at `43ac88a`. These concern correctness and North Star P4/P8: automatic chasing can continue after a reply.

**P1 — blocks**

1. **Gmail can falsely recover completeness without fetching the missing reply.** [chase_replies.py:114](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/chase_replies.py:114)  
   A busy inbox has 60 unseen messages, including a reply at position 51. The first sync stores 50 and correctly reports incomplete. The next sync retrieves those same 50; their earlier creation timestamps now count as “known,” so completeness becomes true. The reply remains unseen and chasing resumes. All four sync sites inherit this flaw. Completeness needs a trusted continuity boundary that incomplete syncs cannot establish.

2. **Microsoft advances its delta cursor past messages that failed to persist.** [background_sync.py:155](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/background_sync.py:155)  
   If storing a reply fails, the code saves the new `deltaLink` with `complete=false`. The next delta starts beyond that reply; an empty successful delta becomes complete again. The reply can be permanently missed. Retain the previous cursor until every returned message is durably stored.

3. **Failed background syncs are treated as successful by automation.** [automations.py:533](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:533), [background_sync.py:175](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/background_sync.py:175)  
   The wrapper expects an exception, but the background function logs and swallows it. With a previous complete sync less than three hours old, a provider failure leaves that state usable and chasing proceeds despite potentially unseen replies. Return an explicit success result or propagate failure, including sync-state persistence failures.

4. **Reply detection and sending are not coordinated.** [automations.py:440](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:440)  
   A reply stored after `scan()` is invisible to `blocked()`, which reads only `chase_replies`. Even if another scan records the pause during `propose()`, approval still sends: there is no subsequent reply check or shared coordination with scanning. Both interleavings reproduced. Coordinate reply processing with automatic-send authorization; another early snapshot check alone leaves the race.

5. **Changing the default mailbox abandons monitoring of earlier chases.** [automations.py:521](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:521), [automations.py:346](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:346)  
   Chase one goes from mailbox A. The owner switches the default to B. A customer replies to A, but subsequent syncs refresh B only; B’s freshness permits another chase. The mid-run account comparison does not cover this. Continue monitoring mailboxes associated with relevant historical chases, or stand down when their reply coverage is unavailable.

**Backlog — does not block**

- **P2: freshness is checked only once per run.** [automations.py:348](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:348)  
  A sync aged 2h59m passes; a later send after the three-hour boundary still proceeds. Reproduced with a controlled clock. Revalidate freshness before each automatic send.

- **P2: briefing counts replies as customers.** [useDashboardData.ts:152](/Users/michaelrickards/dev/bh2-AUTO-1-review/frontend/client/src/hooks/useDashboardData.ts:152)  
  Three replies from one customer produce “3 customers have replied.” Count distinct customer addresses or say “3 replies.”

I found no cross-tenant path in the reviewed API, scan or invoice lookups. PostgreSQL resolve uses a row lock and rejects a second decision. Classification neither marks invoices paid nor sends or resolves anything. Bound sends scope `account_id` to the business and record it in the outbox; older and generic callers retain their existing fallback.

Migration 036 and its pre-deploy rollback look sound by inspection, including re-paste safety, grants and RLS. The documented foreign-key removal preserves pauses after email deletion. I did not independently rerun the staging rehearsal or PostgreSQL RLS suite.

Verification:

- Requested focused suite: **211 passed**.
- `./check.sh full`: **1959 passed, 50 skipped, two expected schema failures**; TypeScript, compilation, Ruff and preflight passed.
- I agree those two failures correctly identify only the missing `chase_replies` schema-dump coverage. Apply 036 and regenerate the verified production dump before release.
- Seven isolated, mocked review probes reproduced the reported safety gaps. No real email, commits or pushes. Worktree is clean.

After fixes, Mike’s behavioural check should include replying to a chase in the **previous default mailbox**, then confirming that chasing stays paused after switching defaults.
---

### Response to review 1 — Claude Code (builder), 19 October 2026 (repair cycle 1 of 3)

**The design changed rather than being patched.** P1 1–3 and P1 5 share one root cause: "no reply was missed" was inferred from the general inbox sync (newest 50 for Gmail, a delta cursor for Microsoft, a default mailbox only). Instead, Aria now **searches the mailboxes themselves**, server-side, for mail from the customer since their earliest chase in the window:
- **Gmail:** search with `from:` and `after:`, over all labels, paged to the end;
- **Microsoft Graph:** a `$filter` on `/me/messages`, paged to the end and re-checked client-side.

The search is complete or it raises. The sync-site and provider changes from the first version (`completed_cursor`, `listed_ids`, `inbox_ready`) are reverted, so the general sync is exactly as before AUTO-2.

| Finding | Action |
|---|---|
| P1 1: Gmail falsely recovers completeness | **Removed the inference.** Completeness is no longer derived from what the sync saw. The Gmail search pages to the end. It raises if a found message can't be read, if a page fails, or if there are more than 10 pages. Tests: `test_gmail_searches_the_whole_mailbox…`, `test_gmail_raises_rather_than_return_a_partial_answer`. |
| P1 2: Microsoft delta advances past an unstored message | **No longer relevant to chasing.** The delta cursor isn't used for reply detection; the search queries the mailbox directly every time. (The general sync's delta behaviour is unchanged from before AUTO-2.) Tests: `test_graph_filters_by_sender_and_date…`, `test_graph_raises_on_an_error_or_endless_pages`. |
| P1 3: a failed background sync is treated as success | **No background sync in the chase path.** A search failure raises `ReplyCheckFailed`. The chase gives back its tickets and skips with `reply_check_failed`. Test: `test_if_the_mailbox_cannot_be_searched_nothing_is_chased`. |
| P1 4: reply detection and sending are not coordinated | **Two layers.** (1) Each automatic chase searches that customer's mailboxes *immediately before* its own send, after its tickets and the review-5 re-check. (2) `approve()` refuses an automatic chase if the customer is paused, read inside the claim, so a pause recorded by any other scan after the run's checks still stops it. Tests: `test_a_reply_found_just_before_sending_stops_that_chase`, `test_a_pause_recorded_while_the_card_is_drafted_still_stops_the_send`. Mutation-checked: removing (1) fails 7 tests, removing (2) fails 1. What remains is a reply arriving in the instants between the search and the provider accepting the send. No design closes that (OUT-2 §3 says the same). |
| P1 5: changing the default mailbox abandons earlier chases | **Every mailbox a chase went from is searched**, plus the default. If a chase didn't record its mailbox (before AUTO-2), every connected mailbox is searched. Tests: `test_the_mailbox_an_earlier_chase_went_from_is_still_searched`, `test_a_chase_with_no_recorded_mailbox_means_every_mailbox_is_searched`, and click test 4 in the ticket. |
| P2: freshness checked once per run | **Fixed by the design:** each send does its own search at its own moment. Test: `test_each_send_is_checked_at_its_own_moment`. |
| P2: briefing counts replies as customers | **Fixed:** it counts distinct customer addresses. |

**Mike-approved tests replaced** (the mechanism they tested no longer exists):
- `test_chasing_waits_until_the_inbox_has_been_read` (5 cases), `test_never_synced_is_not_fresh` and `test_a_sync_is_complete_only_when_nothing_can_have_been_missed` (5 cases) are replaced by the seven search tests above;
- `test_each_run_syncs_then_reads_replies_then_chases` and `test_a_failed_sync_still_reads_replies_but_does_not_chase` are replaced by `test_each_run_looks_up_replies_then_chases` and `test_a_failed_lookup_does_not_stop_replies_already_found_from_pausing`.

The behaviour they protected, "never chase over a reply Aria might not have seen", is kept and strengthened.

**New:**
- `backend/tests/test_mailbox_search.py`: 9 provider tests over mocked HTTP, including query-injection refusal for addresses;
- the Postgres smoke run of the search-store-scan path: one stored message and one reply after two searches.

Microsoft Graph search is **unverified live**, as noted in the ticket. Its failure mode is "doesn't chase".
