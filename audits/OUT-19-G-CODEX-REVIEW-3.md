**APPROVE — OUT-19 G, review 3, commit `67c4b9a`.** Reviewed against North Star **P8: Trust over cleverness**.

**P1:** None found.  
**P2:** None found. Both review-2 defects are fixed with behavioural regressions:

- Fresh boosts now check adverse deliverability immediately, while allowing time to establish volume and genuine replies.
- Effective capacity is zero without today’s passing check; regressions cover yesterday’s and tomorrow’s checks.

The strengthened tests address the requested gaps:

| Check | Assessment |
|---|---|
| Lock ordering | Rejects review 1’s check-release-relock shape by requiring evaluation after the final lock, without rollback before saving. |
| Provider ceiling | Attempts reply approval at 25 total sends and asserts refusal with no provider send. |
| Mixed inboxes | Calls real research capacity with and without the boost, complementing the existing sending regression. |
| Bounce hold | Exercises three authenticated hard bounces through `observe_health()` and verifies reset to 20. |
| Retirement | Exercises `replace_mailbox(..., retire_old=True)` and verifies reset to 20. |

No new defect found in the changes since `62c120f`.

**Backlog, non-blocking:** PostgreSQL lock-contention coverage; rendered owner/staff and capacity-display tests; SQL-bounded historical evidence queries. The lock-order regression establishes transaction sequencing, not concurrent PostgreSQL behaviour.

**Verification:** Read-only inspection plus passing isolated, in-memory checks of the actual quality/freshness functions and changed Python syntax. Full pytest and `check.sh` were not run because their harnesses write files. Nothing modified; pre-existing untracked `data.db` left untouched.

**Mike’s behaviour check:** Settings → Sending mailboxes: confirm stale checks show zero capacity, lower owner limits remain visible, and staff have no boost action.