**REQUEST CHANGES — five P1 findings.** Reviewed `8459515` against `3c9c886`, under North Star P8. No files modified, committed or pushed.

**P1 — must fix before merge**

1. **Retries exceed the pilot’s available places.** [outreach_research.py:718](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:718) subtracts active enrolments, but enrolment happens only after all search attempts. Previously stored, unenrolled contacts don’t consume pilot places. Reproduced with the default limit and three batches: **15 accepted, only 5 enrolled**. Reserve pilot places for stored contacts, or enrol atomically with storing.

2. **Capacity from unrelated audiences permits unusable research.** [outreach_research.py:699](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:699) pools every ready campaign belonging to the brand. Audience matching applies only to the pilot-place calculation—and disappears entirely when the limit is `0`. Reproduced: the brand has a ready campaign for another audience; research **accepts 20 and enrols none**. Calculate usable capacity for matching campaigns while subtracting competing usage from all campaigns. Enrolment allocation must also respect those campaigns’ individual capacity.

3. **Pausing/completing a campaign makes its existing sends disappear from capacity.** [outreach_research.py:698](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:698) retains usage only for currently ready/running campaigns. The send path still counts historical usage against the brand and mailbox. Reproduced: five committed sends on a subsequently paused campaign, plus a new ready campaign, produce **room 20 instead of 15**. Count consumed capacity independently of current campaign status.

4. **Shared mailboxes can exceed capacity between storing and enrolment.** [outreach_research.py:709](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:709) subtracts unenrolled contacts only for the current brand. Store commits before enrolment, exposing a window where another brand sharing the mailbox sees those places as free. Holding the first run at that boundary reproduced **40 stored contacts for one 20-capacity mailbox**. The business lock serializes transactions but cannot correct missing accounting. Stored contacts must consume shared-mailbox capacity before that commit.

5. **The paid-search capacity check is stale before reservation.** [outreach_research.py:843](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:843) checks room outside the business lock, then rolls back. The locked spend reservation does not recheck it. Injecting another run’s queue before lock acquisition reproduced **one paid search, 10p spent, zero accepted**, despite room already being zero. Recheck under the reservation lock; concurrent searches also need capacity claims or equivalent serialization so they cannot both purchase research for the same places.

**P2**

- **Reserved/unknown sends can count twice:** once through usage events and again through the enrolment’s unchanged `next_step`/`next_due_at` ([lines 688–700](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:688)). This understates room. Released events are correctly excluded; accepted sends normally advance the enrolment.
- **Negative campaign remainder reduces another campaign’s available capacity.** Line 707 sums unclamped remainders. A campaign with cap 5 and 10 queued contacts subtracts five places from another campaign’s usable allowance.
- **The pilot setting is inconsistent across enrolment paths.** Automatic enrolment reads the setting; [manual enrolment still hard-codes five](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_manage.py:198). Raising or lifting the setting does not consistently lift the application’s pilot restriction.

**Checks and test quality**

- The new capacity suite **passes all 19 tests**, using its fixture adapted in memory to SQLite because the workspace is read-only.
- Four selected behavioural tests **fail against the base research implementation**: warming inbox, full inbox, no ready campaign, and pilot capacity. They are meaningful regression tests.
- They miss the failures above. In particular, the pilot test supplies only one populated search batch, and the shared-mailbox test waits until the first run has enrolled.
- Lifting the pilot in unrelated fixtures is reasonable for cost/routing tests, but reduces default-configuration coverage. The explicit pilot tests do not compensate for missing retries and concurrency cases.
- The warm-up test’s source-string assertion does not prove arithmetic parity. By inspection, the helper matches the existing arithmetic for sendable states. Its negative-cap clamp differs, but such a cap already prevented sending. **I found no previously allowed send refused solely by the new equality assertion.** Health freshness remains a separate send-path check.
- Pilot parsing correctly defaults missing, blank, invalid and negative values to five; zero lifts it. **Lifting it is unsafe with the audience-capacity bug above.**
- Store rechecks remain under the existing business lock; I found no lock-order change. That protects ordinary same-brand aggregate capacity, but not the missing pilot/shared-mailbox accounting.

**PostgreSQL and backlog**

The new UUID comparisons/string keys, date comparison and aware `timestamptz` boundary appear compatible with the schema. London midnight and the following local midnight correctly accommodate DST; due-time comparisons use aware datetimes. These are inspection findings, **not PostgreSQL execution evidence**.

Add PostgreSQL contention and UK-midnight/DST regressions covering these fixes. Also complete the documented `prepare()` open-card scan/index prerequisite before raising the pilot limit.

I did not run `check.sh` because it writes compilation artifacts, or execute PostgreSQL tests. The review remained read-only.

**Verdict: REQUEST CHANGES.**