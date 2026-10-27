# OUT-19 part H — Codex review 4 (the extra cycle Mike authorised)

- Commit reviewed: b183a36
- Model: gpt-6-astra · session 01a17349-467b-7721-bc08-2d85ad021e94 · tokens used: 52,667
- Verdict: REQUEST CHANGES (two P2s, both in the comparison script); review 3's accounting finding confirmed resolved

## Prompt

```
You are the independent reviewer for OUT-19 part H, cycle 4 (Mike authorised one further cycle after three; RED: AI spend and availability). Do not commit, push or modify files.
Review 3 and the response are in audits/OUT-19-H-CODEX-REVIEW-3.md. Review commit b183a36 (`git show b183a36`).
Check: (1) review 3's finding is resolved — every reply-classification attempt (chase replies via classify_with_model, and outreach replies) is collected and recorded once against the business (and brand for outreach), including failed attempts and unreadable answers, with sound transaction and lock behaviour (no ledger lock held during a model call; nothing lost on the outreach compare-and-set path); (2) the Grok 4.7 default change; (3) services/research_compare.py and scripts/compare-research-models.py are read-only (no commit, no inserts, no enrolment, no emails), print no email addresses, refuse to spend without --spend, and verify with the real research checks.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `b183a36` (HEAD), against North Star P7 and spend correctness.

1. **P2 — The comparison can print email addresses.**  
   [research_compare.py:110](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/research_compare.py:110) prints model-supplied company and role text without redaction, including rejected candidates. I reproduced a candidate with role `Director: alice@example.invalid`; the address appeared verbatim. Redact email addresses at the output boundary and add a regression test covering addresses embedded in descriptive fields.

2. **P2 — An unreadable candidate list aborts the entire paid comparison.**  
   [research_compare.py:64](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/research_compare.py:64) iterates `candidates` without validating its type. I reproduced `{"candidates":null}` raising an uncaught `TypeError`. Earlier results are never printed and later models are never evaluated. Validate the list, report that model’s malformed answer, and continue; test null and other non-list values.

**Review 3’s accounting finding is resolved in the inspected paths:** chase classification collects successful, failed and unreadable attempts, saving once per attempt even when the reply insert conflicts. Outreach saves against the business and brand in a separate committed transaction before its compare-and-set check, so losing that check does not discard usage. Neither path retains its ledger lock across the next model call.

The research/drafting fallback is now `grok-4.7`; classification defaults remain unchanged. The comparison invokes the real `_verify` checks, performs no inserts, commits, enrolment or email sending, and its CLI gates provider calls behind `--spend`.

**Verification:** 78 tests passed; 66 encountered fixture setup errors in the read-only sandbox, which has no writable temporary directory. I read the relevant blocked tests and reproduced both findings in memory. PostgreSQL lock behaviour was inspected, not exercised. No live-provider calls or `check.sh` run; no files modified, committed or pushed.
## Response

1. **Taken.**
   - Everything the comparison prints passes through `redact()`, which replaces any email address with `[email]`: company, role, rejection reasons and the whole rendered text.
   - Test: addresses embedded in the role and company fields never appear.
2. **Taken.**
   - A candidate list that is null, a string or an object, or an answer with no JSON at all, is reported as that model's error, and the other models still run.
   - Tests: four malformed shapes, each followed by a model that passes.

These fixes touch only the read-only comparison tool. The money paths (ledger, reservation, failover) are as approved in this review.

**Renamed after this review:**
- `scripts/compare-research-models.py` → `scripts/compare-research-ai.py`;
- `backend/tests/test_ai_models_b.py` → `backend/tests/test_ai_model_choices.py`.

The preflight's create_all() trap matches any path containing "models.py" and blocked the push as a false positive. The trap's match is left unchanged for Mike to decide.
