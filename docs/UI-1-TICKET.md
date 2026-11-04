# UI-1: light mode is readable in the call details panel

**Tier:** GREEN (UI only). **Reported by Mike, 3 Nov 2026.** In the Calls section in light mode, the call details panel that slides in from the right was almost unreadable.

**Cause:** the panel's background follows the theme (white in light mode), but its text and boxes were hard-coded in dark-mode colours: near-white text `#e8e6e1` and translucent white boxes.

**Fix:**
- **The call details panel (`CallsPanel.tsx`):** every colour follows the theme. Dark mode keeps its exact previous values; light mode uses the light theme's text, divider and hover colours.
- **Transcript bubbles (`design-system.css`):** the text uses the theme foreground, and the caller bubble has a light background in light mode. Dark mode is overridden to exactly the previous colours.
- **Sidebar email and sign-out icon, and Aria chat's "or type a message below" and input placeholder:** the same treatment, with dark mode unchanged.

**Review:**
- Codex quick review 1 found 2 × P2: dark mode shifted slightly. Fixed, since every colour is now chosen per mode.
- Review 2 found 1 × P2: the bubble text in dark mode was a hair off. Fixed with a dark override.
- No other hard-coded dark-only text remains in the panel.

**Not tested in a browser.** Mike checks it on the next deploy.
