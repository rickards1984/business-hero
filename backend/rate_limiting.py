"""
Rate limiting for cost-attack and abuse-prone endpoints (slowapi).

Buckets are keyed per-user where a JWT is present, per-IP otherwise. The JWT
payload is decoded WITHOUT signature verification here — that is deliberate
and safe for this purpose only: the key just selects which counter to
increment; real authentication still happens in every route's auth
dependency. A forged `sub` moves an attacker to a different bucket, nothing
more, and requests with no JWT at all share the caller's IP bucket.

Storage is in-memory per process (fine for the current single-worker deploy;
counters reset on redeploy). Set RATE_LIMIT_STORAGE_URI=redis://... later to
make limits global across workers with no code change.

Limit classes (per the approved table — see audits/SESSION-2-CHANGES.md):
  AI chat   20/minute          assistant chat, support chat, meeting messages
  AI heavy  6/minute;60/hour   quote AI gen, email AI, meeting prep/start
  TTS       10/minute          /v1/tts, receptionist voice previews
  Sync      10/minute          email/xero/calendar sync triggers
  Webhook   60/minute per IP   unauthenticated Twilio webhooks
"""
from __future__ import annotations

import base64
import json
import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger("rate_limiting")

# Public limit strings, imported by the route modules so the policy lives here.
LIMIT_AI_CHAT = "20/minute"
LIMIT_AI_HEAVY = "6/minute;60/hour"
LIMIT_TTS = "10/minute"
LIMIT_SYNC = "10/minute"
LIMIT_WEBHOOK_IP = "60/minute"

RATE_LIMIT_MESSAGE = (
    "Rate limit exceeded for this action — please wait a minute and try again."
)


def _client_ip(request) -> str:
    """First X-Forwarded-For hop (Railway proxy), else the socket address."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


def user_or_ip_key(request) -> str:
    """
    Bucket key: JWT `sub` claim when a Bearer token is present (decoded
    without verification — see module docstring), else client IP.
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        parts = token.split(".")
        if len(parts) == 3:
            try:
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass  # malformed token -> fall through to IP bucket
    return f"ip:{_client_ip(request)}"


def ip_key(request) -> str:
    """Bucket key for unauthenticated endpoints (webhooks): always the IP."""
    return f"ip:{_client_ip(request)}"


# headers_enabled must stay False: slowapi's header injection requires every
# decorated endpoint to return a starlette Response object, but ours return
# dicts/pydantic models — with it on, every limited endpoint 500s on its
# FIRST request (caught in local testing). The 429 handler in main.py sets
# Retry-After manually instead.
limiter = Limiter(
    key_func=user_or_ip_key,
    storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"),
    headers_enabled=False,
)
