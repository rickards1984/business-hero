Reviewed `f8a96b3` against the requested base under **North Star P8**. No files modified, committed or pushed.

**P1**

- **Concurrent drafts can exceed the £3 reserve without a bounded reservation.** [_ai_draft](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_setup.py:815) checks recorded spend, then releases the lock without reserving anything. Multiple requests can pass before any finishes; research also cannot see those pending costs. A deterministic interleaving probe admitted two £1 drafts at £27.74 spent, ending at **£29.74 against a £27.75 limit**. More overlapping requests increase the overrun. Reserve each draft’s cost under the shared business lock before calling providers, including failover, and settle afterwards. Add concurrent draft/draft and draft/research regression tests. The current implementation does not establish Mike’s profitability condition.

**P2**

- **Legacy research spend disappears from the new allowance.** [spent_pence](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_allowance.py:73) reads only the brand-specific research meter. Existing research `_spent` deliberately includes the pre-OUT-18 business-wide meter, failing closed against every brand. A probe with £19 legacy research, £1 brand research and 20p drafting returned **120p** from the new allowance calculation; the existing research calculation returned **2,000p** before drafting. Where legacy rows remain, raising the owner’s research budget permits expenditure the hidden ceiling should prevent. Preserve the conservative treatment or explicitly reconcile those rows, with a regression test.

- **Owner-facing messages advertise unavailable top-ups.** [Allowance refusal messages](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_allowance.py:100) say “Top up to carry on now” and “Top up, or write it yourself.” These reach research summaries and draft errors. The frontend’s separate “coming soon” warning does not correct them. Use consistent unavailable-until-F wording. Also distinguish the budget card’s projected brand commitments from actual billing, which part F has not implemented.

**Backlog / follow-through**

- Escape literal underscores in the ledger and top-up `LIKE` prefixes. `_` currently matches any character. **I found no collision among the current meter names:** normal research ledger rows are excluded correctly, so mirrored research is not double-counted.
- Part F must combine `can_charge`, a durable charge reservation and commitment updates under one lock. Today it is an unused predicate, not atomic charging enforcement.
- Replace the reply-sorting source-string assertion with a behavioural test proving classification still runs and records cost above the allowance. Add top-up accounting, inactive-owner, feature-denied, cross-tenant and concurrent-budget coverage.
- Restore the D/E integration review document deleted by this diff unless its removal is intentional.
- Before activating AI reply suggestions, apply allowance checking and metering to that adapter; its current callback boundary is not protected by `_ai_draft`.

The allowance arithmetic and oldest-brand ordering match the approved prices. Research checks the allowance under the shared reservation lock before reserving. Current setup drafting paths pass a brand through `_ai_draft`; classification remains deliberately ungated. Budget writes validate strict integer bounds, recheck active-owner authority under lock, and reject amounts below commitments. Both HTTP routes apply the feature gate; budget reads permit staff, consistent with the decision restricting **setting** to owners. The hidden allowance is exposed as a percentage, not its monetary value.

**Verification:** All **18 allowance tests passed** with a process-local in-memory SQLite adapter. The normal run was blocked by unavailable writable temporary storage. Research/draft stop tests exercise the new wiring, but the draft test’s fake incurs no cost and misses the reservation defect. Additional in-memory probes confirmed the race and legacy omission above. `check.sh`, browser behaviour and PostgreSQL concurrency were not verified.

**Verdict: REQUEST CHANGES.**