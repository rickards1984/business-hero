"""
Twilio webhook security: X-Twilio-Signature validation + media-stream tokens.

Twilio signs every webhook it sends with HMAC-SHA1 over the EXACT public URL
plus the POST params, using the account's auth token as the key. Behind
Railway's proxy the app sees an internal URL, so the public URL must be
reconstructed before validating — see get_public_url().

Env vars:
  TWILIO_AUTH_TOKEN            already required for sending; also the
                               validation/signing secret here.
  TWILIO_SIGNATURE_VALIDATION  kill switch. Default "on". Set to "off" in
                               Railway to bypass ALL checks in this module
                               (signature + stream token) without a rollback.
  PUBLIC_BASE_URL              optional, e.g. https://api.example.com — when
                               set, used verbatim for signature URLs instead
                               of reconstructing from proxy headers.

Twilio does NOT sign WebSocket handshakes, so the media-stream endpoint is
protected differently: /incoming-call (itself signature-validated) mints a
short-lived single-purpose token bound to the CallSid, carried in the wss://
URL. See make_stream_token / verify_stream_token.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Mapping, Optional

from fastapi import HTTPException, Request, WebSocket
from twilio.request_validator import RequestValidator

logger = logging.getLogger("twilio_security")

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Media-stream tokens are single-purpose (one CallSid) and short-lived.
STREAM_TOKEN_TTL_SECONDS = int(os.getenv("TWILIO_STREAM_TOKEN_TTL", "300"))  # 5 min


def _validation_enabled() -> bool:
    """Kill switch: TWILIO_SIGNATURE_VALIDATION=off disables this module."""
    return os.getenv("TWILIO_SIGNATURE_VALIDATION", "on").strip().lower() not in (
        "off", "false", "0", "disabled",
    )


def _source_ip(request_or_ws) -> str:
    """Best-effort caller IP for log lines (first X-Forwarded-For hop)."""
    fwd = request_or_ws.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    client = getattr(request_or_ws, "client", None)
    return client.host if client else "unknown"


def get_public_url(request: Request) -> str:
    """
    Reconstruct the public URL Twilio signed.

    Priority:
      1. PUBLIC_BASE_URL env var (deterministic, recommended in production).
      2. X-Forwarded-Proto / X-Forwarded-Host headers (set by Railway's proxy).
      3. The request URL as seen by the app (correct in local dev).
    Query string is preserved — Twilio includes it in the signature.
    """
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""

    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}{path}{query}"

    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}{path}{query}"


async def require_valid_twilio_signature(
    request: Request, form: Mapping[str, str]
) -> None:
    """
    Reject the request with 403 unless it carries a valid X-Twilio-Signature.

    Call AFTER reading the form body (the signature covers the POST params).
    Never raises anything but HTTPException(403); config problems are logged
    CRITICAL and also rejected (fail closed — the kill switch is the escape
    hatch, not silent passthrough).
    """
    if not _validation_enabled():
        logger.warning(
            "[TwilioSecurity] SIGNATURE VALIDATION IS DISABLED via "
            "TWILIO_SIGNATURE_VALIDATION — request from %s allowed unchecked",
            _source_ip(request),
        )
        return

    if not TWILIO_AUTH_TOKEN:
        logger.critical(
            "[TwilioSecurity] TWILIO_AUTH_TOKEN is not set — cannot validate "
            "webhook signatures. Rejecting request from %s. Set the token or "
            "set TWILIO_SIGNATURE_VALIDATION=off to bypass temporarily.",
            _source_ip(request),
        )
        raise HTTPException(status_code=403, detail="Signature validation unavailable")

    signature = request.headers.get("x-twilio-signature", "")
    url = get_public_url(request)
    validator = RequestValidator(TWILIO_AUTH_TOKEN)

    if not signature or not validator.validate(url, dict(form), signature):
        logger.warning(
            "[TwilioSecurity] REJECTED webhook: invalid or missing "
            "X-Twilio-Signature (source_ip=%s, url=%s, signature_present=%s)",
            _source_ip(request), url, bool(signature),
        )
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


# ---------------------------------------------------------------------------
# Media-stream tokens (Twilio cannot sign WebSocket handshakes)
# ---------------------------------------------------------------------------

def _stream_token_digest(call_sid: str, expires_at: int) -> str:
    payload = f"{call_sid}.{expires_at}".encode()
    return hmac.new(TWILIO_AUTH_TOKEN.encode(), payload, hashlib.sha256).hexdigest()


def make_stream_token(call_sid: str) -> str:
    """Mint a single-purpose token: valid only for this CallSid, for a few minutes."""
    expires_at = int(time.time()) + STREAM_TOKEN_TTL_SECONDS
    return f"{call_sid}.{expires_at}.{_stream_token_digest(call_sid, expires_at)}"


def verify_stream_token(token: Optional[str], call_sid: str, ws: WebSocket) -> bool:
    """
    Verify a media-stream token against the CallSid Twilio reported in the
    'start' event. Returns True if the stream may proceed. Logs every
    rejection with the source IP. Respects the kill switch.
    """
    if not _validation_enabled():
        logger.warning(
            "[TwilioSecurity] STREAM TOKEN VALIDATION DISABLED via "
            "TWILIO_SIGNATURE_VALIDATION — stream from %s allowed unchecked",
            _source_ip(ws),
        )
        return True

    if not token:
        logger.warning(
            "[TwilioSecurity] REJECTED media-stream: no token (source_ip=%s, call_sid=%s)",
            _source_ip(ws), call_sid,
        )
        return False

    parts = token.rsplit(".", 2)
    if len(parts) != 3:
        logger.warning(
            "[TwilioSecurity] REJECTED media-stream: malformed token (source_ip=%s)",
            _source_ip(ws),
        )
        return False

    token_call_sid, expires_str, digest = parts
    try:
        expires_at = int(expires_str)
    except ValueError:
        logger.warning(
            "[TwilioSecurity] REJECTED media-stream: bad expiry in token (source_ip=%s)",
            _source_ip(ws),
        )
        return False

    if time.time() > expires_at:
        logger.warning(
            "[TwilioSecurity] REJECTED media-stream: token expired (source_ip=%s, call_sid=%s)",
            _source_ip(ws), call_sid,
        )
        return False

    if not hmac.compare_digest(digest, _stream_token_digest(token_call_sid, expires_at)):
        logger.warning(
            "[TwilioSecurity] REJECTED media-stream: bad token signature (source_ip=%s)",
            _source_ip(ws),
        )
        return False

    if token_call_sid != call_sid:
        logger.warning(
            "[TwilioSecurity] REJECTED media-stream: token CallSid mismatch "
            "(source_ip=%s, token_sid=%s, reported_sid=%s)",
            _source_ip(ws), token_call_sid, call_sid,
        )
        return False

    return True
