**REQUEST CHANGES — OUT-19 E, review 1, North Star P8.**

Reviewed `2866295..9b7008a`. No files modified, committed or pushed.

**P1**

- **Briefing offers answers whose supporting facts are no longer approved.** [outreach_replies.py:113](/Users/michaelrickards/dev/bh2-OUT-19E/backend/services/outreach_replies.py:113) returns stored `suggested_body` without validating `knowledge_refs`. Reproduced: retire the supporting fact, then request the briefing; it returns `"Weekday appointments"` with `facts: []`. The UI still offers **Copy the answer**. Validate the referenced versions against current facts; otherwise withhold the answer and explain why. Use the matched campaign’s brand, as the approval path does.

- **Both new HTTP reads bypass the outreach feature gate.** [router.py:1735](/Users/michaelrickards/dev/bh2-OUT-19E/backend/app/email/router.py:1735) checks authenticated context but never calls `assert_feature_access`. The shared router has no global feature dependency. Consequently, an explicit admin denial of outreach does not prevent these reads, unlike existing outreach history endpoints. Apply the canonical gate, using retained-history semantics where appropriate, and test explicit denial and suspension.

**P2**

- **Briefing bypasses existing retention minimization.** [outreach_replies.py:109](/Users/michaelrickards/dev/bh2-OUT-19E/backend/services/outreach_replies.py:109) exposes prospect name, role, company and email without checking `retention_due_at`. Existing prospect reads redact expired contact fields. Apply equivalent minimization before returning or copying the briefing.

- **Headroom overstates actual sendability.** [metering.py:647](/Users/michaelrickards/dev/bh2-OUT-19E/backend/services/metering.py:647) ignores health-check freshness, although reservation requires today’s check. Reproduced: yesterday’s healthy inbox reports `left: 25` today while sending would be refused. Return availability/blocking information, or describe this strictly as remaining ceiling allowance. Also, `headroom` returns the mailbox email address: it contains no prospect details, but does **not** meet a literal “no personal data” requirement when that address identifies a person.

- **The warm-up regression test does not isolate the mailbox limit.** [test_outreach_replies_ceiling.py:108](/Users/michaelrickards/dev/bh2-OUT-19E/backend/tests/test_outreach_replies_ceiling.py:108) fills a campaign whose cap equals the mailbox cap. Removing the mailbox warm-up guard entirely still leaves **all 22 tests passing**; the campaign guard masks the defect. Add a shared-mailbox/multiple-campaign case with spare campaign and brand capacity. Cover NULL/unrecognised kinds and reserved/unknown outcomes independently.

- **Copy promises more than the implementation provides.** [ReplyCeilingBanner.tsx:19](/Users/michaelrickards/dev/bh2-OUT-19E/frontend/client/src/components/ReplyCeilingBanner.tsx:19) promises “Every reply still gets answered”, although owner action remains necessary. “Boosting opens once…” implies an implemented eligibility unlock; part G does not exist. Label Boost as coming later. [OutreachReplyCard.tsx:48](/Users/michaelrickards/dev/bh2-OUT-19E/frontend/client/src/components/OutreachReplyCard.tsx:48) also attributes every missing suggestion to absent approved facts, although classification, eligibility or drafting failure can cause it. Use neutral wording or a recorded reason.

**Backlog**

- Show/copy the fact source references already returned by the briefing API.
- Add cross-business briefing/headroom tests and explicit reply settlement/release tests.
- Expose headroom through the tenant-scoped Aria tool layer; it currently exists only as an HTTP read.

**Checks that passed**

- Replies skip campaign, brand-daily, brand-monthly and mailbox cold limits.
- Cold counting includes NULL/unrecognised message kinds and excludes `bespoke`.
- In the inspected reservation path, cold sends cannot exceed their warm-up allowance; neither kind can reserve beyond the shared daily ceiling.
- Replies can exhaust the shared ceiling and block cold sends. That matches section E. Cold sends alone leave the additional reply allowance.
- Settlement/release still update the same daily rows; lock acquisition order is unchanged.
- Part D already excludes replies from research usage.
- Briefing requires an active owner. All inspected lookups are business-scoped; I found no cross-business disclosure path.

**Verification**

The new suite passed **22/22**, using in-memory SQLite and disabled cache/bytecode writes to preserve read-only access. Restoring only part D’s reservation function in memory produced **7 failures**, confirming meaningful regression coverage of the core change.

I did not run `check.sh` because it writes compiled files, or perform browser/PostgreSQL concurrency tests. After fixes, the key behaviour checks are opening a briefing after retiring its fact, viewing headroom with stale health, and checking the disabled Boost explanation.