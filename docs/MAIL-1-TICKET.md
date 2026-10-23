# MAIL-1 — Several mailboxes per business, with a dependable default

**Tier:** AMBER (email account management; OAuth sign-in). **Builder:** Claude. **Reviewer:** Codex. **Tests first, reviewed by Mike.**
**Decisions:** Mike, 19 Oct 2026, Addition B: more than one outreach mailbox per business, for example a FitFutures inbox and a New Body Gym inbox on newbodyhf.co.uk. Mike's report on 21 Oct: Email settings offers no way to connect a second Gmail.

## Why

- **The screen allows one account per provider.** It hides "Connect Google" once one Google account is connected.
- **Nothing ever marks a mailbox as the default.** The Google and Microsoft connections never set it, and the screen has no control for it.
- **Choosing a default is two separate requests.** It clears every default, then sets one. If the account belongs to another business, or the second request fails, the business is left with **no default**. The clearing also runs before the ownership check.
- **The Google sign-in always uses the same account.** It doesn't ask which account to use, so it tends to reconnect whichever Google account the browser is already signed in to.
- **Why it matters:** since AUTO-2, chases go only from the default mailbox. With several mailboxes and none marked default, Aria rightly stops chasing. Connecting a second mailbox today would silently stop invoice chasing.

## Behaviour

1. **Connect any number of mailboxes.** "Connect Google" and "Connect Microsoft" are always available. The Google sign-in asks which account to use (`prompt=consent select_account`).
2. **The first mailbox a business connects becomes its default.** Later ones never take the default. Reconnecting an existing mailbox (same address and provider) keeps its identity and its default flag.
3. **"Make default" switches in one database transaction:** an ownership check first, then clear, then set. An account that isn't this business's own gets "not found", and nothing changes. The 037 rule (at most one default per business) backs this up.
4. **A label per mailbox,** such as "FitFutures outreach", stored as the mailbox's display name. It's 1–60 characters and scoped to the business.
5. **Disconnecting the default** while two or more mailboxes remain returns `needs_default: true`. The screen then asks the owner to choose, and says invoice chasing is paused until they do. With exactly one left, that one is the default by AUTO-2's rule.
6. **The screen:** each mailbox is listed with a "Default" chip on the default, a "Make default" button on the others, an editable label, and "Disconnect". A warning shows when two or more are connected and none is the default.

## Not in this ticket

- Choosing a mailbox per outreach campaign (OUT-8).
- Changing where generic Aria emails, quotes or metering notices are sent from: they're the OUT-2 §3 follow-ups.

## Tests

`backend/tests/test_mailboxes.py`.

## Click test (after merge)

1. In Email settings, `m.rickards@newbodyhf.co.uk` shows **Default**.
2. Press "Connect Google" and choose `outreach@newbodyhf.co.uk`. It's listed without Default. Give it the label "New Body outreach".
3. Repeat with `partners-ukfi@newbodyhf.co.uk`, labelled "FitFutures outreach".
4. Invoice chasing still goes from `m.rickards@`. The home page shows no warning.
5. In MSC's business, connect `ops@msccompany.co.uk`.

## Mike's approval — 23 October 2026

The tests are approved. Build authorised.
