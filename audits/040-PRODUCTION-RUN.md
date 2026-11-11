# 040 — production run record

**Run by Mike, 11 Nov 2026, directly on production (`oxblcmwhuwtobdhsfgyi`).**

**Staging was skipped,** by mistake (Mike: "I ran it straight in production by mistake and didn't run it in staging"). He reports that every STEP 0–2 output matched its EXPECT, and that nothing went wrong.

**Assessment:** the risk was low. 040 adds one index (`idx_aria_actions_outreach_enrolment`) and changes no data, table, policy or permission. The STEP 2 verification checks its exact definition and validity. No follow-up is needed.

**Lesson:** 041, which creates tables, is rehearsed on staging first, as its runbook says.

**STEP 3** (`OUTREACH_PILOT_ENROLMENTS=0` in Railway) lifts the limit of 5 contacts per campaign. Its status is recorded when Mike confirms it.
