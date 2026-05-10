"""Helpers shared across the executive-meeting data loaders."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


# Threshold for labelling deltas as "flat" — anything within ±2% counts as flat.
_FLAT_PCT_THRESHOLD = 2.0


def pct_delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """
    Percentage change from previous to current. Returns None if either input is
    None or previous is zero (undefined).
    """
    if current is None or previous is None:
        return None
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 2)


def absolute_delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Simple subtraction with None-safety."""
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def trend_label(delta_pct: Optional[float]) -> str:
    """Map a percentage delta to 'up', 'down', or 'flat' (or 'unknown')."""
    if delta_pct is None:
        return "unknown"
    if abs(delta_pct) <= _FLAT_PCT_THRESHOLD:
        return "flat"
    return "up" if delta_pct > 0 else "down"


def truncate(value: Optional[str], max_len: int = 500) -> Optional[str]:
    """Truncate a string to max_len, appending an ellipsis if truncated."""
    if value is None:
        return None
    s = str(value)
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)].rstrip() + "…"


def iso_or_none(value: Any) -> Optional[str]:
    """Best-effort isoformat for datetime/date — returns None for falsy inputs."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Coerce to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Coerce to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def empty_period_metric() -> dict:
    """Boilerplate for revenue/expenses/profit when financials are unavailable."""
    return {
        "current": None,
        "previous": None,
        "delta_absolute": None,
        "delta_pct": None,
        "trend": "unknown",
    }


def build_period_metric(
    current: Optional[float],
    previous: Optional[float],
) -> dict:
    """Build a {current, previous, delta_absolute, delta_pct, trend} block."""
    delta_pct = pct_delta(current, previous)
    return {
        "current": round(current, 2) if current is not None else None,
        "previous": round(previous, 2) if previous is not None else None,
        "delta_absolute": absolute_delta(current, previous),
        "delta_pct": delta_pct,
        "trend": trend_label(delta_pct),
    }


def utc_now_iso() -> str:
    """Best-effort UTC ISO timestamp for prep_data.generated_at etc."""
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()
