# Business Hero — Compliance & Site Operations Module

**Status: planned, post-launch.** Not started. Business Hero core ships first.

This document records the brief, the decisions taken around it, and the
findings that shaped them. It is the starting point for the architecture
proposal, not the architecture itself.

---

## 1 · The brief

> Business Hero is an existing multi-tenant UK SME business-management
> platform. Do NOT create a standalone application. The new Compliance module
> must integrate into the existing Business Hero repository, authentication,
> business/tenant model, subscription/feature system and existing
> project/quoting/business data wherever appropriate.
>
> The first production tenant and live pilot is Multi Skilled Contractors Ltd
> (MSC), a small UK construction contractor preparing for CHAS Elite and the
> Build UK Common Assessment Standard Version 5.
>
> However, the architecture MUST be multi-tenant and productised from day one
> so Business Hero can later sell Compliance as a subscription module to other
> businesses.
>
> Product principle: Do not build a "CHAS questionnaire app". Build a generic
> compliance-control and evidence-management engine. CAS V5 is the first
> versioned framework mapped into that engine.
>
> The engine must separate: company controls; framework requirements;
> policies; evidence; tasks; people; contractor businesses;
> competency/qualifications; insurances; projects; site evidence; audits;
> findings; and immutable audit history.
>
> Frameworks must be versioned because Build UK CAS V6 is due 1 November 2026.
> A control should be able to map to several framework requirements and
> eventually to several standards.
>
> Worker experience will be a mobile-first PWA/Home-Screen web application
> using the existing Business Hero identity where practical. Workers should see
> only information/actions relevant to them and their assigned projects.
> Management should see full compliance status and evidence.
>
> Required first workflows include contractor onboarding/approval,
> qualifications and expiry monitoring, insurance monitoring, RAMS issuance and
> acknowledgement, site induction, daily site record, toolbox talk,
> hazard/near-miss/accident reporting, quality inspections/snags, variation
> records, plant/equipment checks and project-document access.
>
> Google Drive should initially remain an optional external document
> repository. Business Hero should store controlled metadata, mappings,
> versions and references rather than trying to replace Drive storage
> unnecessarily.
>
> AI may draft, classify, summarise and recommend. AI must NOT autonomously
> certify compliance. Compliance status must derive from deterministic
> requirements, verified records and authorised human approval.
>
> All new tables must be tenant-scoped and secure from creation. Apply Business
> Hero's current secure server-side patterns and RLS model. No client-controlled
> business IDs, no frontend-only authorisation and no unprotected storage of
> compliance/worker data.
>
> Do not reproduce the complete Build UK CAS copyrighted question set in
> product code at this stage. Create an extensible framework/mapping layer with
> our own control descriptions.
>
> Before coding: inspect the current repo, current migrations, auth/business
> membership model, feature entitlement implementation, existing
> projects/tasks/files/quoting entities and existing security remediations.
> Produce an architecture proposal and migration plan. Do not duplicate
> existing entities unnecessarily.
>
> Phase 1 deliverable: schema + architecture + route map + RBAC model + UI
> information architecture + implementation plan. No broad implementation until
> reviewed.
>
> Roles anticipated: platform admin, business owner/admin, compliance manager,
> project/site manager, supervisor, employee/operative, subcontractor business
> admin, subcontractor operative, auditor/read-only.
>
> Success criterion: MSC should be able to operate through Business Hero for
> several weeks and naturally produce the evidence needed for its CHAS
> Elite/CAS desktop assessment while running actual projects.

---

## 2 · Decisions taken

### D1 — Sequencing: after launch, marketed at launch

Business Hero core ships first. Compliance is announced as "coming soon" and
built afterwards.

**MSC's CHAS Elite desktop assessment is prepared separately**, using Google
Drive documents, and is **not blocked on this software**. Those are two
different goals with two different deadlines, and conflating them is how the
assessment date gets missed.

### D2 — Scope correction: desktop ≠ site verification

CAS has two assessment levels. **Desktop reviews documents remotely; the
site-based level adds an on-site verification audit.** MSC is going for the
desktop assessment.

On the assessment critical path:
- Policies and their version history
- Insurances and expiry monitoring
- Competency, qualifications and card expiry
- Contractor onboarding and approval records
- Evidence that documented procedures are actually followed

**Not** on the assessment critical path — valuable for operations and for the
product, but not needed for the desktop review:
- Daily site records, toolbox talks, site inductions
- Plant and equipment checks
- Hazard, near-miss and accident reporting
- Quality inspections and snags

This materially reduces Phase 1.

### D3 — Framework versioning is a dated requirement

CAS V5 is current. **Version 6 publishes 1 November 2026.** Versioned
frameworks with many-to-many control mapping are therefore not premature
abstraction — remapping is a known, dated event. Controls describe what the
business does; framework versions describe what a standard asks for; the
mapping between them changes without the controls changing.

### D4 — One codebase, separate products

Compliance ships as a **separately purchasable module** with its own entry
point, its own branding and its own pricing — but shares the platform's
auth, tenant model, entitlement system and codebase. Same pattern as Control
Tower: sell standalone *or* bundled, never all-or-nothing.

The reason is commercial, not technical. **Compliance sells to a different
buyer than Business Hero does.** Business Hero is bought by an owner who wants
their admin handled; compliance is bought by someone facing a CHAS deadline or
a main contractor demanding accreditation. Different urgency, different pitch,
often a different person. A business already using Constructionline and a
separate accounting package might buy compliance alone.

A second codebase would buy nothing: the permission boundary has to be correct
either way, and building it twice doubles the surface where it can be wrong.
The real protection is server-side entitlement plus RLS.

`compliance` becomes a canonical feature key alongside `outreach`.

### D5 — A new user type, not a new role

A subcontractor operative reaching only the compliance module is **not a
permissions tweak**. Everything today assumes a member of a business sees that
business's data. This is a person attached to **projects**, seeing only their
own tasks and evidence, with no access to quoting, invoicing, accounting or
the assistant.

Closer to a portal than a role. Two consequences:
- It needs its own access model, designed rather than retrofitted
- **It must not consume a paid seat at £25.** Operative headcount is not the
  same as management headcount, and pricing it per-seat would make the module
  unsellable to anyone with a real workforce

### D6 — Includes a project planner

Not compliance and safety alone. The module holds **progress** accountable as
well as compliance.

Compliance evidence and job progress are largely the same records viewed
differently — a daily site record is both. Building them as separate systems
would mean capturing the same information twice, which is exactly what makes
site software get abandoned.

### D7 — Liability: manage evidence, never certify

Compliance software carries exposure that quoting software does not. If a
customer fails an audit or has an accident and the product said "compliant",
the product is in the conversation.

- The UI must **never state a compliance verdict.** Only "requirements met"
  against recorded evidence, with the evidence visible
- Terms must state explicitly that the product manages evidence and does not
  certify or guarantee compliance
- AI drafts, classifies, summarises and recommends. **AI never certifies.**
  Status derives from deterministic requirements, verified records and
  authorised human approval
- Design this in from the start; it is not retrofittable

---

## 3 · Open questions

1. **When is MSC's desktop assessment?** The hard deadline. If it falls after
   1 November 2026, MSC is assessed against **V6**, which changes what to map.
2. **What does MSC use for evidence today** — paper, WhatsApp, Drive, nothing?
   Determines how much is new build versus organising what exists.
3. How many operatives and subcontractors would need access at MSC? Sizes the
   portal and tests the pricing assumption in D5.

---

## 4 · Phase 1 deliverable

Schema, architecture, route map, RBAC model, UI information architecture and
implementation plan. **No broad implementation until reviewed.**

Before any of that: inspect the current repo — migrations, auth and business
membership model, the entitlement implementation as of `033`, existing
project/task/file/quoting entities, and the security remediations in `030a`,
`030b` and `031`. Do not duplicate existing entities.

**Do not reproduce the Build UK CAS question set in product code.** It is
copyrighted. Build an extensible framework/mapping layer with our own control
descriptions.
