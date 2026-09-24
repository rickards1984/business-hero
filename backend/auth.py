"""Authentication dependencies for FastAPI."""

import os
from typing import Any, Optional, Dict
from datetime import datetime, timezone
from fastapi import Header, HTTPException, Depends, Request, Query, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select
from sqlalchemy import text
from db import get_session
from models import Business
from supabase_auth import verify_supabase_token
from assistant_chat import get_business_for_user

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
master_key_header = APIKeyHeader(name="x-master-key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)
supabase_bearer = HTTPBearer(auto_error=False, description="Supabase access token for AI Assistant endpoints")


def extract_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract token from Authorization header.
    
    Handles both 'Bearer <token>' and plain '<token>' formats.
    """
    if not auth_header:
        return None
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return auth_header


def get_master_key() -> str:
    """Get the master admin key from environment."""
    key = os.getenv("MASTER_ADMIN_KEY")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MASTER_ADMIN_KEY not configured"
        )
    return key


async def verify_master_key(
    x_master_key: Optional[str] = Depends(master_key_header),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(bearer_auth),
    auth_header: Optional[str] = Header(None, alias="Authorization")
) -> bool:
    """Verify the master admin key.
    
    Accepts either:
    - x-master-key header
    - Authorization: Bearer <MASTER_ADMIN_KEY>
    - Authorization: <MASTER_ADMIN_KEY>
    """
    token = None
    
    if x_master_key:
        token = x_master_key
    elif authorization:
        token = authorization.credentials
    elif auth_header:
        token = extract_token(auth_header)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Use x-master-key header or Authorization: Bearer <key>"
        )
    
    master_key = get_master_key()
    if token != master_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid master key"
        )
    return True


async def get_access_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(supabase_bearer),
    access_token: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
) -> str:
    """Extract and return the Supabase access token from Authorization header.
    
    Used for AI Assistant endpoints that require Supabase JWT authentication.
    Raises 401 if no token is provided.
    """
    if credentials:
        return credentials.credentials
    if access_token:
        return access_token
    if token:
        return token
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header or access_token query param"
        )
    return credentials.credentials


async def get_user_auth_context(
    request: Request,
    token: str = Depends(get_access_token),
    session: Session = Depends(get_session),
) -> dict:
    """Authenticate Supabase user and return basic identity + admin flag."""
    user = await verify_supabase_token(token)
    request.state.user_email = user.email
    return {
        "user_id": user.id,
        "email": user.email,
        "is_platform_admin": is_platform_admin_user(user.id, session),
        "access_token": token,
    }


# Write-shaped requests a READ-ONLY business must still be allowed to make.
# Matched against the request path; each one is here for a stated reason.
#
# DECISION 3 promises a read-only customer can still export, and that they can
# pay to restore. Both of those are POSTs, so a blanket "refuse every
# POST/PUT/PATCH/DELETE" would break the two things the decision exists to
# protect. Nothing else belongs in this list: it is the difference between
# "read-only" and "locked out".
READ_ONLY_ALLOWED_PATH_PREFIXES = (
    "/v1/billing/checkout-session",  # pay to restore full access
    "/v1/billing/portal",            # Stripe customer portal — update the card
)
# Exports. Suffix-matched because the quote id sits in the middle of the path.
READ_ONLY_ALLOWED_PATH_SUFFIXES = (
    "/generate-pdf",                 # POST /v1/quotes/{id}/generate-pdf
)
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _is_read_only_allowed_request(request: Optional[Request]) -> bool:
    """True when this request is one a read-only business may still make."""
    if request is None:
        # No request object means the dependency was called directly, which
        # only happens in tests. Fail CLOSED: a caller that cannot say what it
        # is asking for does not get the exemption.
        return False
    if request.method.upper() not in _MUTATING_METHODS:
        return True
    path = request.url.path
    if path.startswith(READ_ONLY_ALLOWED_PATH_PREFIXES):
        return True
    return path.endswith(READ_ONLY_ALLOWED_PATH_SUFFIXES)


def enforce_read_only(request: Optional[Request], business: Optional[Business]) -> None:
    """Refuse a mutating request from a read-only business. Server-side.

    DECISION 3: "enforced server-side, per PART D. Hiding the buttons is not
    enforcement." This sits in the two shared context dependencies that every
    authenticated endpoint resolves, so a new endpoint is covered the day it
    is written rather than when someone remembers to add a decorator. It keys
    on the HTTP METHOD, which is why it cannot be forgotten: a create or an
    edit is a POST/PUT/PATCH/DELETE by definition, and the exceptions are the
    short, stated list above.
    """
    if business is None or not is_read_only(business):
        return
    if _is_read_only_allowed_request(request):
        return
    raise HTTPException(status_code=403, detail=READ_ONLY_DETAIL)


def _load_business(session: Session, business_id) -> Optional[Business]:
    if not business_id:
        return None
    return session.exec(select(Business).where(Business.id == business_id)).first()


async def get_user_business_context(
    request: Request,
    token: str = Depends(get_access_token),
    business_id: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """Return user_id and business_id from a Supabase JWT.

    If business_id is provided, verify user membership for that business.

    Also enforces DECISION 3's read-only state: a business whose
    `subscription_status` is `unpaid` or `canceled` is refused every mutating
    request here, except the exports and billing paths named above. Platform
    admins are exempt — they are how a read-only account gets fixed.
    """
    user = await verify_supabase_token(token)
    is_platform_admin = is_platform_admin_user(user.id, session)
    if is_platform_admin:
        request.state.user_email = user.email
        if business_id:
            return {
                "user_id": user.id,
                "business_id": business_id,
                "is_platform_admin": True,
            }
        try:
            business_ctx = get_business_for_user(user.id)
        except ValueError as exc:
            args = exc.args
            if len(args) >= 2 and args[0] == "NO_BUSINESS":
                return {
                    "user_id": user.id,
                    "business_id": None,
                    "is_platform_admin": True,
                }
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return {
            "user_id": user.id,
            "business_id": business_ctx.id,
            "is_platform_admin": True,
        }
    try:
        business_ctx = get_business_for_user(user.id, requested_business_id=business_id)
    except ValueError as exc:
        args = exc.args
        if len(args) >= 2:
            error_type, message = args[0], args[1]
            if error_type == "NO_BUSINESS":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            if error_type == "FORBIDDEN":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            if error_type == "NOT_FOUND":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    request.state.user_email = user.email
    enforce_read_only(request, _load_business(session, business_ctx.id))
    return {"user_id": user.id, "business_id": business_ctx.id, "is_platform_admin": False}


async def get_user_context_no_business(
    request: Request,
    token: str = Depends(get_access_token),
) -> dict:
    """Return user context without enforcing business membership."""
    user = await verify_supabase_token(token)
    request.state.user_email = user.email
    return {"user_id": user.id, "email": user.email, "access_token": token}


async def get_platform_admin_context(
    user_ctx: dict = Depends(get_user_context_no_business),
    session: Session = Depends(get_session),
) -> dict:
    if not is_platform_admin_user(user_ctx["user_id"], session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform admin required")
    return user_ctx


async def get_current_business(
    x_api_key: Optional[str] = Depends(api_key_header),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(bearer_auth),
    auth_header: Optional[str] = Header(None, alias="Authorization"),
    session: Session = Depends(get_session)
) -> Business:
    """Get the current business from API key.
    
    Accepts either:
    - x-api-key header
    - Authorization: Bearer <business_api_key>
    - Authorization: <business_api_key>
    """
    token = None
    
    if x_api_key:
        token = x_api_key
    elif authorization:
        token = authorization.credentials
    elif auth_header:
        token = extract_token(auth_header)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Use x-api-key header or Authorization: Bearer <key>"
        )
    
    statement = select(Business).where(Business.api_key == token)
    business = session.exec(statement).first()
    
    if not business:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return business


def is_platform_admin_user(user_id: str, session: Session) -> bool:
    result = session.execute(
        text("SELECT 1 FROM platform_admins WHERE user_id = :user_id LIMIT 1"),
        {"user_id": user_id},
    ).first()
    return result is not None


def _is_trial_expired(trial_ends_at: Optional[datetime]) -> bool:
    if not trial_ends_at:
        return True
    if trial_ends_at.tzinfo is None:
        return trial_ends_at < datetime.utcnow()
    return trial_ends_at < datetime.now(timezone.utc)


# ── ENTITLEMENT-SPEC DECISION 3 — subscription_status -> access level ────────
#
# THE ONE RESOLVER. DECISION 3 separates two columns this codebase had
# conflated, and the separation is the whole point:
#
#   plan_tier            what was purchased.  NEVER written by a payment event.
#   subscription_status  whether it is paid for. Stripe's field, verbatim.
#   is_active            the ADMIN's manual switch. Not Stripe's.
#
# Access follows `subscription_status`, never `plan_tier`:
#
#   active, trialing  -> FULL access to everything plan_tier includes
#   past_due          -> FULL access, plus a user-visible warning. Stripe is
#                        still retrying; the customer has usually done nothing
#                        wrong, and a card that expired on Tuesday must not
#                        take the receptionist off the phones on Wednesday.
#   unpaid, canceled  -> READ-ONLY. NOT a downgrade to starter: plan_tier
#                        still records what they bought, so paying restores
#                        exactly what they had, with no re-entry.
#
# READ-ONLY means, precisely (DECISION 3; export scope decided 8 Sep 2026):
#   CAN     log in; view quotes, invoices and accounting; export quotes and
#           invoices as PDF/CSV; reach billing to pay and restore.
#   CANNOT  create or edit anything; use any AI feature; send anything
#           outbound; keep a Twilio number (release is its own ticket).
#
# Why read-only and not lockout: UK VAT records must be kept six years (HMRC
# VAT Notice 700/21) and GDPR Art. 20 portability does not lapse with payment,
# so a customer's own invoices must stay reachable. A read-only account makes
# no LLM calls, no voice minutes and no outbound sends — it costs storage.

ACCESS_FULL = "full"
ACCESS_READ_ONLY = "read_only"
ACCESS_SUSPENDED = "suspended"

FULL_ACCESS_STATUSES = frozenset({"active", "trialing", "past_due"})
READ_ONLY_STATUSES = frozenset({"unpaid", "canceled"})
# Keeps full access, but the customer must be told. A banner, not a silent
# flag: surfaced by GET /v1/billing/status.
WARNING_STATUSES = frozenset({"past_due"})

# Stripe also sends `incomplete` and `incomplete_expired`: a subscription
# whose FIRST payment never completed. Such a customer never had paid access
# to lose, so those are deliberately in neither set — they fall through to the
# trial and admin checks, which is where a never-paid account belongs.


def resolve_access_level(business: Optional[Business]) -> str:
    """`subscription_status` -> access level. The only place this is decided.

    Precedence, and why:

    1. **Admin suspension wins.** `is_active = False` is a human decision
       about this business and a paid subscription must not overrule it.
       (It does not override READ-ONLY, which is already the narrower state.)
    2. Then `subscription_status` — Stripe's account of whether it is paid.
    3. Only when Stripe has said nothing at all (no subscription: a business
       the admin created, or one still in trial) does the trial window decide.

    Fails closed: an unrecognised status falls to the trial/admin path rather
    than being treated as paid.
    """
    if business is None:
        return ACCESS_SUSPENDED

    status_value = (business.subscription_status or "").strip().lower()

    if status_value in READ_ONLY_STATUSES:
        return ACCESS_READ_ONLY

    # The admin switch. Kept ABSOLUTE deliberately: the old webhook wrote this
    # column from the Stripe status, so rows written before BH-006 are
    # ambiguous. They are repaired by runbook (audits/BH-006-PROD-RUNBOOK.md),
    # not by guessing here — a guess would silently un-suspend a business an
    # admin had switched off on purpose.
    if not business.is_active:
        if _is_trial_expired(business.trial_ends_at):
            return ACCESS_SUSPENDED
        return ACCESS_FULL

    if status_value in FULL_ACCESS_STATUSES:
        return ACCESS_FULL

    if _is_trial_expired(business.trial_ends_at):
        return ACCESS_SUSPENDED
    return ACCESS_FULL


def is_read_only(business: Optional[Business]) -> bool:
    return resolve_access_level(business) == ACCESS_READ_ONLY


def needs_payment_warning(business: Optional[Business]) -> bool:
    """True when the customer keeps full access but must be told to pay."""
    if business is None:
        return False
    return (business.subscription_status or "").strip().lower() in WARNING_STATUSES


# ── ENTITLEMENT-SPEC PART B — the canonical plan -> feature table ────────────
#
# THE ONLY COPY IN PYTHON. `main.py` imports this; it used to declare its own
# identical-but-separate dict, which is how the vocabularies drifted.
#
# Two further copies exist and cannot be deduplicated away:
#   * frontend/client/src/lib/entitlements.ts  (PLAN_FEATURE_DEFAULTS)
#   * backend/migrations/033_entitlement.sql   (the plan_defaults CTE, S7)
# All three must agree. backend/tests/test_entitlement_defaults.py PARSES the
# other two and compares against this one, so drift fails the build instead of
# quietly removing someone's paid access.
#
# WHAT THIS REPLACED, and why it matters: the previous table gave `starter`
# nothing at all, `pro` only {"email": True}, and invented two keys — `calendar`
# and `voice` — that appear in no plan, no migration and no frontend list.
# 033 SECTION 7 strips flags that merely restate the plan default; run against
# that table it measured EIGHT feature losses across the two live businesses on
# staging. SECTION 7 is safe only once THIS table is the one deployed.

# `calendar_sync` is in the vocabulary but gates NOTHING today, deliberately.
# Google issues Gmail and Calendar under ONE consent, so a business that has
# connected email has already granted calendar access — there is no separate
# state to check and no request to refuse. It is named here so the concept has
# a word and cannot be lost, and it is TRUE on every tier because it rides on
# `email`, which is also true on every tier. Making it a real gate would mean
# splitting the OAuth grant into two scopes and two consent screens first; the
# flag is not the missing piece, the grant is.
CANONICAL_FEATURES = (
    "quoting", "invoicing", "accounting", "email", "aria_chat", "aria_voice",
    "whatsapp", "board_meetings", "calendar_booking", "calendar_sync",
    "receptionist", "outreach",
)

# Every tier names every feature explicitly. A missing key would resolve to
# False by omission — a denial nobody wrote down.
PLAN_FEATURE_DEFAULTS: Dict[str, Dict[str, bool]] = {
    "starter": {
        "quoting": True, "invoicing": True, "accounting": True, "email": True,
        "aria_chat": True, "aria_voice": False, "whatsapp": False,
        "board_meetings": False, "calendar_booking": False,
        "calendar_sync": True,
        "receptionist": False, "outreach": False,
    },
    "pro": {
        "quoting": True, "invoicing": True, "accounting": True, "email": True,
        "aria_chat": True, "aria_voice": True, "whatsapp": True,
        "board_meetings": True, "calendar_booking": True,
        "calendar_sync": True,
        "receptionist": True, "outreach": False,
    },
    "business": {
        "quoting": True, "invoicing": True, "accounting": True, "email": True,
        "aria_chat": True, "aria_voice": True, "whatsapp": True,
        "board_meetings": True, "calendar_booking": True,
        "calendar_sync": True,
        "receptionist": True, "outreach": True,
    },
    # `beta` mirrors `business` for testing parity.
    "beta": {
        "quoting": True, "invoicing": True, "accounting": True, "email": True,
        "aria_chat": True, "aria_voice": True, "whatsapp": True,
        "board_meetings": True, "calendar_booking": True,
        "calendar_sync": True,
        "receptionist": True, "outreach": True,
    },
}


def _plan_feature_defaults(plan_tier: Optional[str]) -> Dict[str, bool]:
    """The plan's own grants. Fails closed to `starter`, the least-privileged.

    `paused` is deliberately not a tier (DECISION 3; 033 SECTION 1's CHECK
    dropped it), so it lands on the starter fallback like any other unknown
    value. Returns a copy — callers have handed this straight into dict
    merges before, and a mutation would repartition every business on the
    process.
    """
    key = (plan_tier or "starter").lower()
    return dict(PLAN_FEATURE_DEFAULTS.get(key, PLAN_FEATURE_DEFAULTS["starter"]))


def strip_plan_defaults(
    flags: Optional[Dict[str, Any]], plan_tier: Optional[str]
) -> Dict[str, Any]:
    """Reduce `feature_flags` to genuine per-business exceptions.

    PART C: `plan_tier` is the source of truth and `feature_flags` holds ONLY
    deliberate exceptions — a beta grant, a goodwill grant, a feature switched
    off for one customer. Empty is the normal state. A default written back
    into the column pins access that no plan change can then remove.

    A key is dropped ONLY when it is in the canonical vocabulary AND holds a
    boolean AND that boolean EQUALS this tier's default. Everything else
    survives:
      * an unknown key — this code cannot know what it means to someone
      * a non-boolean (`brand_color`, the wizard's `industry`)
      * a boolean that CONTRADICTS its default, in either direction. An
        explicit `false` against a granting plan is a deliberate denial.

    This is the same rule as `setFeatureFlag` in entitlements.ts and as the
    `redundant` CTE in 033 SECTION 7.
    """
    defaults = PLAN_FEATURE_DEFAULTS.get(
        (plan_tier or "starter").lower(), PLAN_FEATURE_DEFAULTS["starter"]
    )
    return {
        key: value
        for key, value in (flags or {}).items()
        if not (isinstance(value, bool) and defaults.get(key) is value)
    }


def _is_feature_enabled(business: Business, feature_name: str) -> bool:
    flags = business.feature_flags or {}
    if feature_name in flags:
        return bool(flags.get(feature_name))
    plan_defaults = _plan_feature_defaults(business.plan_tier)
    return bool(plan_defaults.get(feature_name, False))


# Features a read-only business may still use. DECISION 3 permits viewing and
# exporting quotes, invoices and accounting; those reads are gated by the
# feature that owns them, so the feature gate must let them through. What it
# must NOT let through is any AI feature or outbound send — those are the
# read-only refusals, and they are named here rather than inferred.
READ_ONLY_PERMITTED_FEATURES = frozenset({
    "quoting",      # viewing and exporting quotes
    "invoicing",    # viewing and exporting invoices
    "accounting",   # viewing accounting history (export of it is excluded by
                    # the 8 Sep 2026 decision, which is about the export
                    # endpoint's scope, not about read access)
})

# Every feature that costs money to serve or reaches a third party. A
# read-only business is refused these outright. Listed explicitly so adding a
# feature to PLAN_FEATURE_DEFAULTS cannot quietly become free-for-nonpayers.
READ_ONLY_REFUSED_FEATURES = frozenset({
    "email", "aria_chat", "aria_voice", "whatsapp", "board_meetings",
    "calendar_booking", "calendar_sync", "receptionist", "outreach",
})

READ_ONLY_DETAIL = (
    "Your subscription is not active, so this account is read-only. You can "
    "still view and export your quotes and invoices. Update your payment "
    "details in Billing to restore full access."
)


def require_feature(feature_name: str):
    async def _dependency(
        auth_ctx: dict = Depends(get_user_business_context),
        session: Session = Depends(get_session),
    ):
        if is_platform_admin_user(auth_ctx["user_id"], session):
            return True
        business = session.exec(
            select(Business).where(Business.id == auth_ctx["business_id"])
        ).first()
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")

        # DECISION 3 / BH-006 defect 5. This used to read `is_active` alone,
        # and the webhook wrote `is_active = status in ('active','trialing')`
        # — so a `past_due` card set it False and `_is_trial_expired()`
        # returns True for every customer who never had a trial
        # (trial_ends_at IS NULL). A customer mid-dunning lost feature access
        # on the next request. The resolver decides now, and past_due is FULL.
        access = resolve_access_level(business)
        if access == ACCESS_SUSPENDED:
            raise HTTPException(
                status_code=403,
                detail="Account inactive or trial expired"
            )
        if access == ACCESS_READ_ONLY and feature_name not in READ_ONLY_PERMITTED_FEATURES:
            raise HTTPException(status_code=403, detail=READ_ONLY_DETAIL)

        if not _is_feature_enabled(business, feature_name):
            raise HTTPException(
                status_code=403,
                detail=f"Feature '{feature_name}' not enabled for your plan"
            )
        return True

    return _dependency
