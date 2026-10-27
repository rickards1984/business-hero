# OUT-20 — Codex review 2

- Commit reviewed: 1d976ec
- Model: gpt-6-astra · session 01a17505-750e-7373-acd2-af470be60a9c · tokens used: 40,754
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-20, cycle 2. Do not commit, push or modify files.
Review 1 and the builder's response are in audits/OUT-20-CODEX-REVIEW-1.md. Review commit 1d976ec (`git show 1d976ec`) with the files at HEAD.
Confirm all eight findings are resolved without new problems: unknown lookups, NS via dns_other, whole-mechanism SPF (_spf_with) and the merge email, DMARC absent/duplicate/invalid/unknown handling (_dmarc_repaired), query invalidation on finish and on a passing automatic check, the non-overlapping auto re-check with unmount cleanup, no edits possible during a redraft, Connect removed, and the paid-support request's pending/duplicate/failure handling.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `1d976ec`, which is HEAD.

1. **P2 — SPF repair can still return the unchanged failing record.** [_spf_with:565](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:565) accepts an existing include regardless of its position. Confirmed: `v=spf1 -all include:_spf.google.com` produces exactly the same replacement, so following the guide cannot fix it. Handle unreachable includes or explain that manual repair is required; add a regression test.

2. **P2 — DMARC repair silently drops policy settings.** [_dmarc_repaired:585](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:585) retains only `p` and `rua`. Confirmed: repairing `V=DMARC1; p=none; sp=reject; rua=mailto:reports@newbody.example; adkim=s; aspf=s` removes `sp=reject` and both strict-alignment settings, despite promising to preserve valid policy. Preserve valid optional tags and test this case.

3. **P3 — Retrying a failed escalation creates another support conversation.** [OutreachSetupWizard.tsx:569](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/components/OutreachSetupWizard.tsx:569) discards the conversation ID when `/support/chat` succeeds but `/support/escalate` fails. Retry calls `/support/chat` without that ID, creating another conversation. Retain the ID and retry escalation on the existing conversation.

The other requested fixes pass inspection: unknown SPF/DMARC lookups withhold record values; NS works through `dns_other`; whole-mechanism matching and merge-email include are fixed; basic DMARC absent/duplicate/invalid/unknown cases are covered; both invalidation paths are present; automatic rounds cannot overlap and cleanup prevents further batch requests/state updates; email editing/save/approval are disabled during redrafting; Connect is removed. Support pending and error presentation are fixed.

**Verification:** targeted pytest: **22 passed, 11 fixture errors** because the sandbox prohibits temporary database files. I read the blocked tests and confirmed the two DNS findings with read-only probes. No files modified, commits made or pushes performed.
## Response

1. **Taken.** `_spf_with` places the provider's include first and removes any other copy of it (qualified or not), keeping every other mechanism in order. An include stranded after `all` is therefore moved to where it counts. Test: `v=spf1 -all include:_spf.google.com` gives `v=spf1 include:_spf.google.com -all`.
2. **Taken.**
   - `_dmarc_repaired` keeps every valid optional tag in order: sp, rua, ruf, adkim, aspf, pct, fo, rf and ri, each validated. An invalid tag is dropped, and the report address is added only if none is valid.
   - Test: the reviewer's record keeps `sp=reject; adkim=s; aspf=s` and drops `pct=bogus`.
3. **Taken.** The conversation id is kept in a ref. A retry after a failed escalation escalates the same conversation and never opens a new one.
