# Operations and release — STUB

**Status: stub.** Deployment facts are in `AGENTS.md` §4 and
`docs/CURRENT_STATE.md` §2.

## Release path

Push to `main` → Railway (backend) and Vercel (frontend) auto-deploy. There
is no staged rollout; a Vercel deploy is atomic per release. **Mike pushes.**

Before any push: `./check.sh full`. The five deploy traps in
`scripts/preflight.sh` each encode a real outage — the root
`requirements.txt` trap alone has caught two.

## Migrations

The pattern is proven and should not be varied: capture a before-snapshot →
rehearse on staging → prove the rollback by running it and diffing → write a
step-by-step runbook with EXPECT and STOP IF at every step → Mike runs it
against prod → regenerate the schema dump (STEP 24b).

Worked examples: `audits/030a-PROD-RUNBOOK.md`, `031-PROD-RUNBOOK.md`,
`033-PROD-RUNBOOK.md` (the most developed, 27 steps).

**Verify staging is structurally equal to prod first.** Staging silently
lacked every PK/FK/UNIQUE/CHECK until it was repaired for 031, which
invalidated rehearsals that depended on a constraint.

## Gaps

- **No application rollback procedure.** Migration rollbacks are proven;
  reverting a bad deploy is not documented
- **No backup or restore test.** Never exercised
- **No monitoring or error reporting** beyond Railway logs. No alerting — a
  Stripe webhook outage ran undetected for two months
- **No staging deployment of the application** — staging is a database only
- Railway replica count must stay 1, and nothing enforces it
