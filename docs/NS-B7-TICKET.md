# NS-B7 — Aria home and the Aria-centred shell (round-2 option A)

**Tier:** AMBER (UI; it reads existing endpoints; no money, auth or schema).
**Plan approved by Mike, 14–15 Oct 2026:** "Round 2 - A; the menu bar on one
row just below Aria. It looked really quite impressive." Earlier:
"Everything seems nearly spot on… simple and elegant… a bit more futuristic…
without being too much like a gimmick."

**Design reference:**
- the live mock-up: https://claude.ai/artifact/Q2fENT71NDrJN41wmGWt5S (row
  "Round 2", board **A**);
- its source, copied to `docs/NS-B7-MOCKUP-A.html`. That file is the
  mock-up's markup: read it for layout, spacing, colours and type, NOT as
  code to paste.

**North Star:**
- P1 Aria is the front door;
- P2 grounded (every figure from real data, with its source and age);
- P6 departments keep their pages, in one visual language. Working modules
  are wrapped, not rebuilt.

## Stage 1 — the shell (this ticket's first build)

Replace the desktop **sidebar** with the option-A layout, on every
`/app/*` page:

1. **The dark top band** (`#0B0C12`, with a fine dot-grid as in the
   mock-up), full width:
   - the Business Hero mark, plus the business name in small monospaced
     caps (`JetBrains Mono`, loaded with the existing Google Fonts link);
   - on the right: **Hold a board meeting** (`/app/board-meeting`), the
     help button (SupportPanel, as today), the theme toggle, and the
     **Settings** menu with the same items as today's sidebar settings
     (Branding, Billing, Email, Voice), plus sign-out.
2. **The menu row** directly under the band, one row:
   - the departments, in this order:
     - **Aria** (`/app/dashboard`);
     - **Comms** (`/app/comms`);
     - **Finance** (`/app/finance`);
     - **Quotes** (`/app/quotes`, only when quoting is enabled, exactly as
       the sidebar decides today);
     - **AI Hub** (`/app/ai`).
   - Active item: white text and a violet underline (`#8E7CFF`). Inactive:
     `#A3A5BD`.
   - It scrolls horizontally if it is too narrow, with no visible
     scrollbar.
3. **On non-home pages, the band is compact:** a small Aria avatar (40 px)
   with "Ask Aria" opening `/app/assistant/chat`, so Aria is one tap away
   everywhere. **On the home page (`/app/dashboard`), the band grows to hold
   the hero** (Stage 2 fills it). For Stage 1, put a clearly marked slot
   there and keep the existing DashboardPage content below.
4. **Mobile (≤ 768 px, and the iOS/Android Capacitor apps):**
   - keep today's bottom navigation (`MobileBottomNav`);
   - the dark band becomes a slim header (mark, business name, avatar);
   - no menu row.
   - Respect safe areas (`env(safe-area-inset-top)`), as the shell does today.
5. **Theme:**
   - The band is always dark, by design. The page body below follows the
     existing light/dark theme.
   - Use the business's `brand_color` (from `useMe`) for the active
     underline and primary buttons when it is set, falling back to violet.
     Check contrast: if the brand colour is too light on dark, use violet
     for the underline.
6. **Avatar performance:**
   - Add compressed copies of `public/aria-avatar.png` (8.5 MB): e.g.
     `aria-avatar-160.webp`, `-320.webp`, `-640.jpg`. Generate them with
     macOS `sips` or any tool available in your sandbox.
   - Use them in the shell and in every existing `<img src="/aria-avatar.png">`
     (RealtimeVoice, AssistantChat, BusinessDashboard, Accounting), with
     `srcSet`.
   - Keep the original file.
7. **Motion:** the avatar's soft "breathing" glow ring, as in the mock-up,
   is disabled under `prefers-reduced-motion`.
8. **Nothing else changes:**
   - every route, page and feature works exactly as before;
   - no backend change;
   - `SubscriptionBanner`, `SectionErrorBoundary` and the support panel stay
     wired as they are.

### Acceptance

- `./check.sh full` is green (`tsc` included).
- The desktop sidebar is gone; the band and the menu row are on every
  `/app/*` page; the active item matches the route.
- Quotes is hidden exactly when it was hidden before.
- Mobile keeps the bottom navigation; no horizontal page scroll at 375 px.
- The original avatar is no longer loaded anywhere (only the compressed
  copies).
- A short note in this ticket listing every file changed, and anything that
  needs Mike's eye in the browser.

## Stage 2 — the Aria home (next; Claude)

On `/app/dashboard`:
- **The hero:** a 168 px avatar with the glow and an "Online · synced N min
  ago" line; a greeting; a short **grounded briefing** built from existing
  dashboard data; the ask bar (opens chat with the prompt); and **Talk**
  (opens voice).
- **Needs you:** the open approval cards from `GET /v1/aria/actions`, using
  `ApprovalCard`.
- **Department tiles**, each with a live figure and its age.
- **Two task lists.**

## Stage 3 — department pages (later)

Each department page gets an Aria summary strip at the top and "Ask Aria
about this" in context, starting with Invoices.

## Stage 1 builder handoff — Codex, 15 October 2026

**Status:** ready for Claude's review and scope check; working tree only.
Serves P1/P6 and Phase 1. No new data, figures, provider calls, backend changes,
commits or pushes. The pre-existing untracked `data.db` was left untouched.

Implemented the dark dot-grid shell, desktop department row, compact Ask Aria
link, and explicitly labelled Stage 2 hero slot above the unchanged dashboard.
Mobile (including 768 px and native Capacitor at any width) retains bottom
navigation; the slim header's Settings menu also exposes theme, board meeting,
help and sign-out. Existing Quotes entitlement logic, support wiring,
subscription banner and section error boundary remain in place. Nested routes
select their department; settings/help do not falsely highlight Aria.

Brand colour applies to the shell's primary board-meeting button, with contrasting
text. The underline falls back to violet for pale colours (relative luminance
above 0.75) or less than 3:1 contrast against the band. Reduced motion disables
the new avatar glow animation. The shell paints the existing body top safe-area
reservation rather than reserving it twice.

**Every changed/added file:**
- `docs/NS-B7-TICKET.md` — this handoff.
- `frontend/client/index.html` — JetBrains Mono in the existing font request.
- `frontend/client/src/components/AppShell.tsx` — shell integration and route selection.
- `frontend/client/src/components/AriaShellHeader.tsx` (added) — band, menu, hero slot.
- `frontend/client/src/components/AriaShellHeader.css` (added) — scoped shell styles.
- `frontend/client/src/components/RealtimeVoice.tsx` — responsive compressed avatar.
- `frontend/client/src/pages/AssistantChat.tsx` — responsive compressed avatar.
- `frontend/client/src/pages/BusinessDashboard.tsx` — both avatar uses compressed.
- `frontend/client/src/pages/Accounting.tsx` — both avatar uses compressed.
- `frontend/client/public/aria-avatar-160.webp` (added, approximately 4 KB).
- `frontend/client/public/aria-avatar-320.webp` (added, approximately 11 KB).
- `frontend/client/public/aria-avatar-640.jpg` (added, approximately 65 KB).

The original PNG remains. Source search finds no remaining frontend reference
that loads it. Assets were resized with the existing local Pillow installation;
no dependency was added.

**Verification:** `./check.sh full`, using this worktree's `.venv/bin/python`:
5 gates passed, 0 failed, 1 skipped (no ESLint script). Pytest: 1,821 passed,
33 skipped, 220 subtests passed. All five preflight traps passed.
`git diff --check` is clean. Preflight's changed-file traps inspect the committed
branch range, so Claude must also scope-check these uncommitted files.

**Mike's browser checks (not verified by check.sh):**
- Desktop: open Aria, then each department and nested accounting/inbox/board
  meeting routes; compare the band, dot grid, monospace labels and active
  underline with option A. Confirm the home slot and original dashboard below.
- Click Ask Aria, Hold a board meeting, Help, and all four Settings destinations;
  confirm Quotes appears only for a business where quoting is enabled.
- Phone at 375 px and 768 px, plus native iOS/Android: check slim header,
  bottom navigation, Settings/theme access, safe areas and no horizontal page
  scroll. Check long business names and landscape too.
- Switch light/dark: body follows the theme while the band stays dark. Check
  a custom brand colour and a very pale one; enable reduced motion to confirm
  the new glow stops. Inspect avatars on chat/voice/accounting for sharpness.

No authenticated browser or native-device run was performed in this sandbox;
the command gate does not verify visual layout or end-to-end behaviour.
