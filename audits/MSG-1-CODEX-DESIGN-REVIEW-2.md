# MSG-1 — Codex DESIGN review 2 (verbatim)

Reviewed docs/MSG-1-DESIGN.md v2 (design only, no code) on 4375e55.

Reviewed commit `4375e555fe1b0bfb267b3f97aa7940f1f4dde3f8`. No files modified. This review assesses North Star P2, P4, P7 and P9. “Resolved” below means resolved **in the design**, not implemented or production-verified.

| Review 1 finding | Status | Assessment against current code |
|---|---|---|
| 1. Existing conversations | **Resolved** | §5.2 now preserves the tables and IDs used by `assistant_chat`, with additive changes and live verification. |
| 2. Isolation | **Partly** | Device partitioning and ownership rules are specified, but existing approval-card access remains business-wide. Finding 1 below. |
| 3. Turn idempotency | **Partly** | Durable claims and unknown outcomes address reconnects; streaming fallback introduces an unresolved execution boundary. Finding 4. |
| 4. Quote-send / Drive approval | **Resolved** | Keeping quote sends on the Quotes page matches `_send_quote_via_aria`; untapped Drive saves are withdrawn. |
| 5. Injection / capabilities | **Partly** | R1’s prohibited actions are explicitly excluded. R3’s proposed enforcement checks action kinds, not the authority for their arguments. Finding 2. |
| 6. Quote review | **Resolved** | Revision invalidation explicitly includes material quote and company inputs consumed by `_get_quote_pdf_data`; saved totals supply the card. |
| 7. Attachment lifecycle | **Resolved** | Reservation, finalisation, decoding limits, ownership, quotas, private storage and deletion now have explicit contracts. |
| 8. OAuth | **Partly** | Separate credentials and refresh handling address `email_accounts` reuse. Google revocation isolation is incorrect. Finding 3. |
| 9. Jobs | **Partly** | Leases, fencing, checkpoints, limits and schedule semantics are specified. Job mutation authority conflicts with §5.3. Finding 2. |
| 10. Admission | **Partly** | Atomic reservation is required, but the amount reserved and failure settlement remain undefined for compound work. Finding 5. |
| 11. Credit unit / settlement | **Partly** | Fixed units, purchase terms and Stripe settlement address the original issues. Reservations and IAP expiry remain problematic. Findings 5–6. |
| 12. Store payments | **Partly** | Native Stripe-route removal addresses `BillingSettings`; the proposed IAP path conflicts with credit expiry. Finding 6. |
| 13. Deletion | **Partly** | Account/business separation and the public request page are specified; authentication deletion and concurrent execution are not. Finding 7. |
| 14. Read tools / grounding | **Partly** | Per-ticket read tools and grounding tests are required, but citation/history reconstruction remains unspecified. Finding 9. |
| 15. Briefing baseline | **Resolved** | §4.3 matches `whatsapp_briefings` and preserves independently configured reminders and alerts. |
| 16. Dependencies / migrations | **Partly** | The beta gate and deletion classification improve the sequence, but required alterations are missing and ordering conflicts remain. Finding 8. |
| 17. Streaming | **Partly** | Provider events, safe labels and usage accounting are now scoped; fallback after tool execution needs a defined boundary. Finding 4. |

No P0 findings.

1. **P1 — Private conversation cards remain accessible through existing business-wide paths.**

   **Where:** Design §§2, 5.1–5.2; [aria_actions._scoped](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/aria_actions.py:538), [list_open](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/aria_actions.py:1001), [approval API](/Users/michaelrickards/dev/bh2-MSG-1/backend/aria_actions_api.py:47).

   The design promises user-private conversation links but does not specify converting existing card storage and access to that model. Cards currently record `proposed_by`, have no conversation association, and list/get/edit/approve paths scope by business. The checked-in [RLS policy](/Users/michaelrickards/dev/bh2-MSG-1/backend/migrations/035_aria_actions.sql:95) also permits business-member reads. Protecting only messenger endpoints would leave another route to private card contents and actions.

   **Change:** Specify which cards are private versus business-shared. Carry conversation ownership through storage, every existing card endpoint, and applicable RLS/grants. Define who may approve a private card and access its personal storage connection. Include same-business/different-user tests against both API and database-client paths.

2. **P1 — An action-kind classifier cannot enforce R3’s argument-level authority.**

   **Where:** Design §5.3, especially lines 114–118; [current tool dispatch](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:22).

   Checking that the owner requested “create document” or “create task” does not prevent fetched instructions from changing the target, amount, recipient or number of writes within that permitted kind. Card tools are also included without an equivalent explicit authority check. An owner requesting one reply could therefore receive an injected extra-recipient card while passing the specified kind check.

   Separately, jobs may perform authorised internal writes on line 115, but line 116 requires that the turn was started by the owner, explicitly excluding jobs. Implementing either rule literally breaks the other.

   **Change:** Define a server-held task authorisation covering permitted operations, targets, bounds and argument provenance; apply it to proposals as well as direct writes. Ambiguous additions require a new owner instruction. Jobs should inherit an explicit, bounded authorisation from creation. Test malicious substitutions **within an otherwise authorised action kind**, not only unsolicited kinds.

3. **P1 — The proposed Google OAuth separation does not isolate revocation.**

   **Where:** [Design §5.7](/Users/michaelrickards/dev/bh2-MSG-1/docs/MSG-1-DESIGN.md:145).

   A separate client in the **same Google Cloud project** does not provide the promised independent disconnect. Google documents revocation as removing the project’s granted scopes and invalidating tokens for all clients registered under that project. Disconnecting Drive can therefore invalidate Gmail/Calendar credentials. [Google OAuth documentation](https://developers.google.com/identity/protocols/oauth2/web-server#tokenrevoke)

   **Change:** Use a separate project for independent revocation, or explicitly design a combined disconnect with its consequences. Verify connect, refresh and revoke behaviour with the same Google account connected to both integrations.

4. **P1 — Streaming fallback is undefined after a tool has already executed.**

   **Where:** Design §§5.2, 5.4; [existing multi-round tool loop](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:889).

   §5.4 executes tools on `tool_call_complete`, but permits fallback after partial output without distinguishing whether a tool already committed. A stream can complete a draft-creation call and then fail. A replacement model can generate a different call sequence; `turn_id:tool_call_index` alone cannot establish that its calls represent the same operations. Reusing an index could return the wrong prior result; allocating another could repeat the effect.

   **Change:** Define a durable execution boundary. Either defer effects until the provider response is accepted, or persist completed calls/results and resume fallback from that exact transcript without replaying committed operations. Bind operation keys to argument fingerprints. Specify terminal cancellation and uncertain-usage settlement, and test failure immediately after a committed tool call.

5. **P1 — Admission does not define the reservation for compound turns or its recovery.**

   **Where:** Design §§5.8–5.9; [ai_chat._Reservations](/Users/michaelrickards/dev/bh2-MSG-1/backend/services/ai_chat.py:167).

   A chat turn costs one credit, a document three, and a job one per tool call. The design does not say whether these charges stack, how many documents a turn may create, or what maximum is reserved before the first provider call. Admitting a one-credit turn that later needs three-credit work forces either mid-turn refusal or unreserved execution.

   The cited `budget_business` precedent is an in-memory, per-provider-attempt reservation, **not** an atomic database credit-balance statement. It supplies no durable customer-credit settlement contract for crashes, retries or reservations crossing allowance expiry.

   **Change:** Define bounded, quoted charges for each admitted operation, including compound turns and maximum job work. Specify durable reservation IDs, affected allowance/top-up lots, exactly-once settlement, release/refund rules, and recovery for cancelled, failed and unknown outcomes. Bound platform spend across tool rounds, summaries and fallback attempts separately from customer credits.

6. **P1 — Twelve-month top-up expiry conflicts with the proposed Apple IAP path.**

   **Where:** Design §§5.9–5.10 and MSG-8.

   §5.9 expires top-ups after twelve months; §5.10 recommends selling those credits through IAP. Apple §3.1.1 prohibits expiry of credits purchased through IAP. The ledger also describes Stripe sessions exclusively, despite MSG-8 introducing another purchase authority. [Apple review guidelines](https://developer.apple.com/app-store/review/guidelines/#in-app-purchase)

   **Change:** Make IAP credits non-expiring, with purchase-source-aware consumption rules, or make all purchased credits non-expiring. Specify verified Apple transaction settlement, unique transaction ownership, replay protection and refund/revocation reconciliation before MSG-8.

7. **P1 — Account deletion lacks an execution barrier and authentication-account completion.**

   **Where:** Design §5.12; [current Supabase authentication lifecycle](/Users/michaelrickards/dev/bh2-MSG-1/frontend/client/src/contexts/AuthContext.tsx:61).

   The deletion sequence removes private records and membership but never explicitly deletes the authentication identity or invalidates sessions. It also does not stop already-running turns, uploads, briefs or approvals before deleting their records. Those operations can finish afterwards and recreate data or complete an outward action. Job checks between steps do not cover an already-running step or interactive turn.

   **Change:** Start with a durable deletion state that rejects new admissions and approvals; fence or drain in-flight work before purging. Include Supabase identity/session handling, pending cards, turns and summaries, schedule cancellation, token revocation, and retryable object cleanup. Specify completion across all memberships and test deletion racing a turn and an approval.

8. **P1 — The migration inventory cannot support the proposed features in its stated order.**

   **Where:** Design §§6–7; [existing action-type constraint](/Users/michaelrickards/dev/bh2-MSG-1/backend/migrations/037_outreach_core.sql:93).

   The inventory omits alterations needed for operation-key uniqueness on existing cards/tasks/quotes, their promised provenance, and new rename/Drive card types. Current action constraints reject those new types. MSG-2 nevertheless claims no migration and can run alongside MSG-1.

   The sequence also assigns push migration 050 to MSG-6 and deletion migration 051 to MSG-7, while the “fastest safe path” puts MSG-7 before MSG-6. Migration 050 remains AMBER despite AGENTS.md explicitly classifying every production migration RED.

   **Change:** Inventory the existing-table alterations and their owning migrations, including card ownership and action types. Give parallel tickets the necessary schema dependencies; reconcile the delivery path with numbered migration order. Classify all migrations RED and put verified schema/security changes before activation.

9. **P2 — Rich-message grounding still loses its source contract when history is trimmed.**

   **Where:** Design R5, §§5.2, 5.4 and §7; [load_conversation_history](/Users/michaelrickards/dev/bh2-MSG-1/backend/assistant_chat.py:667).

   Existing history loads only `role` and `content`. V2 adds ID payloads, read tools and a running summary, but does not define how those IDs survive summarisation, resolve to authorised current records, or distinguish historical figures from current ones. Labelling a summary “data under R3” prevents it supplying authority; it does not make its figures current or grounded.

   **Change:** Define typed source references and history reconstruction, preserving record IDs and revision/as-of information through trimming. Revalidate access and fetch current values when answering current-state questions. Add tests for an edited or deleted source after summarisation and for revoked access.

No tests or `check.sh` were run: this was a read-only design review. Production schema, provider configuration and runtime behaviour were not inspected.

**Verdict: REQUEST CHANGES.**
