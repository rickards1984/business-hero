Reviewed `f8de2d0`, fixes against `8d93ff4`, for North Star P8. Worktree unchanged.

**P1**

None outstanding. Both review-1 findings are closed:

- Suggestions pass `_grounded` against current approved facts for the matched campaign’s brand.
- Both routes enforce the canonical feature gate. Briefing correctly allows retained history; headroom requires full access.

**P2**

One new finding:

- **Retention notice falsely claims deletion.** [OutreachReplyCard.tsx:44](/Users/michaelrickards/dev/bh2-OUT-19E/frontend/client/src/components/OutreachReplyCard.tsx:44) says details and messages are “no longer kept”. The fix only redacts the briefing response. I confirmed the original remains stored; [outreach_read.py:271](/Users/michaelrickards/dev/bh2-OUT-19E/backend/outreach_read.py:271) still returns it, and the card displays it above this notice. Change the notice to “Their details and message are withheld from this briefing.” No deletion change is needed for this fix.

The original P2 findings are otherwise closed: retention redaction, stale-health blocking, isolated warm-up coverage, and the misleading reply/Boost/missing-answer wording.

**Verification**

- **73 focused tests passed**, using in-memory SQLite with cache/bytecode writes disabled.
- Restoring pre-fix functions caused **six targeted regression cases to fail**: three gate cases, grounding, retention and stale health.
- Removing only the mailbox warm-up guard caused **all six isolation cases to fail**, including NULL/unrecognised kinds and reserved/unknown outcomes.
- Additional checks passed for matched-campaign brand selection and NULL/exact-expiry/future retention boundaries.
- Real Gmail and Microsoft adapter code, with synthetic HTTP responses: **six accepted/unknown/rejected reply scenarios passed**. Replies remain `bespoke`; accepted/unknown outcomes consume ceiling capacity without increasing cold usage; rejection releases capacity.
- Frontend copy was inspected, not browser-tested. No frontend copy regression test exists in the review-1 section.
- `check.sh` was not run because it writes compiled files. No live sends or PostgreSQL concurrency tests were performed.

**Backlog**

- Persist the adapter/reply settlement checks and add cross-business briefing/headroom tests.
- Expose headroom through the tenant-scoped Aria tool layer.
- Align headroom with reservation’s rejection of future-dated health checks.
- Fact-source display/copy backlog is closed.

Behaviour check after the wording fix: open an expired contact’s **Aria’s briefing** and confirm the notice describes withholding without claiming deletion.

**Verdict: REQUEST CHANGES.**