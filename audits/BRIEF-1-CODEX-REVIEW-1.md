# BRIEF-1 — Codex review 1 (preserved verbatim)

**Findings — not approved.** These affect grounded figures and reliable delivery (P2/P8).

1. **P1 — Period boundaries ignore the business timezone.** [whatsapp_briefings.py:85](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:85) creates naive timestamps for calls, emails and quotes, whose columns are `timestamptz`. PostgreSQL interprets those bounds using its session timezone. With UTC sessions during British Summer Time, Monday 00:00–00:59 local is excluded and Saturday 00:00–00:59 included. Pass the business timezone through and construct aware local-midnight bounds. The SQLite tests cannot detect this.

2. **P1 — Outstanding invoices omit supported statuses.** [whatsapp_briefings.py:135](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:135) excludes `partially_paid` and `overdue`. Both are supported by existing invoice update/import paths (`main.py:2992`, `main.py:3154`). Consequently, weekly and monthly summaries can say nothing is outstanding despite money being owed. Include these states and calculate partial-payment balances correctly; the update path records `paid_amount` without updating `amount_due`.

3. **P1 — A failed send suppresses the entire briefing.** [whatsapp_briefings.py:206](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:206) treats every message row as sent, including `twilio_status="failed"` written by the sender. A transient failure therefore prevents retries for the rest of Friday/the first, with no later catch-up. Additionally, [line 233](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:233) ignores the returned SID and reports success even when sending returns `None`. Distinguish failed attempts from accepted sends and report success only when confirmed.

4. **P2 — Unknown call outcomes are credited as answered.** [whatsapp_briefings.py:97](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:97) substitutes `"handled"` for null/empty outcomes. This exceeds the explicitly agreed three outcomes and inflates “answered by Aria.” Count only explicit qualifying outcomes.

Additional checks:

- Ledger figures correctly reuse `accountancy_pack._ledger` and `ledger_pnl`, including inclusive transaction dates and archived-row exclusion.
- No remaining runtime callers of the removed functions or readers of `briefing_snapshots` were found. Alerts and automations still create pending actions.
- Per-business exception handling protects later businesses, although a briefing exception skips remaining work for that business on that tick.
- The scheduled guard uses aware midnight, so a successful 23:59 send is covered for that local day; the following day is outside the scheduled window. Manual test sends bypass the guard and can suppress that day’s scheduled briefing.
- Existing sender logging exposes full recipient phone numbers (`whatsapp_service.py:305`); invalid-variable logging can expose variable contents. These are inherited issues.
- Sanitisation removes newlines and prevents blank output, but allows **exactly 1024 characters**, rather than the requested *under 1024*.

Read-only review completed; five changed Python files passed AST syntax checks. `check.sh` and pytest were not run because they write bytecode, caches or temporary databases. No files changed, committed or pushed.