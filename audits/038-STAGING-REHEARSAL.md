# 038 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/038_outreach_replies.sql` (OUT-7)
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 24 Oct 2026, by Claude Code
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** `scripts/rehearse-038-staging.py` refuses any URL that isn't staging and never prints the URL. It also refuses to start if staging already holds any 038 object.

**Steps:** Section 1 (one concurrent index, autocommit), then Section 2 as one transaction. Counts checked against the runbook. Re-paste. The runbook's STEP 6 rollback (both blocks). Compare with the before-state. Re-apply and leave applied.

## Result, verbatim
```
- before: {'outreach_tables': 17, 'columns': 1105, 'policies': 94, 'out7_key': 0, 'out7_index': 0, 'freeze_fn': 0, 'knowledge_policy': 0, 'slot_policies': 0, 'rls_on': 0, 'anon_privileges': 0, 'reply_rows': 0}
- after first apply: {'outreach_tables': 19, 'columns': 1137, 'policies': 95, 'out7_key': 1, 'out7_index': 1, 'freeze_fn': 1, 'knowledge_policy': 1, 'slot_policies': 0, 'rls_on': 2, 'anon_privileges': 0, 'reply_rows': 0}
- deltas as the runbook states: +2 tables, +32 columns, +1 policy: ok
- re-paste: no change: ok
- after STEP 6 rollback: {'outreach_tables': 17, 'columns': 1105, 'policies': 94, 'out7_key': 0, 'out7_index': 0, 'freeze_fn': 0, 'knowledge_policy': 0, 'slot_policies': 0, 'rls_on': 0, 'anon_privileges': 0, 'reply_rows': 0}
- rollback returns the exact before-state: ok
- re-applied and left applied (staging parity): {'outreach_tables': 19, 'columns': 1137, 'policies': 95, 'out7_key': 1, 'out7_index': 1, 'freeze_fn': 1, 'knowledge_policy': 1, 'slot_policies': 0, 'rls_on': 2, 'anon_privileges': 0, 'reply_rows': 0}
```

**Staging's starting state matched production's recorded post-037 state** (94 policies, 1,105 columns). **No fixes were needed.**
