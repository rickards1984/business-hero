**REQUEST CHANGES — review 2, commit `62c120f`, North Star P8.**

**P1:** None found. I found no remaining bypass of the 50-cold-email ceiling, owner limits below 20, recorded provider limits, tenant scoping, or paused/failing inbox checks.

**P2 — two remaining defects**

1. **The fresh-level grace period also suspends deliverability checks.**  
   [outreach_boost.py:329](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:329) returns before `_misses()` for fourteen days after **any boost**, including when bounce or unsubscribe rates deteriorate.

   I reproduced this using the actual functions: **150 cold emails, two unsubscribes, boost granted yesterday → remains at 30**. Identical evidence after fifteen days drops it to 20. No complaint, pause or independent failure is needed.

   The ticket’s review-1 addendum describes this grace period, but its primary rule still says a failing rolling fortnight drops a step. Giving a new level time to establish volume is understandable; exempting worsening deliverability is a broader change. Preserve immediate reset for complaints/pauses and check adverse rates during the fresh-level period. Add regressions distinguishing insufficient volume from worsening rates.

2. **“Effective” capacity still ignores health-check freshness.**  
   [outreach_boost.py:254](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:254) obtains capacity from `mailbox_daily_cap()`, which deliberately leaves freshness to its caller. `_evaluate()` adds an unmet condition for yesterday’s check but leaves `effective` positive.

   Consequently, [BoostInbox](/Users/michaelrickards/dev/bh2-OUT-19G/frontend/client/src/components/OutreachSetupWizard.tsx:956) says the inbox “can send up to …” while the send path blocks it. I reproduced positive effective capacity alongside “Today’s inbox check must pass.” Return zero or display a separate blocked status, and cover stale/future checks.

**Review-1 findings and regression coverage**

| Review-1 finding | Review-2 assessment |
|---|---|
| P1-1: pause/complaint reset | Fixed at every existing mailbox pause writer I found: complaint/bounce hold, failed health check and retirement. Real complaint and failed-check regressions exist; boosted bounce-hold and retirement regressions are missing. |
| P1-2: lost recovery period | Fixed. `reset_at` and `dropped_at` survive return to 20; behavioural regressions cover both. |
| P1-3: qualification outside final lock | Fixed in code: `_evaluate()` runs after `_authority()` without releasing its lock. **The new test does not reproduce the original race:** it pauses before the first qualification check, so the review-1 implementation would also reject it. |
| P1-4: missing volume/genuine-reply measures | Both now enforced and behaviourally tested for established levels. Fresh-level exception remains as described above. |
| P1-5: provider limit lost/extra reply allowance | Fixed in health persistence, send reservation and headroom. Persistence is behaviourally tested; the reply test checks headroom, **not an attempted send at the provider ceiling**. |
| P2-1: mixed-inbox brand policy | Shared `brand_level()` fixes the disagreement. The regression exercises sending but never calls research capacity, so agreement is not behaviourally established end to end. |
| P2-2: inconsistent evidence boundaries | Fixed with shared UK-day boundaries; behavioural boundary regression exists. |
| P2-3: unsubscribe attribution | Fixed with accepted-only messages; failed-send exclusion regression exists alongside accepted-message coverage. |
| P2-4: displayed capacity/owner action | Owner-only action is implemented. Lower mailbox-limit display is tested at the API calculation level; freshness remains defective and rendered owner/staff behaviour is untested. |

The new complaint and health-hook tests are meaningful improvements over source inspection. Failed checks now count **failed days**, addressing that previous backlog item.

**Backlog / test strengthening**

- Replace the ineffective race regression with one targeting the original qualification-to-grant gap; add PostgreSQL lock-contention coverage.
- Exercise actual cold/reply sends at the recorded provider ceiling, and research capacity for mixed-level inboxes.
- Add boosted retirement/bounce-hold and rendered owner/staff regressions.
- Bound historical evidence queries in SQL. The research source-string test still provides little behavioural assurance.

I found no missed mailbox pause writer or path retaining a boost through those pauses/complaints. Owner and provider bounds are correctly applied in sending; replies retain their separate ceiling, additionally constrained by the recorded provider limit.

**Verification:** read-only inspection of both diffs and isolated in-memory execution of actual functions with controlled dependencies. I did not run `check.sh` or pytest because they write bytecode/database files. No files were modified; the pre-existing untracked `data.db` remains untouched.

After correction, Mike’s behaviour check is Settings → Sending mailboxes: stale checks show sending blocked, lower limits display correctly, and staff see no boost action. **Verdict: REQUEST CHANGES.**