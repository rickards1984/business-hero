# OUT-7 awaiting-classification fix — Codex review 1

- Commit reviewed: 6318d04
- Model: gpt-6-astra · session 01a16f80-dcc9-7073-be02-4c97abf15459 · tokens used: 31,226
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for an OUT-7 fix. Do not commit, push or modify files.
Review commit 6318d04 on branch fix/OUT-7-awaiting-classification (`git show 6318d04`).
backend/services/outreach_replies.py propose_answer now returns {'status': 'awaiting_classification'} (no handover, no card)
for a reply with resolution='pending' and category='unknown' whose updated_at is within 15 minutes of now(); older ones
fall through to the existing handover. This fixes a race where a second sync handed over a reply the first sync was still
classifying (scan stores pending/unknown, commits, classifies outside the transaction, then compare-and-sets).
Check:
1. No reply can be stranded: every path that stores pending/unknown either classifies (scan) or hands over; a worker crash is bounded by the 15-minute wait. Is there any caller that needs a handover result and now gets awaiting? Clock consistency: updated_at is written with outreach_send.now (real clock); the check uses outreach_replies.now.
2. No path where awaiting_classification lets an answer be sent or a slot be reserved without classification.
3. The tests (deterministic race inside classify, bounded wait, rewritten concurrent test) prove the behaviour and are not weakened.
Run: .venv/bin/python -m pytest backend/tests/test_outreach_replies.py -q
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES**

1. **P2 — Crash recovery is not bounded without another proposal call.** The timeout in [outreach_replies.py:236](/Users/michaelrickards/dev/bh2-OUT-7fix/backend/services/outreach_replies.py:236) only runs inside `propose_answer`. After a worker crashes following the capture commit, subsequent scans exclude the stored reply; `storage_completed` neither retries classification nor calls `propose_answer`. No production proposal caller exists yet. Add stale pending/unknown recovery to the scan path and test recovery through a subsequent storage scan.

2. **P2 — The bounded-wait test uses inconsistent clocks.** [test_outreach_replies.py:229](/Users/michaelrickards/dev/bh2-OUT-7fix/backend/tests/test_outreach_replies.py:229) uses real time plus 16 minutes, but the inherited fixture patches `outreach_send.now` to **23 October 2026, 11:00 UTC**. The inserted timestamp therefore uses that fixed clock, contrary to the test comment. Today this tests roughly a day’s age, not 16 minutes, and can miss an excessively long timeout. Advance from the stored timestamp; assert waiting immediately before 15 minutes and handover at the boundary.

The deterministic classification race and revised concurrent assertions retain meaningful coverage, including exactly one card and slot. The awaiting return cannot draft, reserve a slot, or send; claim and dispatch retain classification checks. Production clock functions are consistent.

**Verification:** The requested pytest command could not run in the read-only sandbox. Retrying with memory-based capture and caching disabled produced **59 fixture setup errors** because temporary directories are unwritable. No files were modified.
## Response

1. Taken. scan now hands over any pending/unknown reply older than the 15-minute wait before capturing new mail. New test: the classifier dies (a BaseException, so scan's guard cannot catch it); a scan at 14 minutes leaves the reply pending, a scan at 15 hands it to the owner. The test fails with the recovery removed.
2. Taken. The wait is now measured from the stored timestamp: 15 minutes less a second still waits, 15 minutes hands over. Found while doing so: assertions inside a classify callback are swallowed by scan's classifier guard, so the earlier version could not fail. Results are now recorded and asserted after scan. Mutation-checked: the test fails with the wait set to 14 or 16 minutes.
