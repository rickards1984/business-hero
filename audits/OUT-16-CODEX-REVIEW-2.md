**REQUEST CHANGES** — one P2 remains. This review serves **North Star P8: trust over cleverness**, applied to outreach.

Reviewed `3923c85..5b3e1b7` on `ticket/OUT-16-sending`. No files modified, committed or pushed.

**P1 — none found.**

**P2 — follow-up subjects still lose continuity above 990 characters.**  
[outreach_send.py:196](/Users/michaelrickards/dev/bh2-OUT-16/backend/services/outreach_send.py:196) truncates the previous subject before adding `Re:`, although [the sequence API permits 998 characters](/Users/michaelrickards/dev/bh2-OUT-16/backend/outreach_manage.py:61). I reproduced a valid 998-character predecessor becoming a 994-character follow-up, losing its last eight characters. This leaves finding 1 incompletely fixed: Gmail requires subject continuity for threading. Preserve the complete subject and add a boundary regression test. [Gmail threading requirements](https://developers.google.com/workspace/gmail/api/guides/threads)

The four original findings:

1. **Subject construction — fixed for ordinary subjects, boundary defect above.** Construction happens in `build_payload`; preview and dispatched subject agree, and existing `RE:` is preserved. Both new assertions pass. Removing the subject fix in memory makes the regression test fail.
2. **Unsubscribe rate limit — fixed.** Both GET and POST explicitly use `ip_key`. The forged-bearer regression passes and would fail with the former key. It exercises GET only; POST coverage would strengthen it.
3. **Fragments and queries — fixed on both configuration paths.** Validation rejects populated fragments, bare `#`, queries and bare `?`. All six committed cases pass using an in-memory database. Removing fragment validation makes the fragment regression fail. Query rejection was already present.
4. **Microsoft threading — acceptable as best-effort threading with honest reporting.** Using `sendMail` avoids replying to the sender of our own outbound message. Microsoft documents `/reply` as replying to the original sender; that supports the follow-up rationale, although “always” is too broad and the same rationale does not apply to incoming replies. [Graph reply documentation](https://learn.microsoft.com/en-us/graph/api/message-reply?view=graph-rest-1.0)

   The adapter preserves the actual returned `conversationId`, reports mismatch or unavailable correlation through `thread_note`, and dispatch persists that note in the action result. The mismatch test would fail without the fix. These mocks establish reporting correctness, **not guaranteed Outlook or recipient-side threading**.

**Outcome mapping is correct:** Gmail 200 and Graph 202 alone count as accepted; other 2xx/3xx remain unknown. Regression cases cover both adapters. Acceptance is appropriately distinguished from delivery. [Graph sendMail contract](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)

**Backlog**

- Add POST rate-limit coverage and an integration assertion that `thread_note` survives dispatch into the stored action result.
- Update the ticket’s stale “2xx = accepted” table.
- Retain the live-mail verification for Message-ID preservation, actual threading and DKIM coverage of both unsubscribe headers.

**Verification:** targeted pytest produced **29 passed, 7 setup errors** because temporary SQLite files cannot be created here. Separately, both subject tests and all six URL cases passed with the existing fixtures redirected to in-memory SQLite. `check.sh` was not run because it writes compiled files. No live emails were sent.

For eventual behavioural confirmation, inspect the follow-up approval card’s subject, then check conversation placement in the authorised owner test mailbox.