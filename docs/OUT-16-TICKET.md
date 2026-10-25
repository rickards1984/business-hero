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
| 2xx | accepted |
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
