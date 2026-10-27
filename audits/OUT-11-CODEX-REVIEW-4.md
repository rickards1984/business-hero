Reviewed `fe7fb70` against **North Star P8**.

- **P1: Closed.** Slot ownership, expiry and minimum spacing are enforced under the business lock. All three regressions pass; all three fail when `claim_pace` is disabled in memory.
- **P2: None found.**
- **Backlog:** Unexpected exceptions before `claim_pace` leave `PACE_TOKEN` in `session.info`. Reproduced with a search exception. Normal success/refusal paths clean up correctly, and subsequent automatic attempts overwrite the token; no bypass demonstrated. Use `finally` for cleanup in [outreach_autopilot.py:270](/Users/michaelrickards/dev/bh2-OUT-11/backend/services/outreach_autopilot.py:270).

Verified:
- Fresh settings reads under the shared lock preserve revocations; refusal releases the owned slot.
- Manual approvals remain unaffected.
- Automatic sends through real Gmail/Graph adapter code, with mocked HTTP, retain honest accepted/refused/unknown outcomes. Unknown outcomes retain their pace slot and held capacity; `thread_note` survives settlement.
- OUT-18 daily/monthly brand caps include unknown usage without charging another brand’s allowance.
- Existing OUT-19 AI ledger entries survive successful and refused automatic sends.

**Validation:** 287 focused tests plus 12 in-memory review probes passed. PostgreSQL concurrency, live delivery and `check.sh` were not verified. No files modified, committed or pushed.

**Verdict: APPROVE.**