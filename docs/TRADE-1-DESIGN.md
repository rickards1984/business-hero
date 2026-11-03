# TRADE-1: the trades site portal (design, revision 2)

**Status:** design revised after Codex design review 1 (`audits/TRADE-1-CODEX-REVIEW-1.md`, CHANGES REQUIRED: 8 × P1, 3 × P2). Every finding is taken; see "Review 1 → changes" at the end.

**Tier:** RED: a new user type and sign-in, private storage, and personal data.

**Builder:** Claude. **Reviewer:** Codex. No code until Codex has re-reviewed this revision **and** Mike has added the portal to the accepted scope (`docs/RC1_SCOPE.md` is still "proposed, not accepted"; design review alone authorises nothing).

## Why (Mike, 23 Oct, 2 and 3 Nov 2026)

- A trades owner needs proof of work and health-and-safety evidence from everyone on site: employees and subcontractors.
- Accreditation wins contracts, so the portal should keep the business's **CHAS** and **CAS** evidence organised all year, not just at renewal.
- It is built while Mike uses Business Hero daily, with MSC as the first business.

**What the portal is not:** it holds and organises *evidence*. It never certifies that anyone is competent or compliant, or that a site is safe. Labels say "submitted", "reviewed", "missing" or "expired", never "compliant" (review 1, finding 9).

## The schemes (checked 3 Nov 2026)

**CHAS** (Veriforce CHAS) has three packages:

| Package | What it covers | Price from |
|---|---|---|
| Standard | The SSIP health-and-safety assessment: policy, RAMS, training and competence, accident reporting, first aid, legal compliance | £429 a year |
| Advanced | Adds PAS 91-style modules | £659 a year |
| Elite | The full Common Assessment Standard | £949 a year |

Public-sector buyers increasingly ask for CAS-level pre-qualification (PPN 03/24, within its procurement scope). CAS itself doesn't require buying CHAS Elite specifically.

**CAS** (Build UK) has 10 sections. The **official version 6 is dated 1 November 2026**. As Codex read it from the official document (pp. 64–68), the quality-section questions this portal can evidence are:

| CAS v6 | Subject |
|---|---|
| Q132 | Keeping up to date with legislation, standards and products affecting quality |
| Q133 | Workforce competence records |
| Q134 | Workforce supervision, instruction and information |
| Q135 | Subcontractor selection and monitoring |
| Q136 | Subcontractor quality-management arrangements |
| Q137 | Subcontractor competence records |
| Q138 | Subcontractor supervision, instruction and information |

**Applicability conditions and certification exemptions apply.** The product will hold a **versioned mapping** (scheme, version, question, applicability), checked against Build UK's official document before phase 4 is built. Phase 1 makes no accreditation claims.

## What already exists (verified in code, corrected after review 1)

- **Team members:** `business_members` (`role`, `invited_email`, `user_id`, `is_active`) and `profiles`.
  - **The shared resolver accepts *any* active membership** (`assistant_chat.get_business_for_user`; `auth.py` and `dependencies.py`). `owner` only decides which business is the default. Owner-only protection exists in a few newer services, but not consistently.
  - **Today that's safe only because every member is an owner.** Adding a worker without changing it would give the worker owner access.
- **Industry:** `quote_settings.industry` and `feature_flags["industry"]` already exist. Trade businesses are marked from these, reconciled into one source, rather than with a third field.
- **Files:** only the logo uses Storage. It's uploaded from the browser to a public `logos` bucket. The backend's "upload-url" endpoint returns a path, not a signed upload. There is no private store.
- **Quotes:** these tables exist (relevant to the estimator ticket that follows).

## The security model (review 1, findings 1–5)

### Authority comes from four things, checked on every request

1. **Who:** the authenticated user.
2. **Which business:** an *explicitly selected* business. It's never inferred when the user belongs to more than one; a missing or forged choice is refused, never silently swapped.
3. **The active membership:** read from the database on each protected operation. It is never trusted from a token claim or a cache, so removal takes effect at once.
4. **The resource assignment:** for site users, the project, or their own documents, checked against the record, never against a path.

`owner` is never a global attribute of a person. Someone who owns business A and works for business B is an owner only in A.

### Capabilities, not membership

- **Every existing endpoint becomes owner-only by default.** This is a capability check, separate from plan entitlement, which is not authorisation.
- **Portal endpoints grant narrow capabilities:** for example, read my assigned project, or submit my own document.
- **A route inventory classifies every route** (the plan-enforcement inventory already does this). A test fails on any unclassified route, and on any portal JWT reaching an owner route. That includes reads, exports, streams, Aria chat and voice, integrations, OAuth callbacks and anything that returns credentials.
- **The direct database path:** row-level security, RPCs and Storage policies are audited. Any "member of business" policy becomes owner-only, or is narrowed, **before** the first worker membership can exist. This is proven with real authenticated-role tests on a staging database, not just mocked backend tests.

### Identities and organisations

- **Kept separate:**
  - a *person* (a Supabase user);
  - a *membership* (a person in a business, with a role: owner, admin, worker or subcontractor representative);
  - a *subcontractor organisation* (a firm, within one client business);
  - a *representative* (a person acting for that firm).
- **Representatives:** a firm's representatives can upload and read only that firm's documents within that client business. There are no shared company logins, and nothing is shared automatically between different client businesses.
- **The named site supervisor** is a label on an assignment in phase 1. Wider supervisor permissions come later.
- **Tenant admin is not platform admin.**

### Invitations

- **Each invitation records:**
  - the intended recipient (email or phone);
  - the business;
  - the least-privilege role;
  - an expiry;
  - its status (pending, accepted, cancelled or expired);
  - an audit history.
- **Acceptance is single-use and atomic.** The signed-in person must match the intended recipient. Nothing in the URL can choose the role or business. Accounts are never merged automatically on an unverified email or phone.
- **Sign-in** (Mike's decision: no password) uses **Supabase email magic links or phone OTP codes by SMS or WhatsApp**. These are different flows, so the screen explains whichever one is used. It does not promise identical one-tap sign-in everywhere.
- **Safeguards:**
  - allowlisted redirect URLs;
  - rate limits on sends and resends;
  - tokens redacted from logs;
  - protection against link-preview bots consuming links;
  - a recycled phone number can't inherit an account;
  - lost-device and recovery handling.
- **Owner accounts** have wider authority and get stronger protection than workers' accounts.

### Revocation

- **Removing someone from business B:**
  - cancels their pending invitations;
  - denies every fresh request at once, including upload completion and new file links;
  - never touches their ownership of business A.
- **File links:** each lasts at most **5 minutes**. A link already issued can still be used until it expires, and that window is stated in the app. Files already downloaded can't be recalled.

### Private storage

- **The bucket:** one **private** bucket, with no browser access at all. Uploads and downloads go through the backend. Service credentials stay on the server (they bypass Storage RLS, so the backend's checks are the control). Storage policies deny everything to browser roles.
- **Every signed link** is issued only after checking the *document record*: business, assignment, owner of the document and category. The file path alone is never enough.
- **Validation before a file is accepted:**
  - server-side size limits;
  - real file-type detection (not the browser's MIME type);
  - images decoded, with dimension and decompression-bomb limits;
  - no SVG;
  - documents limited to PDF and images, and scanned or quarantined until validated;
  - generated object names;
  - versions kept, not overwritten.
- **Location data:** EXIF and GPS are stripped from every image that's served.
- **Housekeeping:** interrupted uploads and orphaned files are cleaned up.

## Personal data (review 1, finding 6)

- **A portal data-protection section is written before collection begins.** For each kind of record (certificates and cards, project assignments, induction and toolbox-talk sign-offs, photos, issue reports), it covers:
  - the purpose and lawful basis;
  - who is controller and processor;
  - the notices people see;
  - access;
  - the retention trigger and period;
  - legal holds;
  - deletion jobs (including backups and provider copies).
- **Consent is not used as the basis for employees' records:** the power imbalance makes it unsuitable. Each purpose gets its proper basis, and **a DPIA is assessed**.
- **Accident and issue reports can contain health data.** That needs an additional special-category condition and narrower access. This is why issue reporting is *not* in phase 1.
- **No location capture in phase 1,** including at sign-in. If later phases use it, its precision and necessity are justified and explained, a denied permission still works, and device time and location are recorded as *reported*, not as proof of presence.
- **This builds on OUT-13 (retention)** with a portal-specific schedule. OUT-13 must be in place before real personal data is collected.

## Phases (revised)

| Phase | Delivers |
|---|---|
| **0. Owner boundary** (security prerequisite, ships before any worker exists) | Every existing route classified and made owner-only by capability; RLS, RPC and Storage policies audited and narrowed; the route-inventory test; staging role tests |
| **1. Invite to review to revoke** | Identities, memberships and explicit business choice; invitations and revocation; subcontractor organisations and representatives; minimal projects with assignment and a named supervisor; **private document submission** (insurance, cards and certificates, with minimal metadata) and **owner review** (submitted, reviewed, missing, expired); validated private storage; the retention schedule for these records; audit records; quotas and site-user counting; **owner-only Aria read tools** for the new records (tenant-scoped, sourced, grounding-tested); trade businesses marked from the existing industry fields |
| **2. On site** | Project briefs and RAMS with document versions; inductions (personal acknowledgement recorded separately from supervisor-recorded attendance); toolbox talks; daily evidence photos and notes (no location unless justified); the owner's live feed |
| **3. Competence and documents** | The competence matrix (Q133 and Q137 evidence; evidence supports competence but doesn't establish it); company documents with expiry reminders; reviewer, date, source and scope on every record |
| **4. Accreditation** | The versioned CHAS Standard and CAS v6 mapping (applicability, exemptions); readiness by section (evidenced, missing, expiring); the evidence pack export |
| **5. Issues, marketing, Aria drafting** | Issue reporting (delivery status, emergency instructions, special-category handling; not automatically RIDDOR reporting); marketing photo approval; AI-drafted talks and briefing summaries (metered) |

**Not in phase 1:** location capture, marketing publication, accreditation scoring, issue reporting, AI drafting.

## Phase 1 acceptance tests (review 1)

| Area | Evidence required |
|---|---|
| Owner surface | A worker or subcontractor JWT fails on every classified owner route. The route-inventory test catches unclassified routes. |
| Direct Supabase path | Real authenticated-role tests on staging deny owner tables, RPCs and Storage operations. |
| Mixed roles | Owner of A and worker in B gets owner capabilities only in A. A missing or forged business is refused, never silently swapped. |
| Isolation | Another business's ids, unassigned projects, co-workers' cards and other firms' documents can't be read, changed or signed. Cross-business links are rejected by database constraints. |
| Invitations | Wrong recipient, expired, cancelled and replayed invitations all fail. Two concurrent acceptances create one membership. Acceptance can't change an existing owner identity or raise a role. |
| Revocation | An existing JWT loses access to B immediately: uploads can't complete and no new links are issued. A still works. Existing links expire within the stated 5 minutes. |
| Uploads | Spoofed types, oversized files, dangerous formats and decompression bombs are rejected or quarantined. Served images carry no GPS. |
| Lifecycle and cost | Retention removes objects and derivatives on schedule. Failed uploads are cleaned up. Quotas and resend limits hold under concurrency. |
| Aria | Owner tool results match the seeded records, carry sources, omit unnecessary personal data and never cross businesses. Workers can't use them. |
| Whole flow | `./check.sh full`, staging RLS and storage tests, and a phone-browser end-to-end test. |

**Mike's check:** invite a subcontractor, open the link on a phone, see only the assigned project, submit insurance, review it as owner, then remove them and confirm their open session loses access straight away.

## Cost controls (review 1, finding 11)

- **Limits:**
  - per-business file count and storage quotas;
  - per-file size limits;
  - rate limits on uploads and invitations;
  - thumbnails, with originals fetched only on request;
  - orphan cleanup.
- **Metering:** storage and messaging use is metered, with cost alerts. SMS and WhatsApp codes cost money, so their sending is capped.
- **Counting site users:** active memberships are counted; pending invitations and removed users are reported separately. The price itself stays undecided until the pricing review (Mike).

## Decided by Mike (3 Nov 2026)

1. **Sign-in:** by invite, with no password. The owner invites by email or mobile. The person signs in with an email link or a phone code (SMS or WhatsApp) and stays signed in on their phone. No app store.
2. **Subcontractors are in from phase 1.** Each firm's representatives upload its own insurance and cards (CAS v6 Q135–Q138).
3. **Pricing:** decided at the pre-launch pricing review. Site users are counted from the start. MSC and New Body stay free.
4. **The readiness model starts with CHAS Standard** plus the CAS v6 workforce and subcontractor competence and supervision questions (Q132–Q138, applicability permitting). Advanced and Elite come later.
5. **Marketing photos** are private by default, and the owner approves each one. Approval records:
   - the exact photo version;
   - the approver and date;
   - the permitted uses;
   - the people and customer permissions confirmed.

   The approved copy has its location stripped and is separate from the operational original. Withdrawal and takedown are supported. Taking part is optional for employees. (Phase 5.)

## Review 1 → changes

| # | Finding | Change |
|---|---|---|
| 1 | Owner endpoints reachable by any member | Phase 0: capability boundary, route inventory, RLS, RPC and Storage audit before any worker exists |
| 2 | Tenant, role and subcontractor model | Four-part authority; people, memberships, organisations and representatives kept separate; owner per business |
| 3 | Invitation authority | Invitation lifecycle, recipient match, no URL-chosen role, safe sign-in flows |
| 4 | Revocation with live sessions | Membership checked per request; 5-minute file links; the window stated |
| 5 | Storage controls | Backend-only private bucket, record-based signing, validation, quarantine, EXIF stripping |
| 6 | Personal data | Portal data-protection section first; no consent basis for employees; DPIA; no location in phase 1; issues deferred |
| 7 | CAS v6 numbering | Corrected to the official v6 (Q132–Q138); versioned mapping with applicability; re-check before phase 4 |
| 8 | Phase order and North Star | Document submission and owner review in phase 1; owner Aria read tools in phase 1; the scope authorisation gate recorded |
| 9 | Evidence presented as compliance | Evidence states only; induction not guaranteed; issues are not statutory reporting |
| 10 | Marketing approval | Recorded approval, permitted uses, withdrawal, stripped derivative |
| 11 | Cost | Quotas, limits, metering and a site-user counting rule |

## Codex design review 2 (`audits/TRADE-1-CODEX-REVIEW-2.md`)

The original 11 findings are resolved at design level; a few are noted as partial. The three remaining P1s concern the phase-0 owner boundary:

- route classification categories;
- the business-selection contract and OAuth state binding;
- revocation in open voice sessions.

They are taken in full in `docs/TRADE-0-TICKET.md`, which also carries the inventory and acceptance tests from that review. Phase 0 runs as its own RED ticket.
