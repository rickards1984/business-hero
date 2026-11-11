# OUT-13 core — Codex DESIGN review 1 (verbatim)

Read-only review completed on `ticket/OUT-13-erasure-core`, against North Star P8/P9 and correctness. Nothing modified, committed or pushed. Tests were not run. Schema conclusions below concern repository migrations, not verified production state.

1. **P1 — The shared cutoff predicate exempts the very dispatch it must stop.**

   **Where:** Ticket C1–C2; `outreach_send.prepare_claim()` and `dispatch()`.

   **Scenario:** A first email is claimed before day 28. Claim commits a `claimed` message and an `executing` card. At dispatch, C1 now classifies the prospect as unresolved, so `past_cutoff = never contacted AND deadline passed` is false. Using that predicate everywhere permits transport after the deadline. Separately, “claim refuses, as today” preserves the existing 30-day check unless explicitly changed.

   **Change:** Separate the effective deadline, evidence of contact, erasure eligibility, and send admission. A first-send deadline check must apply despite its own claim/executing state. Apply the 28-day effective deadline at claim and immediately before transport, using a fresh clock after lock waits and other checks. Preserve the notice exemption for follow-ups and enforce retention independently. Define how related-table evidence reaches the helper: `past_cutoff(prospect, moment)` cannot determine C1 from the prospect row alone.

2. **P1 — Unresolved first sends can retain never-emailed people indefinitely.**

   **Where:** C1, C4; `outreach_send.dispatch()`; `outreach_replies.reconcile()`.

   **Scenario:** The process dies after committing claim but before transport. The message remains `claimed`, its card remains `executing`, and the session-only dispatch permit is lost. Every erasure pass skips it forever. The inspected reconciliation function explicitly accepts only `reply_outreach`; it does not resolve first-email claims. Logging an unresolved count provides no exit.

   Also, an imported message or arbitrary reply is not proof that this system’s notice was supplied. C1’s “Notice has been given” overstates what its conservative preservation rules establish.

   **Change:** Specify first-send reconciliation, including safe recovery of abandoned pre-transport claims and authoritative treatment of uncertain outcomes. Give unresolved cases an owner-visible age, escalation path and explicit retention exception. Distinguish “preserve because contact may have occurred” from “notice is evidenced”; never infer non-delivery merely from elapsed time.

3. **P1 — Reusing the existing memory API breaks atomic erasure.**

   **Where:** C3; `aria_memory._write()`, `delete()` and `_change()`.

   **Scenario:** C3 promises one transaction but directs deletion through memory’s existing locked read-modify-write. `_write()` commits; unsuccessful operations can roll back. Calling these helpers during erasure can commit partial deletion, release the business lock, or undo earlier work. A later failure leaves copies behind after the prospect—and therefore its work-list entry—has gone.

   **Change:** Introduce a transaction-neutral memory mutation for this operation. Acquire `business_settings` first, read its current document, apply memory and guard changes coherently, and commit exactly once after all erasure work succeeds. Test failure after each phase, including memory and chat mutation, for complete rollback.

4. **P1 — Concurrent chat and memory writers can restore erased identifiers.**

   **Where:** C3; `assistant_chat.process_chat_message()` / `save_message()`; `aria_memory.propose()`.

   **Scenario:** Chat loads the prospect or conversation before erasure and waits for a model response. Erasure redacts existing messages and commits. Chat then inserts a new response containing the same email/name through a separate connection without the business lock. A delayed memory proposal can similarly acquire the settings lock *after* erasure and recreate a removed entry. Serialization alone does not reject stale content.

   **Change:** Define a write-time policy for in-flight conversations and memory proposals, such as checking an erasure generation and revalidating/redacting stale output before persistence. Include delayed-response and delayed-memory PostgreSQL tests. Best-effort matching can acknowledge unidentified references; it should not silently exempt predictable restoration of the exact identifiers just erased.

5. **P1 — Immediate hiding misses action cards and inherited evidence fields.**

   **Where:** C2; `aria_actions.get()`, `list_open()`, `_view()`; `outreach_read._project()` and evidence reads; migration 035/037 SELECT policies.

   **Scenario:** Cleanup is delayed. The prospect projection hides fields, but an existing card still returns recipient, body, source and unsubscribe URL unchanged. Evidence is expired according to its own `expires_at`, not the prospect’s cutoff; its `source_url` survives even the current evidence-expiry projection. Additionally, authenticated members have direct SELECT access to prospects, evidence and actions under tenant-membership policies without cutoff filtering.

   **Change:** Enumerate the complete read boundary. Apply prospect cutoff handling to action previews and child evidence, including identifying URLs. Decide explicitly whether “hidden” means application presentation only or all client-readable access; backend projection changes alone cannot promise the latter. Test delayed physical cleanup through each supported read path.

6. **P1 — `qualified()` does not cover every card-creation path.**

   **Where:** C2; `outreach_research._prepare_cards()`, `outreach_autopilot.send_next()`, `aria_actions.propose()`, `outreach_send.build_payload()`.

   **Scenario:** Manual preparation calls `qualified()`, but scheduled preparation and autopilot call `propose()` directly. `build_payload()` does not call `qualified()`. An expired prospect can therefore receive a new card and unsubscribe token after cutoff while cleanup is delayed.

   **Change:** Put the authoritative cutoff check in the shared, business-locked proposal path before token creation. Keep manual qualification for useful refusal messages. Test scheduled preparation, autopilot and direct proposal creation, including waiting on a lock across the deadline.

7. **P1 — The deletion graph is incomplete for schema-valid cross-prospect references.**

   **Where:** C3; migration 037’s message self-FKs, dispatch-job FKs and usage-event FKs; migration 038’s reply-slot FKs.

   **Scenario:** `retry_of` and `reply_target_id` reference `(business_id, id)`, not prospect identity. Another prospect’s message can reference the message being erased. Handling self-references only “within the prospect’s own messages” leaves an incoming FK that blocks deletion on every pass.

   The basic order otherwise works for the ordinary unsent case: delete jobs, null usage `message_id`, delete messages, then enrolments/evidence/prospect. Nulling usage `message_id` also disables its nullable composite message FK. Batch reviews are parents of messages, so deleting a message does not require deleting its review. Retaining actions avoids their message/job FK problem. Replies and slots must remain exclusion checks, not be cascaded away.

   **Change:** Specify incoming-reference discovery across the tenant and an explicit policy for external references—safe unlinking where justified or a reported exception. Select linked cards through message/job action IDs as well as payload enrolment IDs; the schema allows messages without enrolments. Add PostgreSQL fixtures for external self-references, nullable enrolments, composite FKs, batch reviews and reply-slot exclusions.

8. **P1 — The copy inventory and exclusions contain factual gaps.**

   **Where:** C3; `assistant_chat.py` tool logging/model calls; `aria_memory` entries; `outreach_dashboard.mark_outcome()`; research summary persistence.

   **Scenario:** Chat logs tool arguments and the first 500 characters of tool results. Those can contain personal information. Chat also sends prospect information to a model provider, so “provider’s own copies (none for never-sent mail)” is only defensible if restricted to the outbound-mail provider.

   Memory has a `group` field outside the proposed matching fields. Dashboard outcomes persist separately under `outreach_outcomes[prospect_id]`. Previously stored research summaries can contain domains; normalizing future labels does not sanitize existing summaries.

   **Change:** Inventory these stores and explicitly erase, minimize or document each retained copy. Include existing summaries and memory groups. Correct the logging/provider statements. Define the purpose and lifetime of retained UUIDs, timestamps and outcome events: absence of a literal email/name/company does not establish that an audit row is unlinkable.

9. **P2 — Free-text replacement needs safeguards against corrupting unrelated history.**

   **Where:** C3; nullable prospect `name`/`email`; `assistant_messages.content`; `aria_memory._clean()`.

   **Scenario:** Research deliberately stores missing names as NULL. Naively converting that to an empty string before replacement can insert the marker throughout a message. Substring replacement can also alter another person’s longer name or address. Company co-occurrence in a message comparing several people is weak attribution. Conversely, exact matching misses case differences and normalized whitespace.

   **Change:** Specify nonempty matching inputs, literal escaping, address/name boundaries, normalization, idempotence and ambiguous-match behavior. Preserve message roles, ordering and unrelated text. Test nameless contacts, shared names, multiple companies, quoted text, URLs and repeated erasure. Describe this as bounded identifier redaction, not comprehensive erasure of free-text references.

10. **P2 — “Usual polling” does not exist for the relevant views.**

    **Where:** C2; `useOutreachData.ts`, `OutreachDashboard.tsx`, `queryClient.ts`.

    **Scenario:** A screen stays open across cutoff. `staleTime` does not periodically fetch; the global default is `refetchInterval: false`, and the inspected outreach views do not add an interval. Previously displayed personal data can remain visible despite correct server projections.

    **Change:** Specify expiry-aware local hiding and query invalidation/refetch for prospect, stage-list, dashboard and action caches. Define the actual display-refresh bound and test a continuously open tab crossing cutoff.

11. **P1 — The hourly cleanup bound lacks an executable, bounded work-list design.**

    **Where:** C4; migration 037 indexes; `automations.run_all_due()`; research and send business locks.

    **Scenario:** The existing prospect expiry index covers `retention_due_at`, not the proposed effective notice deadline. A broad scan with related-state checks can repeatedly inspect old contacted/unresolved records. Per-prospect chat searches then repeatedly scan the business’s history while holding the same settings lock needed by sending, research storage and owner settings changes. One blocked transaction can delay all following prospects despite per-prospect commits. Placing cleanup after synchronous research also delays its start.

    **Change:** Specify the candidate SQL, supporting indexes and representative query plans; bounded pages with stable cursors; lock/statement timeouts; and progress past failing candidates without starvation. Bound chat-redaction work and measure lock duration. Run cleanup before provider-dependent research or independently. Treat “about an hour” as a monitored target with backlog/oldest-overdue reporting, not a consequence of an hourly trigger. Include recovery after downtime and businesses lacking outreach settings.

12. **P2 — The digest guard needs explicit merge, pruning and size semantics.**

    **Where:** C5; `outreach_research._save_config()`; `outreach_setup._save_settings_doc()`; `main.preserve_automations()`.

    **Scenario:** The inspected writers generally lock and reread settings, and the generic settings endpoint preserves `outreach_*`; JSON storage is therefore not inherently unsafe. However, `_save_config()` replaces the research subdocument. Saving a configuration captured before taking the lock could overwrite newly added guards. Separate stale document snapshots for memory and research changes could also overwrite each other within erasure.

    After the last prospect is erased, a paused business may have neither research runs nor further erasure candidates. Candidate-driven pruning would retain its guards indefinitely. A growing 90-day array also increases every settings read/write while sharing the send-path lock.

    **Change:** Require locked fresh reads and preservation of unrelated keys; deduplicate guards and retain the latest applicable expiry. Prune businesses with guards even when they have no prospects or research is disabled. Define null-address/domain handling, normalization and digest versioning. Establish a measured size bound or choose indexed storage. Test concurrent research/configuration/memory saves and pruning an otherwise idle business.

VERDICT: CHANGES REQUESTED