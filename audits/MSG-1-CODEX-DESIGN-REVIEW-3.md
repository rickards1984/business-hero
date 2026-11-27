# MSG-1 — Codex DESIGN review 3 (verbatim)

Reviewed docs/MSG-1-DESIGN.md v3 (design only, no code) on 6652a81.

Reviewed commit `6652a813d0f74aef492f171be5baa08803e61e78`, against North Star P2, P4, P7 and P9. **One remaining design blocker.** “Resolved” means resolved in the design, not implemented or production-verified.

| Review-2 finding | Status | Check against current code |
|---|---|---|
| 1. Private cards | **Resolved** | §5.1 explicitly replaces business-only access in `aria_actions._scoped`, `list_open`, existing API endpoints and the 035 RLS policy. Private versus shared cards and connection ownership are defined. |
| 2. Argument authority / jobs | **Resolved** | §5.3 adds stored operation, count and target authorisation checked before writes and proposals. This supplies the control missing from `_execute_tool_async`. Jobs explicitly inherit bounded authority. |
| 3. Google revocation | **Resolved** | §5.7 requires a separate project, credential store and refresh path rather than reusing `oauth_utils` and `email_accounts`. Project separation addresses [Google’s documented revocation scope](https://developers.google.com/identity/protocols/oauth2/web-server#tokenrevoke). |
| 4. Streaming fallback | **Resolved** | §§5.2–5.4 specify durable calls/results, argument-bound operation keys and continuation from the persisted transcript. Current `assistant_chat` retains results only in its in-memory message loop; v3 explicitly scopes the necessary replacement. |
| 5. Compound reservations | **Partly** | Stacking, bounded admission, named lots and separate platform budgets are now specified. The description of `ai_chat._Reservations` matches its in-memory implementation. Expiry recovery still contradicts committed-work settlement; finding 1 below. |
| 6. IAP expiry | **Resolved** | All purchases are non-expiring, with source-specific verification, transaction ownership, deduplication and refunds. This addresses [Apple §3.1.1](https://developer.apple.com/app-store/review/guidelines/#in-app-purchase). Existing `outreach_billing` is correctly treated as the Stripe precedent, not an Apple implementation. |
| 7. Account deletion | **Resolved** | §5.12 now specifies a durable barrier, draining/fencing, pending-card handling, retryable purge and authentication-identity deletion across memberships. Current `AuthContext.signOut` supplies none of that; the new workflow is explicitly scoped. |
| 8. Migrations / order | **Resolved** | §6 includes existing-table operation keys, private-card fields and the Drive action-type constraint currently restricted by 037. Migration order matches §7; rename uses the existing settings JSON rather than a new card type. |
| 9. Grounding through trimming | **Resolved** | §5.14 specifies typed references, preservation through summaries, access revalidation and current-value refetching. This directly addresses `load_conversation_history` currently returning only role/content. |

No P0 findings.

1. **P1 — Reservation expiry can release credits for work that already committed.**

   **Where:** [§5.9, settlement and sweeper rule](/Users/michaelrickards/dev/bh2-MSG-1/docs/MSG-1-DESIGN.md:178).

   The sweeper “releases those past `expires_at` (30 minutes)” without requiring reconciliation or stopping the associated execution. For example, a document commits, the worker crashes before completing the turn or settlement, and recovery happens after expiry. The stated expiry rule permits releasing the entire hold despite the committed document. If execution remains alive, released credits can also be admitted elsewhere before its eventual settlement.

   This conflicts with the same paragraph’s requirement to charge committed operations exactly once. The existing `_Reservations` guard cannot repair it: it tracks platform spend in memory, not durable customer credits.

   **Change:** Make expiry trigger recovery, not unconditional release. Stop/fence further execution, reconcile persisted committed operations, settle those charges exactly once, and release only the unused remainder. Unknown operations retain the stated no-charge treatment. Fully release a reservation only when reconciliation establishes that nothing chargeable committed. Require recovery tests covering a committed creation followed by a crash, and expiry racing settlement.

**For the task packets — not additional blockers:**

- **MSG-0/1:** Include `cancelled` in the turn state machine; define disconnect/reconnect behaviour and cumulative authorisation counts across fallback. Complete the operation vocabulary for document updates and job/schedule controls.
- **MSG-3:** Define the durable event earning the base one-credit chat charge, including successful replies with no tool calls. Specify refund interactions with held purchase lots.
- **MSG-4/9:** Enumerate every PDF/export path, including `send_quote_email`, which generates PDFs directly. Specify atomic revision validation against edits and company-setting changes.
- **MSG-7:** Turn the deletion barrier into concrete race tests for legacy endpoints, in-flight uploads and signed upload URLs, brief generation, and workers that outlive cancellation.
- **Migration packets:** Supply exact columns, constraints, ownership backfills, grants and rollback evidence, including the provenance promised by §5.1.

No files modified. No tests or `check.sh` run: this was a read-only design review. Production schema and provider configuration were not inspected.

**Verdict: REQUEST CHANGES.**
