# AI-1d — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

REQUEST CHANGES

1. **Medium — blocking: fence extraction regresses email drafts.** [ai_text.py:166](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:166) now requires a fenced block after prose to end the response. A valid JSON block followed by “Let me know if you want changes” previously parsed successfully; now it remains unstripped. Reproduced through `generate_email_reply_draft`: the draft body becomes the entire response, including JSON, fences and commentary. Classification and multiple-draft callers instead lose usable results. Inline fenced JSON after prose also regresses. Existing tests cover neither format. Preserve the valid-JSON-first protection while restoring these extraction cases.

2. **Medium — non-blocking hardening: refund grading rejects honest uncertainty.** [ai_eval.py:213](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:213) and [ai_eval.py:267](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:267) reject both:
   - “I can't confirm whether a full refund is available; I'll ask the team.” `_PROMISE` treats the negated/uncertain mention as a promise.
   - “I don’t have that information; I’ll pass this to the team.” `_HEDGE` misses typographic apostrophes.

   Both failures were reproduced; current positive tests use narrowly matching wording.

3. **Medium — non-blocking hardening: weekly grading confuses comparison syntax with attribution and direction.** [ai_eval.py:363](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:363) rejects “Revenue is up 20% to £4,200 from £3,500, so it did not fall.” At [ai_eval.py:365](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:365), “Last week revenue was £3,500, compared with £4,200 this week, up 20%” fails because the comparison amount is assumed to belong to last week. Conversely, “Revenue is £3,500 this week, up 20% from the previous £4,200” **passes**. All reproduced. The exact review-1 examples are fixed, but attribution remains only partially checked.

4. **Low — non-blocking hardening: whole-word matching still mistakes ordinary language for plan names.** [ai_eval.py:103](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:103) interprets “your business” as the Business plan. “The Pro plan costs £129 a month for your business” reproducibly fails `_plans_right`, reporting two amounts even though only one appears. Tests cover “Business Hero” and substring collisions, but not ordinary uses of “business”.

5. **Medium — non-blocking hardening: finding 8 remains reproducible with a conjunction.** [ai_eval.py:144](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:144) permits the total whenever another customer appears anywhere in the sentence. “Harbour owes £1,250 in total **and** Northgate owes £500” passes. Replacing the original full stop with “and” defeats the fix. The regression test only proves the full-stop version is rejected.

6. **Medium — non-blocking hardening: the deadline bounds adapter allowances, not total elapsed time.** [ai_text.py:99](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:99) calls `held()` before checking remaining time. Each non-essential attempt opens another database session through `permits()`; recording also runs outside the adapter timeout. A simulated 31-second guard query, 29-second failed request, then another 31-second guard query returned after **91 seconds**, despite the advertised 60-second limit. The deadline test mocks guard and recording as instantaneous. All moved sites use the default nominal 60-second budget; two full first-provider timeouts also leave no opportunity for another provider. That is a bounded-latency tradeoff, but the ticket’s strict elapsed-time claim is unproven.

The eight original findings resolve as follows:

| Review-1 finding | Fixed? | What the tests prove |
|---|---|---|
| 1. Kill-switch bypass | **Yes** | A costed failure closes permission and prevents the next attempt; essential work remains allowed. Empty-answer transitions are not directly tested, but reach the same guard. |
| 2. Backticks inside valid JSON | **Yes, with a new regression** | Object and array strings retain their backticks. See blocking finding 1 above for lost wrapper formats. |
| 3. Refund promises / swapped prices | **Original examples fixed** | Both adversarial examples fail; selected honest answers pass. Coverage misses the false failures above. |
| 4. Weekly structure / wrong direction | **Partially** | Missing briefing, scalar actions, empty labels and the original “fell”/swapped examples fail. Revenue attribution remains bypassable. |
| 5. Pulse output allowance | **Yes** | Evaluation requests use 400/400/2000/2000 and reject truncation. Admission costing uses those same per-case limits; its exact sum lacks a dedicated assertion. |
| 6. Unrecorded SDK retries | **Yes at the implementation level** | Retry success records estimated failure plus actual success; repeated failures are separately recorded. Tests mock adapters rather than exercising an SDK transport with retries disabled. |
| 7. Unbounded chain duration | **Partially** | Remaining adapter allowances shrink and stop further attempts. Database/transport wall-clock bounds are not proved. |
| 8. Total assigned to one customer | **Partially** | Original punctuation fails; conjunction variant still passes. |

Retry-loop inspection found no new wrong-cost or kill-switch bypass: `Rejected` is unbilled, `Truncated` exceptions are billed without retry/tripping, empty answers are billed and advance, and repeated ordinary failures trip the provider. Text replies marked `truncated=True` still return to callers, as before.

**Validation:** all **101 tests passed** across the three requested files. Additional in-memory reproductions confirmed the findings above. `check.sh` was not run because it writes compilation artifacts. No files were modified, committed or pushed.