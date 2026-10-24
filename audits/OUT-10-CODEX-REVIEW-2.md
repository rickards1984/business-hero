**REQUEST-CHANGES — 3 P1 findings remain.**

Reviewed OUT-10 against `ticket/OUT-15-outreach-setup`, including all fixes since `88bf0e0`.

**P1 — blocking**

1. **Corporate identity remains insufficiently verified.** [outreach_research.py:400](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:400) strips legal suffixes and accepts substring matches. A Companies House record for “Studio 1 Ltd” passes against a page saying either “sole trader trading as Studio 1” or “Studio 10 Ltd”. Both probes produced **eligible, enrolled contacts**. [Line 388](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:388) also accepts an empty company status. Require an unambiguous legal-entity disclosure and explicitly active status; uncertainty must remain review-only.

2. **Email proof still accepts part of another valid address.** [outreach_research.py:325](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:325) omits valid local-part characters from its boundary rules. A page containing only `!sam@studio1.example`, `/sam@studio1.example`, `=sam@studio1.example` or `#sam@studio1.example` proves the nonexistent shorter `sam@studio1.example`. All four probes produced **eligible, enrolled contacts**. Compare complete mailbox addresses without extracting suffixes.

3. **Spend reservation still fails to bound or preserve all charges.** [outreach_research.py:809](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:809) retains `max_retries=1`. Using the real SDK with mocked transport, a read timeout triggered a second request; the successful response then reduced the entire reservation to **1p**, losing the first request’s uncertain spend. Additionally:
   - [Line 813](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:813) bounds output and tool calls, but not input cost. Synthetic usage of 300,000 input tokens, 8,000 output tokens and eight searches settled **2,009p against a 2,000p cap**.
   - [Line 531](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:531) uses the initially loaded budget. Lowering it to zero during the first search still allowed two additional searches.

   Disable uncertain retries, reserve a defensible maximum covering all billable work, and reread the current cap before each reservation.

**Backlog — non-blocking**

- **Officer matching still overclaims:** [line 322](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:322). “Sam James” matches officer “SMITH, Sam James”; two matching tokens do not establish a matching surname.
- **Morning preparation covers only new enrolments:** [line 607](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:607). An existing enrolment whose follow-up becomes due receives no morning card through this path.
- **Research memory remains unavailable through Aria tools:** [line 120](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:120). Status and lessons have HTTP/UI access but no corresponding registration in `assistant_tools.py`; asking Aria for these records cannot retrieve them through the promised tool.

The DNS-pinning, shared daily quota and locked suppression fixes address their original failure mechanisms. Initial disabled-business/expired-approval checks are present. I found no cross-tenant learning query or general model-controlled action execution.

Verification: **235 targeted tests passed**; `./check.sh` passed with **3,264 passed, 305 skipped**. The known OUT-7 flake did not occur. Ten additional offline probes reproduced the remaining defects; they remain in [/tmp/test_out10_review2.py](/tmp/test_out10_review2.py).

No network, commits or pushes. Worktree clean; the empty test-generated `data.db` was removed.