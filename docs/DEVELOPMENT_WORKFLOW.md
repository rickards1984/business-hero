# Development workflow

How work moves from an approved ticket to merged code. Every agent follows
this. The rules it depends on — task packet, autonomy tiers, escalation —
are in `AGENTS.md`; the merge gate is `docs/DEFINITION_OF_DONE.md`.

**Decided 2026-09-08 by Mike.** This supersedes the stub.

---

## 1 · The shape of it

```
ticket approved
  → builder creates a worktree for the ticket branch
  → builder implements
  → ./check.sh full green (the pre-push hook enforces this)
  → builder pushes ITS OWN FEATURE BRANCH — never main
  → builder opens a PR carrying the evidence
  → the other agent reviews on the PR
  → fixes go to the SAME branch, not a new one
  → Mike merges
  → prod SQL, if any, is run by Mike from a runbook
```

Two rules that are not negotiable and are stated here so no one has to infer
them:

- **A builder never merges its own PR.** Merge is Mike's, and merge is the
  deploy gate — `main` auto-deploys to Railway and Vercel.
- **Production SQL stays human.** An agent writes the runbook and rehearses
  it on staging. Mike runs it against prod. No agent executes prod SQL.

---

## 2 · Worktrees

One worktree per ticket, in this clone. Worktrees share the main `.git`, so
one hook configuration and one set of refs covers all of them.

```bash
# from the repo root
git worktree add ../bh-BH-004 -b ticket/BH-004-single-entitlement-gate
cd ../bh-BH-004
```

| | Convention |
|---|---|
| Worktree directory | `../bh-<TICKET-ID>` — a sibling of the repo, never nested inside it |
| Branch name | `ticket/BH-000-short-kebab-name` |
| Foundation work | `foundation/<name>` |
| One worktree | one ticket. Never two tickets in one worktree |

**The sibling rule matters.** A worktree created inside the repo would land
inside the tree `check.sh`, `ruff` and the schema-conformance scanner walk —
so a second copy of the backend would be linted and parsed as if it were
live code.

When the PR is merged:

```bash
git worktree remove ../bh-BH-004
git branch -d ticket/BH-004-single-entitlement-gate
```

Stale worktrees are not free — `git worktree list` should stay short enough
to read. Prune anything merged.

### Never in a worktree

- `main`. It is checked out in the primary clone and git will refuse anyway.
- Two agents on the same branch. `AGENTS.md` §7: no two agents edit the same
  feature on the same branch simultaneously.

---

## 3 · Branch and push rules

- **Builders push their own feature branch only.** No agent pushes `main`.
- `git push -u origin ticket/BH-000-...` on first push.
- Rebase rather than merge `main` into a ticket branch, and **re-run
  `./check.sh full` after any rebase** — a check output that predates the
  rebase proves nothing about what you are asking someone to merge.
- If two tickets contend for `backend/main.py` or
  `frontend/client/src/pages/QuotesPage.tsx`, sequence them. Whoever merges
  second rebases.
- One migration in flight at a time, repository-wide.

---

## 4 · The pre-push hook

`./check.sh full` runs automatically before every push and **refuses the
push if it is red**.

The working agreement already says "iterate until green". The hook makes
that mechanical rather than voluntary — a red branch never reaches a
reviewer or Mike's merge button in the first place.

### Install — once per clone

```bash
git config core.hooksPath .githooks
```

The hook is `.githooks/pre-push`, tracked in the repository, so it is
reviewable like any other code. `core.hooksPath` is set in `.git/config`,
which worktrees share — **set it once and every worktree is covered.**

Verify it is live:

```bash
git config core.hooksPath      # → .githooks
```

If that prints nothing, the hook is not running and your pushes are
unguarded. Set it before doing anything else.

### What it does

- Runs `./check.sh full` from the repository root
- Exit 0 → push proceeds
- Exit non-zero → push refused, with the failing step named
- Branch deletions skip the check — there is no tree to verify
- A missing or non-executable `check.sh` is itself a refusal, because a gate
  that cannot run must not be assumed green

### `--no-verify` is NOT PERMITTED

Not for a "docs-only" change, not for a "trivial" fix, not because the run
is inconvenient. `check.sh full` takes seconds.

The reason is not ceremony. **A bypassed gate is indistinguishable from a
forgotten one to the next person who reads the branch.** A reviewer seeing a
green PR assumes the tree was verified; there is nothing in the history that
says otherwise. That assumption is exactly what the hook exists to make
safe, and one silent bypass makes every subsequent green PR less
trustworthy.

**If the gate is wrong, that is a ticket, not a bypass.** Fix `check.sh`, or
fix the test, in the open where a reviewer can see it.

A PR whose branch was pushed with `--no-verify` should be closed and
re-pushed properly, not reviewed.

---

## 5 · The pull request

Every ticket ends in a PR. The PR is where the evidence lives — not the
ticket file, not a chat message. A reviewer must be able to judge the work
from the PR alone.

### Template

```markdown
## BH-000 — <ticket title>

**Outcome**  One sentence: the user/business result.
**Risk tier**  GREEN | AMBER | RED  (per AGENTS.md §2)
**Builder**  Claude Code | Codex
**Reviewer**  the other one

### What changed
Short prose. Why, not just what. Link the audit doc or file:line that
proved the problem existed.

### check.sh full
```
<paste the actual output — the counts, not "tests pass">
```
Run at commit <sha>, after the final change and after any rebase.

### What was tested
- The test that fails without this change: <name>, in <file>
- Edge cases covered:
- Failure/boundary cases covered:

### What could NOT be verified
Be specific. Visual layout, third-party behaviour, production data,
anything check.sh cannot reach. If this section is empty, say
"nothing — check.sh covers this change" rather than deleting it.

### What Mike should click
Required for any UI-touching change. See §7.

### Non-goals
What this deliberately did not touch.
```

**The two sections people will be tempted to skip are the two that matter.**
"What could NOT be verified" is where honesty lives — `docs/DEFINITION_OF_DONE.md`
Gate 3 is the one gate with no acceptable failure mode. And "What Mike
should click" is the only browser testing this project currently has.

---

## 6 · Review — who reviews whom

The reviewer is never the builder. Assignment follows the lane, so it does
not have to be negotiated per ticket.

| Lane | Builder | Reviewer |
|---|---|---|
| **A — enforcement and billing** (entitlement, metering, Stripe, migrations) | Claude Code | Codex |
| **B — money path** (invoice PDF, manual invoices) | Codex | Claude Code |
| **C — evidence** (tenant-isolation test) | Codex | Claude Code |
| Foundation and documentation | either | the other |
| UX critique and visual review | Fable — advisory, not a merge gate | — |

Where the table is silent: whichever agent did not write the code reviews
it. If that is ambiguous, ask Mike rather than self-assigning.

### What a review must do

- Verify the claim, do not restate it. For RED work the reviewer confirms
  the security or money property **independently** — re-reading the
  builder's sentence is not review.
- Check the check: is the pasted output from the final commit?
- Read "What could NOT be verified" adversarially. Is anything missing from
  it that should be there?
- Confirm every gate in `docs/DEFINITION_OF_DONE.md` that applies.
- Approve, or request changes with specifics. "Looks good" is not a review.

### Defects

Fixes go to **the same branch and the same ticket**. Do not open a follow-up
ticket for a defect found in review — that converts a blocked merge into a
merged defect plus a backlog item.

---

## 7 · Until frontend tests exist, Mike is the browser test

There are no frontend tests and no end-to-end tests
(`docs/CURRENT_STATE.md` §1). Playwright smoke tests for the golden journeys
are `docs/RC1_SCOPE.md` P1-5.

Until they exist:

> **Every UI-touching PR must state what Mike needs to click.**

Not "test the quotes page". The specific path, the expected result, and what
would indicate failure:

```
1. Quotes → New Quote → AI mode → paste the fire-doors job → Generate
   Expect: line items grouped by trade within ~30s, green snackbar
   Failure looks like: silent reset with no message
2. Save → open the quote → Preview PDF
   Expect: PDF opens in a new tab, itemised, VAT line present
```

This is a real gate, not a formality. It is the only thing standing between
a UI regression and a customer, and it is why `AGENTS.md` §1 puts "what Mike
should click" in the report rather than asking him to review code.

When a journey gains Playwright cover, the corresponding manual steps can be
dropped from this requirement — and the PR that adds the test should say
which steps it retires.

---

## 8 · Production SQL

Unchanged, and it stays this way:

1. An agent writes the migration and the runbook.
2. Staging is verified structurally equal to prod **first** — it has
   silently lacked every constraint before (`audits/FINDINGS.md`).
3. Rehearse on staging with a before-snapshot; prove the rollback by running
   it and diffing against that snapshot.
4. The runbook carries EXPECT and STOP IF at every step. Worked example:
   `audits/033-PROD-RUNBOOK.md`.
5. **Mike runs it against prod.** No agent executes prod SQL.
6. Regenerate the schema dump afterwards (STEP 24b) — parsed as CSV, never
   with `grep`.

---

## 9 · Quick reference

```bash
git config core.hooksPath .githooks              # once per clone
git worktree add ../bh-BH-004 -b ticket/BH-004-single-entitlement-gate
cd ../bh-BH-004
./check.sh                                       # during work
./check.sh full                                  # before push (hook runs it too)
git push -u origin ticket/BH-004-single-entitlement-gate
gh pr create --fill                              # then paste the evidence sections
git worktree remove ../bh-BH-004                 # after merge
```
