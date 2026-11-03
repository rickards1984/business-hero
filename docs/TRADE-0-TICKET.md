# TRADE-0: the owner boundary (security prerequisite for the site portal)

**Tier:** RED (authorisation, tenant isolation, database policies). **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

**Gate:** Mike accepts the site portal into scope. No worker, subcontractor or invitation exists until this ticket is deployed and verified.

**Source:** `docs/TRADE-1-DESIGN.md`, revision 2, and Codex design reviews 1 and 2 (`audits/TRADE-1-CODEX-REVIEW-{1,2}.md`). It serves North Star P9 (safe by construction) and is the prerequisite for P2, P6 and P8 in the portal.

## Why

Today the shared resolver (`assistant_chat.get_business_for_user`, and the dependencies in `auth.py` and `dependencies.py`) accepts **any active membership** of a business. That's safe only because every member is an owner. The portal adds workers and subcontractor representatives, so before the first one exists every route, socket, Aria tool, export, callback and database policy must check **authority in the selected business**, not mere membership.

## 1. Classification: every route gets exactly one category (review 2, finding 2)

| Category | Who may call it | Examples |
|---|---|---|
| `tenant_owner` | An active **owner** membership in the selected business | Almost every existing business route |
| `platform_admin` | A platform admin. Tenant ownership is **never** enough | Admin business, outreach and profit routes |
| `self_bootstrap` | Any signed-in person, with a minimal response | `/v1/me`, choosing a business |
| `provider` | A provider signature or call-bound token, never a user JWT | Stripe, Twilio and receptionist media stream, WhatsApp webhooks |
| `oauth_continuation` | Bound, single-use state, with current authority rechecked | Xero, FreeAgent, QuickBooks, Google and Microsoft callbacks |
| `public` | Anyone, with a documented reason and no tenant data | Health checks, the outreach unsubscribe link |
| `portal` | Narrow capabilities (the TRADE-1 phases add these) | None in TRADE-0 |

- **Unclassified routes fail.** A test compares the manifest against the **assembled** application's route tree: every HTTP method and path and every WebSocket, including routes excluded from OpenAPI, late registrations and mounted apps.
- **Unknown roles inherit nothing.** A membership role other than `owner` has no owner authority. Tenant `admin` doesn't inherit owner or platform-admin authority until it is defined.
- **The plan-enforcement inventory** (six modules, `APIRoute` only) is the pattern, not the census.

## 2. Tenant selection: one contract for HTTP, voice and callbacks (review 2, finding 3)

- **The business is chosen explicitly** with an `X-Business-Id` header, or by the resource's own business for resource routes.
- **A sole active membership may be inferred.** This keeps today's single-business owners working with no change. With two or more active memberships, a missing choice is **refused**, never defaulted to the owner's business.
- **Conflicting business ids** (header, query, body or resource) are refused.
- **Authority is read from the database for every protected operation** (membership active, role `owner`), never from token claims or a cache.
- **The same person can be owner in A and worker in B.** Owner authority applies only in A.

## 3. OAuth continuation (review 2, finding 3)

- **State is single-use and expires.** It is bound to the **initiator, business, provider and intended operation**, stored server-side (not just encrypted into the URL) and consumed atomically.
- **On callback,** the initiator's current owner authority in that business is rechecked **before** credentials are saved or the integration changes.
- **Rejected:** forged, expired, replayed, wrong-provider and wrong-business state, and an initiator revoked between start and callback.
- **Covers:** Xero, FreeAgent, QuickBooks, and Google and Microsoft mail and calendar.

## 4. Revocation reaches open sessions (review 2, finding 4)

- **HTTP:** every request rechecks membership (see §2).
- **Owner voice (`realtime_voice`):** the handshake check isn't enough. Before **each tool call and each delivery of business data**, the session rechecks the person's current authority. On loss of authority it suppresses the in-flight result, tells the browser, and closes.
- **Streaming responses** found by the census get the same treatment.
- **The receptionist media stream** stays `provider`, with its call-bound token checks unchanged.

## 5. Inventory to cover (review 2, finding 5)

- **Routes:**
  - all of `backend/main.py`;
  - `app/email/router.py` and its OAuth router;
  - `accounting.py`;
  - `realtime_voice.py`;
  - `receptionist_api.py` and `receptionist_call_handler.py`;
  - `onboarding_api.py`, `support_api.py`, `whatsapp_briefing_api.py`;
  - **both** `automation_api.py` and `automations_api.py`;
  - booking, quoting, invoice PDF, invoices, executive meetings, usage, home and Aria actions;
  - outreach read, manage, setup, public, unsubscribe and dashboard;
  - admin business, outreach and profit.
- **Authentication paths:**
  - `auth.py` and both dependencies in `dependencies.py`;
  - `get_business_for_user`;
  - direct JWT-verification call sites;
  - platform-admin overrides;
  - API and master-key paths.

  Entitlement stays separate from authorisation.
- **Aria:**
  - chat, voice, home and briefing, executive-meeting prep and messages, action approval and execution;
  - `assistant_chat._execute_tool_async`, `assistant_tools.execute_tool`, `realtime_voice.execute_tool`.

  Authority is checked **before** any sensitive context is loaded, any model is called, or anything changes.
- **Exports and files:**
  - the accountancy pack;
  - invoice and quote PDFs;
  - attachments and any signed-link endpoint.

  Read-only subscription exemptions never bypass authorisation.
- **Integrations:** connect, start, status, sync and disconnect for each provider; Awaz credential return and rotation; the Stripe, Twilio, WhatsApp and outreach provider and public callbacks. Each exception has its own authentication and business-binding contract.
- **The direct Supabase path:**
  - every exposed table and view, its grants and RLS predicates;
  - every callable function (`is_business_member`, `is_platform_admin`, `setup_default_accounting_categories`, `whoami`, and every security-definer function);
  - every bucket and object operation, including the public `logos` bucket (public read stays; upload, overwrite and delete become owner-only).

  It explicitly covers membership and role changes, `businesses`, `profiles`, `platform_admins`, and the business data tables. **Policies that test "member of the business" become owner-only, or are narrowed.**
- **The frontend's direct Supabase reads** (AuthContext, BusinessDashboard, BillingSettings, BrandingSettings, admin and support pages, TasksPanel, CallsPanel, EmailsTab, dashboard hooks, DebugPanel) are covered by the RLS work. Hiding a component protects nothing.
- **Deployed state:**
  - both migration directories are reconciled against the **live catalogs**, because repository SQL is not deployed policy;
  - a census confirms every current member is an owner.

  These are read-only queries Mike runs.

## 6. Acceptance tests (review 2, finding 6)

1. **Inventory completeness:** the manifest equals the assembled HTTP and WebSocket route tree. A new unclassified route fails.
2. **Role matrix:** owner, worker, subcontractor representative, tenant admin, inactive member, unrelated user, unauthenticated caller and platform admin, run through the real guards. A validation error is never mistaken for an authorisation pass.
3. **Mixed businesses:**
   - owner of A and worker in B;
   - owner of A and owner of B;
   - a missing, forged or conflicting business.

   There is no silent fallback, and existing owners keep everything they use today.
4. **Nothing happens after a denial:** no protected data is loaded, no export generated, no provider or model called, no credential returned, and nothing changed.
5. **Live revocation:**
   - an existing JWT is refused after removal or demotion;
   - an **already-open voice session** stops at its next tool call or data delivery;
   - A stays usable when B is revoked.
6. **OAuth:** forged, expired, replayed, wrong-provider, wrong-business and initiator-revoked state are all rejected; legitimate callbacks still work.
7. **Exceptions:**
   - owners can't use platform-admin routes;
   - valid provider signatures and call tokens still work, and a user JWT can't stand in for them;
   - public flows work without exposing business data.
8. **Real Supabase roles (staging):**
   - reads and writes;
   - self-promotion of role;
   - RPC execution;
   - Storage list, read, upload, overwrite and delete, run as worker and mixed-role identities, with positive owner controls.

   Service-role success never counts as RLS evidence.
9. **Deployment:** staging constraints, policies and grants are verified; the migration is rehearsed with its rollback; Mike runs an approved production runbook.
10. **The whole check:** `./check.sh full`, plus the staging role and storage suite, plus browser and voice checks.

**Mike's check (staging):**
- owner tasks all still work;
- a test worker can't open owner data or talk to Aria;
- a mixed-role user can't carry owner authority into the worker business;
- removing the test worker cuts off their open session.

**Not in TRADE-0:** any portal table, invitation or document collection.
