# Harness setup — ~90 minutes, then it pays for itself all week

Run from `~/Documents/business-hero-2`. Back up the existing CLAUDE.md first.

```bash
cd ~/Documents/business-hero-2
cp CLAUDE.md CLAUDE.md.bak-preharness-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p scripts .github/workflows
# copy check.sh, scripts/preflight.sh, CLAUDE.md, .github/workflows/ci.yml in
chmod +x check.sh scripts/preflight.sh
```

## Step 1 — Local TypeScript (the single highest-value ten minutes)

```bash
cd ~/Documents/business-hero-2/frontend/client
npm install
npx tsc --noEmit
```

Right now TS errors only surface at the Vercel build. That is a ~3 minute loop
for something that should take 8 seconds, and it means Claude Code is writing
TypeScript blind. This one command changes that.

Expect errors on the first run — the codebase has never been typechecked
locally. That backlog is itself useful information. Do not fix them all now;
just note the count.

Add to `.gitignore` if not already there: `node_modules/`

## Step 2 — Python tooling

```bash
cd ~/Documents/business-hero-2
pip3 install --user pytest ruff
pytest backend/tests -q
```

`backend/tests/test_feature_gating.py` already exists — that is where the
regression test for the plan-upgrade bypass belongs, so that bug can never
silently return.

## Step 3 — Staging database (free, and it removes the biggest fear)

Create a **new** Supabase project called `business-hero-staging` on the free
tier. Do **not** reuse the old Trackwise project — two projects already caused
one wrong-project incident; three would be worse.

Dump prod schema (no data) into it:

```bash
/opt/homebrew/opt/libpq/bin/pg_dump \
  -h aws-1-eu-west-1.pooler.supabase.com -p 5432 \
  -U postgres.oxblcmwhuwtobdhsfgyi -d postgres \
  --schema-only --schema=public -f /tmp/bh-schema.sql
```

Then apply `/tmp/bh-schema.sql` to staging via its SQL editor.

**Why this matters more than it looks:** every migration — including `030` —
gets applied to staging first and proven there. Nothing untested touches prod
again. This is what makes it safe to let an agent write SQL at all.

## Step 4 — Browser testing (do this on Day 3, not now)

```bash
cd ~/Documents/business-hero-2/frontend/client
npm install -D @playwright/test && npx playwright install chromium
```

Your "first-time-customer Chrome walkthrough" ship gate is currently manual and
takes an evening. As a Playwright script it takes 40 seconds and can run on
every push. Worth building once the UI has stopped moving.

## Step 5 — CI

Push the workflow file. GitHub Actions free tier covers this comfortably on a
private repo. Every push now gets typechecked, tested and preflighted before
Railway and Vercel deploy anything.

---

# The spec template — this is your actual leverage

You said you are the ideas person and the tester, not the coder. Correct, and
the highest-value thing you can do is write specifications, because **autonomy
scales with specification quality.** "Fix the invoice numbering" gets you
something plausible. The version below gets you something correct — and you can
write it without knowing any Python.

```markdown
## What
One sentence. The behaviour, not the implementation.

## Why it matters
The business consequence if it is wrong. This is the part only you know.

## Acceptance criteria
- [ ] Specific, checkable statements about behaviour
- [ ] Include the edge cases you have seen go wrong in real life
- [ ] Include what must NOT happen

## How I will test it
The clicks you will perform to confirm it works.

## Out of scope
What not to touch while in here.
```

## Worked example — the invoice numbering bug

```markdown
## What
Invoice numbers must be unique and sequential per business, permanently.

## Why it matters
Duplicate invoice numbers are an HMRC problem and make an accountant
distrust the whole system. A customer who spots two INV-14s will assume
their books are wrong — and they will be right.

## Acceptance criteria
- [ ] Numbers are sequential per business, starting at 1
- [ ] Deleting invoice 5 does NOT cause the next invoice to reuse 5
- [ ] Two invoices created at the same moment get different numbers
- [ ] Business A's numbering is unaffected by Business B's
- [ ] Existing invoice numbers are never rewritten by this change
- [ ] Format stays INV-{n}

## How I will test it
Create three invoices, delete the middle one, create a fourth.
Expect INV-1, INV-2, INV-4 — never a second INV-3.

## Out of scope
Invoice PDF layout. Quote numbering.
```

Note what you did there: you specified `COUNT(*)+1` is wrong without ever
mentioning `COUNT(*)`. The delete-then-create criterion catches it on its own.
That is the skill, and it is a business skill, not a coding one.

---

# Cost

Almost all of this is free — npm, pytest, ruff, Playwright, GitHub Actions free
tier, Supabase free tier for staging. The spend is ~90 minutes of setup.

The real saving is in model routing. In Claude Code, use **Sonnet** for
mechanical work (UI fixes, boilerplate, writing tests, refactors) and reserve
**Opus** for the money engine, migrations and anything in the RED tier. On the
mechanical two-thirds of the work that is a large cost reduction for no
meaningful quality loss — and with `check.sh` in place, a cheaper model that
iterates against a real test signal beats an expensive model guessing once.
