- **P1:** None.
- **P2:** The banner fix is overridden in dark mode. [AdminDashboard.tsx:259](/Users/michaelrickards/dev/bh2-PROFIT-1b/frontend/client/src/pages/AdminDashboard.tsx:259) sets `color: 'inherit'`, but [design-system.css:2281](/Users/michaelrickards/dev/bh2-PROFIT-1b/frontend/client/src/styles/design-system.css:2281) forces translucent body text with `!important`. Fix that conflict so the banner inherits its intended contrasting colour.
- **Backlog:** Persist floor-specific boundary tests for `allowed()` and `check_after_record()`.

The income logic correctly takes the larger of trial budget and subscription income **including top-ups**. Other guard logic is unchanged.

Verification: **47 tests passed** using in-memory SQLite with file writes disabled. The new regression fails with the original `income()` implementation. Additional boundary checks passed for status, essential/non-essential permissions, and once-only committed alerts.

£85 / £200 still exceeds the 40% alarm; the kill threshold becomes £160.

Full `check.sh` and visual verification were not run. After the CSS correction, check the admin banner in both themes. No files changed.

**REQUEST CHANGES** — banner colour conflict.