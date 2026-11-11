# OUT-13 core — Codex DESIGN review 2 (verbatim)

Read-only review of `ticket/OUT-13-erasure-core`, against North Star P8/P9 and correctness. Nothing modified, committed or pushed. Tests were not run; schema conclusions concern repository migrations, not verified production state. Migration 041 is proposed, not present.

Revision 2 resolves several original findings, but the deletion order and reconciliation design still block approval.

| Original finding | Revision 2 assessment |
|---|---|
| **1 — Cutoff predicate** | **Resolved at design level.** R1 separates send admission, hiding and erasure eligibility. The fresh pre-transport deadline check applies despite the dispatch’s own claim. Deployment transition remains unresolved below. |
| **2 — Unresolved first sends** | **Partially resolved.** Conservative wording and owner-visible escalation are improvements. The lease predicate misses existing claims, and manual negative reconciliation can erase an emailed person; findings 14–15 below. |
| **3 — Memory API commits** | **Resolved by Mike’s boundary.** Automatic erasure no longer calls memory mutation helpers. |
| **4 — Concurrent chat/memory restoration** | **Resolved by Mike’s boundary.** Retained conversational copies are explicitly outside automatic erasure. I found no direct background outreach writer into chat or memory. An owner’s chat can fetch outreach information and automatically persist it in the assistant’s reply (`assistant_chat.py:913`), including a reply completing after erasure. That is consistent with the stated boundary, but the title’s “everywhere” claim should be removed. |
| **5 — Read boundary** | **Substantially resolved.** R3 names cards, evidence and identifying URLs, and honestly limits hiding to application presentation. Direct authenticated SELECT remains possible until physical deletion—and indefinitely for preserved exceptions. Say that explicitly rather than suggesting R5 bounds every case. |
| **6 — Alternative card-creation paths** | **Resolved at design level.** The shared, locked `build_payload(one_card=True)` check before token creation covers the identified proposal paths. |
| **7 — Deletion graph** | **Partially resolved.** Cross-prospect message references now prevent erasure and nullable-enrolment cards are discoverable. However, the new card-first order fails ordinary FKs, and cross-prospect exclusions lack an owner-visible resolution path; findings 13 and 19. |
| **8 — Copy inventory** | **Partially resolved.** Outcomes, existing research summaries and mail-versus-model provider copies are addressed. R5 removes tool-result logging but must also explicitly remove tool-argument logging at `assistant_chat.py:871`; arguments can contain personal information. The claim that contacts “never reach Railway logs from chat” is otherwise unsupported. Existing logs remain an acknowledged external retention boundary. |
| **9 — Free-text corruption** | **Resolved by Mike’s boundary.** Automatic free-text redaction is removed. Replace the superseded chat/memory deletion tests so they cannot reintroduce it. |
| **10 — Browser polling** | **Partially resolved.** Explicit polling improves connected foreground behaviour, but does not establish the asserted five-minute maximum; finding 20. |
| **11 — Bounded cleanup** | **Partially resolved.** Running first, candidate transactions and monitoring help. Cross-run progress, query/index alignment, transaction budgeting and missing settings remain unresolved; findings 17–18. |
| **12 — Digest guard** | **Resolved in architecture.** A separate tenant-keyed table, maximum-expiry upsert and global pruning address the previous JSON overwrite and idle-business problems. Specify version 1 explicitly, matching only unexpired rows, and an expiry index/bounded pruning operation. These are implementation requirements, not a separate blocker on the evidence inspected. |

New and remaining actionable findings:

13. **P1 — Card-first deletion fails immediately; sharing a transaction does not defer these FKs.**

    **Where:** [Ticket R5](/Users/michaelrickards/dev/bh2-OUT-13/docs/OUT-13-CORE-TICKET.md:86); [migration 037](/Users/michaelrickards/dev/bh2-OUT-13/backend/migrations/037_outreach_core.sql:401), lines 510–511; [migration 038](/Users/michaelrickards/dev/bh2-OUT-13/backend/migrations/038_outreach_replies.sql:76).

    **Scenario:** An erasable prospect has a failed message referencing its card. Step 1 deletes the card while that message and its dispatch job still exist. These FKs are immediate, without cascading deletion, so PostgreSQL rejects the statement. Every subsequent pass repeats the failure.

    Checking only this prospect’s reply slots is also insufficient for schema-valid external references: a slot’s standalone `action_id` FK does not establish that the card belongs to the slot’s prospect. Similar inconsistencies are possible between payload-based card discovery and message ownership.

    **Change:** Discover and validate the complete deletion set first. Delete jobs, unlink usage/self-references and delete messages **before** deleting cards. Check incoming references to selected cards across the tenant; preserve and report external dependencies. I found the three declared action-FK holders named above, with no additional SQL FK to `aria_actions` in the searched migrations. Test both ordinary failed sends and external card references on PostgreSQL.

14. **P1 — Abandoned-claim reconciliation selects a lease the sender never creates, and does not explicitly retire dispatch authority.**

    **Where:** Ticket R2; [claim insertion](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_send.py:419); [dispatch ordering](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_send.py:424).

    **Scenario:** Current claims leave `lease_until` NULL. A process dying after claim commit therefore never satisfies “lease expired more than an hour ago.” Its claimed message/executing card survives indefinitely, outside R2’s stated uncertain-transport exception.

    The marker itself is useful evidence: dispatch commits `dispatch_started_at` **before** calling the provider. Under the business lock, a fresh NULL marker proves this dispatch has not yet handed off. Lease expiry alone does not prove the worker is dead or prevent it resuming. R2 lists message, reservation and card changes but omits the required terminal job transition. Dispatch’s final CAS checks the **job**, not a freshly reread card status.

    **Change:** Define legacy NULL-lease handling and the future lease lifecycle—or use a defined claim-age policy. Under the shared lock, reread state and atomically change the job from `claimed` to a terminal state alongside settlement. A resumed dispatcher must lose its CAS and never call transport. Test both lock orderings and a paused original worker resuming after reconciliation.

15. **P1 — “It wasn’t sent” is not authoritative non-acceptance and can erase an emailed person.**

    **Where:** Ticket R2; [transport and settlement](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_send.py:467); [terminal metering states](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/metering.py:896); existing reconciliation at `outreach_replies.py:510`.

    **Scenario:** Dispatch commits its marker, then waits for the provider. The owner sees no Sent-folder entry yet and selects “It wasn’t sent.” If reconciliation releases usage and marks the send failed, erasure can proceed. The provider subsequently accepts the email; later settlement cannot repair a released terminal usage event. The emailed recipient has been erased.

    Separately, merely changing the message to `failed`, as R2 states, leaves its executing card and reservation unresolved.

    **Change:** Preserve uncertainty until independently verified acceptance or definite non-acceptance for the original operation. Absence from Sent is not sufficient. Specify terminal transitions for job, message, card and usage, including fencing against late settlement and idempotent repeated reconciliation. Accepted reconciliation must preserve provider/thread evidence needed by follow-ups. An owner report can initiate verification without making the record erasable.

16. **P1 — Migration 041 lacks a safe transition for deadlines shortened into the deployment hour.**

    **Where:** Ticket R1/R4; [current dispatch](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_send.py:424).

    **Scenario:** A 29-day-old prospect has an approved claim under the current 30-day deadline. Migration 041 moves its deadline into the past. An old application process still has dispatch authority and no deadline check in `dispatch()`, so it can send after the new cutoff. Conversely, a newly blocked dispatch must be settled as definitely not transported; leaving it claimed creates another retention exception.

    Proposed cards may also remain visible in existing clients during this transition.

    **Change:** Specify rollout ordering: install compatible admission/dispatch checks before shortening deadlines, prevent old senders continuing through the cutover, and account for all existing claims. Define treatment of proposed cards, unstarted claims and already-marked/in-flight transport separately. Preserve possible sends; terminally settle proven non-transport. Include a staging cutover test with each state and verify the immediate backlog/owner-visible exceptions.

17. **P1 — The work list does not yet guarantee progress across hourly runs or bounded candidate execution.**

    **Where:** [Ticket R4](/Users/michaelrickards/dev/bh2-OUT-13/docs/OUT-13-CORE-TICKET.md:65).

    **Scenario:** Enough old preserved or failing candidates consume the 120-second budget. If the next hourly pass starts at the beginning, later never-contacted prospects are never reached. “Resumes next hour” does not define a durable cursor, wraparound or retry policy.

    The query also omits `notice_due_at` from its selected cursor values, and its `(notice_due_at, id)` ordering does not match the proposed `(notice_due_at, business_id, id)` index. Candidate-local timeouts do not bound page selection. A 30-second statement timeout applies to each statement, not the whole multi-statement candidate transaction.

    **Change:** Specify durable progress with fair wraparound/retry of skipped candidates. Return the full keyset key and align ordering, predicate and index. Bound page queries, pruning and total candidate time as well as individual statements. Separate actionable overdue backlog from preserved exceptions in monitoring. Test a permanently blocked prefix larger than one run’s capacity and recovery after downtime.

18. **P1 — Cleanup cannot currently run without an outreach settings row.**

    **Where:** Ticket R4/R5; [send.lock_business](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_send.py:120).

    **Scenario:** R4 promises every business “whatever its … settings row.” The chosen lock helper ensures `business_settings`, but then requires an `outreach_settings` row. A schema-valid prospect without that row fails every erasure attempt.

    **Change:** Define an erasure-compatible lock path that retains the established lock ordering while tolerating absent outreach settings. Do not silently provision operational settings merely to delete data. Test a prospect in a business lacking each settings row.

19. **P1 — Additional permanent exclusions contradict the “one retention exception” promise.**

    **Where:** Ticket R1, R2 and R4.

    **Scenario:** A never-emailed prospect has an incoming cross-prospect message reference. R1 permanently excludes it, but R2’s owner-visible exception only covers uncertain transport. An executing card without a reconcilable job has the same gap. Generic pass counts and oldest-overdue logging do not give the owner a resolvable exception.

    **Change:** Give every blocked erasure a classified reason, age and owner-visible resolution/escalation path. Distinguish evidenced contact, transport uncertainty, dependency conflicts and corrupt/orphaned state. Provide safe repair rules for dependencies rather than silently retaining them indefinitely.

20. **P2 — Polling does not enforce the promised five-minute display limit.**

    **Where:** Ticket R3; [useOutreachData](/Users/michaelrickards/dev/bh2-OUT-13/frontend/client/src/hooks/useOutreachData.ts:8); `frontend/client/src/lib/queryClient.ts`.

    **Scenario:** A tab crosses cutoff while offline, its refetch fails, or the browser suspends background activity. Previously successful query data remains rendered. Refetching on focus does not itself hide that data while the request is pending or failing. R3 also needs to cover contact-detail queries, not only dashboard, stage lists and home cards.

    **Change:** Apply expiry-aware local hiding to every relevant cached projection, including resumed tabs, and use polling for freshness. Alternatively, explicitly narrow the promise to successful connected refreshes. Test cutoff crossing with a failed fetch, background/resume and an already-open contact detail.

VERDICT: CHANGES REQUESTED