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

## Review 2 (repair cycle 1 of 3)

| | |
|---|---|
| Reviewed commit | `b293ab9` |
| Session id | `01a141a2-2ad0-7853-a37f-a1595039ff9f` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 46,713` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** at `b293ab9b87e98fe22ca89c4a2f10bdf6454da529`.

1. **P1 — Partial payments are still overstated when `amount_due` is populated.** [home_summary.py:27](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/services/home_summary.py:27)  
   Create a £1,000 manual invoice, then record £400 paid through the existing status endpoint. Creation sets `amount_due=1000` ([invoices_api.py:228](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/invoices_api.py:228)); recording payment changes only `paid_amount` ([main.py:3020](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/main.py:3020)). The new CASE therefore reports **£1,000 owed instead of £600**, on both home and Aria. Finding 2 remains unresolved for this supported flow. Reconcile the balance rules with actual writers and add this regression case.

2. **P2 — Home and Aria use different dates for overdue classification.** [assistant_tools.py:2414](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/assistant_tools.py:2414)  
   At 00:30 BST on 16 October, a UTC server’s `date.today()` is still 15 October. An invoice due on the 15th is overdue on home but not in Aria’s summary. The UK-day choice is reasonable; apply it consistently and test the midnight boundary.

3. **P2 — “Shown cards” ignores refreshed changes and removals.** [DashboardPage.tsx:59](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:59), [ApprovalCard.tsx:65](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/components/ApprovalCard.tsx:65)  
   Leave home open and edit or dismiss a draft in another tab. Polling updates the query and briefing, but `shown` only appends unseen IDs; the card also retains its initial proposal in local state. Home continues displaying the old preview or an actionable dismissed card. Server version checks prevent an incorrect send, but the refresh repair is incomplete. Reconcile existing cards and distinguish locally completed cards retained for confirmation from stale open cards.

Prior findings: **1, 3, 5, 6, 7 and 9 are addressed by inspection; 2 and 4 remain incomplete as above.** For **8**, avoiding an unsupported “Aria is on it” claim is sound. However, P4 does not itself prohibit assigned tasks—it governs approval of actions. The single-list fallback is reasonable pending Mike’s acceptance of the scope revision; the ticket still specifies two lists.

Other requested checks:

- **PostgreSQL:** No syntax/type defect found in the aggregate. Numeric CASE branches, nullable payment columns, archived NULL handling and Python `date` comparison against the documented `date` column are sound. `status` is documented NOT NULL; exclusions are case-insensitive. PostgreSQL execution was not performed.
- **Auth/access:** JWT and business-membership resolution precede tenant-scoped SELECTs. The endpoint performs no writes and permits read-only access as intended.
- **Other Aria keys:** Existing status subtotals remain gross face-value totals, while outstanding/overdue now represent balances. That distinction should be explicit; they are no longer interchangeable.
- **Refresh load:** Five query families every minute is reasonable at current scope, but is not five SQL statements: summary alone executes six. Calls fetch up to 500 rows and tasks fetch all returned rows. No demonstrated load blocker; no load test performed.

`./check.sh full` passed: **5 gates passed, 0 failed; 1,837 tests passed, 33 skipped; 220 subtests passed.** ESLint skipped. Frontend reviewed by inspection only.

Anything else: no additional blocker found; no edits, commits or pushes, and the pre-existing untracked `data.db` remains untouched.
---

### Response to review 2 — Claude Code (builder), 15 October 2026

| Finding | Action |
|---|---|
| 1 · App-recorded payments still overstated (P1) | Balance owed = the **smaller** of the recorded `amount_due` and `amount` less the larger paid column. That covers a manual invoice (amount_due = full amount, payment in `paid_amount`) and a synced one (amount_due already net, paid column also set) without deducting twice; never below zero. Tests: £1,000 with £400 recorded in the app is £600; a provider balance is not reduced twice; an overpayment is not negative |
| 2 · Home and Aria use different days (P2) | `home_summary.uk_today()` is used by both. Aria's summary no longer uses the server's `date.today()`. Tested at 23:30 UTC on 15 October (00:30 BST on the 16th): the invoice due on the 15th is overdue in both. Aria's result now says, in a `note`, that outstanding and overdue are balances while the per-status totals are face value |
| 3 · Shown cards ignore refreshed changes and removals (P2) | The home renders the server's open drafts, refreshed, keyed by `id:version`, so an edit elsewhere remounts the card with its new content and a dismissal elsewhere removes it. Only cards the owner acted on **here** are retained (to show their result) |
| 8 · Scope note | One list, "Your tasks", pending Mike's acceptance. The ticket will be updated when he decides |

## Review 3 (repair cycle 2 of 3)

| | |
|---|---|
| Reviewed commit | `cfbe0c6` |
| Session id | `01a141a5-b45f-7241-a8ef-15986ab2206d` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 44,434` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** at `cfbe0c693c7995fd535db5d2d6eccba5ff9df5ef`.

1. **P1 — CSV updates can leave receivables understated.** [home_summary.py:35](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/services/home_summary.py:35)  
   Create a £1,000 manual invoice, then import the same invoice number with an unpaid total of £1,200. [main.py:3188](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/main.py:3188) updates `amount` but leaves `amount_due=1000`. The minimum reports **£1,000 instead of £1,200** on home and to Aria. Reproduced against the aggregate in SQLite; no regression test covers this writer sequence.

2. **P1 — Stale local payments override refreshed provider balances.** [home_summary.py:31](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/services/home_summary.py:31)  
   Mark a £1,000 synced invoice paid locally, leaving `paid_amount=1000`. Subsequently correct the payment in the accounting provider to £400 and sync: the row becomes `amount_due=600`, `amount_paid=400`, unpaid—but retains `paid_amount=1000`. Home and Aria report **£0 instead of £600**. Xero’s [upsert](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/main.py:4614), [background sync](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/services/background_sync.py:412) and [scheduler sync](/Users/michaelrickards/dev/bh2-NS-B7-review/backend/services/briefing_scheduler.py:523) all preserve that stale column. Reproduced in SQLite; reconciliation needs an explicit authority rule and regression coverage.

3. **P2 — A locally edited draft can reappear after dismissal elsewhere.** [DashboardPage.tsx:59](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:59), [DashboardPage.tsx:110](/Users/michaelrickards/dev/bh2-NS-B7-review/frontend/client/src/pages/DashboardPage.tsx:110)  
   Edit version A locally and save. `onChanged` retains the original proposed A; polling displays version B. Dismiss B in another tab. Once polling removes B, `actedOn` restores A and its changed key remounts an actionable, outdated card. The callback also runs for edits and failures, so retention is not restricted to completed actions. Server checks prevent an incorrect send, but review-2 finding 3 remains incomplete.

Writer audit: manual creation, quote conversion, fresh CSV imports and consistent Xero/QuickBooks/FreeAgent rows fit the formula; local partial-payment recording now works and is tested. **CSV updates and provider refreshes after local payment changes do not.**

Review-2 finding 2 is resolved and tested: home and Aria share the UK date, including the midnight boundary. Untouched drafts now refresh correctly by frontend inspection.

`./check.sh full`: **5 gates passed, 0 failed**, ESLint skipped; **1,841 tests passed, 33 skipped**, 220 subtests passed. Targeted home-summary tests: **20 passed**. Frontend inspected only; no browser or PostgreSQL execution.

Scope note: the single task list still awaits Mike’s acceptance.

No edits, commits or pushes; pre-existing untracked `data.db` remains.
---

### Response to review 3 — Claude Code (builder), 15 October 2026

| Finding | Action |
|---|---|
| 1 & 2 · No single formula fits every writer (P1) | **One authority per kind of row**, from the writer audit. *Synced* rows (`external_id` set; Xero upsert, background sync, scheduler sync) use the provider's `amount_due`, else `amount − amount_paid`; a payment ticked in the app (`paid_amount`) does not override the ledger, and a local "paid" status still excludes the row until the next sync. *Local* rows (manual, CSV, quote) use `amount −` the larger paid column. Their `amount_due` is only ever the creation total, and a CSV update can leave it stale, so it is ignored. Tests: a CSV update to £1,200 is owed in full; a stale local £1,000 payment does not hide the provider's £600; the synced fallback works. Earlier tests now mark their provider rows as synced |
| 3 · A finished-then-edited draft can reappear (P2) | `ApprovalCard.onChanged` passes the card's new state. The home retains a card only when it has **finished** (status no longer `proposed`); an edit is not retained, so an edited draft simply follows the server's list |

## Review 4 (confirm-only, repair cycle 3 of 3)

| | |
|---|---|
| Reviewed commit | `84c12cb` |
| Session id | `01a141a9-3c5e-7492-a28c-2b37c935e900` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 37,840` |
| **Verdict** | **ACCEPT-WITH-CHANGES** (backlog only) |

Verbatim:

---

**ACCEPT-WITH-CHANGES** at `84c12cbe8516f7a3c81ef086480d2932070694b7`. **No new P1 found under the stated per-row authority rule.**

- **Finding 1 resolved:** the local CSV-update case reports **£1,200**.
- **Finding 2 resolved:** the refreshed provider balance reports **£600**, despite the stale £1,000 local payment.
- **Finding 3 resolved by inspection:** callbacks pass the updated card; proposed edits are not retained. **Not browser-tested.**

The three new money tests fail against the previous formula and pass against this fix. Independent SQLite writer-sequence probes also returned the correct figures through both the aggregate and Aria.

Writer audit covered manual creation, quote conversion, CSV inserts/updates, local status/payment changes, Xero upserts, and background/scheduler provider syncs. These fit the declared rule: provider balances govern externally identified rows; recorded payments govern local rows.

`./check.sh full`: **5 gates passed, 0 failed; 1,844 tests passed, 33 skipped; 220 subtests passed.** Targeted tests: **23 passed**. ESLint skipped; no PostgreSQL or browser execution.

Backlog notes for Mike:

- Add a browser regression: edit a home draft, dismiss it in another tab, then confirm polling removes it permanently.
- Add writer-level integration tests; committed money regressions seed resulting rows rather than invoke the writers.
- Explain that local partial payments and CSV total edits do not override synced balances, while local paid/cancelled statuses still suppress them.
- Resolve the outstanding single-task-list scope decision.

No edits, commits or pushes; pre-existing untracked `data.db` left untouched.
---

Backlog notes recorded in `docs/BACKLOG.md`. The task-list scope decision is with Mike.
