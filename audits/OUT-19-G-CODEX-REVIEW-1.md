**REQUEST CHANGES — OUT-19 G, review 1, commit `83356ca`.** Reviewed against section G and North Star **P8: Trust over cleverness**.

**P1 — must fix**

1. **Complaints and pauses can leave the stored boost intact indefinitely.**  
   Boost review is invoked only by `_apply_health`. The complaint handler pauses the inbox without resetting its boost, and the daily scheduler excludes disabled inboxes unless their pause is DNS-related. Sending is blocked while paused, but the promised immediate reset does not occur.  
   See [health hook](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_setup.py:710) and [complaint handler](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_replies.py:489). Reset the boost in the transaction that applies each pause, including complaints.

2. **Returning to 20 forgets the recovery period.**  
   `review()` deletes the boost entry on a complaint/pause and on a 30→20 drop. Eligibility then uses the original stage-20 review date. Consequently:
   - lifting an ordinary pause can immediately allow another boost using pre-pause evidence;
   - a 30→20 drop loses its mandatory 14-day hold.

   Preserve the reset/drop timestamps and enforce the appropriate recovery window. [Reset logic](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:256). An isolated execution of the actual functions confirmed immediate eligibility after a pause reset and release.

3. **Boost qualification is not rechecked under the final lock.**  
   `eligibility()` rolls back, releasing the lock. `boost()` reacquires it but checks only whether the level changed. A pause, failed check or new complaint can land in between without changing a base level of 20; the request still grants 30.  
   [Boost transaction](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:228). Evaluate all qualification conditions inside the transaction that saves the boost.

4. **Automatic review omits two required measures.**  
   `_quality_misses()` checks rates, complaints and failures, but `review()` never checks the 150 cold-email minimum or a genuine reply. An inbox with zero sends and zero genuine replies throughout the fortnight retains 50 indefinitely. This contradicts “miss any measure” in section G.  
   [Review](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:263). Isolated execution confirmed this result. The existing “clean fortnight” test also needs reconciling with the approved written rule.

5. **A recorded provider limit disappears at the next health check.**  
   `_apply_health()` replaces `health_evidence`; `_evaluate()` does not include `provider_daily_cap`. With the newly removed default, an inbox boosted to 50 and restricted by a recorded provider cap of 25 becomes capable of 50 after its next passing check.  
   See [replacement](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_setup.py:695) and [optional provider bound](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/metering.py:639). Preserve recorded provider limits independently of DNS evidence.

   Separately, the existing reply calculation permits `provider cap + 20`. If the recorded value represents the provider’s total sending limit, it must also constrain total cold-plus-reply usage.

**P2 — correctness fixes**

1. **Research and sending disagree for mixed-level inboxes.**  
   Research uses the brand’s highest boost; `_cold_limits()` uses the sending inbox’s boost for both daily and monthly brand limits. Example: one brand has inboxes at 50 and 20; the boosted inbox has already sent 20 today. Research can allocate new contacts to the unboosted inbox, but that inbox’s send path rejects them because brand usage has reached 20.  
   [Research calculation](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_research.py:724), [send calculation](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/metering.py:773). Use one shared brand-cap policy and test this behaviour end to end.

2. **Evidence windows use inconsistent boundaries.**  
   Cold sends include the entire UK date 28/14 days ago; replies use an exact timestamp cutoff. Sends earlier on that boundary date can therefore satisfy the minimum or dilute bounce/unsubscribe rates while corresponding negative replies are excluded.  
   [Evidence window](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:107). Apply consistent boundaries and test threshold cases.

3. **Link unsubscribes can be attributed to an inbox that never emailed the person.**  
   The tracing query accepts any outbound message, including drafts, cancelled messages and failed sends. It does not require accepted/committed sending evidence. This can wrongly deny or remove another inbox’s boost.  
   [Attribution query](/Users/michaelrickards/dev/bh2-OUT-19G/backend/services/outreach_boost.py:135).

4. **The screen presents granted level as actual sending capacity.**  
   It says an inbox “sends up to 30” even with an owner limit of 15, provider limit of 25, or a pause. The boost button also has no owner-role guard, although the backend correctly refuses staff.  
   [BoostInbox](/Users/michaelrickards/dev/bh2-OUT-19G/frontend/client/src/components/OutreachSetupWizard.tsx:947). Distinguish granted level from effective capacity and show the action only to owners.

**Backlog and test quality**

- The suite has useful real-send boundary tests and owner endpoint checks. However, research sizing and health-hook tests merely inspect source strings. They cannot establish transaction safety or consistent capacity.
- Add behavioural regression coverage for the findings above, including PostgreSQL concurrency, actual complaint handling, health-check persistence and mixed-inbox research.
- Repeated failed checks on one day increment the meter repeatedly. Eligibility remains conservative, but displayed counts should distinguish failed checks from failed days.
- Evidence scans all historical replies and matching meter rows on every review; bounded database queries would improve scalability.

Ordinary cold-send limits remain capped at 50, and owner limits below 20 remain enforced. The reply formula remains capped at 70. I found no cross-business inbox access in the reviewed boost paths.

**Verification:** read-only inspection plus isolated, in-memory execution of selected actual functions. I did not run `check.sh` or the 42-test suite: the former writes bytecode, and the test harness creates database files. No files were modified; the pre-existing untracked `data.db` was left untouched.

After fixes, Mike’s behaviour check should cover Settings → Sending mailboxes and the reply banner: effective limits displayed honestly, owner-only boosting, and recovery messaging after an inbox drops back.