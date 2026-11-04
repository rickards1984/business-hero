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
