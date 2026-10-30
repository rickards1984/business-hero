**P1/P2: None found** within `ddb7fdb..442451e`.

The fix closes review 5’s reproduced sequence: the retry increments the persisted attempt before contacting Stripe, so reconciliation cannot apply its older answer even after the lost-response handler releases the claim.

Rejected requests return before incrementing. The counter stays stable between attempts, and a fresh reconciliation can activate the brand.

All three regressions passed using in-memory SQLite. Removing `attempt` from the fingerprint made the race regression fail, confirming it exercises the defect. The renewal test checks the exact expiry.

`check.sh` was not run because it writes files. Nothing was modified, committed or pushed; existing `data.db` was untouched.

**Verdict: APPROVE.**