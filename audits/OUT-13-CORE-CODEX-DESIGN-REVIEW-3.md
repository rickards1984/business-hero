# OUT-13 core — Codex DESIGN review 3 (verbatim)

Read-only review of `ticket/OUT-13-erasure-core`, serving North Star P8/P9 and correctness. Nothing modified, committed or pushed. Tests and live-database checks were not run.

| Previous finding | Revision 3 assessment |
|---|---|
| **1 — Cutoff predicates** | **Resolved at design level.** Separate admission, hiding and erasure predicates remain. T1’s 28-day calculation matches the repository’s prospect writer; live-data qualification below. |
| **2 — Unresolved first sends** | **Resolved for first sends.** Claim age replaces the unused lease; fencing prevents resumed transport; uncertainty remains owner-visible. T3’s broader job selection has a reply-send problem below. |
| **5 — Read boundary** | **Resolved.** T9 explicitly acknowledges direct SELECT and retained exceptions. |
| **7 — Deletion graph** | **Resolved at design level.** T7 discovers the deletion set, checks external references and deletes dependent rows before cards. |
| **8 — Copy inventory** | **Resolved.** Tool arguments and results are covered; retained chat, logs and model-provider copies have explicit boundaries. |
| **10 — Browser visibility** | **Resolved at design level.** Local deadline hiding covers failed fetches and contact detail. |
| **11 — Bounded cleanup** | **Partially resolved.** Query ordering, timeouts, missing settings and monitoring improve; cross-pass starvation remains. |
| **12 — Digest guard** | **Resolved.** Version, expiry matching, expiry index and bounded global pruning are specified. |
| **13 — Card-first deletion** | **Resolved.** T7 corrects the immediate-FK ordering. |
| **14 — Abandoned claims** | **Partially resolved.** The age policy and CAS fence work; existing settlement cannot handle every unstarted job selected by T3. |
| **15 — Owner-declared non-acceptance** | **Resolved.** T4 removes the unsafe negative confirmation. |
| **16 — Deadline transition** | **Resolved with the stated rolling-deploy limitation.** No deadline backfill meets old code. Old workers can still send under their previous rule during overlap; this is explicitly acknowledged. |
| **17 — Work-list progress** | **Not resolved.** A 24-hour exception cooldown does not guarantee fairness. |
| **18 — Missing settings** | **Resolved at design level.** T8 tolerates absent rows without provisioning them. |
| **19 — Invisible exclusions** | **Resolved for processed candidates.** T5/T6 classify and display blocked erasures. Candidates starved before processing remain uncovered. |
| **20 — Polling limit** | **Resolved at design level.** T9 replaces successful-refetch dependence with local hiding. |

The mechanism checks establish:

- **T1:** [`outreach_research._store`](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_research.py:878) writes both timestamps from the same `moment`, with `NOTICE_WITHIN = 30 days`. I found no other production prospect insertion or import writer in the repository. This supports the calculation for repository-created prospects, but not the universal claim about existing data: migration 037 permits NULL or earlier `notice_due_at` values and imposes no corresponding timestamp constraint.
- **T2:** The proposed check fits dispatch’s caught `ActionRefused` block. The normal blocked path commits the marker and settles definite non-acceptance. However, mailbox validation after the CAS can still raise before settlement; T3 must recover those unstarted claims. “Never left claimed” is therefore stronger than the existing path guarantees.
- **T3:** **The CAS is a real transport fence.** Dispatch consumes its session-local permit, requires a committed claim, performs the conditional UPDATE and requires one affected row before transport. Stale preliminary reads cannot bypass that UPDATE. Fence and settlement must commit atomically.
- **T7:** The ordinary deletion order matches migrations 037/038/035: jobs first, usage and self-reference unlinking, messages, then cards. “Any incoming reference” must include dispatch-job references too, not only the two listed examples. Migration 037 declares an independent job-to-card FK.

Remaining findings:

21. **P1 — Daily exception expiry can recreate permanent starvation.**

    **Where:** [T5, candidate query and fairness](/Users/michaelrickards/dev/bh2-OUT-13/docs/OUT-13-CORE-TICKET.md:56).

    **Scenario:** A permanently blocked prefix takes at least 24 hourly passes to process within the 120-second budget. Before the worker reaches its end, the earliest exceptions become eligible again. Every pass restarts at the beginning, so daily rechecks consume all capacity indefinitely. Later never-emailed prospects remain past deadline without their own owner-visible exception. An aggregate backlog alert does not supply that exception.

    **Change:** Persist forward progress across runs with wraparound, or give previously unprocessed candidates a separate guaranteed processing budget from exception retries. Test a blocked prefix exceeding **24 passes’ capacity**, including advancing the clock through cooldown expiry.

22. **P1 — T3 selects unstarted reply jobs that `_settle` cannot terminally settle.**

    **Where:** [T3](/Users/michaelrickards/dev/bh2-OUT-13/docs/OUT-13-CORE-TICKET.md:30), [`_settle`](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_send.py:507), [migration 038 reply-slot constraints](/Users/michaelrickards/dev/bh2-OUT-13/backend/migrations/038_outreach_replies.sql:82).

    **Scenario:** A reply claim commits, then its worker dies before dispatch. T3 selects it after an hour because its job is `claimed` with no dispatch marker. `_settle(definitely_not_accepted)` changes its reply slot to `unknown`, but that slot still has NULL `dispatched_at`. Migration 038 requires `unknown` slots to have a dispatch timestamp. PostgreSQL rejects the update and rolls back settlement; job, message, card and usage do not terminate as promised.

    For an ordinary initial-send claim, the proposed settlement does correctly produce failed job/message/card and released usage.

    **Change:** Explicitly restrict this erasure reconciler to initial-send jobs, or define a separate valid settlement for unstarted replies that preserves reply-slot safeguards. Add a PostgreSQL test for a committed reply claim whose dispatch never began.

VERDICT: CHANGES REQUESTED