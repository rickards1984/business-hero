# OUT-18 part A — Codex review 3

- Commit reviewed: 3b81a62
- Model: gpt-6-astra · session 01a1700d-9648-7840-9a1c-ece039c325ec · tokens used: 44,456
- Verdict: APPROVE

## Prompt

```
You are the independent reviewer for OUT-18 part A, cycle 3 (RED: research spend caps and daily personal-data limits). Do not commit, push or modify files.
Reviews 1 and 2 with the builder's responses are in audits/OUT-18-CODEX-REVIEW-1.md and -2.md. Review commit 3b81a62 (`git show 3b81a62`) and backend/services/outreach_research.py at HEAD.
Confirm both review 2 findings are resolved: every usage_meters write in run() (reservation, settlement, overspend pause) now happens after the business lock with no transaction end in between, so the lock order is business lock -> meter everywhere; and the new test test_every_meter_write_happens_under_the_business_lock deterministically fails if any meter write happens without the lock.
Also check no other code path writes the research meter or the research config without the business lock (search the repository).
The part B setup-status commit on the branch is out of scope. If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**APPROVE** — `3b81a62` reviewed against HEAD. Part B excluded. No P1/P2/P3 findings.

Both review 2 findings are resolved:

1. Reservation and settlement acquire the business lock before `_spend()`. No intervening commit or rollback releases it. Overspend settlement and the brand’s config pause remain locked through the same commit.
2. The replacement test deterministically detects an unlocked `_spend()` call: it records lock acquisition and resets held-lock state on commit or rollback. Both parameter cases would fail against the previous settlement ordering, without thread-scheduling dependence.

Repository searches found no additional production research-meter writer or research-config save bypassing the shared business-settings lock, including whole-document settings writers.

The test observes `_spend()` calls rather than SQL execution; it covers the current write paths, not arbitrary future SQL bypasses.

Pytest failed before collection because the sandbox has no writable temporary directory. Tests were reviewed statically; no passing execution is claimed. No files were modified, committed or pushed.