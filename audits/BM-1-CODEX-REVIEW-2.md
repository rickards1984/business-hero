1. **Resolved — original P2**, `MeetingDetailView.tsx:113`: `/end` response immediately sets completed status, summary, sentiment and duration, and clears `forceChat`. Refresh waits at most 15 seconds; failure only logs.
2. **Resolved — original P2**, `executive_meeting_orchestrator.py:474`: Reasoning allowance includes 2,000-token headroom. Length exhaustion is logged; empty or JSON output returns `None`, while non-empty plain text is retained.
3. **Resolved — original P2**, `executive_meeting_orchestrator.py:63`: Fine-tuned IDs use their base model. Responses-only `-pro` models are rejected before client invocation, with an error naming `EXECUTIVE_MEETING_AI_MODEL`.

No regressions found within the requested scope. **22 tests passed** in `backend/tests/test_board_meeting_ai.py`. No browser verification or full `check.sh` run; no files modified.

**Verdict: APPROVE.**