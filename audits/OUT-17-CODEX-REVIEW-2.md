# OUT-17 — Codex review 2

- Commit reviewed: 19a7013
- Model: gpt-6-astra · session 01a16f53-bd41-7f62-9464-09c6169067b7 · tokens used: 54,333
- Verdict: APPROVE

## Prompt

```
You are the independent reviewer for OUT-17, cycle 2. Do not commit, push or modify files.
Review 1 is in audits/OUT-17-CODEX-REVIEW-1.md with the builder's response. The branch is now rebased onto main (which includes OUT-10 research).
Review the HEAD commit (19a7013) and the whole branch diff against origin/main (frontend/ and audits/ only).
Check whether findings 1 and 3 are resolved, and whether the justification for not taking finding 2 holds (look at OutreachPage.tsx's non-owner "Inspection only" mode and the server's access checks).
Confirm every claim in OutreachIntro.tsx against backend/services/outreach_research.py and the research switch in OutreachSetupWizard.tsx.
Run: (cd frontend/client && npx tsc --noEmit -p .)
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**APPROVE** — reviewed HEAD `19a7013` and the whole branch diff against `origin/main`, limited to `frontend/` and `audits/`. No outstanding P1/P2/P3 findings.

1. **Finding 1 resolved.** Research now exists and is explicitly opt-in. The implementation supports up to 20 contacts per weekday, prioritises decision-makers, and checks company websites and Companies House. The research switch matches the copy. Drafting, brand/mailbox identity, linked approved privacy notice, owner approval, home-screen replies and pausing are supported. The unsupported accuracy/compliance guarantee is removed. Six required setup steps match backend status.
2. **Finding 2 withdrawal justified.** Staff navigation matches the existing “Inspection only” mode. Reads use authenticated business context and tenant-scoped queries; write services enforce active ownership. The intro and “New” marker remain owner-only.
3. **Finding 3 resolved.** Cached reply cards, the unresolved-replies link and error notice are all gated by `outreachOn`.

Requested TypeScript check **passed** (exit 0). No files modified.

Browser behaviour was not tested. Mike’s checks: compare owner/staff navigation, disable Outreach after loading replies, and exercise setup at 360px.