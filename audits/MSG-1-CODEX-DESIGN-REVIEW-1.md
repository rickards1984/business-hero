# MSG-1 — Codex DESIGN review 1 (verbatim)

Reviewed docs/MSG-1-DESIGN.md (design only, no code) on 08761b6.

Reviewed `08761b6e47381727dbb52fc27b1ffc286928f448`, after reading `AGENTS.md` and `docs/NORTH_STAR.md`. No files changed. This review assesses P2, P4, P7 and P9: grounding, approval, routing and tenant isolation. These are design findings, not claims that the proposed implementation already contains vulnerabilities.

1. **P1 — Migration 047 assumes a conversation table that already exists.**

   **Where:** Design §5.1, lines 88–95. [assistant_chat.py](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:620), `get_conversation`, `create_conversation` and `resolve_conversation`, already use `assistant_conversations`, including `updated_at`. The checked-in [schema snapshot](/Users/michaelrickards/dev/bh2-MSG-1/audits/live-schema-public.txt:125) agrees; it is not proof of current production state.

   **Change:** Specify an additive alteration of the existing table, preserving ownership, IDs and compatibility with the old endpoint. Backfill only demonstrably missing data after checking constraints and orphans. Include live-schema verification, staging rehearsal, RLS/grant changes and rollback before deployment—not a generic “create and backfill” migration.

2. **P1 — Tenant isolation does not cover relationships or offline storage.**

   **Where:** §§4.1, 5.1 and 5.8. Existing [resolve_conversation/load_conversation_history](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:667) distinguish conversation ownership from business membership. Existing [AuthContext.signOut](/Users/michaelrickards/dev/bh2-MSG-1/frontend/client/src/contexts/AuthContext.tsx:120) signs out but has no messenger-cache cleanup.

   Adding `business_id` alone does not prevent an attachment pointing to another tenant’s message, or a queued message being submitted after the device switches accounts/businesses.

   **Change:** Define user-private versus business-shared conversations; validate every linked message, attachment, document, card and job against that ownership model. Partition caches and queues by authenticated user **and** business, purge on logout, and revalidate queued work before submission. Require cross-tenant, same-business/different-user, revoked-membership and account-switch tests.

3. **P1 — Message deduplication does not make a chat turn idempotent.**

   **Where:** §§5.1–5.2. `client_message_id` promises only that a resent message is stored once. [process_chat_message](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:747) separately saves the user message, calls providers, executes tools and saves the reply.

   A reconnect after draft creation but before the final SSE event can therefore repeat spend, cards, documents or quotes even if the user-message insert is deduplicated.

   **Change:** Introduce a durable turn operation with a scoped unique key, request fingerprint, atomic claim, execution state and replayable result. Give side effects stable operation keys. Specify reconnect, concurrent submission, crash recovery and unknown-outcome behaviour. Never automatically replay approval requests from an offline queue.

4. **P1 — The promised quote approval card does not exist, and Drive approval is contradictory.**

   **Where:** §§4.2, 5.3 and D4. [aria_actions.CHAT_ACTION_TYPES](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/aria_actions.py:36) contains four chat actions; `send_quote` is absent. [assistant_tools._send_quote_via_aria](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_tools.py:3153) only directs the owner to the Quotes page.

   D4 also permits standing permission or direct Drive saves despite the requested “nothing outward without a tap” boundary.

   **Change:** Either retain the existing Quotes-page send flow explicitly, or ticket a new reviewed quote-send action. Specify Drive saves as exact-content, exact-destination approvals using the existing versioned, durable claim pattern in [aria_actions.approve](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/aria_actions.py:609). Remove the untapped alternative unless Mike explicitly changes the boundary.

5. **P1 — The prompt-injection acceptance criterion is weaker than the stated rule.**

   **Where:** §2 says an external instruction requires the owner to ask and approve; §5.10 merely tests that injection produces “at most a card.” Meanwhile §§4.2 and D3 introduce immediate internal writes.

   [assistant_chat._execute_tool_async](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:22) currently converts model-requested actions into proposals. [test_aria_no_unapproved_actions.py](/Users/michaelrickards/dev/bh2-MSG-1/backend/tests/test_aria_no_unapproved_actions.py:1) already demonstrates why prompt wording and advertised tool lists are insufficient.

   **Change:** Define separate server-enforced capability sets for interactive turns and jobs. Tie mutations to the authenticated owner’s requested task; fetched text must not supply authority. Test injected recipients, bank-detail substitutions, document/task creation, scheduling and summary poisoning—not just sending. Payments, refunds and bank-detail changes must remain unavailable even through an approval card.

6. **P1 — A timestamp does not prove the exported quote was reviewed.**

   **Where:** §5.3. [quoting_api.update_quote](/Users/michaelrickards/dev/bh2-MSG-1/backend/quoting_api.py:437) changes prices, customer details, terms and line items. [_get_quote_pdf_data](/Users/michaelrickards/dev/bh2-MSG-1/backend/quoting_api.py:759) reads the current quote and current company settings.

   After review, an edit—or a change between card display and approval—could produce an unreviewed PDF while `reviewed_at` remains populated.

   **Change:** Bind review and export approval to a content revision/hash, including material PDF inputs. Invalidate review after relevant edits; reject stale approvals. Define treatment of existing quotes and apply the rule consistently to PDF generation, download and Drive export. Build displayed totals from `create_quote`’s persisted, server-calculated result, with database grounding tests.

7. **P1 — Attachment security stops at signed download URLs.**

   **Where:** §§5.1, 5.4 and 5.10. The proposed metadata requires `message_id`, but the upload-before-send lifecycle is unspecified. The current [generate_ai_quote](/Users/michaelrickards/dev/bh2-MSG-1/backend/quoting_api.py:1146) is an image-consuming endpoint, not a reusable private attachment repository.

   **Change:** Specify authenticated upload reservation/finalisation, server-generated immutable object keys, tenant-bound attachment lookup, storage policies denying direct client access, aggregate quotas and abandoned-upload cleanup. Validate decoded content, pixel counts and decompressed PDF/DOCX size, with parser timeouts. Define deletion of both rows and objects. Rendering must not fetch arbitrary embedded URLs or execute active content; signed URLs must not become permanent message payloads.

8. **P1 — “Separate Drive connection” lacks a separate credential and consent design.**

   **Where:** §5.5. Existing [oauth_utils.get_valid_access_token](/Users/michaelrickards/dev/bh2-MSG-1/backend/providers/oauth_utils.py:125) refreshes credentials into `email_accounts`; Microsoft refresh uses mail scopes. Existing [OAuth URL builders](/Users/michaelrickards/dev/bh2-MSG-1/backend/app/email/router.py:203) use the email integration’s clients and callbacks.

   A separate button does not establish independent token storage or revocation. Google documents that revoking combined authorisation revokes its scopes together. [Google OAuth documentation](https://developers.google.com/identity/protocols/oauth2/web-server)

   **Change:** Design tenant/user-bound Drive connection records, provider identity, scopes, callback state, refresh handling and disconnect semantics. Bind each save card to the chosen connection and destination; never silently substitute a reconnected account. Resolve consent isolation explicitly. Also validate OneDrive account types: Microsoft documents delegated `Files.ReadWrite.AppFolder` as personal-account-only, so D5 is not merely a folder preference. [Microsoft permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)

9. **P1 — A database claim is insufficient background-job recovery.**

   **Where:** §5.6. [briefing_scheduler._scheduler_loop](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/briefing_scheduler.py:207) is a periodic process loop; it does not supply the proposed job execution state machine. The existing [chat loop](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:889) caps rounds, but executes every tool call within a round.

   **Change:** Define leases, heartbeat/fencing, checkpoints, attempt limits, cancellation checkpoints and idempotent steps. Separate recurring schedules from individual runs, with unique scheduled-run keys, timezone/DST and missed-run rules. Recheck membership, entitlements and provider availability before execution. Count individual tool calls, bound result sizes and elapsed time, and define whether `waiting_approval` ends preparation or later resumes work. A recovered worker must never repeat uncertain effects.

10. **P1 — `require_priced` does not enforce the proposed allowance or job budget.**

    **Where:** §§5.2, 5.6–5.7. [ai_costs.require_priced](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/ai_costs.py:139) only verifies a model’s price. [ai_chat.turn](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/ai_chat.py:465) reserves the deeper-thinking budget only when `budget_business` is supplied; ordinary chat does not receive that protection.

    **Change:** Specify atomic admission/reservation and settlement for all billable work, including concurrent chat/jobs, fallbacks, vision, summaries and uncertain provider outcomes. Separate customer allowance from platform cost accounting: `ai_pence` includes other purposes and estimated costs. Reconcile “nothing cut off mid-turn” with a bounded reservation before admitting the turn. The platform kill switch cannot substitute for per-business enforcement.

11. **P1 — Credits/top-ups have neither a stable unit nor a settlement contract.**

    **Where:** §5.7 and D6. Variable-cost pence cannot simultaneously guarantee “one message = one credit.” Changing a conversion constant can also change the purchasing power of existing credits. At the example 2p cost, 250 messages consume the entire £5 selling price before payment fees and other costs.

    The relevant precedent is [outreach_billing.start_topup/apply_page_event](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/outreach_billing.py:655), which reserves purchases, validates payment ownership/amount and credits paid sessions once—not merely `backend/app/billing`.

    **Change:** Choose fixed message credits or clearly labelled variable usage credits. Define immutable purchase terms, consumption order, expiry/carryover, period boundaries, plan changes and refunds/disputes. Require a durable purchase ledger, verified paid-webhook settlement, replay protection and reconciliation. Price against explicit margin assumptions; keep purchase execution outside Aria’s tools.

12. **P1 — The cited Apple rule does not justify web-only top-ups.**

    **Where:** §§5.7 and 5.9. Apple §3.1.3(b) permits cross-platform purchases subject to those items also being available through IAP; another applicable exception or regional arrangement would need its own justification. [Apple guidelines](https://developer.apple.com/app-store/review/guidelines/)

    The shared bundle also exposes [BillingSettings](/Users/michaelrickards/dev/bh2-MSG-1/frontend/client/src/pages/BillingSettings.tsx:76), which redirects to Stripe checkout and its portal. Hiding a purchase link in the messenger therefore does not make the native app consumption-only.

    **Change:** Choose and document a compliant distribution/payment model per platform and storefront before MSG-5/7. Audit every reachable billing route in the native bundle. Google permits consumption-only apps, but that is a distinct policy basis. [Google payments guidance](https://support.google.com/googleplay/android-developer/answer/10281818?hl=en)

13. **P1 — Account deletion is a new security/data lifecycle, not an AMBER release checklist item.**

    **Where:** §§5.4, 5.9 and MSG-7. Current [AuthContext.signOut](/Users/michaelrickards/dev/bh2-MSG-1/frontend/client/src/contexts/AuthContext.tsx:120) only signs out; conversation ownership is separately stored by [create_conversation](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:635). “Delete account” and “delete business” therefore need distinct semantics.

    **Change:** Create a RED deletion design covering membership, sole-owner handling, shared business records, jobs, tokens, attachments, caches, subscriptions and justified retention. Specify what happens to exported Drive files. Include an authenticated, retryable deletion workflow and a public deletion-request route: Google requires an outside-app web path as well. [Google deletion requirements](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en)

14. **P1 — New stored data lacks the required Aria read tools and grounding contract.**

    **Where:** §§5.1, 5.4 and 5.6. [assistant_tools.execute_tool](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_tools.py:664) dispatches named tools; adding tables or placing IDs in message payloads does not make their contents accessible to Aria. Current [load_conversation_history](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:667) loads only role/content.

    **Change:** Include tenant-scoped list/get tools for documents, attachments, job status/schedules and allowance state in their owning tickets. Define citation resolution and freshness, plus how rich records survive history trimming and summaries. Add grounding tests for quote totals, brief figures, balances and usage. This is an explicit North Star §8 requirement.

15. **P2 — The briefing baseline and retirement plan are stale.**

    **Where:** §§3, 4.3 and D7. [briefing_scheduler._check_and_send_scheduled_messages](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/briefing_scheduler.py:343) delegates to `whatsapp_briefings`. That [service](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/whatsapp_briefings.py:1) explicitly retires the daily pulse in favour of deterministic weekly/monthly summaries without AI calls.

    **Change:** Name the actual channels being replaced and preserve independently configured reminders/alerts. Specify per-user scheduling and conversation destination; a new messenger brief must work without `whatsapp_configs`. Deduplicate scheduled and early-open generation by local date, and define freshness. Although morning briefs are free to the customer, any model cost still belongs in platform metering and budgets.

16. **P1 — Ticket dependencies omit required safety work and migrations.**

    **Where:** §6. MSG-1 promises allowance admission but MSG-5 depends on MSG-1; beta starts before MSG-5. MSG-6 creates `push_devices` but is AMBER and absent from the migration sequence. MSG-7 includes deletion/auth-related work but is AMBER. Drive connection and consent storage have no migration allocation.

    [db.init_db](/Users/michaelrickards/dev/bh2-MSG-1/backend/db.py:91) still calls `create_all()`. [BusinessSettings](/Users/michaelrickards/dev/bh2-MSG-1/backend/models.py:116) currently stores settings in JSONB, so MSG-2 must clarify whether `assistant_name` is a JSON key or a new column.

    **Change:** Make admission controls a prerequisite for enabling messenger traffic, or specify an explicit capped beta gate. Inventory every schema change, serialise migrations and put verified security setup before code activation. Reclassify deletion and OAuth work appropriately. Expand the table into task packets with negative acceptance criteria, tests, dependencies and verification commands before approving implementation.

17. **P2 — Streaming is missing its provider-layer design.**

    **Where:** §5.2 and MSG-1. [ai_chat.turn](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/ai_chat.py:465) returns a completed response; the current adapters do not expose the proposed streaming contract. [AssistantChat.handleSendMessage](/Users/michaelrickards/dev/bh2-MSG-1/frontend/client/src/pages/AssistantChat.tsx:108) consumes JSON.

    **Change:** Scope a router-compatible streaming interface with typed events, cancellation, final usage accounting and reconnect semantics. Define fallback after partial output and ensure incomplete tool arguments never execute. Specify that status events expose safe labels rather than raw tool inputs/results. Include this work in MSG-1’s dependencies and budget.

No tests or `check.sh` were run: this was a read-only design review, with no implementation to verify. Production schema and provider configuration were not inspected.

**Verdict: REQUEST CHANGES.**
