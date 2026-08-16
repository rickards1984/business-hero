# CLAUDE.md — Business Hero working agreement

This file is read automatically by Claude Code at the start of every session.
It sets the rules of engagement for this repository.

## Context
- This is `business-hero-2`: a B2B SaaS monorepo.
- Backend: FastAPI / Python on Railway.
- Frontend: React / TypeScript on Vercel (in this same repo).
- Database: Supabase (PostgreSQL), accessed via SQLAlchemy/SQLModel and raw Supabase REST.
- External APIs: Xero (accounting), Gmail (email), OpenAI (Aria/insights), Twilio (WhatsApp/SMS), Google Calendar.
- We are pre-launch, preparing to onboard the first paying customers. Stability and performance are the priority over new features.

## How we work (IMPORTANT — follow exactly)
1. **Audit before editing.** When asked to investigate, REPORT FINDINGS FIRST with file:line references. Do not edit code in the same step as investigating unless explicitly told "fix it now".
2. **One change at a time, approval required.** Before editing any file, show the proposed diff and WAIT for explicit approval ("yes", "go", "approved"). Never batch-edit multiple files without showing each.
3. **Make ONLY the change requested.** Do not refactor adjacent code, rename things, reformat, add comments, or "improve" things that weren't asked for, even if they look improvable. Note such things separately as suggestions instead.
4. **If a referenced file/function/line does not exist or does not match the description, STOP and report it. Do not guess.**
5. **After any edit:** summarise exactly what changed with file:line references, and confirm the file still parses / type-checks.
6. **Never commit or push** unless explicitly told to. Leave that to the human.
7. **Do not touch** `.env`, secrets, API keys, or Railway/Vercel/Supabase config without explicit instruction.
8. **Preserve the canonical patterns:**
   - The single SQLAlchemy engine lives in `backend/db.py` (`engine`). Do not create new engines.
   - Sessions: HTTP routes use `Depends(get_session)`; background/webhook code uses `get_session_context()` (reads) or `get_session_transactional()` (writes — commits on clean exit, rolls back + logs on exception). Do not introduce new session patterns.

## Known production findings (from log analysis, May 2026)
- **Gmail N+1:** email sync fetches ~50 messages one-at-a-time per run. Suspected to also affect the comms tab load. Gmail supports batch fetching — candidate fix.
- **OpenAI 429:** account hit quota; daily pulse + weekly briefing failed to generate on 2026-05-29. Billing/limit issue, not code — but insight generation should fail gracefully and never block a page load.
- **Twilio 400 "Content Variables parameter is invalid":** recurring near midnight. Template variable bug, possibly a regression of a previously-fixed issue.

## Migration policy
- All new database migrations go in `supabase/migrations/`, numbered 028 onward.
- Never edit existing migration files. Do NOT touch `backend/migrations/` (historical 001–011, kept for record only).

## Current task
Security remediation — fixing critical RLS holes found in the 4 July audit. Working through Session 1: schema drift capture, then the two broken policies (xero_connections, accounting_connections), then the ~30-table RLS batch. See audits/AUDIT-2026-07-04.md.
