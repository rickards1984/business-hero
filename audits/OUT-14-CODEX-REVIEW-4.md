**P1/P2: None found.**

The fix closes review 3’s reproduced case: an included brand with an old `awaiting_payment` record displays “included in the plan” and contributes zero to “waiting for payment”.

Precedence now matches the billing service: **free → included → billing record → existing paid fallback**. No new defect found in the scoped diff.

Verification: **6 targeted tests passed**, using an in-memory SQLite fixture. Full `check.sh` and browser checks were not run. No files modified, committed or pushed; existing `data.db` untouched.

Mike’s check: open the dashboard for an included brand retaining an old payment record and confirm the label and zero payment alert.

**Verdict: APPROVE.**