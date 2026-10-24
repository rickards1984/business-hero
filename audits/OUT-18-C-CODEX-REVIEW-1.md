# OUT-18 part C — Codex review 1

- Commit reviewed: 2d55672
- Model: gpt-6-astra · session 01a17024-b3d6-7d40-88d5-e9b364c1368a · tokens used: 53,792
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-18 part C in this repository (RED: outreach sending limits). Do not commit, push or modify files.
Read docs/OUT-18-TICKET.md part C. Review commit 2d55672 (`git show 2d55672`), mainly backend/services/metering.py reserve_outreach_usage.
Mike's decision: 20 new emails a day PER BRAND instead of 20 per business. The change counts the brand's reserved/committed/unknown outreach_usage_events for this UK day (joined message -> campaign -> brand) under the business lock and refuses at min(20, business_daily_cap); the business-scope outreach_daily_usage row is still counted but no longer limits.
Check:
1. Can more than the limit be reserved for one brand on one UK day — concurrency (is the business lock held for the count and the reservation insert, in every caller of reserve_outreach_usage including the OUT-11 automatic path if present), local date handling, states counted, released excluded, messages whose campaign changed brand?
2. Does settlement (settle_outreach_usage) or anything else still assume the business row enforces the limit? Does any other path send outreach without reserve_outreach_usage?
3. Is anything left promising or enforcing "20 per business" (code, Aria tools, copy)? Is the per-brand count's query plan acceptable (indexes on outreach_usage_events/outreach_messages)?
4. The tests in backend/tests/test_outreach_send.py prove the brand limit, another brand's usage not counting, released not counting, and the owner's lower cap.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reservation enforcement looks correct, but Aria’s settings contract still needs the new meaning.

1. **P2 — Aria receives the old, misleading cap name without its new scope.** [outreach_read.py:58](/Users/michaelrickards/dev/bh2-OUT-18/backend/outreach_read.py:58) returns `business_daily_cap`; [assistant_tools.py:548](/Users/michaelrickards/dev/bh2-OUT-18/backend/assistant_tools.py:548) provides no explanation that it now applies **separately to each brand**. Aria cannot reliably explain the changed limit from this response. Preserve the storage name if necessary, but expose explicit per-brand semantics and add a grounding test. This serves P2/P8.

2. **P3 — Older contracts still explicitly promise a business-wide limit.** [OUT-2-CONTRACTS.md:110](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-2-CONTRACTS.md:110) says “tenant cap stays 20/day across every inbox”; [OUT-6-TICKET.md:23](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-6-TICKET.md:23) also specifies 20 across campaigns/mailboxes. Mark those provisions superseded by OUT-18 C.

3. **P3 — The count lacks a directly matching date index.** [metering.py:641](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/metering.py:641) filters by business/date/state. Declared event indexes place `period_start` or `mailbox_id` between business and date/state. Message and campaign identity indexes support the joins, but event filtering can scan accumulated tenant history. Reasonable at pilot volume; obtain a representative `EXPLAIN` before scaling and consider `(business_id, local_send_date, state)`. I did not verify live indexes or an execution plan.

Other checks:

- **Concurrency:** the sole production reservation caller is `prepare_claim`. It holds the business/settings locks through counting, event insertion and action-claim commit. Replies use that same path. No OUT-11 automatic sender is implemented here.
- **Dates/states:** count and insertion use the same Europe/London date; claim checks reject a date rollover while waiting. Reserved, committed and unknown count; released does not.
- **Campaign reassignment:** the query uses the campaign’s current brand, so direct reassignment would move historical usage. No supported campaign-brand or message-campaign reassignment path was found; campaign PATCH rejects `brand_id`.
- **Settlement/bypass:** settlement maintains business totals without imposing 20. No outreach transport bypass was found. Monthly 500, mailbox warm-up and campaign limits remain enforced.
- **Tests:** the four new tests cover the requested cases by inspection. They do not exercise concurrent reservations for the last brand slot or UK-day rollover.

**Verification:** pytest and `check.sh` were not run: the sandbox is read-only and the fixtures create temporary SQLite databases. No files were modified, committed or pushed.
## Response

1. **P2 — taken.**
   - The settings read (API and Aria's tool) now carries `daily_limit`: `{scope: "per_brand", new_emails_per_brand_per_day, message}`, stating that `business_daily_cap` applies separately to each brand.
   - Test `test_aria_is_told_the_daily_limit_is_per_brand` (api and tool).
   - The stored column name is unchanged (no migration).
2. **P3 — taken.** OUT-2-CONTRACTS.md and OUT-6-TICKET.md mark the business-wide 20/day provisions as superseded by OUT-18 C.
3. **P3 — recorded, not built.** docs/OUT-18-TICKET.md notes the missing `(business_id, local_send_date, state)` index. It is fine at pilot volume; a production `EXPLAIN` comes before scaling, then a later migration if needed.
