"""
Tier-gating helpers for premium features.

Tiers (in capability order):
- starter:  Lowest tier, limited features
- pro:      Mid tier, most features available
- business: Top paid tier, all features + premium support
- beta:     Treated as business-tier for testing parity
- paused:   Subscription paused, no premium feature access

Adding a feature gate? Add the feature key to FEATURE_GATES with the
list of plan_tier values that should have access.

NOTE: A separate `require_feature` exists in `auth.py` that uses the
`feature_flags` JSON column on businesses. This module is a simpler,
plan_tier-based gate intended for whole-feature access control. They
serve different purposes and may both be applied to the same endpoint.
"""
import logging
from typing import List

from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

logger = logging.getLogger(__name__)

# Map feature_name -> list of plan_tier values granted access.
FEATURE_GATES: dict = {
    "executive_board_meeting": ["pro", "business", "beta"],
    "executive_board_meeting_advanced": ["business", "beta"],
}


def get_business_tier(business_id: str, session: Session) -> str:
    """
    Return the business's plan_tier value, lowercased.

    Falls back to 'starter' on any error so callers fail closed
    (deny access to gated features rather than mistakenly grant it).
    """
    try:
        row = session.execute(
            text("SELECT plan_tier FROM businesses WHERE id = :bid LIMIT 1"),
            {"bid": business_id},
        ).fetchone()
        if row and row[0]:
            return str(row[0]).lower()
    except Exception as exc:
        logger.warning(
            f"[TierGating] Could not determine plan_tier for {business_id}: {exc}"
        )
    return "starter"


def require_tier_feature(
    business_id: str,
    feature_name: str,
    session: Session,
) -> str:
    """
    Raise HTTPException 403 if the business's tier doesn't include `feature_name`.
    Returns the current tier on success.
    """
    if feature_name not in FEATURE_GATES:
        raise HTTPException(status_code=500, detail=f"Unknown feature: {feature_name}")

    allowed_tiers: List[str] = FEATURE_GATES[feature_name]
    current_tier = get_business_tier(business_id, session)

    if current_tier not in allowed_tiers:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "tier_upgrade_required",
                "message": (
                    f"This feature requires a {allowed_tiers[0].title()} or "
                    f"higher plan."
                ),
                "current_tier": current_tier,
                "required_tiers": allowed_tiers,
                "feature": feature_name,
            },
        )

    return current_tier


def check_feature_access(
    business_id: str,
    feature_name: str,
    session: Session,
) -> bool:
    """
    Non-raising variant of `require_tier_feature`.

    Use this for conditional UI hints (e.g. show/hide badges) where a
    403 isn't appropriate.
    """
    try:
        require_tier_feature(business_id, feature_name, session)
        return True
    except HTTPException:
        return False
