**REQUEST CHANGES** — reviewed `8459515..9e73780` under North Star P8. No files modified, committed or pushed.

**P1 findings**

1. **Stored contacts without enrolments disappear from capacity accounting.**  
   [outreach_research.py:1041](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:1041) keeps a contact even when `_take_place()` returns `None`. Reviews likewise decrement only the current attempt’s `left`; neither consumes campaign/mailbox room on the next attempt.

   Reproduced:
   - Five-capacity warming inbox, three review-only batches: **15 contacts stored, three paid searches**.
   - Pilot limit five, injected qualification refusal: **15 accepted, zero enrolled**.

   `_today_counts()` eventually enforces the brand’s 20-contact ceiling, but does not preserve the smaller inbox/pilot allowance. Failed qualification must not silently produce an accepted, unallocated contact; retained reviews need durable capacity accounting. This leaves review-1 P1s 1/4 incompletely closed.

2. **The search lease can expire while its owner is still working.**  
   [outreach_research.py:774](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:774) uses the fixed run `moment` for both expiry checks and renewal. Re-entry across attempts therefore writes the same expiry. `run_due()` also passes one timestamp through every business and audience, so a later run can create an already-expired claim.

   A second run can acquire the claim after ten minutes while the first continues verification or another paid attempt. There is no heartbeat or ownership check before storing. The promise of one paid search per business is therefore not maintained. Use a fresh lease clock and protect ownership throughout potentially long-running work.

**P2 findings**

- **Exceptions leak committed search claims.** Cleanup at [outreach_research.py:1070](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:1070) is reached only through normal control flow. Injecting a card-generation exception left the claim persisted. Planning, verification, settlement and summary exceptions can also bypass cleanup. Use exception-safe, token-checked cleanup after rolling back any failed transaction. Normal `break` paths do reach release.
- **Two previous P2s lack behavioural regression protection.** The negative campaign remainder has no regression in the requested section. Manual enrolment’s test at [test_outreach_research_capacity.py:289](/Users/michaelrickards/dev/bh2-OUT-19/backend/tests/test_outreach_research_capacity.py:289) checks source strings, not whether raised/unlimited settings actually allow enrolment or enforce the configured boundary.

**Review-1 closure**

| Previous finding | Cycle-2 assessment |
|---|---|
| P1: retries exceed pilot places | Fixed for qualified contacts; qualification/review gaps above remain |
| P1: unrelated audience supplies capacity | Closed; regression fails against base |
| P1: paused campaign’s sends disappear | Closed; regression fails against base |
| P1: shared-mailbox store/enrolment window | Closed for successfully enrolled contacts; unallocated storage remains |
| P1: stale pre-reservation check/concurrent searches | Locked check fixed; regression fails against base. Lease lifecycle remains incomplete |
| P2: reserved/unknown sends counted twice | Same-day claimed-send regression passes and fails against base; unknown state lacks explicit coverage |
| P2: negative campaign remainder | Clamped correctly by inspection; missing regression |
| P2: inconsistent manual pilot limit | Shared setting implemented; behavioural test missing |

**Other requested checks**

- `qualified()` remains enforced before enrolment. Its refusal is swallowed without undoing storage—the first P1 above.
- `pause_all` and `_still_allowed()` remain checked under the business lock before storage/enrolment. Removing `_enrol()` did not remove those guards.
- Claim/settings writes occur after acquiring the existing business lock. Token-checked release preserves another owner’s claim. I found no lock-order inversion.
- PostgreSQL query structure appears valid: the correlated `EXISTS` returns a Boolean and is tenant-scoped; both nonaggregate selected columns appear in `GROUP BY m.campaign_id, u.mailbox_id`. Python then sums campaign and mailbox totals separately. This matches PostgreSQL’s documented [EXISTS](https://www.postgresql.org/docs/current/functions-subquery.html) and [GROUP BY](https://www.postgresql.org/docs/current/sql-select.html) semantics. **This is inspection, not PostgreSQL execution evidence.**

**Verification and backlog**

- **133 tests passed**, including all **27 capacity tests**, with the filesystem-backed fixture adapted in memory to SQLite.
- **Six behavioural regressions failed against `8459515`**, demonstrating meaningful detection of the original defects.
- `check.sh` was not run because it writes artifacts; PostgreSQL tests were not executed.
- Backlog: PostgreSQL contention/lease-expiry tests, explicit unknown-send coverage, DST-transition coverage, and the documented open-card scan/index prerequisite before lifting the pilot.

**Verdict: REQUEST CHANGES.**