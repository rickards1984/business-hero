# RC1 — the decisions waiting on Mike

Every open scope question in one place, in plain English, each with a
recommendation and what it costs. **Nothing here has been decided.** The RC1
boundary is Mike's gate; this document exists so the choice is informed, not
so it is pre-empted.

Two groups, and the split matters: **Part A cannot be traded away** — they are
security or correctness, and shipping without them means shipping something
known to be wrong. **Part B is genuine product scope** — reasonable people
could ship RC1 either way.

---

## Part A — required. Security and correctness, not scope

### A1 · Deploy the accounting tenant-isolation fix (BH-002)

**What.** One business could attach another business's expense category to its
own transaction, and six different screens then displayed that other
business's category name — including an Excel pack customers send to their
accountant, and the AI assistant's spending answers.

**Why it is not optional.** It is a cross-tenant data leak. It was confirmed
in code and reproduced on synthetic data, twice, by an independent reviewer.

**Recommendation: deploy it, on its own, before anything else in RC1.** It is
backend-only, no schema change, and rollback is `git revert`. Run the detection
query in `docs/BH-002-DEPLOYMENT.md` first so you know whether any real rows
are affected.

**Cost.** Under an hour, including your browser checks. No dependency on the
foundation work.

---

### A2 · Fix the two confirmed Stripe defects (RC1 P0-7)

**What.** A `customer.subscription.deleted` webhook carrying an old Pro price
*upgrades* the business to Pro, because deletion is handled identically to
creation. And the de-duplication record is written *after* the account change
is committed, so a replayed webhook applies the change twice.

**Why it is not optional.** It is billing correctness. Both were reproduced
against the extracted handler. `CURRENT_STATE.md` previously claimed both
already worked.

**Recommendation: keep in P0, and fix before any founder account moves to a
real subscription** — that is exactly when replays and cancellations start
arriving.

**Cost.** Small — half a day with tests. Acceptance criteria are already
written into P0-7.

---

### A3 · Revoke the `businesses` UPDATE grant before claiming enforcement works
*(RC1 P0-3, sequencing)*

**What.** `authenticated` — which is customers *and* admins, the same Postgres
role — currently holds table-wide UPDATE on `businesses`.

**Why it is not optional.** While it stands, a customer can edit their own
`plan_tier` or `feature_flags` directly. Every server-side entitlement gate in
P0-1 is then decoration. Shipping P0-1 and calling entitlement "enforced"
while this grant exists would be a false claim.

**Recommendation: move P0-3 ahead of P0-1**, or at minimum forbid any
"enforcement is complete" statement until it lands. Q6 of the BH-001 read
tells you whether the grant is still there.

**Cost.** Sequencing only — no extra work, just a different order.

---

### A4 · Move the non-registered-business VAT slice from P1-8 into P0

**What.** "An invoice PDF from a non-VAT-registered business shows no VAT line
at all" is listed as a release criterion in `RC1_SCOPE.md`, but the work sits
in P1-8 (region rollout).

**Why it is not optional.** A non-registered contractor showing VAT on an
invoice is charging tax they cannot collect. That is a legal problem, not a
polish problem — and it is the exact customer RC1 targets.

**Recommendation: move that one slice into the P0 money path.** Leave the rest
of P1-8 (multi-region rollout) at P1.

**Cost.** Small. It is one branch in the PDF renderer plus a test, not the
whole region feature.

---

### A5 · Give the PDF and manual-invoice work one shared contract

**What.** P0-4 (invoice PDF) and P0-5 (manual invoice creation) are separate
tickets that both produce invoices.

**Why it is not optional.** Two invoice-producing paths with different rules is
how a VAT bug ships on one and not the other, and how a read-only customer
gets blocked on one path and not the other.

**Recommendation: state once — same entitlement gate, same read-only
behaviour, same tax treatment — and have both tickets cite it.**

**Cost.** An hour of writing. It removes a whole class of divergence.

---

## Part B — genuine product scope. Either answer is defensible

### B1 · Does receptionist service ship in RC1?

**The tension.** RC1 is described as "the smallest contractor edition", but
P0-2 includes full receptionist metering and hard caps — a substantial piece
of work that only matters if the receptionist is live for customers.

**If yes:** RC1 grows by the metering system, the cap enforcement, and the
overage path. Weeks, not days. But founder accounts start producing the
allowance calibration data the pricing model needs.

**If no:** RC1 ships materially sooner. Metering moves to RC2, the receptionist
stays founder-only, and the 350/120-minute allowances stay uncalibrated until
then.

**Recommendation: no — defer receptionist metering to RC2.** RC1's stated test
is the contractor money journey: lead → quote → invoice → payment. The
receptionist is not on that path. Deferring keeps the release honest to its own
definition.

**Watch out for:** the entitlement spec's founder-account decision (MSC on
`business`, New Body on `pro`) exists *to calibrate allowances*. Deferring
metering means that calibration does not start yet. Worth accepting knowingly.

---

### B2 · Which direction does "accounting sync" go?

**The tension.** The RC1 journey ends in "accounting sync", but the code that
exists imports data *from* Xero/QuickBooks/FreeAgent. No push-invoice
implementation was found. So either the journey means something already built,
or it means something not yet started.

**If import-only:** the journey is already covered, and nothing more is needed.

**If it means pushing invoices out:** that is an unbuilt integration against
three providers, and it is a large addition to RC1.

**Recommendation: define it as import-only for RC1** and rewrite the journey
to say so. Pushing invoices to the customer's accounting package is a real
feature, and it deserves its own release rather than arriving as an
unexamined implication of one phrase.

**Cost of the recommendation:** none. It is a definition.

---

### B3 · Who builds the export that read-only customers are promised?

**The tension.** The entitlement decision promises unpaid and cancelled
customers can still export their quotes and invoices — the statutory-records
argument. No ticket in RC1 builds an export.

**Recommendation: add a small P1 ticket for quote/invoice CSV+PDF export, or
remove the promise from the spec.** Do not leave it as written, because as
written it is a commitment with no owner.

**Cost.** Small if the PDF work in P0-4 is reused.

---

### B4 · Define subscription-status access next to plan gating, not after it

**The tension.** P0-6 (status drives access) currently sits after P0-2
(metering). Both P0-1 and P0-6 decide "can this caller do this thing".

**Recommendation: specify plan gating and status gating together as one access
decision, even if they are built in two tickets.** Building them apart means
writing the same decision twice and reconciling it later.

**Cost.** Sequencing only.

---

## And one that is not RC1 scope at all

**A database constraint for category ownership.** A composite foreign key on
`(category_id, business_id)` would make BH-002's whole class of bug impossible,
rather than relying on three application checks staying correct forever. It is
a schema change, so it is RED and needs a migration runbook. **Recommendation:
open it as a post-RC1 ticket now, so it is not forgotten** — the application
fix is correct, but it is a fix that a future careless join can undo.
