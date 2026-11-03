# TRADE-1: the trades site portal (design)

**Status:** design, awaiting Mike's decisions. **Tier:** RED overall: a new user type and sign-in, private photo and document storage, and personal data (training records, photos of people).

**Builder:** Claude. **Reviewer:** Codex. No code until Mike has decided the questions below and Codex has reviewed this design.

## Why (Mike, 23 Oct, 2 and 3 Nov 2026)

- A trades owner needs proof of the work done on site, and of health and safety compliance, from everyone working there: employees and subcontractors.
- Accreditation wins contracts, so the portal should model **CHAS** and **CAS** requirements, and keep the business ready for them all year rather than scrambling at renewal.
- It is built while Mike uses Business Hero daily. MSC is the first business to use it.

## What the schemes ask for (checked 3 Nov 2026)

**CHAS** (now Veriforce CHAS) has three levels:

| Level | What it covers | Price from |
|---|---|---|
| Standard | The SSIP health-and-safety assessment: H&S policy, risk assessments and method statements (RAMS), training and competence, accident reporting, first aid, legal compliance | £429 a year |
| Advanced | Standard plus PAS 91-style modules: environmental, quality, equality, modern slavery | £659 a year |
| Elite | The full **Common Assessment Standard**, now required by public-sector buyers (PPN 03/24) | £949 a year |

**CAS** (Build UK) has 10 sections: identity, financial, corporate standing, health and safety, environmental, quality, building safety, fairness inclusion and respect, information security, and information management. **Version 6 took effect on 1 November 2026** and matters directly for this portal:

- **Q135, competence records** (moved to Quality, so every supplier answers it): a competence matrix of training records, certificates and CPD, covering the workforce *and key subcontractor roles*.
- **Q136, supervision:** how each team gets supervision, instruction and information, with named supervisors per team.
- **Q138, keeping up to date:** how the business tracks changes such as the Building Safety Act and Building Regulations.

The exact question wording is checked against Build UK's published v6 set when we build.

**Sources:**
- [CAS v6 changes](https://www.joblogic.com/blog/common-assessment-standard)
- [Build UK CAS question set v5](https://builduk.org/wp-content/uploads/2025/07/Common-Assessment-Standard-Question-Set-Version-5.pdf)
- [CHAS levels and documents](https://www.tradecomply.co.uk/guides/chas-accreditation-explained-pillar)

## What already exists (verified in code, 3 Nov 2026)

- **Team members:** `business_members` (with `role`, `invited_email`, `user_id`) and `profiles` (with `job_title`). In practice the app is owner-only: there is no invite flow, and only `owner` is checked.
- **Sector:** there is no sector field on `businesses`, so nothing marks a business as a trade.
- **Files:** Supabase Storage is used only for the logo, uploaded from the browser. There is no private, per-business document or photo store.
- **Quotes:** `quotes`, `quote_line_items` and `quote_settings` exist. They are relevant to the estimator ticket that follows, not to this one.

## The design, in plain terms

### People and roles

| Role | Who | Sees |
|---|---|---|
| Owner or admin | Mike | Everything: every project, person, record and the compliance dashboard |
| Supervisor | A named lead per team or site (CAS Q136) | Their projects, their team's records, sign-offs |
| Worker | An employee | Their own projects, briefs, inductions, talks; their own uploads |
| Subcontractor | A key subcontractor (a firm or a person) | As a worker, plus their company's own insurance and certificates |

- Workers and subcontractors never see the business's finance, inbox, Aria or other areas. They get a separate, phone-first part of the app.

### What each part does

**For people on site (phone-first):**
1. **My projects:** the projects I'm assigned to, with the site address and the brief (scope, hazards, RAMS, site contacts).
2. **Site induction:** the first time on a project, the person reads the induction and the RAMS and signs (name, time, location). Nobody starts work without it, and the owner sees who has and hasn't been inducted.
3. **Toolbox talks:** the supervisor runs a talk and everyone present signs it on their phone or on the supervisor's phone. It is recorded with date, site, topic and attendees.
4. **Daily evidence:** progress photos and notes against the project and a task, with time and location. These are proof of work for the owner and the customer.
5. **Report an issue:** accident, near miss, unsafe condition. It is routed to the owner immediately (and by WhatsApp, if set up). This is CHAS accident reporting.
6. **My competence:** each person's cards and qualifications (CSCS, SMSTS or SSSTS, asbestos awareness, working at height and so on), uploaded once, with expiry dates.

**For the owner (in Business Hero):**
1. **Projects:** create a site, assign people and a supervisor, write the brief and attach the RAMS.
2. **Live feed:** everything coming in from site: inductions, talks, photos and issues.
3. **People and competence matrix:** everyone (staff and subcontractors) against the qualifications their role needs, with expired or missing items flagged. This *is* the CAS Q135 evidence.
4. **Company documents:** H&S policy, insurance (employer's liability, public liability), environmental and quality policies, modern slavery statement, and the existing CHAS or SSIP certificate, each with an expiry or review date and reminders.
5. **Compliance dashboard:** readiness against CHAS (the level the business chooses) and CAS, by section. It shows what's evidenced, what's missing and what expires soon, and points to where in the app the evidence lives.
6. **Evidence pack:** one export of the evidence for the business's renewal (policies, competence matrix, induction and toolbox-talk records, accident log), arranged by CHAS or CAS section. It is like the accountancy pack, but for accreditation.
7. **Marketing photos:** the owner marks a progress photo as approved for marketing, under the consent rules below.

### Aria's part (later phases; she follows the profit rule)

- Drafting a toolbox talk on a topic.
- Turning a brief into an induction checklist.
- Summarising the week's site activity in the owner's briefing.

## RED areas and how each is handled

- **A new kind of user:** workers and subcontractors sign in with their own identity and their role decides what they see. Every new endpoint is checked in tests, as for the plan enforcement work: a worker can never reach owner data, and businesses never see each other's data.
- **Private files:** photos and documents go to a **private** storage bucket, one folder per business, readable only through short-lived signed links the backend issues after checking the person's role. They are never public URLs like the logo.
- **Personal data:** training records, photos of people, location and time stamps.
  - Retention and deletion follow OUT-13, which becomes a dependency.
  - Location is captured only at sign-in and upload, never tracked.
- **Database changes:** new tables (projects, assignments, inductions, talks, evidence, competence records, company documents, issues), each with row-level security. They are migrations Mike runs from runbooks.

## Phases (proposed)

| Phase | Delivers | Why first |
|---|---|---|
| **1. Foundations** | sector marking, roles and worker sign-in, projects and assignment, private storage | everything else rests on it |
| **2. On site** | inductions, toolbox talks, daily evidence, issue reporting, the owner's live feed | the daily value for MSC |
| **3. Competence and documents** | competence records, the competence matrix, company documents with expiry reminders | CAS v6 Q135 and Q136 |
| **4. Accreditation** | the CHAS and CAS readiness dashboard, the evidence pack export | the renewal payoff |
| **5. Aria and marketing** | AI-drafted talks, briefing summaries, marketing photo approvals | nice to have, metered |

Each phase is its own ticket, with tests first, a Codex review, and Mike's sign-off.

## Decided by Mike (3 Nov 2026)

1. **Sign-in for site workers and subcontractors:** by invite link, with no password. The owner invites by email or mobile; the person taps a sign-in link (sent by email, WhatsApp or SMS) and stays signed in on their phone. No app store.
2. **Subcontractors are in from phase 1.** They sign in like staff and upload their own company insurance and cards (CAS v6 covers key subcontractor roles).
3. **Pricing is decided at the pre-launch pricing review.** Site users are counted per business from the start, so the portal can be priced per person or included up to a number. MSC and New Body stay free.
4. **The readiness dashboard models CHAS Standard first,** plus CAS v6's competence, supervision and keeping-up-to-date questions (Q135, Q136, Q138), which every supplier now answers. Advanced and Elite (full CAS) sections come later.
5. **Marketing photos:** every photo is private by default. The owner approves each one for marketing and, when approving, confirms that:
   - no identifiable person is shown without their consent;
   - the customer has agreed to their property being shown.

   A reminder appears at approval.
