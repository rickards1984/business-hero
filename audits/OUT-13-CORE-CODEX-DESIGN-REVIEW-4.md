# OUT-13 core — Codex DESIGN review 4 (verbatim, targeted): APPROVE DESIGN

No blocking findings. Revision 3.1 resolves the design issues:

| Item | Assessment |
|---|---|
| **21 — Starvation** | Resolved: exception retries cannot consume the separate new-candidate budget. |
| **22 — Unstarted replies** | Resolved: `reply_outreach` jobs are excluded from T3, avoiding the invalid reply-slot settlement. |
| **T1 qualification** | Resolved: the minimum deadline and NULL fallback cover schema-permitted timestamps. |
| **T2 qualification** | Resolved: uncertain claims remain protected and owner-visible; terminal settlement is no longer universally promised. |
| **T7 qualification** | Resolved: external dispatch-job references explicitly block deletion. |
| **T3 qualification** | Resolved: fencing and settlement commit atomically. |

U1’s first-pass test assertion requires the blocked prefix to **already have exception rows**. An initially unprocessed prefix takes multiple passes to classify; cooldown expiry must not interrupt that progress.

I found no additional U1–U3 path that would erase an emailed person, indefinitely retain a never-emailed person without an owner-visible exception, lose or duplicate a send, or regress existing behaviour.

Read-only review against the ticket, send code and migrations. No files changed; tests and live-database checks were not run.

VERDICT: APPROVE DESIGN