# AGENTS.md — universal rules for every coding agent

Applies to Claude Code, Codex, Fable and any future agent. Claude-specific
notes live in `CLAUDE.md`, which **references this file and does not repeat
it**. Where the two ever disagree, this file wins.

Business Hero is a live SaaS with real customers imminent. Read this before
acting.

---

## 1 · The verification loop

**Do not ask Mike to check your code.** He is the product owner and tester,
not a code reviewer. Prove your own work.

For every change:

1. Make the change.
2. Run `./check.sh` (or `./check.sh full` before any push).
3. If it fails, fix and re-run. Iterate until green. Never report a failure
   you have not attempted to fix.
4. Report: what changed, the `check.sh` result, and **what Mike should click
   to confirm the behaviour is right**.

That last line is his job. He tests behaviour against real-world business
knowledge. You test correctness. Do not swap the two around.

If `check.sh` cannot verify a change (visual layout, third-party behaviour),
**say so explicitly** and describe the manual test. Never imply verification
you did not perform.

### The one verification command

```bash
./check.sh          # fast: tsc, ruff, py_compile, pytest
./check.sh full     # adds scripts/preflight.sh deploy traps — before any push
```

Green means: frontend typechecks, backend compiles, ruff is clean, all backend
tests pass, and the five deploy traps pass. It does **not** mean the feature
works — there are no frontend tests and no end-to-end tests. See
`docs/TESTING.md`.

---

## 2 · Autonomy tiers

### GREEN — proceed without asking, report when green
UI fixes, styling, empty states, loading skeletons, copy, component
refactors, adding tests, logging, non-behavioural cleanup.

A mistake here is visible immediately and costs nothing. Just go.

### AMBER — plan first, one approval, then run to completion
New endpoints, PDF generation, feature work, integration wiring.

Propose the plan with acceptance criteria. Once approved, execute the whole
plan without stopping between steps. Report at the end with results.

**Migrations are not in this tier.** This list read "schema-additive
migrations" until 8 Sep 2026. That was wrong, and it never described
practice: every migration this project has run went through a RED prod
runbook (`audits/*-PROD-RUNBOOK.md`). All prod SQL is RED, additive or not —
and "additive" is precisely the dangerous case, because `create_all()` gives
a new table **RLS OFF and default grants** (§3.3), so an additive change is
the one that silently exposes data.

### RED — never autonomous, always explicit approval per action
- Money: quoting maths, invoice numbering, VAT, Stripe, plan enforcement
- Security: RLS, grants, policies, auth, `businesses` / `business_members`
- **Pushing or merging `main`**, or any command that deploys
- Any SQL against production — **including every schema migration**
- Deleting data or dropping anything

**Feature branches are the builder's; `main` is Mike's.** A builder pushes
its own ticket branch as a matter of course — that is not RED, it is how work
reaches review, and the pre-push hook gates it by refusing a red tree. What
is RED is `main`: no agent pushes it and no agent merges into it. Mike
merges, and **the merge is the deploy**. Mechanics in
`docs/DEVELOPMENT_WORKFLOW.md` §3.

**Tests first.** Write the failing test that encodes correct behaviour. Mike
reviews *the test*, not the implementation. Then code until green.

A rounding error on VAT is invisible until it is on eighty invoices. That is
why this tier exists.

---

## 3 · Do not regress — each was a real, costly incident

1. **Railway installs from ROOT `requirements.txt`**, not `backend/`. Adding a
   dep to only the backend file crashes the deploy. Bit us twice (`slowapi`,
   `reportlab`). `scripts/preflight.sh` TRAP 1 checks this.
2. **Repo must stay outside Dropbox/CloudStorage *and* outside the
   TCC-protected user folders** (`.git/index.lock`; macOS privacy prompts).
   It lives at `~/dev/business-hero-2`. Do not move it.

   Moved from `~/Documents/business-hero-2` on 8 Sep 2026. macOS TCC treats
   `~/Documents` as a protected location, so every agent process needed its
   own Full Disk Access grant — and the grant was revoked five times in three
   weeks, each time mid-task, each time presenting as a filesystem error
   rather than a permissions one. `~/dev` is not TCC-protected, so no grant
   is needed and none can be revoked. The Dropbox constraint is unchanged and
   still binds: `~/dev` satisfies both.
3. **`create_all()` runs at every boot.** A new SQLModel class silently
   creates a live table with **RLS OFF and default grants**. Any new model is
   a possibly-exposed table. Confirm RLS and policies before deploying.
   `create_all()` creates tables but **never columns** — a new field on an
   existing model does nothing to the live database.
4. **Migration files are NOT evidence of live state.** They have drifted from
   prod before. Verify against `pg_class` / `pg_policies` /
   `information_schema` on the live DB.
5. **Two Supabase projects exist.** Business Hero is `oxblcmwhuwtobdhsfgyi`;
   staging is `gzcrsrqmygublveuzqyg`. Confirm the project selector before any
   SQL.
6. **GPT-5 models reject `temperature` / `max_tokens`.** Use
   `max_completion_tokens` and omit temperature.
7. **Railway replica count must be 1.** Rate limiting and the Xero refresh
   lock are in-process and break silently at 2+.
8. **`anon` / `authenticated` hold broad table grants**, so RLS is the only
   gate on the client path. An RLS-off table is publicly reachable.
9. **Staging lacks prod's constraints.** Every PK/FK/UNIQUE/CHECK was missing
   from staging until repaired for 031. A rehearsal that depends on a
   constraint proves nothing until staging is verified structurally equal.
   See `audits/FINDINGS.md`.
10. **Supabase CSV export quotes any field containing a comma.** Building a
    schema dump with `grep` silently drops every `numeric(p,s)` row. Parse it
    as CSV. See `033-PROD-RUNBOOK.md` STEP 24b.

---

## 4 · Architecture facts

- **Frontend:** React/TS on Vercel — `frontend/client/src/` (124 files,
  ~33.8k lines)
- **Backend:** FastAPI on Railway — `backend/` (~41.3k lines, ~209 routes)
- **DB:** Supabase Postgres, project `oxblcmwhuwtobdhsfgyi`
- **Deploy:** merge to `main` → Railway + Vercel auto-deploy. **Mike merges;
  the merge is the deploy.** Builders push their own feature branches only.
- **Two DB paths, opposite RLS behaviour.** The backend connects as an
  elevated role and **bypasses RLS** — tenant isolation is application-layer
  `WHERE business_id = …`. The frontend uses supabase-js with the public anon
  key and **is subject to RLS**. Never reason about one as if it were the
  other.
- **Admin and customer are the same Postgres role** (`authenticated`). Grants
  are evaluated before RLS, so a column grant given to admin is given to
  customers too. Admin-only writes belong on the backend.
- **Two migration directories exist** — `backend/migrations/` (16 files) and
  `supabase/migrations/` (21 files) — with no single ordering between them.
  Treat neither as authoritative; see rule 3.4.

---

## 5 · Operating principles

- Inspect the real repository before making architectural claims.
- Check `git status` before changing anything. **Never overwrite or discard
  uncommitted work.**
- Do not perform a broad rewrite because another structure looks cleaner.
- Prefer incremental, tested changes.
- **No two agents edit the same feature on the same branch simultaneously.**
- Every meaningful task gets a ticket ID, an isolated branch/worktree,
  acceptance criteria and verification commands.
- **The builder must not be the sole approver** of security-sensitive or
  cross-cutting work.
- Every reproducible bug leaves behind a regression test.
- **The test harness and repository evidence outrank any assumption made in
  chat.** Do not rely on a conversation as durable memory — write decisions
  into the repository.
- Bundle non-urgent questions rather than interrupting repeatedly.
- Do not add features until RC1 scope is agreed (`docs/RC1_SCOPE.md`).

### Ask Mike only about
Genuine product choices, missing authority or credentials, production
actions, or material budget/scope changes. Not about which file to edit.

### Never without explicit permission
Deploy to production, modify production data, rotate secrets, trigger real
emails/SMS/calls, perform irreversible database operations, or incur
third-party charges.

---

## 6 · The task packet

One format, used by every agent. A ticket that cannot fill in
**Current evidence** is not ready to start.

```markdown
## TICKET  BH-000
**Outcome**            The user/business result, in one sentence.
**Current evidence**   file:line, test name, or audit doc proving the
                       problem exists. No evidence = not ready.
**Scope**              Exactly what changes.
**Non-goals**          What must not be touched while in here.
**Dependencies**       Ticket IDs that must land first.
**Affected systems**   Backend / frontend / DB / third party.
**Security & data risk** RED/AMBER/GREEN per §2, and why.
**Acceptance criteria** Checkable behavioural statements, including the
                       edge cases and what must NOT happen.
**Required tests**     The tests that must exist and pass.
**Verification**       Exact commands. Normally `./check.sh full`.
**Likely files**       Where known. A hint, not a constraint.
**Builder**            Claude Code | Codex
**Reviewer**           The other one. Never the builder.
**Branch**             ticket/BH-000-short-name
**Budget band**        S (<2h) | M (half day) | L (1-2 days)
**Max repair cycles**  Default 3, then escalate.
**Completion evidence** Filled in by the builder: command output.
**Status**             proposed | approved | in progress | in review |
                       merged | blocked
```

---

## 7 · Multi-agent workflow

```
ticket approved
  → builder implements on its own branch/worktree
  → builder runs ./check.sh full and records the output in the ticket
  → a DIFFERENT agent reviews the diff
  → defects return to the same ticket (no new ticket)
  → CI runs on the PR
  → Mike merges, only when docs/DEFINITION_OF_DONE.md passes
  → post-merge smoke check
```

**Claude and Codex must never independently rewrite the same feature.** The
second agent is a reviewer, an adversarial tester, or the owner of a separate
bounded ticket.

### Rules for contested resources

- **Shared files.** `backend/main.py` (5,295 lines) and
  `frontend/client/src/pages/QuotesPage.tsx` are the hot spots. Only one
  in-flight ticket may modify either. If two need it, sequence them.
- **Schema migrations.** One migration in flight at a time, full stop. It is
  RED, it needs a staging rehearsal with a proven rollback, and two
  concurrent migrations cannot both be rehearsed against the same staging DB.
- **Dependency changes.** Any new package goes in **root
  `requirements.txt`** and `backend/requirements.txt`. Flag it in the ticket
  — it changes the deploy.
- **Conflicts.** The ticket that lands second rebases and re-runs
  `./check.sh full` — the builder does that on its own branch, before Mike
  merges. Never merge a branch whose check output predates the rebase.

---

## 8 · Escalation

Stop and escalate — do not keep burning tokens — when:

- acceptance criteria conflict with each other or with the code;
- required authority or credentials are missing;
- production data or actions would be affected;
- an architectural decision has material consequences;
- **the same verification failure survives three genuine repair attempts**;
- scope expands materially beyond the ticket;
- the task looks likely to exceed its budget band.

Escalating early is correct behaviour, not failure. Report what was tried,
what the failure was, and what you would need to proceed.

---

## 9 · Claims discipline

Any commercial claim in product copy, marketing or outreach must be
defensible if challenged. Keep "won" and "pipeline" clearly distinguished.
Anonymise third parties unless permission is on file.

Do not describe the platform as secure because no vulnerability has been
found. Describe what has been verified, and when.

---

## 10 · Where to look

| Question | File |
|---|---|
| What is the real state of the system? | `docs/CURRENT_STATE.md` |
| What is in RC1? | `docs/RC1_SCOPE.md` |
| When is a ticket done? | `docs/DEFINITION_OF_DONE.md` |
| Why is the money engine like that? | `audits/MONEY-ENGINE-BATCH1-SPEC-v2.md` |
| Why is entitlement like that? | `audits/ENTITLEMENT-SPEC.md` |
| What did the migrations do? | `audits/*-PROD-RUNBOOK.md` |
| What is known-broken? | `audits/FINDINGS.md` |
| What does it cost to run? | `audits/PRICING-MODEL.md` |
| What is the live schema? | `audits/live-schema-public.txt` |
