# OUT-16 — Outreach actually sends

**Tier:** RED (email transport to third parties, and unsubscribe).

## Why
Neither the Gmail nor the Microsoft provider could send outreach. `outreach_send.dispatch` calls `send_outreach`, which didn't exist. An approved card raised, was recorded as outcome "unknown", stayed "executing" and held capacity. Nothing reached a prospect.

## Part A — sending (this ticket)

**`providers/outreach_mime.py`** builds one RFC 5322 message:
- From (with the mailbox's display name), To, Cc, Subject, Date;
- **our own Message-ID**, and In-Reply-To/References for follow-ups;
- the **one-click unsubscribe headers** (RFC 8058: List-Unsubscribe, List-Unsubscribe-Post);
- plain text.

No other extra header is allowed. A line break in any header value refuses the message before any provider call.

**Gmail** (`GoogleGmailProvider.send_outreach`):
- `users.messages.send` with the raw message, and the Gmail thread id for follow-ups.
- Returns Gmail's message and thread ids.

**Microsoft 365** (`MicrosoftGraphProvider.send_outreach`):
- `me/sendMail` with the full MIME message. Graph's JSON form allows only `x-` headers, which would drop our Message-ID and unsubscribe headers.
- Graph returns no ids, so the sent copy is found by its `internetMessageId` (3 tries, 1.5 seconds apart). If not found yet, the send is still accepted, with no provider ids.

**Honest outcome**, never retried by the adapter:

| Result | Outcome |
|---|---|
| the provider's documented success (Gmail 200, Graph `sendMail` 202) | accepted |
| any other 2xx or 3xx | unknown |
| 4xx, including rate limits, an invalid token or an unsafe message | definitely not accepted |
| 5xx, timeout or network error | unknown (it may still have been delivered); the existing reconciliation handles it |

**Permissions:** the connections already request `gmail.send` and `Mail.Send`.

## Part B — the unsubscribe page (this ticket)
- `GET /u/{token}` shows a confirmation with a button and never changes anything (mail scanners and link previews open links).
- `POST /u/{token}` unsubscribes, through the existing `outreach_send.unsubscribe`: it suppresses the address, stops sequences, cancels pending sends and dismisses waiting cards. It is what the button posts, and what Gmail, Yahoo and Apple Mail send for one-click unsubscribe.
- Rate limited, unauthenticated; an unknown or revoked token is a plain 404.
- The unsubscribe link is `OUTREACH_UNSUBSCRIBE_BASE_URL`, or by default `PUBLIC_BASE_URL` + `/u`, which serves this page.

## Part C — later
The definitive deliverability check: each mailbox sends a test email to the owner, and Business Hero reads the receiving server's `Authentication-Results` (agreed in OUT-15).

## Known limit
A Microsoft follow-up needs the first email's provider ids. If Graph didn't show the sent copy within the lookup window, that prospect's follow-up waits until the ids are known.

## Codex review 1 (`audits/OUT-16-CODEX-REVIEW-1.md`) — what changed
- **Follow-up subjects.** Gmail threads a follow-up only when its subject matches the conversation's, and recipients' mail clients group on it too. A follow-up's subject is now "Re:" plus the subject of the email it follows (no "Re: Re:"), whatever subject the step's template carries. The approval card shows the subject that will actually be sent.
- **Microsoft threading.** Graph's MIME `/reply` always addresses the original message's sender, and for a follow-up that sender is our own mailbox. So follow-ups and replies go through `sendMail` with In-Reply-To, References and the "Re:" subject, which is what the recipient's client threads on. Graph's own grouping is then checked, not assumed: the conversation the sent copy actually landed in is the one recorded, and any mismatch, or a copy not found yet, is named in `thread_note` on the result.
- **Outcomes.** Only each provider's documented success status counts as accepted: Gmail 200, Graph `sendMail` 202. Any other 2xx or 3xx is "unknown". Accepted means the provider took the message, not that it was delivered.
- **Unsubscribe page.** The rate limit is keyed on IP alone. The shared key trusts an unverified bearer token's `sub`, so on a public page a forged token could buy a fresh bucket. Unsubscribe addresses with a fragment or query are refused, on both configuration paths.
- **Not provable here.** Whether each provider preserves our Message-ID, and whether its DKIM signature covers both unsubscribe headers (needed for full RFC 8058 compliance), can only be checked on a real sent message. Part C's test email covers this. Mike's first live send should be checked by viewing the original message.

## Codex review 2 (`audits/OUT-16-CODEX-REVIEW-2.md`)
- A follow-up keeps the whole of the previous subject, even at the sequence API's 998-character limit. The MIME writer folds the long Subject line; it is never cut.
- Backlog done: the POST unsubscribe rate limit is tested; a `thread_note` is shown to reach the stored action result; the outcome table above is corrected.
