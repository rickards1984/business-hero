# BRIEF-1 — Codex review 3, targeted (preserved verbatim)

**Findings — not approved.**

- **P2 — Settings saves can erase delivery claims.** [whatsapp_briefings.py:270](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:270) stores claims under `whatsapp_briefings`, but [main.py:1504](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/main.py:1504) does not preserve that key during whole-document settings replacement. A save can remove the delivered flag, retry count or active claim, allowing duplicate sends. Preserve this as server-owned state.

- **P2 — An expired attempt can clear its successor’s claim.** [whatsapp_briefings.py:280](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:280) checks only the day before clearing `busy_until`. Reproduced in memory: A claims; B claims after expiry; A settles unsuccessfully; C claims while B remains in flight. Use an attempt token and require ownership when settling.

- **P2 — A briefing exception skips that business’s scheduled reminder.** [briefing_scheduler.py:392](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/briefing_scheduler.py:392) lets the exception reach the per-business handler, bypassing the reminder below. Because reminders require an exact minute match, the next tick cannot recover it. Catch briefing failures separately.

The message-log dependency is resolved. Claim acquisition is atomic, and I found no new advisory/row-lock inversion. Dead-process claims expire as intended, subject to the ownership issue above.

Read-only review; no files changed. Full tests and `check.sh` were not run.