# TRADE-1 Codex design review 1

Model gpt-6-astra · session 01a1a2e4-f462-70f2-89bd-8fa003baa431 · 54,885 tokens · verdict **CHANGES REQUIRED**

## Prompt

```
You are the independent design reviewer (read-only) for docs/TRADE-1-DESIGN.md in this worktree: a trades site portal for Business Hero (FastAPI/SQLModel on Railway, React/MUI on Vercel, Supabase Postgres with RLS and Supabase Auth). Read AGENTS.md, docs/NORTH_STAR.md and the design. Verify the "What already exists" claims against the code (backend/auth.py, backend/models.py, audits/live-schema-public.txt, the logo upload flow in backend/main.py).

Review the design before any code: 
- Security: the new worker/subcontractor role with passwordless invite links (Supabase magic links / OTP; WhatsApp or SMS delivery) — account takeover, invite forwarding, revocation when someone leaves, a worker who is also an owner elsewhere, tenant isolation, every existing endpoint's assumption that a signed-in member is the owner (get_current_user_and_business etc.) — what must change so a worker can never reach owner data?
- Private storage: signed URLs, RLS on storage.objects, upload validation (type/size/EXIF location), cost.
- Personal data/UK GDPR: photos of people, location stamps, training records; lawful basis; retention (OUT-13 dependency); the marketing-photo approval rule.
- CHAS/CAS modelling: is the mapping sound and honest (no claim that Business Hero makes anyone compliant)? CAS v6 Q135/136/138 as described.
- Phasing: is phase 1 the right smallest safe slice? What is missing from it?
- Anything in the design that conflicts with the North Star or AGENTS.md rules.

Output: a verdict (APPROVE / APPROVE WITH CHANGES / CHANGES REQUIRED), numbered findings (P1 blocking, P2 should change), each with the concrete risk, and a recommended phase-1 scope with its acceptance tests. Do not edit files, commit or push.
```

## Final message (verbatim)

**Verdict: CHANGES REQUIRED.** The direction fits Business Hero, but the design does not yet define a safe worker-access boundary. Its CAS v6 question mapping is also incorrect.

This was a read-only repository and primary-source review. I did not edit files, query production, send messages, commit or push. I did not run `check.sh`; this is design review, not implementation verification.

**Verification of “What already exists”**

| Claim | Finding |
|---|---|
| Membership and profile fields exist | Confirmed in [schema snapshot](/Users/michaelrickards/dev/bh2-TRADE-1/audits/live-schema-public.txt:193), including `is_active`. The snapshot also records `profiles.job_title`. This does not verify today’s live policies. |
| “Only owner is checked” | Misleading: [the resolver](/Users/michaelrickards/dev/bh2-TRADE-1/backend/assistant_chat.py:506) accepts **any active membership**. `owner` determines default-business preference, not authorization. Some newer services have explicit owner checks; protection is inconsistent. |
| No sector field | Correct for [Business](/Users/michaelrickards/dev/bh2-TRADE-1/backend/models.py:23), but industry information already exists in `quote_settings.industry` and `feature_flags["industry"]`. “Nothing marks a business as a trade” overstates the gap. |
| Browser logo upload; no private document store | Confirmed in the inspected storage paths. [BrandingSettings](/Users/michaelrickards/dev/bh2-TRADE-1/frontend/client/src/pages/BrandingSettings.tsx:189) uploads directly to `logos` and obtains a public URL. The backend’s [“upload-url” endpoint](/Users/michaelrickards/dev/bh2-TRADE-1/backend/main.py:1707) returns an empty URL and a path; it does not sign an upload. |
| Quote tables exist | Confirmed in the schema snapshot. |

**Numbered findings**

1. **P1 — Existing owner endpoints must be protected before creating any worker membership.**

   **Risk:** a worker with one active membership passes the shared resolver and can reach APIs that treat membership as owner authority. A separate interface does not prevent direct requests.

   [auth.py](/Users/michaelrickards/dev/bh2-TRADE-1/backend/auth.py:235) and both [shared dependencies](/Users/michaelrickards/dev/bh2-TRADE-1/backend/dependencies.py:16) resolve membership and subscription access without requiring an owner role. Subscription entitlement is not role authorization.

   Require an explicit capability boundary: existing owner APIs default to owner-only; portal capabilities are narrowly granted. Inventory **all** entry points, including direct JWT verification, Aria/chat/voice, exports, integrations, OAuth callbacks and credential-returning endpoints. Audit existing public-table RLS, RPCs and Storage policies too: adding workers may satisfy existing “member of business” policies. Backend checks cannot protect the direct Supabase path.

2. **P1 — Tenant selection, roles and subcontractor identity need a precise model.**

   **Risk:** someone who owns business A and works for B may resolve to A unexpectedly, or inherit inappropriate authority in B. “Their company’s documents” is undefined for several people representing one subcontractor.

   Resolve authorization from `(authenticated user, explicitly selected business, active membership, resource assignment)`. Never treat `owner` as a global user attribute. Reject mismatched business/project/document references, backed by database constraints.

   Separate human identities, tenant memberships, subcontractor organisations and representatives. Define which representatives can upload or read company documents; no shared company login or automatic document sharing between client tenants. Distinguish tenant admin from platform admin. A named site supervisor need not initially receive a broader access role.

3. **P1 — An invitation must not itself grant reusable account authority.**

   **Risk:** forwarding or intercepting a login link lets another person authenticate; a mixed-role user’s account could expose their separate owner business too.

   Define an invitation lifecycle: intended verified recipient, business, least-privilege role, expiry, cancellation, single-use atomic acceptance and audit history. An authenticated recipient must match the invitation; URL parameters cannot choose the role or tenant. Do not automatically merge accounts by unverified email or phone.

   Use allowlisted callbacks, safe session handling, rate limits, resend limits and token redaction. Address link-preview consumption, recycled phone numbers, lost devices and recovery. Owner accounts need protection proportionate to their wider authority.

   Supabase documents **phone OTP through SMS/WhatsApp**, not interchangeable email-style magic links. Specify the supported channel flow rather than promising identical one-tap behaviour everywhere. [Supabase phone authentication](https://supabase.com/docs/guides/auth/phone-login)

4. **P1 — Revocation must work with an already-issued session.**

   **Risk:** “stays signed in” allows a departed worker to retain access if authorization relies on token claims, cached membership or previously signed URLs.

   Check current active membership and assignment on each protected operation, including upload completion and URL issuance. Removal must cancel pending invitations and deny fresh access immediately. Removing membership in B must not disable legitimate ownership in A.

   Specify the residual access window for existing signed URLs. They are bearer capabilities: membership removal does not make an issued URL disappear. If immediate download revocation is required, use an authenticated download gateway. Already downloaded files cannot be recalled.

5. **P1 — A private bucket and business folder are insufficient controls.**

   **Risk:** another member can read sensitive documents, clients can bypass validation, or forged paths can target another tenant.

   Define `storage.objects` permissions for reads, listing, insertion, replacement and deletion. Prefer backend-mediated access with no general client access to the private bucket; service credentials remain server-only. Every signing operation must authorize the document record, tenant, assignment and document category—not merely its path. Supabase service keys bypass Storage RLS. [Storage access control](https://supabase.com/docs/guides/storage/security/access-control)

   Add server-enforced byte limits, actual file-type checks, image decoding and dimension limits, malware handling for documents, generated object names and quarantine until validation completes. Strip EXIF/GPS from image derivatives; do not copy the logo flow’s browser-only checks or SVG allowance. Handle interrupted uploads, orphan cleanup and immutable versions.

6. **P1 — Personal-data controls must precede collection, including phase-1 certificates.**

   **Risk:** the portal collects unnecessary location or identity information without a defined purpose, lawful basis or enforceable deletion schedule.

   “Follow OUT-13” needs a concrete portal extension covering record categories, purposes, controller/processor responsibilities, notices, access, retention triggers, legal holds, deletion jobs and backup/provider copies. An outreach retention policy cannot simply be reused for training and safety records.

   Remove sign-in geolocation from phase 1. For later site evidence, justify precision and necessity, explain collection, and support denied location permission. Device time/location is reported evidence, not proof of presence.

   Employment consent is often unsuitable because of the power imbalance; record the appropriate basis per purpose and assess whether a DPIA is required. Accident records may contain health data requiring an additional special-category condition and narrower access. [ICO worker-monitoring guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/employment/monitoring-workers/data-protection-and-monitoring-workers/?search=example)

7. **P1 — The CAS v6 mapping is materially wrong.**

   The official v6 set is dated **1 November 2026**, but its numbering differs from the design:

   | Subject | CAS v6 question |
   |---|---|
   | Keeping current with legislation, standards and products affecting quality | 132 |
   | Workforce competence records | 133 |
   | Workforce supervision, instruction and information | 134 |
   | Subcontractor selection and monitoring | 135 |
   | Subcontractor quality-management arrangements | 136 |
   | Subcontractor competence records | 137 |
   | Subcontractor supervision, instruction and information | 138 |

   “Every supplier answers” is also inaccurate: applicability and certification exemptions exist. **Risk:** the product could claim readiness against the wrong requirements. Replace the secondary-source mapping with a versioned primary-source mapping, including applicability and exemptions. [Build UK official CAS v6, pp. 64–68](https://builduk.org/CommonAssessmentStandard)

8. **P1 — Phase ordering conflicts with a recorded decision and the North Star.**

   **Risk:** phase 1 ships an incomplete subcontractor experience and stores data invisible to Aria.

   Mike explicitly includes subcontractor insurance/cards in phase 1, while the phase table places competence/documents in phase 3. Resolve this by including a minimal private document submission workflow in phase 1.

   Defer AI drafting and summaries, but **not tenant-scoped Aria read tools**: the tool layer already exists in [assistant_tools.py](/Users/michaelrickards/dev/bh2-TRADE-1/backend/assistant_tools.py). Provide owner-only, minimal projections of new data, with source links and grounding tests. Workers should remain unable to invoke owner Aria.

   State alignment with North Star P2, P6, P8 and P9. Also record the scope authorization: [RC1_SCOPE.md](/Users/michaelrickards/dev/bh2-TRADE-1/docs/RC1_SCOPE.md:3) still says “proposed, not accepted.” Design review does not authorize implementation or production migrations.

9. **P2 — Evidence must not be presented as compliance or guaranteed safety.**

   **Risk:** uploading cards, naming a supervisor or acknowledging RAMS is mistaken for demonstrated competence or compliant practice.

   Use states such as “submitted,” “reviewed,” “missing” and “expired,” with reviewer, date, source and scope. A matrix supports evidence; it does not establish competence by itself. A portal cannot guarantee “nobody starts work without induction.” Record document versions and distinguish personal acknowledgement from attendance recorded by a supervisor.

   Issue reporting also needs delivery status and emergency instructions; it is not automatically statutory accident reporting. CHAS package names and advertised starting prices are supported by [CHAS](https://www.chas.co.uk/contractors/products-packages/), but the public-sector claim needs qualification by procurement scope; CAS does not mandate purchase of CHAS Elite specifically.

10. **P2 — Marketing approval needs durable evidence and withdrawal handling.**

    **Risk:** an owner tick-box authorizes publication without demonstrable consent, customer permission or image rights.

    Keep Mike’s approval rule, but record the exact image/version, approver, permitted uses and supporting permissions. Provide withdrawal and takedown handling, including marketing derivatives. Employee participation must be genuinely optional where consent is used. Approval should not automatically make the operational original public; remove location metadata from the approved derivative.

11. **P2 — Cost controls belong in the storage and invitation foundations.**

    **Risk:** free tenants still incur storage, egress, scanning and messaging costs; retries or OTP abuse can create uncontrolled spend.

    Define file/count/tenant quotas, upload and invitation rate limits, thumbnail strategy, orphan cleanup, usage metering and cost alerts. Count site users by a stated rule—pending, active and revoked should not be interchangeable. Keep pricing undecided as Mike requested; agree operational limits separately.

**Recommended phase-1 scope**

A usable **invite → assigned project → private document submission → owner review → revoke access** slice, serving P2/P6/P8/P9 and the security prerequisite:

- Complete owner/worker authorization across existing backend and Supabase access paths.
- Individual staff/subcontractor identities, explicit business context, invitations and revocation.
- Minimal projects, assignments and a named supervisor; broader supervisor permissions deferred.
- Private subcontractor insurance/card submission with minimal metadata and owner review.
- Validated storage, retention integration, audit records, quotas and site-user counting.
- Owner-only Aria read tools for the new records.
- No phase-1 location capture, marketing publication, accreditation scoring, incident reporting or AI drafting.
- Reconcile existing industry metadata before adding another sector source.

This remains RED. Rehearse the migration with verified staging constraints and rollback; inspect grants/RLS before code containing new SQLModel tables can boot. `create_all()` must not create exposed tables ahead of the approved migration.

**Phase-1 acceptance tests**

| Area | Required evidence |
|---|---|
| Existing owner surface | Worker/subcontractor JWTs fail against every classified owner route, including reads, exports, streams and integrations. A route-inventory test detects unclassified additions. |
| Direct Supabase access | Real authenticated-role tests deny owner tables, RPCs and forbidden Storage operations; tests must not rely solely on mocked backend dependencies. |
| Mixed roles | A user owning A and working in B gets owner capabilities only in A. Missing/forged tenant context never silently selects another business. |
| Resource isolation | Another tenant’s IDs, unassigned projects, coworkers’ cards and unrelated subcontractor documents cannot be read, changed or signed. Cross-tenant relationships fail at database level. |
| Invitations | Wrong-recipient, expired, cancelled and replayed invitations fail; concurrent acceptance creates one membership. Acceptance cannot alter an existing owner identity or elevate a role. |
| Revocation | An existing JWT loses B access immediately after removal; pending uploads cannot finalize and fresh URLs cannot be issued. A remains usable. Existing-link expiry matches the documented bound. |
| Uploads | Spoofed MIME, oversized files, dangerous formats, decompression bombs and unsafe documents are rejected/quarantined. GPS metadata is absent from served image derivatives. |
| Lifecycle and cost | Retention removes objects and derivatives according to policy; failed uploads are cleaned up; quota and resend limits hold under concurrent requests. |
| Aria | Owner tool results match seeded records and counts, omit unnecessary personal data, cite sources and never cross tenants. Worker tool access fails. |
| Verification | Run `./check.sh full`, staging RLS/storage integration tests and phone-browser end-to-end tests. `check.sh` alone cannot establish these behaviours. |

Mike’s behavioural check should be: invite a subcontractor, open their link on a phone, view only the assigned project, submit insurance, review it as owner, then revoke membership and confirm the existing worker session loses access.