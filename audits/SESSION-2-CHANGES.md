# Session 2 — Perimeter Hardening (2026-07-06)

Branch: `security-perimeter-session-2`. Not merged, not deployed — manual review required.
Scope per session brief: Twilio signature validation, rate limiting, OpenAI client hardening.

---

## 1. Files changed and why

### New files
| File | Purpose |
|---|---|
| `backend/twilio_security.py` | X-Twilio-Signature validation (`RequestValidator`), public-URL reconstruction behind Railway's proxy, kill switch, and HMAC-SHA256 media-stream tokens (5-min TTL, single-CallSid). All rejections log source IP. Missing auth token fails CLOSED (403 + CRITICAL log). |
| `backend/rate_limiting.py` | slowapi limiter + key functions. Buckets per-user (JWT `sub`, decoded unverified — key selection only, auth still enforced by route deps) with IP fallback; webhooks always per-IP. Limit policy constants live here. |

### Security changes
| File | Change |
|---|---|
| `backend/whatsapp_briefing_api.py` | `/v1/whatsapp/webhook`: signature validation before any processing (placed before the handler's broad `try` so the 403 cannot be swallowed); 60/min per-IP rate limit. |
| `backend/receptionist_call_handler.py` | `/incoming-call`: signature validation; 60/min per-IP limit; TwiML stream URL now carries the short-lived token (redacted in logs). `/media-stream`: closes (code 1008) unless token is valid, unexpired, and matches the CallSid from Twilio's `start` event — also closes the pre-existing hole where anyone could connect and claim any `business_id`. |
| `backend/receptionist_api.py` | `GET /voices/{id}/preview` + `POST /voice-preview`: now require JWT (`get_current_user_business`, same as sibling routes) — they spend OpenAI credit and were previously public. Verified all frontend callers already send the JWT. 10/min TTS limit. |
| `backend/main.py` | Limiter wired to app + 429 handler (JSON message + `Retry-After: 60`). Limits: assistant chat 20/min; TTS 10/min; xero/invoice/sync-all + admin email/calendar sync 10/min. |
| `backend/support_api.py` | `/v1/support/chat` 20/min. |
| `backend/executive_meeting_api.py` | `{id}/message` 20/min; `prep-now`, `start-now`, `{id}/start`, `{id}/extract-actions` 6/min + 60/hour. |
| `backend/quoting_api.py` | `/ai/generate` 6/min + 60/hour. |
| `backend/app/email/router.py` | `briefings/generate`, `analyze`, `drafts/generate`, `drafts/generate-options` 6/min + 60/hour; `sync/run`, `sync/inbox`, `sync/ensure` 10/min. |
| `backend/requirements.txt`, `backend/pyproject.toml` | + `slowapi>=0.1.9`. |

Rate-limited endpoints gained a `request: Request` parameter where missing (slowapi requirement, no behaviour change).

### OpenAI client hardening (timeout=30.0, max_retries=1 — the proven email-subsystem pattern)
11 sites: `openai_utils.py:26`, `support_api.py` (×2), `main.py` (tts), `assistant_chat.py`, `assistant_tools.py`, `receptionist_api.py` (×2 preview TTS), `services/briefing_generator.py` (×2), `services/executive_meeting_orchestrator.py`.
Watch after deploy: executive meetings and weekly briefings generate long outputs — if Railway logs show timeout errors there, raise that client's timeout rather than reverting the pattern.

### Config-only changes (no behaviour change until env vars set)
| File | Change |
|---|---|
| `backend/realtime_voice.py` | `ARIA_REALTIME_MODEL` (default `gpt-realtime`), `ARIA_REALTIME_VOICE` (default `shimmer`). |
| `backend/quoting_api.py` | `QUOTE_AI_MODEL` (default `gpt-5.4`) replaces the hardcoded model at both sites (request + `ai_model` audit field). |

---

## 2. Env vars to set in Railway BEFORE merging

| Variable | Required? | Value |
|---|---|---|
| `PUBLIC_BASE_URL` | **Yes (recommended)** | Scheme + host only, no trailing slash, no path. It must be the EXACT origin Twilio's webhook URLs point at — check Twilio Console → Phone Numbers → your number → webhook URL, and use its origin. E.g. `https://your-app.up.railway.app` or `https://api.yourdomain.co.uk`. Without it, validation falls back to X-Forwarded headers (works on Railway, but the explicit var is belt-and-braces). |
| `TWILIO_AUTH_TOKEN` | Already set | Confirm it exists (Railway → Variables). It now also powers signature validation and stream-token signing. |
| `TWILIO_SIGNATURE_VALIDATION` | No | Leave unset (default on). **Emergency kill switch: set to `off`** if legitimate Twilio traffic gets 403s post-deploy — no rollback needed. |
| `TWILIO_STREAM_TOKEN_TTL` | No | Default 300 seconds. |
| `RATE_LIMIT_STORAGE_URI` | No | Default in-memory. Set `redis://...` later if the app moves to multiple workers. |
| `ARIA_REALTIME_MODEL` / `ARIA_REALTIME_VOICE` / `QUOTE_AI_MODEL` | No | Defaults preserve current behaviour exactly. |

---

## 3. Post-deploy live test checklist (MANDATORY before calling it done)

1. **(a) Real WhatsApp message:** send a message to the business WhatsApp number. Expect: normal processing/reply. Railway logs must NOT show `[TwilioSecurity] REJECTED`. If every message is rejected, the URL reconstruction is wrong → set/fix `PUBLIC_BASE_URL` (or set `TWILIO_SIGNATURE_VALIDATION=off` and report back).
2. **(b) Real receptionist call:** phone the receptionist number. Expect: AI answers and holds a conversation (proves signature validation AND the media-stream token round-trip). Logs show the redacted stream URL and no token rejections.
3. **(c) Forged-webhook rejection:**
   `curl -i -X POST https://<PUBLIC_BASE_URL>/v1/whatsapp/webhook -d "From=whatsapp:+447700900000&Body=test"` → expect **403**, and a `[TwilioSecurity] REJECTED webhook` log line with your IP.
   Same for `curl -i -X POST .../v1/receptionist/incoming-call -d "To=+441234567890"` → **403**.
4. **(d) Normal session under limits:** click through a normal session — dashboard, a few assistant chat messages, generate an email draft, run an email sync, preview a receptionist voice. Expect: zero 429s. (A 429 in normal use means a limit is mis-tuned — tell me which endpoint.)
5. **Voice preview auth:** logged out, `curl -i https://<PUBLIC_BASE_URL>/v1/receptionist/voices/alloy/preview` → expect **401/403** (was 200 + MP3 before).
6. **429 sanity (optional):** hammer one endpoint (e.g. paste 25 rapid messages into support chat) → expect 429 with the friendly message after ~20.

## 4. Deploy steps
1. Set env vars from §2 in Railway.
2. Merge `security-perimeter-session-2` → `main` (your manual step; Railway auto-deploys).
3. Watch Railway logs during the first minutes for `[TwilioSecurity]` lines.
4. Run checklist §3 immediately (a live call + WhatsApp message within minutes of deploy).

---

## 5. Verification performed locally (honest report)
- `py_compile`: all 16 changed files pass.
- Module imports: 15/16 changed modules import cleanly on local Python 3.9; `app.email.router` can't import locally due to **pre-existing** Python-3.10 syntax in `providers/google_gmail.py` (fine on Railway's 3.11). Full `main.py` import is impossible locally for the same pre-existing reason.
- Signature validation tested against the real `twilio` `RequestValidator` (genuine computed signatures): valid → allowed; forged/missing → 403.
- Stream tokens: 6/6 cases (valid / wrong-CallSid / malformed / tampered / missing / expired).
- Kill switch and `PUBLIC_BASE_URL` precedence: tested.
- Rate limiter exercised end-to-end via TestClient: per-user buckets isolate users; multi-window `6/minute;60/hour` enforces at the 7th call; IP buckets for webhooks; malformed JWT falls back to IP; 429 body + `Retry-After: 60`. **This testing caught and fixed a real bug**: slowapi `headers_enabled=True` 500s on endpoints returning dicts — now disabled with `Retry-After` set manually.
- Existing test suite: `test_microsoft_graph_mapping` passes (3/3). `test_feature_gating` fails 3/3 **on clean HEAD too** (stale `FakeSession` mock missing `.execute`, predates this session). `test_awaz_webhook_auth` can't even collect locally (same pre-existing 3.10-syntax import chain). No test regressions from this session.

## 6. Known gaps / later cleanup (not this session)
- **`/v1/realtime/voice` websocket has no rate/connection cap** (slowapi is HTTP-only). It is JWT-authenticated. Suggested future fix: a per-user concurrent-connection counter (in-process dict or Redis) capping at 1–2 simultaneous Realtime sessions, checked after the auth message.
- **UI relabel:** legacy voice list in `receptionist_api.py` shows "Neutral" accent labels; the effective default is British (`shimmer_british`). Relabel to "British (default)" for clarity — cosmetic.
- Rate limits are per-process (in-memory); multiply by worker count if workers ever increase, or set `RATE_LIMIT_STORAGE_URI`.
- Pre-existing: `tests/test_feature_gating.py` mock needs `.execute` support; `pip-audit`/CI dependency scanning still outstanding from the July audit.
