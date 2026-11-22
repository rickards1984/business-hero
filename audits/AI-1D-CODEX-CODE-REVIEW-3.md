# AI-1d — Codex code review 3 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

REQUEST CHANGES

1. **Medium — blocking: fence compatibility still regresses production sites.** [ai_text.py:177](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:177). **Review-2 point 1’s examples are fixed and tested**, including single-draft generation with a closing remark. However, JSON followed by a closing ` ``` ` without an opening fence now remains unstripped. Compared with `HEAD~3`, reproduced outcomes are:
   - Inbox sorting: valid classifications become `[]`.
   - Three-tone email drafts: generated replies become the generic fallback.
   - Aria’s draft tool: generated replies become the generic fallback. It also loses previously accepted `json\n[...]` responses.

   The single-draft site had no stripping before AI-1d, so these formats are not a regression there. Existing tests miss these asymmetric wrappers. Preserve valid-JSON-first protection while restoring the previous sites’ accepted formats.

2. **Medium — non-blocking grading hardening: honest refund uncertainty still fails across commas.** [ai_eval.py:298](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:298). **Review-2 point 2’s exact examples are fixed and tested**, including curly apostrophes. But this honest answer reproducibly fails: “I can't confirm whether you get a full refund, a partial refund or no refund; I'll ask the team.” Splitting at the comma separates “partial refund” from its hedge, falsely classifying it as a promise. Tests prove the selected wording, not uncertainty spanning a list.

3. **Medium — non-blocking grading hardening: weekly comparisons acquire a new false failure.** [ai_eval.py:389](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:389), [ai_eval.py:408](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:408). **Review-2 point 3’s examples are fixed and tested**, including rejection of the reversed figures. However, “Revenue is £4,200, up 20% compared to £3,500 last week” now fails because `_NOW_TO` interprets “to £3,500” as this week’s revenue. Also, “Revenue is up — 20% to £4,200 from £3,500” fails because splitting at the dash removes the direction from the percentage’s clause. Both are honest answers to the weekly case; neither is tested.

4. **Low — non-blocking grading hardening: ordinary “business” remains only partially handled.** [ai_eval.py:103](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:103). **Review-2 point 4’s exact example is fixed and tested.** “Pro costs £129 a month for a growing business” still reproducibly fails: “business” becomes a second plan name, producing the misleading “two amounts together” error. The exclusion list handles selected phrases rather than the general distinction.

5. **Medium — non-blocking grading hardening: shared-total protection rejects a correct reversed sentence.** [ai_eval.py:138](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_eval.py:138). **Review-2 point 5’s conjunction bypass is fixed and tested.** But “The total owed is £1,250 by Harbour Lettings and Northgate Estates” now fails, incorrectly reporting Harbour’s amount as wrong. Requiring both names before the total rejects this legitimate collective attribution. Existing positive tests put both names first.

6. **Medium — non-blocking inherited latency hardening: the deadline claim remains too strong.** [ai_text.py:87](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:87), [ai_text.py:114](/Users/michaelrickards/dev/bh2-AI1d/backend/services/ai_text.py:114). **Review-2 point 6’s repeated-guard scenario is fixed and tested:** the 31-second guard consumes the attempt allowance and no second guard starts after expiry. However, “only an attempt’s costing and one guard query can run past it” is false:
   - Model resolution can synchronously refresh its database cache before the first deadline check. An in-memory simulation of a 75-second configuration read returned after 75 seconds with **zero guard calls**.
   - Adapter timeouts are HTTP operation/inactivity limits, not total elapsed deadlines. Repeated response reads can exceed the remaining allowance.

   The tests prove guard accounting and shrinking adapter allowances, not a strict wall-clock bound.

**Validation:** **121 tests passed** across `test_ai_text.py`, `test_ai_text_sites.py` and `test_ai_eval_sets.py`; additional in-memory reproductions confirmed the findings. No new cost/attribution error, kill-switch bypass, crash or event-loop blocking regression was identified. The other support and briefing cases showed no additional demonstrated regression.

`check.sh` was not run because it writes artifacts. No files were modified, committed or pushed. **Finding 1 is the blocker; findings 2–6 can follow separately.**