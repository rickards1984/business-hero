# NS-B7 — Codex reviews, verbatim

## Review 1

| | |
|---|---|
| Reviewed commit | `6fc68dd` |
| Session id | `01a1419b-6540-76a0-8ed5-27c7fe613080` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 66,914` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** at `6fc68dd4`. The main blockers are P2/P8 truthfulness and the missing hero on some mobile/native layouts.

1. **P1 — Invoice totals cover only the first page.** [useDashboardData.ts:60](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/hooks/useDashboardData.ts:60)  
   `/v1/invoices` defaults to 50 records, sorted by due date. With 50 older paid invoices and an overdue invoice beyond them, the home reports £0 and “none overdue.” Fetch all relevant records or use an authoritative aggregate.

2. **P1 — Partial payments disappear from outstanding and overdue totals.** [useDashboardData.ts:63](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/hooks/useDashboardData.ts:63)  
   A £1,000 overdue invoice with £400 paid and status `partially_paid` contributes nothing, despite £600 outstanding. Additionally, this endpoint returns `paid_amount`, not `amount_due`. Calculate the remaining balance from the actual response contract. These invoice defects were inherited from the dashboard, but now also drive Aria’s new factual briefing.

3. **P2 — “Nothing needs you” can contradict failed queries or open tasks.** [AriaHero.tsx:35](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/components/AriaHero.tsx:35)  
   If approvals fail while invoices, email and calls return empty, the hero declares “Nothing needs you right now,” above “Your drafts couldn’t be loaded.” Open high-priority tasks are also ignored. Include relevant failures and tasks, or narrow the claim. Partial failures must remain visible even when another source supplies a briefing line.

4. **P2 — Approval counts and newly created drafts remain stale.** [useDashboardData.ts:102](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/hooks/useDashboardData.ts:102), [DashboardPage.tsx:90](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:90)  
   Approve or dismiss the only card: `ApprovalCard` updates its local state, but the hero still says one draft awaits approval. Likewise, visit an empty home, create a draft in chat, then return: the cached empty list remains. Global query defaults disable mount/focus/interval refetching; `staleTime` does not schedule refreshes. Wire mutation invalidation and an appropriate refresh policy.

5. **P2 — Email classification does not prove a reply is needed.** [useDashboardData.ts:134](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/hooks/useDashboardData.ts:134), [DashboardPage.tsx:107](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:107)  
   An “Action Required” email requesting payment or document review becomes “needs a reply,” without reply-state evidence. Conversely, an actionable message older than the latest 200 is excluded, allowing “All clear.” Use the supported “needs action” wording and disclose or eliminate the sampling limit.

6. **P2 — Old figures are presented without age or stale-state disclosure.** [AriaHero.tsx:55](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/components/AriaHero.tsx:55), [DashboardPage.tsx:98](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:98)  
   Leave home open while invoices change elsewhere: figures remain unchanged, the hero still displays unconditional “ONLINE,” and no tile shows age. This misses the explicit Stage 2 freshness requirement. Show actual data freshness and qualify retained data after failures.

7. **P2 — The hero disappears at 768px and on wider Capacitor screens.** [DashboardPage.tsx:72](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:72)  
   The shell treats widths ≤768px and every native platform as mobile; the dashboard hook only treats widths <768px as mobile. At exactly 768px, or on a native tablet/landscape screen wider than that, neither renders the hero. Share the shell’s mobile decision.

8. **P2 — The approved two task lists are absent.** [DashboardPage.tsx:130](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:130)  
   Opening home shows only a Tasks heading and “Show all.” Expanding it exposes the existing single task panel, without “Aria is on it” and “Yours.” Implement the approved lists with truthful assignment data, or explicitly revise Stage 2 scope.

9. **P2 — Ask input has no visible keyboard focus.** [AriaShellHeader.css:57](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/components/AriaShellHeader.css:57)  
   Tabbing into the main question field removes the outline without a replacement focus indicator. Add input focus styling or a visible form `:focus-within` state.

`./check.sh full` passed: **5 gates passed, 0 failed**, ESLint skipped; **1,821 tests passed, 33 skipped**, 220 subtests passed. Source inspection found Quotes gating, settings destinations, sign-out, support and subscription-banner wiring preserved.

No authenticated browser or native-device verification was performed; 375px overflow, safe areas and visual theme behaviour remain unverified. No source edits, commits or pushes. The check run left an untracked `data.db`; I left it untouched.
---

### Response to review 1 — Claude Code (builder), 15 October 2026

| Finding | Action |
|---|---|
| 1 · Invoice totals cover only the first page (P1) | New read-only `GET /v1/home/summary` (`home_api.py`, `services/home_summary.py`) computes receivables on the server over **every** invoice of the business. The browser no longer adds anything up. Tested with 60 paid invoices plus one overdue |
| 2 · Part-payments ignored (P1) | Balance owed = the provider's `amount_due` when recorded, else `amount` less the larger of the two legacy paid columns, never below zero. Statuses that are not owed are excluded (case-insensitive). **Aria's `get_invoice_summary` now uses the same `receivables()`**, so the home and Aria cannot disagree. Previously Aria also summed gross amounts. Tested: the part-payment variants, archived and fully-paid invoices, tenant isolation, due-today, and a test that Aria and the home agree |
| 3 · "Nothing needs you" despite failures and tasks (P2) | The hero names any source that failed ("I couldn't load your drafts or invoices and email just now"), even when other lines exist. "Nothing needs you" appears only when everything loaded and there are no drafts, nothing overdue, no emails flagged and no high-priority tasks, and it now says exactly that. High-priority tasks join the briefing |
| 4 · Stale approval counts and drafts (P2) | Home queries refresh on mount, on returning to the tab, and every 60 s. `ApprovalCard` takes `onChanged`, and the home invalidates the drafts and the summary when a card changes. Shown cards stay on screen so an approved one can say "Sent" rather than vanishing |
| 5 · "Needs a reply" overclaims; a 200-email sample (P2) | The wording is now "need action". The count is computed on the server over every message flagged "Action Required" in the last 14 days, and the window is stated on the tile and in the briefing |
| 6 · No freshness (P2) | The summary returns when email and accounting last synced. The tiles say "Accounts synced 12 min ago" or "Not synced from your accounts software", and likewise for email. The hero's permanent "ONLINE" becomes "UPDATED 14:05", or "SOME FIGURES UNAVAILABLE" with an amber dot |
| 7 · Hero missing at 768 px and on native tablets (P2) | `useShellMobile()` is the one decision (≤768 px or any native app), used by the shell and the home |
| 8 · Two task lists absent (P2) | **Partly, by decision, for Mike.** "Aria is on it" would be untrue today: Aria takes no action on her own (P4; that is Phase 3). The home shows **Your tasks**: the six most pressing open tasks, by priority then due date, with an "Added by Aria" chip on those she proposed and the owner approved, and the full panel a tap away |
| 9 · No visible focus on the ask field (P2) | `:focus-within` ring on the ask bar |
