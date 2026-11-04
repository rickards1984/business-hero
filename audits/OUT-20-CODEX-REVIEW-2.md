# OUT-20 Codex review 2 (targeted)

Model gpt-6-astra · verdict **CHANGES REQUIRED** (4 × P2)

## Prompt

```
Read-only targeted re-review of OUT-20 in this worktree (`git diff origin/main...HEAD`). Your review 1 is audits/OUT-20-CODEX-REVIEW-1.md; the response is the "Codex review 1" section of docs/OUT-20-TICKET.md. Confirm each of the 7 findings is fixed and proven, and that the checklist now cannot show "Running" when research would find nothing for a reason it could know in advance (and vice versa). APPROVE or CHANGES REQUIRED with P1/P2. Brief. Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED — P2.** “Running” parity is still not established.

- **P2 — Audience and campaign checks can describe different audiences.** [outreach_launch.py:85](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:85): a current audience without a campaign plus an expired audience with a ready campaign passes both checks. Research cannot use either.
- **P2 — Campaign selection causes the reverse mismatch.** [outreach_launch.py:41](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:41) checks only setup’s selected campaign per audience. An older paused campaign can hide another ready campaign: checklist says “Not running” while research can proceed.
- **P2 — Spending gates remain incomplete.** [outreach_launch.py:81](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:81) checks positive balance, whereas research requires enough for the entire search reservation. Platform spending limits and provider availability are also omitted.
- **P2 — Available capacity is never checked.** [outreach_launch.py:105](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:105) permits “Running” with zero campaign/inbox capacity, including exhausted pilot places; research refuses before searching.

Original findings: **#1–2 partially fixed; #3 incomplete; #4 fixed with a regression test; #5–7 fixed by code inspection, without frontend regression tests.** The new tests do not prove scheduler/enrolment parity.

Test execution was blocked by the read-only environment’s lack of a writable temporary directory. No edits, commits or pushes.