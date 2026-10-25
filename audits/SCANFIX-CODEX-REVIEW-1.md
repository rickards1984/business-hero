# Outreach scan lock fix — Codex review 1

- Commit reviewed: af354fd
- Model: gpt-6-astra · session 01a17373-5ae0-7e51-8f2d-aec2d346032c · tokens used: 39,988
- Verdict: REQUEST CHANGES (two P2s in the wizard; no backend safety regression found)

## Prompt

```
You are the independent reviewer for an urgent production fix in this repository (RED: outreach reply safety and locking). Do not commit, push or modify files.
Review commit af354fd on branch fix/outreach-scan-lock (`git show af354fd`). Context is in the commit message: brand saves timed out because outreach_replies.scan held the business lock while reading the whole inbox on every email sync.
Check:
1. Safety is unchanged: every genuine reply from a contacted prospect is still found and stops/pauses their enrolments; opt-outs still suppress; the OUT-7 stale-unclassified recovery still runs; nothing is missed because of the new pre-lock filter (sender normalisation via _address on both sides, the received_at >= first accepted send bound, messages arriving between the unlocked read and the lock, a prospect contacted for the first time after the filter ran, time zones/string comparison of received_at on PostgreSQL).
2. Locking: the business lock is now taken only when there is a candidate or a stale reply; the unlocked reads hold no locks; the per-id re-check under the lock prevents double recording; no other path relies on scan holding the lock across the whole inbox.
3. Performance: the unlocked candidate query's cost on a large inbox (it still selects id/from_email since the first send) and whether an index or a tighter filter is needed now.
4. The wizard change in frontend/client/src/components/OutreachSetupWizard.tsx (saved/err messages, keeps unsaved rows, no auto-advance, Next button).
5. The three new tests prove the fix and fail against origin/main.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — two P2 wizard defects. I found no P1 backend safety regression by inspection.

1. **P2 — Saving still automatically advances.**  
   [OutreachSetupWizard.tsx:159](/Users/michaelrickards/dev/bh2-scanfix/frontend/client/src/components/OutreachSetupWizard.tsx:159) passes `choose` as `onSaved`. `choose` calls `setActive(null)`, so once the saved brand appears, `current` selects the next incomplete step—normally mailboxes. The success message disappears with the brand step. Keep `active='brand'` after saving; advance only through Next. Confirm by saving one brand and checking that its success message and add-another controls remain visible.

2. **P2 — Failed rows can be discarded by name.**  
   [OutreachSetupWizard.tsx:280](/Users/michaelrickards/dev/bh2-scanfix/frontend/client/src/components/OutreachSetupWizard.tsx:280) removes every row whose trimmed name matches a successful save. With two same-name rows containing different sender identities, success on the first followed by failure on the second deletes the failed row too. Track successful row identities, not names. Also, the successful-batch `setRows([blank])` discards partially completed rows excluded from `filled`. Preserve every unsaved row.

Backend review:

- **Sender and time filtering:** Both sides use `_address`. The global first accepted-send bound is conservative relative to the existing per-prospect history check. Repository schema evidence declares both timestamps `timestamptz`; PostgreSQL compares instants, not timestamp strings. SQLite TEXT fixtures do not establish timezone correctness.
- **Concurrent arrivals:** Mail arriving after candidate selection, or a prospect first contacted after the contacted-set read, can be deferred to a subsequent scan. There is no cursor advancement that permanently excludes them. This is eventual detection, not same-invocation completeness. Claim and dispatch independently call `recheck_inbound`, so they do not rely solely on scan having already paused the enrolment.
- **Reply safety:** Candidate processing retains stopping, opt-out suppression, and OUT-7 recovery. Pending unknown replies trigger the locked path even without new candidates; this includes replies still within the classification wait.
- **Locking:** Preliminary queries take no business or row locks. PostgreSQL still takes ordinary relation-level read locks, released by rollback. The locked per-ID `NOT EXISTS` re-check prevents duplicate capture between cooperating scans. I found no caller requiring scan to lock the entire inbox.
- **Performance:** The query still transfers and normalises every unrecorded message since the first send on every scan; cost grows with inbox history. Migration 007 defines `(business_id, received_at DESC)`, but I did not verify its production presence or a query plan. This residual cost does **not** justify blocking the urgent lock fix on a new index. A tighter, normalisation-safe sender filter merits follow-up; an index alone cannot eliminate the broad result set.

**Tests:** Pytest could not execute the tests: all 63 failed during fixture setup because the read-only sandbox provides no writable temporary directory. I read the three new tests and compared their assertions with `origin/main`; each should fail against its old implementation. They cover the intended lock/read changes, but do not prove PostgreSQL locking, timezone handling, or pre-filter races. The `'id='` assertion is also weak because it matches `business_id=`.

No files modified, committed, or pushed. `check.sh` was not run; no runtime or visual verification is claimed.
## Response

1. **Taken.** Saving selects the saved brand and keeps the brands step open (`active='brand'`). Only **Next: sending inbox** moves on, so the success message and the add-another controls stay visible.
2. **Taken.** Rows are tracked by position. Only rows that saved are removed; failed rows and half-filled rows are all kept.

**Test:** the "read by id" assertion now checks for `AND id=:id`, which `business_id=` cannot match.

**Recorded, not built:** the residual cost of the unlocked candidate query on a long inbox history. It reads ids and senders only, takes no locks, and Codex agrees it doesn't block this fix. A tighter, normalisation-safe sender filter is a follow-up.
