# AI-1b — Codex code review 3 (verbatim)

Model gpt-6-astra, read-only sandbox, 21 Nov 2026. After 3 repair cycles the two remaining findings were escalated to Mike, who chose: fix both and run one more review (21 Nov 2026).

---

REQUEST CHANGES

1. **Blocking — HIGH — Finding 2 remains partially resolved: admission is not atomic with settlement.** [ai_chat.py:190](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:190). Recorded spend is read **before** acquiring the reservation lock. Reproduced: B reads 480p while A holds 15p; A records its 15p and releases its reservation; B then acquires the lock and admits another 15p against its stale 480p reading. Recorded spend plus reservations becomes **510p against a 500p budget**. This occurs within one process. Per-attempt and failover reservations are implemented, but the concurrency guarantee still fails. The spend read and reservation decision must be coordinated with settlement.

2. **Blocking — MEDIUM — New regression: unrecorded costs never expire at month rollover.** [ai_chat.py:195](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:195), [ai_chat.py:208](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:208). Reservations and unrecorded costs are keyed only by business, with no period or expiry. Failure scenario: 500p of November costs cannot be recorded; in December, recorded monthly spend resets to zero, but the retained 500p still blocks Starter’s stronger model. Reproduced refusal with zero current-month spend and 500p retained unrecorded. This contradicts “It starts again on the 1st.” Track costs by billing period and define settlement across rollover.

3. **Resolved — Finding 4, previously MEDIUM: final truncation warning.** [assistant_chat.py:954](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:954). The previous failure scenario—five tool rounds followed by a truncated final answer—now appends the warning. The regression test passes.

4. **Resolved — Finding 9, previously MEDIUM: empty answers falsely claiming success.** [assistant_chat.py:961](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:961). Two empty responses with no executed tools now produce an inability-to-answer message. A prepared-card claim requires an actual proposal. Regression tests pass with and without a preceding tool round.

5. **Optional hardening — LOW — Finding 8 partially resolved.** [ai_chat.py:87](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:87). Follow-up chains and the original “Change my account name” example now pass. However, after a profit question, **“Can you change my account name?”** still selects `chat_complex`: the new-topic detector only recognises verbs at the beginning. Reproduced; this need not block the safety fixes.

Previously resolved findings **1, 3, 5, 6 and 7 show no regression in this targeted review**.

Verification: **78 tests passed**, including the single-process configuration test; ledger tests used in-memory SQLite to accommodate the read-only sandbox. Additional controlled reproductions confirmed the race and retained-cost defects. `check.sh` and live-provider tests were not run. No files modified, commits or pushes.

As this is the final repair cycle, findings 1–2 above require escalation to the owner.