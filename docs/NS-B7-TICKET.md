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
