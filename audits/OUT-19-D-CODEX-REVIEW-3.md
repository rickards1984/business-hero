**P1 — Retained reviews still bypass shared-mailbox capacity across brands.**  
[outreach_research.py:743](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:743) counts unplaced contacts only for the current brand; they never reduce shared-mailbox availability.

Reproduced with two brands sharing a five-capacity inbox: brand A retains **five reviews**, leaving its room at zero. Brand B still sees **five places**, purchases another search and accepts five contacts—**ten retained against five places**. Review-2’s first P1 remains partially open. Retained reviews need durable mailbox-capacity accounting and a cross-brand regression.

**P2:** No additional defects found.

The other findings are closed: `_unstore` removes only the newly inserted prospect and evidence within the same uncommitted transaction; renewal requires matching ownership; exception cleanup releases claims and re-raises `KeyboardInterrupt`; lock order is unchanged. The `min()` calculation does not double-count `_today_counts()`.

**Verification:** All 37 capacity tests passed using an in-memory SQLite fixture. Targeted in-memory removal of the fixes caused the corresponding behavioural regressions to fail. No files modified. `check.sh` and PostgreSQL verification were not run.

**Backlog:** PostgreSQL contention/lease-expiry and DST coverage remain outstanding.

**Verdict: REQUEST CHANGES — North Star P8.**