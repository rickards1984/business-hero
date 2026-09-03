"""
Admin business endpoints — 030b Part A.

Replaces four frontend sites that wrote `businesses` directly through
supabase-js, gated only by `biz_update_if_owner` — a column-blind RLS policy
behind a table-wide UPDATE grant. Any owner could set their own `plan_tier`,
`is_active` and `feature_flags` from the browser.

These endpoints are what makes revoking that grant possible. The revoke itself
is Release 2 (spec Part E) and is deliberately not in this module.

Every route is gated by `get_platform_admin_context`, which chains
`verify_supabase_token` then a `platform_admins` lookup. The admin surface
settles on this one scheme (Part C).
"""
import logging
import secrets
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Session

from auth import get_platform_admin_context, strip_plan_defaults
from db import get_session

# `business_id` is typed UUID on every route so a non-UUID path segment is
# rejected by FastAPI as a 422 before it reaches a query. That is defence in
# depth, not the fix for route shadowing — the fix is registration order, and
# it lives at the bottom of main.py.
logger = logging.getLogger("admin_business_api")
router = APIRouter(prefix="/v1/admin/businesses", tags=["Admin"])


# The canonical set — ENTITLEMENT-SPEC PART A, DECISION 1. `paused` was removed
# by DECISION 3; `elite` and `enterprise` were never storable.
CANONICAL_TIERS = ("starter", "pro", "business", "beta")

# The ten columns the admin detail page reads. `api_key` is deliberately absent:
# it is a credential, it is returned exactly once at creation, and no read
# endpoint may expose it.
ADMIN_COLUMNS = (
    "id", "name", "timezone", "plan_tier", "is_active", "trial_ends_at",
    "feature_flags", "limits", "subscription_status", "current_period_end",
)

OVERVIEW_FIELDS = ("plan_tier", "is_active", "trial_ends_at", "feature_flags", "limits")
CREATE_FIELDS = ("name", "timezone") + OVERVIEW_FIELDS

# RULING (030B-SPEC, 20 Aug 2026) — feature_flags option (a): structure-only
# validation, with `brand_color` permitted as a NAMED TEMPORARY EXCEPTION.
#
# Both real businesses hold a colour string here today, so a strict boolean
# validator would reject live data. When ENTITLEMENT-SPEC PART B moves it to
# its own column in 033, DELETE THIS CONSTANT and the branch that reads it —
# the validator then tightens with no other change.
_TEMPORARY_STRING_FLAGS = ("brand_color",)


def _bad_request(detail: str):
    return HTTPException(status_code=400, detail=detail)


def _validate_plan_tier(value: Any) -> str:
    """Reject an unrecognised tier. Never remap one.

    `backend/main.py` used to rewrite ("premium", "elite") to "business"
    silently, which meant a typo and a real tier were indistinguishable in the
    response. An unknown value is an error that names itself.
    """
    if not isinstance(value, str):
        raise _bad_request(
            f"plan_tier must be one of {', '.join(CANONICAL_TIERS)} — got {value!r}"
        )
    normalised = value.strip().lower()
    if normalised not in CANONICAL_TIERS:
        raise _bad_request(
            f"Unknown plan_tier {value!r}. Must be one of: {', '.join(CANONICAL_TIERS)}."
        )
    return normalised


def _validate_flat_object(value: Any, field: str) -> dict:
    """Shared floor for `feature_flags` and `limits`: a flat JSON object."""
    if not isinstance(value, dict):
        raise _bad_request(f"{field} must be a JSON object — got {type(value).__name__}")
    for key, item in value.items():
        if isinstance(item, (dict, list)):
            raise _bad_request(
                f"{field}.{key} must be a single value — nested objects and "
                f"arrays are not accepted"
            )
    return value


def _validate_feature_flags(value: Any) -> dict:
    flags = _validate_flat_object(value, "feature_flags")
    for key, item in flags.items():
        if key in _TEMPORARY_STRING_FLAGS:
            if not isinstance(item, str):
                raise _bad_request(f"feature_flags.{key} must be a string")
            continue
        if not isinstance(item, bool):
            raise _bad_request(
                f"feature_flags.{key} must be true or false — got "
                f"{type(item).__name__}. Only {', '.join(_TEMPORARY_STRING_FLAGS)} "
                f"may hold a string, pending migration 033."
            )
    return flags


def _validate_limits(value: Any) -> dict:
    # RULING: kept and accepted opaquely. Deliberately permissive pending 033's
    # `usage_meters`, which will define the real schema. Nothing reads this
    # column for enforcement today, so a strict validator would invent a
    # contract no consumer has asked for.
    return _validate_flat_object(value, "limits")


def _validate_bool(value: Any, field: str) -> bool:
    # `isinstance(True, int)` is True, so the order matters: check bool first
    # and reject everything else, or 1 would pass as True.
    if not isinstance(value, bool):
        raise _bad_request(f"{field} must be true or false — got {value!r}")
    return value


def _validate_trial_ends_at(value: Any) -> Optional[str]:
    """NOTE: this field AFFECTS ACCESS, it is not metadata.

    `require_feature` denies when `not is_active AND _is_trial_expired(...)`,
    and `_is_trial_expired(None)` is True — so clearing this on an inactive
    business locks the customer out immediately. The admin UI carries a
    warning adjacent to the field for the same reason.
    """
    if value is None or isinstance(value, str):
        return value
    raise _bad_request("trial_ends_at must be an ISO timestamp string or null")


_VALIDATORS = {
    "plan_tier": _validate_plan_tier,
    "feature_flags": _validate_feature_flags,
    "limits": _validate_limits,
    "is_active": lambda v: _validate_bool(v, "is_active"),
    "trial_ends_at": _validate_trial_ends_at,
    "name": lambda v: v,
    "timezone": lambda v: v,
}


def _validate_body(data: dict, allowed: tuple) -> dict:
    """Validate every field before anything is written.

    An unknown key is a 400 rather than a silent drop — a typo must not look
    like a success. `api_key` is called out by name because it is the one key
    a caller might plausibly try to set.
    """
    if not isinstance(data, dict):
        raise _bad_request("Request body must be a JSON object")

    if "api_key" in data:
        raise _bad_request(
            "api_key is generated server-side and cannot be set by a client"
        )

    unknown = [k for k in data if k not in allowed]
    if unknown:
        raise _bad_request(
            f"Unknown field(s): {', '.join(sorted(unknown))}. "
            f"Accepted: {', '.join(allowed)}."
        )

    return {key: _VALIDATORS[key](value) for key, value in data.items()}


def _json_statement(sql: str, fields):
    """Bind the JSONB columns by type so a dict can be passed straight through."""
    statement = text(sql)
    json_fields = [f for f in fields if f in ("feature_flags", "limits")]
    if json_fields:
        statement = statement.bindparams(
            *[bindparam(f, type_=JSONB) for f in json_fields]
        )
    return statement


def _read_admin_row(session: Session, business_id: str) -> dict:
    row = session.execute(
        text(
            f"SELECT {', '.join(ADMIN_COLUMNS)} FROM businesses WHERE id = :bid"
        ),
        {"bid": business_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return {column: getattr(row, column) for column in ADMIN_COLUMNS}


def _generate_api_key() -> str:
    """`sk_` + 43 characters. The only place an api_key is minted.

    Replaces a browser-side `Math.random()` generator that produced a 32-char
    `bh_` key. `Math.random()` is not a CSPRNG and this value is accepted as
    bearer auth by `get_current_business`.
    """
    api_key = f"sk_{secrets.token_urlsafe(32)}"
    return api_key


# ── A3 — create ──────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_business(
    data: dict,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Create a business. Supersedes the direct supabase-js insert."""
    fields = _validate_body(data, CREATE_FIELDS)

    name = (fields.get("name") or "")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise _bad_request("name is required")

    business_id = str(uuid4())
    api_key = _generate_api_key()

    plan_tier = fields.get("plan_tier") or "starter"

    row = {
        "id": business_id,
        "name": name,
        "timezone": fields.get("timezone") or "Europe/London",
        "plan_tier": plan_tier,
        "is_active": fields.get("is_active", False),
        "trial_ends_at": fields.get("trial_ends_at"),
        # ENTITLEMENT-SPEC PART C. AdminDashboard submits a whole FEATURE_PRESETS
        # block here, so a business was created already claiming every feature
        # its plan grants — access no later downgrade could remove. Validation
        # has already run (_validate_body); this drops only what merely restates
        # the plan default, keeping genuine exceptions, unknown keys and
        # `brand_color`. `limits` is deliberately passed through untouched.
        "feature_flags": strip_plan_defaults(fields.get("feature_flags") or {}, plan_tier),
        "limits": fields.get("limits") or {},
    }

    session.execute(
        _json_statement(
            """
            INSERT INTO businesses
                (id, name, timezone, api_key, plan_tier, is_active,
                 trial_ends_at, feature_flags, limits)
            VALUES
                (:id, :name, :timezone, :api_key, :plan_tier, :is_active,
                 :trial_ends_at, :feature_flags, :limits)
            """,
            ("feature_flags", "limits"),
        ),
        {**row, "api_key": api_key},
    )
    session.commit()

    logger.info("business %s created by admin %s", business_id, auth_ctx.get("user_id"))
    # The api_key is returned exactly once, here. No read endpoint exposes it.
    return {**row, "api_key": api_key}


# ── A4 — admin read ──────────────────────────────────────────────────────────

@router.get("/{business_id}")
async def get_business_admin(
    business_id: UUID,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """The ten columns the admin detail page reads. Never `api_key`."""
    return _read_admin_row(session, str(business_id))


# ── A1 — update overview ─────────────────────────────────────────────────────

@router.put("/{business_id}/overview")
async def update_business_overview(
    business_id: UUID,
    data: dict,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Update any of the five overview fields. Omitted means unchanged.

    An explicit `null` for `trial_ends_at` clears it, and is distinguishable
    from omission — the difference is whether the key is present at all.
    """
    fields = _validate_body(data, OVERVIEW_FIELDS)

    current = _read_admin_row(session, str(business_id))
    if not fields:
        return current

    # NO `updated_at` HERE. `businesses` has no such column and never has —
    # this statement and the one in `set_business_active` carried it from
    # 030b Release 1 until it was found, and both endpoints 500'd on every
    # request for the whole of that time (UndefinedColumn -> main.py's
    # catch-all -> "Internal Server Error"). If audit timestamps are wanted,
    # they need a migration plus the repo's `update_updated_at_column` trigger,
    # not a fragment here — `onboarding_api` writes this table too and would
    # not set it. `backend/tests/test_schema_conformance.py` now fails the
    # build if this comes back.
    assignments = ", ".join(f"{name} = :{name}" for name in fields)
    session.execute(
        _json_statement(
            f"UPDATE businesses SET {assignments} WHERE id = :bid",
            fields.keys(),
        ),
        {**fields, "bid": str(business_id)},
    )
    session.commit()

    logger.info(
        "business %s overview updated by admin %s: %s",
        business_id, auth_ctx.get("user_id"), ", ".join(sorted(fields)),
    )
    # Built from the applied changes rather than a re-read, so the caller sees
    # what it asked for without a second round trip.
    return {**current, **fields}


# ── A2 — explicit active state ───────────────────────────────────────────────

@router.put("/{business_id}/active")
async def set_business_active(
    business_id: UUID,
    data: dict,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Set the active state EXPLICITLY. This is not a toggle.

    Both frontend sites used to send `!business.is_active` — an inversion of a
    value held in browser memory. Two admins on one business, or one stale tab,
    and it flipped the wrong way with no error. The request now says what it
    wants to be true, so a stale client is simply redundant rather than wrong.

    Setting the current value is a success, not an error, which makes a retry
    after a dropped response safe.
    """
    if not isinstance(data, dict) or "is_active" not in data:
        raise _bad_request("is_active is required and must be true or false")
    is_active = _validate_bool(data["is_active"], "is_active")

    unknown = [k for k in data if k != "is_active"]
    if unknown:
        raise _bad_request(
            f"Unknown field(s): {', '.join(sorted(unknown))}. Accepted: is_active."
        )

    session.execute(
        text("UPDATE businesses SET is_active = :is_active WHERE id = :bid"),
        {"is_active": is_active, "bid": str(business_id)},
    )
    session.commit()

    logger.info(
        "business %s is_active set to %s by admin %s",
        business_id, is_active, auth_ctx.get("user_id"),
    )
    return {"id": str(business_id), "is_active": is_active}
