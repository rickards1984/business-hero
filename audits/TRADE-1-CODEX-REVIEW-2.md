# TRADE-1 Codex design review 2

Model gpt-6-astra · session 01a1a2e8-c5b5-71e1-8cbe-814f4294bf25 · 43,604 tokens · verdict **CHANGES REQUIRED (narrowly, phase-0 contract)**

## Prompt

```
Read-only re-review of the TRADE-1 design, revision 2 (docs/TRADE-1-DESIGN.md in this worktree). Your review 1 is audits/TRADE-1-CODEX-REVIEW-1.md; the table "Review 1 → changes" maps each finding to the change. For each of the 11 findings, say whether the revision resolves it at design level. Then: is phase 0 (owner boundary) correctly specified and complete enough to start as its own ticket — list the concrete inventory it must cover in this repository (routers, websocket/voice, Aria tools, exports, integrations/OAuth callbacks, direct Supabase RLS/RPC/storage), and its acceptance tests? Any remaining P1? Output APPROVE / APPROVE WITH CHANGES / CHANGES REQUIRED with numbered findings. Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED — narrowly for the phase-0 security contract.** Revision 2 substantially resolves review 1, but phase 0 is not yet complete enough to hand straight to a builder. It is suitable as a separate security ticket once the requirements below are incorporated. It serves North Star **P9** and the security/tenant-isolation prerequisite.

This is a design and repository review, not verification of deployed policies.

1. **Disposition of the original 11 findings**

   | Review 1 | Resolved at design level? | Assessment |
   |---|---|---|
   | **1. Owner boundary** | **Partial** | Capability checks, comprehensive inventory and direct Supabase testing are now required. However, the phase-0 classification and acceptance contract still need the corrections in findings 2–5 below. |
   | **2. Tenant, role and subcontractor identity** | **Yes, with a sequencing correction** | Four-part authority, tenant-specific ownership, separate organisations/representatives and database isolation constraints address the original model problem. Explicit tenant selection and current membership checks must be part of phase 0, not deferred to phase 1. |
   | **3. Invitation authority** | **Yes** | Recipient matching, atomic single-use acceptance, lifecycle, role restrictions and channel-specific authentication are specified. Recovery, recycled-number handling and stronger owner authentication remain mandatory implementation details before phase 1 can pass. |
   | **4. Revocation** | **Partial** | Fresh-request denial, membership checks and the five-minute signed-link window resolve the ordinary request/file case. Already-open voice/streaming sessions need explicit treatment; see finding 4. |
   | **5. Private storage** | **Yes, with wording clarification** | Record-based authorization, browser-role denial, validation/quarantine and immutable versions address the original finding. Clarify whether downloads are backend-proxied or use backend-issued signed URLs; both are currently described. |
   | **6. Personal data** | **Yes, as a pre-collection gate** | The portal-specific schedule, purpose/access controls, OUT-13 dependency, DPIA assessment and removal of phase-1 location capture address the finding. The required schedule still has to be produced before collection. |
   | **7. CAS mapping** | **Yes against review 1** | Q132–Q138 now match the mapping recorded in review 1; applicability, exemptions and versioning are acknowledged. This review does not independently revalidate the external scheme documents. |
   | **8. Phase order/North Star** | **Yes** | Phase 1 includes private document submission, owner review and sourced, grounded owner Aria tools. The scope-authorization gate is explicit. Add explicit P2/P6/P8/P9 references to the implementation tickets. |
   | **9. Evidence versus compliance** | **Yes** | Evidence-only states, versioned acknowledgements, the attendance distinction and limits on issue reporting address the finding. |
   | **10. Marketing permissions** | **Yes** | Version-specific approval, permitted uses, supporting permissions, optional participation and withdrawal/takedown are specified. Takedown must include published derivatives. |
   | **11. Cost controls** | **Yes at design level** | Quotas, rate limits, metering, alerts and active-membership counting are specified. Numeric limits and concurrency behaviour belong in the phase-1 acceptance contract. |

2. **P1 — Phase 0 needs an explicit authorization classification, not literal “every endpoint owner-only.”**

   [The current wording](/Users/michaelrickards/dev/bh2-TRADE-1/docs/TRADE-1-DESIGN.md:65) can mean either insufficient protection or a damaging blanket change. Existing platform-admin routes must remain **platform-admin-only**; tenant ownership must never become sufficient. Webhooks, public unsubscribe links, health checks and OAuth callbacks cannot simply require an owner bearer token.

   Require these explicit classifications:

   - Tenant-owner operation.
   - Platform-admin operation.
   - Authenticated self/bootstrap operation, with a minimal response.
   - Provider/service-authenticated operation.
   - OAuth continuation, bound to an authorized initiating identity and tenant.
   - Intentionally public operation, with a documented reason.
   - Future narrowly scoped portal capability.

   Unknown routes must fail classification. Unknown membership roles and tenant `admin` must not inherit owner or platform-admin authority.

   The referenced plan-enforcement inventory is **a pattern, not a complete census**: [test_plan_enforcement.py](/Users/michaelrickards/dev/bh2-TRADE-1/backend/tests/test_plan_enforcement.py:32) enumerates six modules and filters for `APIRoute`. It does not establish coverage of the whole application or WebSockets.

3. **P1 — Tenant resolution and OAuth continuation authority must ship in phase 0.**

   [Phase 1 currently owns “explicit business choice”](/Users/michaelrickards/dev/bh2-TRADE-1/docs/TRADE-1-DESIGN.md:144), but phase 0 cannot enforce ownership correctly without it. The existing [resolver](/Users/michaelrickards/dev/bh2-TRADE-1/backend/assistant_chat.py:506) accepts any active membership and defaults to an owner business.

   Phase 0 must define one tenant-selection contract across HTTP, voice and callbacks. Missing context for a multi-membership user must fail; conflicting query/body/resource business IDs must fail. State explicitly whether a sole membership may be inferred—the prose and acceptance table currently leave that unclear.

   OAuth needs more than adding a dependency to initiation routes. For example, [Xero’s callback](/Users/michaelrickards/dev/bh2-TRADE-1/backend/main.py:3645) derives the business from encrypted state without establishing the initiating user’s current owner authority.

   Require expiring, single-use state bound to **initiator, business, provider and intended operation**, with current authority rechecked before credentials are persisted or the integration changes. Test revocation between initiation and callback. Encryption of a business ID alone is insufficient.

4. **P1 — Define revocation for already-open voice and streaming operations.**

   The design promises checks on every protected operation, but its concrete revocation tests cover new requests, uploads and links. [Realtime voice](/Users/michaelrickards/dev/bh2-TRADE-1/backend/realtime_voice.py:717) authenticates in its own handshake and retains business context.

   Specify that removal or demotion prevents subsequent tool execution and protected data delivery through an existing connection. Define how active sessions are invalidated and how in-flight results are suppressed; a handshake-only check cannot satisfy immediate revocation.

   Also make “portal JWT” precise: the test concerns **the selected tenant and current membership**, not an account-wide token label. The same authenticated person must be allowed owner access in A and denied owner access in B.

5. **Phase-0 inventory — the ticket must cover these concrete repository surfaces.**

   | Surface | Required inventory |
   |---|---|
   | **Registered routes** | Every HTTP method/path and WebSocket in the assembled application, including routes excluded from OpenAPI, late registrations and mounted applications. Record handler, authorization category, tenant source, guard and test. |
   | **Main-module routes** | All of `backend/main.py`: business/settings/branding, `/v1/me`, tasks, calls, briefings, assistant chat/TTS, invoices/chasing/import, billing, accounting/sync/export, integrations and OAuth, platform-admin routes, health/debug/schema routes. |
   | **Included routers** | `app/email/router.py` including its OAuth router; `accounting.py`; `realtime_voice.py`; `receptionist_api.py` and `receptionist_call_handler.py`; `onboarding_api.py`; `support_api.py`; `whatsapp_briefing_api.py`; **both** `automation_api.py` and `automations_api.py`; booking, quoting, invoice PDF, invoices, executive meetings, usage, home and Aria actions; outreach read/manage/setup/public/unsubscribe/dashboard; admin business/outreach/profit. Registrations begin in [main.py](/Users/michaelrickards/dev/bh2-TRADE-1/backend/main.py:412), with additional admin registrations near the end. |
   | **Authentication paths** | `auth.py`, both shared dependencies in `dependencies.py`, `assistant_chat.get_business_for_user`, direct JWT-verification call sites, platform-admin overrides and API/master-key paths. Entitlement checks remain separate from authorization. |
   | **WebSocket/voice** | Owner realtime voice handshake, context loading and tool calls; receptionist `/media-stream` separately classified as a provider-authenticated stream, preserving its call-bound token checks. Include any streaming HTTP responses found by the census. |
   | **Aria and business snapshots** | Chat, voice, home/briefing, executive-meeting prep/messages, action approval/execution; `assistant_chat._execute_tool_async`, `assistant_tools.execute_tool`, `realtime_voice.execute_tool` and their service calls. Authorization must precede loading sensitive context, provider calls and side effects. |
   | **Exports and files** | Accountant-pack export, invoice PDFs, quote PDF generation, downloads/attachments and any generated artifact or signed-link endpoint. Read-only subscription exemptions must not bypass role authorization. |
   | **Integrations and callbacks** | Google/Microsoft email/calendar, Xero/FreeAgent/QuickBooks; connect/start/status/sync/disconnect and callbacks; Awaz credential-returning/rotation paths; Stripe, Twilio/receptionist, WhatsApp and outreach provider/public callbacks. Each exception needs its own authentication and tenant-binding contract. |
   | **Direct Supabase** | All exposed tables/views, grants, RLS predicates and callable functions—not only resources used by the UI. Explicitly cover membership/role mutation, `businesses`, `profiles`, `platform_admins`, tasks, calls, support, email accounts and sync state, accounting/quotes/invoices, integration secrets and outreach. |
   | **RPC and Storage** | Inventory executable functions, including `is_business_member`, `is_platform_admin`, `setup_default_accounting_categories`, `whoami` and security-definer functions. Audit all buckets and object operations, especially existing public `logos`: intended public reads can remain public, but worker upload/overwrite/delete must not follow broad membership permission. |

   The frontend confirms direct accesses through `AuthContext`, `BusinessDashboard`, `BillingSettings`, `BrandingSettings`, admin pages, support pages, `TasksPanel`, `CallsPanel`, `EmailsTab`, dashboard hooks and `DebugPanel`. Hiding those components provides no protection.

   Reconcile both migration directories against database catalogs. Repository SQL is evidence of intended policy, not proof of deployed policy. The assertion that every current member is an owner also needs a deployment preflight census.

6. **Phase-0 acceptance tests — move these into its own ticket.**

   - **Inventory completeness:** compare the policy manifest with the assembled HTTP/WebSocket route tree. Adding an unclassified route must fail. Include late registrations and non-OpenAPI routes.
   - **Role matrix:** owner, worker, subcontractor representative, tenant admin, inactive member, unrelated user, unauthenticated caller and platform admin. Exercise valid requests through real guards; do not mistake validation errors for authorization.
   - **Mixed tenants:** owner A/worker B; owner A/owner B; missing, forged and conflicting context. No silent fallback. Existing owners retain legitimate functionality.
   - **No denied side effects:** assert no protected data load, export generation, provider/model call, credential return or mutation occurs after denial.
   - **Live revocation:** reuse an existing JWT after removal/demotion; repeat HTTP operations and exercise an already-open voice session and tool call. A remains accessible when B is revoked.
   - **OAuth:** reject forged, expired, replayed, wrong-provider and wrong-tenant state; reject callbacks after initiator revocation/demotion. Verify legitimate callbacks still work.
   - **Exceptions:** ordinary owners cannot use platform-admin routes. Valid provider signatures/call tokens work; worker JWTs cannot substitute for them. Intentionally public flows remain functional without disclosing tenant data.
   - **Real Supabase roles:** test reads and writes, role self-escalation, RPC execution and Storage list/read/upload/overwrite/delete using authenticated worker and mixed-role identities. Include positive owner controls. Do not use service-role success as RLS evidence.
   - **Deployment evidence:** verified staging constraints/policies/grants, migration rehearsal and rollback, plus an explicitly approved production runbook. No worker creation before the boundary is deployed and verified.
   - **Verification:** `./check.sh full` plus the staging role/storage suite and browser/voice checks. Phase 0 requires no portal tables, invitations or document collection.

   Mike’s phase-0 behavioural check should use prepared staging identities: owner operations still work; a worker cannot open owner data or invoke Aria; a mixed-role user cannot switch authority into the worker business; revocation stops the existing session.

**Remaining P1s: findings 2–4 above.** They are bounded clarifications of the owner boundary, not reasons to redesign the portal. Once recorded in the phase-0 ticket, it can proceed through RED approval and independent review.

No files were edited, committed or pushed. I did not run `check.sh` or live database tests for this read-only review.