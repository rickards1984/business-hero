# Definition of Done

A ticket is done when **every** applicable gate below passes. Not when the
code is written, and not when the builder believes it works.

This is the merge gate. A reviewer refusing a merge cites a gate number.

---

## Gate 0 — the ticket was ready

- [ ] Ticket followed the packet in `AGENTS.md` §6
- [ ] **Current evidence** cited a real file:line, test name or audit
      document. A ticket with no evidence of the problem should never have
      started
- [ ] Risk tier (GREEN/AMBER/RED) declared, and the tier's rules were
      followed — for RED, **the tests existed and Mike reviewed them before
      implementation**

---

## Gate 1 — verification is green and recorded

- [ ] `./check.sh full` passes on the final commit
- [ ] **The actual output is pasted into the ticket.** Not "tests pass" — the
      counts, so a reviewer can see 382 became 391 and not 382 became 380
- [ ] The run is from the final state of the branch. A check output that
      predates the last commit or a rebase does not count
- [ ] CI is green on the PR

## Gate 2 — the change is tested

- [ ] New behaviour has a test that **fails without the change**. If you did
      not watch it fail, you have not shown the test tests anything
- [ ] Every reproducible bug leaves behind a regression test
- [ ] Tests assert behaviour, not implementation
- [ ] For anything touching money, entitlement, tenancy or auth: the test
      covers the failure case and the boundary, not only the happy path
- [ ] No test was weakened, skipped or deleted to make the suite pass. If one
      had to change, the ticket says which and why

## Gate 3 — honest status

- [ ] The ticket states what was **verified** and what was only **written**,
      using the vocabulary in `docs/CURRENT_STATE.md` §0
- [ ] Anything `check.sh` cannot verify — visual layout, third-party
      behaviour, production data — is called out explicitly with the manual
      test needed
- [ ] No claim of verification that was not performed. This is the one gate
      with no acceptable failure mode

## Gate 4 — independent review

- [ ] A **different agent** than the builder reviewed the diff
- [ ] For RED work, the reviewer explicitly confirms the security or money
      property the ticket claims — restating the claim is not review
- [ ] Defects returned to the same ticket, not spawned as new ones
- [ ] Reviewer's name and verdict recorded in the ticket

## Gate 5 — no collateral damage

- [ ] `git status` clean of unintended files; nothing uncommitted destroyed
- [ ] No new dependency without both `requirements.txt` files updated and the
      ticket flagging it
- [ ] No new SQLModel class without confirming RLS and grants on the table it
      silently creates (`AGENTS.md` §3.3)
- [ ] No `.env`, key, token or customer data in the diff
- [ ] Public API signatures unchanged, or the change is named in the ticket

## Gate 6 — documentation reflects reality

- [ ] `docs/CURRENT_STATE.md` updated if the status of any module changed
- [ ] A decision with lasting consequence is written to `docs/decisions/`
- [ ] Non-obvious *why* is a comment in the code, not only in the ticket. The
      next agent reads the file, not the history
- [ ] Nothing in the repository now contradicts the change

---

## Additional gates for RED work

Money, security, RLS, grants, auth, Stripe, plan enforcement, migrations,
deletions, production actions.

- [ ] Tests written **first** and reviewed by Mike before implementation
- [ ] Reviewed by an agent that did not build it
- [ ] For a migration: rehearsed on staging (`gzcrsrqmygublveuzqyg`), with a
      **before-snapshot captured** and the **rollback proven** by running it
      and diffing against that snapshot
- [ ] For a migration: staging verified structurally equal to prod first —
      staging has silently lacked every constraint before
      (`audits/FINDINGS.md`)
- [ ] A step-by-step prod runbook exists, in the style of
      `audits/033-PROD-RUNBOOK.md`, with EXPECT and STOP IF at every step
- [ ] Mike ran it, and the result is recorded
- [ ] After any schema change: `scripts/dump-live-schema.sql` re-run and
      `audits/live-schema-public.txt` regenerated (033 runbook STEP 24b) —
      **parsed as CSV, never with `grep`**

## Additional gates for anything customer-facing

- [ ] Mike has clicked it in the real application
- [ ] Failure states are visible to the user where they are looking — not
      behind a modal, not only in the console
- [ ] Money renders to the penny with the correct currency for the region
- [ ] Works in dark mode. Financial tables specifically: check contrast

---

## Definition of **not** done

Stated plainly, because each has happened here:

- Code written, tests not run
- Tests pass locally, `check.sh` never run in full
- A failure reported without an attempt to fix it
- "Should work" without a verification command
- A schema change assumed live because a migration file exists
- A change verified against staging where staging differs from prod
- An endpoint claimed gated because the button is hidden
- **A status claim inherited from another document rather than checked.**
  `CLAUDE.md` recorded "PART D done" for one meaning of PART D while the
  spec's PART D — server-side enforcement — remained one endpoint out of
  seven. Both statements were written in good faith. Check the code
