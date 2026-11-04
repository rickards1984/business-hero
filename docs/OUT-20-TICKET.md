# OUT-20: one Launch checklist per brand

**Tier:** AMBER. It switches on research, which spends AI money, but only within approvals and budgets that already exist. **Mike, 4 Nov 2026:** "I set it up for UKFI… it says it's set up and ready… but nothing has been researched." He suggested a launch button.

**Cause:** setup ends at "ready", but prospect research is a separate per-brand switch. It is **off by default** and lives on the Settings tab. With it off, nothing is found and nothing is drafted.

**Built:**
- **`services/outreach_launch.py`:**
  - `checklist()` shows, per brand: setup finished, outreach not paused, the sending mailbox checked, an audience approved, the privacy notice approved, the campaign's emails approved, and research on. Each item carries what to fix and where.
  - `launch()` (owner only) switches the brand's research on, and **only** when every approval is in place. Otherwise it refuses with 409, naming what's missing. It never approves anything.
  - `pause()` (owner only) switches the brand's research off. Emails already in a sequence carry on under their own approvals, and Pause all still stops everything.
- **Routes:** `GET /v1/outreach/setup/launch`, `POST /v1/outreach/setup/launch` and `POST /v1/outreach/setup/launch/pause`, all through the existing owner and entitlement paths.
- **Screen:** a Launch panel at the top of Outreach → Overview (owner only). Each brand shows Running or Not running, a tick or a fix link per item, and one Launch or Pause button.
- **Tests:** `test_outreach_launch.py` has 8:
  - a set-up brand with research off shows exactly that;
  - Launch turns research on;
  - Pause turns it off;
  - Launch refuses when the templates aren't approved;
  - only the owner can act;
  - Pause all blocks launch;
  - the routes work for the owner and give 403 to staff.

## Codex review 1 (`audits/OUT-20-CODEX-REVIEW-1.md`, 7 × P2) → fixed

1. **Runtime parity.** The checklist now uses the rules research applies when it runs. The audience approval must be *current* (`research._audience`: reviewer and dates), and the campaign must be `ready` or `running`. It also checks that outreach is included in the plan, the brand is paid for (`brand_live`), the AI allowance has room, and the monthly research budget has room. Each is its own item, with its fix.
2. **Pause** uses `growth=False`, like research's own switch: an owner can always stop spend.
3. **The screen:**
   - Pause is shown whenever research is on, even while another item is failing;
   - a failed load shows an error with Retry;
   - the checklist sits under the `outreach` key, so the page's refresh after Pause all, and every setup or research change, refreshes it.
4. **Tests (13):**
   - an out-of-date approval, a paused campaign, unapproved templates after setup, an unpaid brand and a used allowance all block launch;
   - Pause works without growth entitlement.

   Mutation testing confirms the pause authority and the campaign status are both caught.

## Codex review 2 (`audits/OUT-20-CODEX-REVIEW-2.md`, 4 × P2) → fixed

The checklist is now built on **research's own functions**, not a copy of their rules:
- **Audience and campaign are judged together, per audience.** An audience counts only if `research._audience` accepts its approval as current, **and** `research.capacity` finds a ready or running campaign of this brand for that audience, **and** that audience's campaign emails are approved on a healthy inbox (setup's rule; launch is deliberately stricter on what sending needs). Two half-ready audiences can't add up to "ready".
- **Spending uses research's own reservation gates for the whole search:**
  - `ai_router.reserve_pence()` (a provider exists and is priced);
  - `ai_costs.allowed(purpose="research")` (the platform limit);
  - `outreach_allowance.may_research(reserve)`;
  - spent plus the reserve within the monthly budget.
- **Today's room** (`capacity`) is shown, with research's own reason, but never blocks launch. A full inbox is a daily state, so the badge reads "On, no room today" rather than "Running".
- **Tests (18):** half-ready audiences, the whole reservation over budget, no provider, the platform limit, and no room today.

## Codex review 3 (`audits/OUT-20-CODEX-REVIEW-3.md`, 2 × P2) → fixed

1. **No Companies House key:** research refuses before every search (it can't confirm a company), so this is now its own blocking item, "Company checks available".
2. **A newer draft hid an older approval:** launch's "emails approved" check now matches by **audience** (its hash), not by approval version, so a newer draft never hides an older approval that research still uses.

**Also proven:**
- an older paused campaign never hides a ready one;
- reverting to version matching is caught by mutation testing.

**Tests:** 21.

**Accepted difference (by design):** launch needs the privacy notice and approved emails on a healthy inbox, while research alone doesn't. In that case launch says "Not running", and research could still find contacts for a brand that can't email them. Launch stays stricter so nothing is found that can't be used.
