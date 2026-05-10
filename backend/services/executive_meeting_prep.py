"""
Executive Board Meeting — Prep Service.

Produces a structured PrepData dict with everything Aria will need to walk
into the meeting fully briefed. Resilient to partial failures: any single
data loader can fail without breaking prep — the failed section just gets
`available: false` and the prep continues.

The output dict is what Prompt 3 will pass to GPT as context.
"""
from __future__ import annotations

import json
import logging
import os
import time as _time_module
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlmodel import Session

from services.executive_meeting_data_loaders import (
    calendar_loader,
    calls_loader,
    emails_loader,
    financial_loader,
    goals_actions_loader,
    invoices_loader,
    last_meeting_loader,
    quotes_loader,
    tasks_loader,
)
from services.executive_meeting_scheduling import compute_period_boundaries

logger = logging.getLogger(__name__)


# Read at import time; Prompt 3 will use this when calling GPT.
# Default kept conservative; Railway env should override.
EXECUTIVE_MEETING_AI_MODEL = os.getenv("EXECUTIVE_MEETING_AI_MODEL", "gpt-5")

PREP_SCHEMA_VERSION = "1.0"
TOKEN_BUDGET_TARGET = 8000  # warn if estimated tokens exceed this
_TOKEN_CHARS_PER_TOKEN = 4  # English+JSON heuristic


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def generate_prep_data(
    business_id: str,
    db_session: Session,
    scheduled_for: Optional[datetime] = None,
    settings_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate the full PrepData dict for a business.

    Parameters
    ----------
    business_id : str
        UUID of the business.
    db_session : Session
        Single read-only SQLAlchemy session shared across all loaders.
        The orchestrator does not commit; if the caller manages the session
        scope (e.g. via Depends(get_session)), no commit is needed.
    scheduled_for : datetime | None
        The meeting's scheduled time (UTC). Used for period anchoring.
        Defaults to "now" when None.
    settings_override : dict | None
        Allows callers (e.g. ad-hoc start-now) to override the loaded settings
        when the persisted settings haven't been saved yet.

    Returns
    -------
    Dict[str, Any]
        The PrepData dict matching the schema_version 1.0 spec. Never raises.
    """
    started_at = _time_module.monotonic()
    generated_at = datetime.now(timezone.utc).isoformat()
    errors_during_prep: List[str] = []
    completeness_components: Dict[str, bool] = {}

    # ---------------- Settings ----------------
    settings: Dict[str, Any] = {}
    try:
        if settings_override is not None:
            settings = dict(settings_override)
        else:
            settings = _load_settings(business_id, db_session) or {}
    except Exception as e:
        logger.exception("[Prep] failed to load executive_meeting_settings")
        errors_during_prep.append(f"settings: {e}")
        settings = {}

    timezone_name = settings.get("timezone") or "Europe/London"
    frequency = settings.get("frequency") or "weekly"

    if scheduled_for is None:
        scheduled_for = datetime.now(timezone.utc)
    elif scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)

    period = compute_period_boundaries(scheduled_for, frequency, timezone_name)

    # ---------------- Business profile ----------------
    business_profile, business_ok = _load_business_profile(business_id, db_session)
    completeness_components["business"] = business_ok
    if not business_ok:
        errors_during_prep.append("business: failed to load profile")

    # ---------------- Run all data loaders (single shared session) ----------------
    financials = _safe_loader(
        financial_loader.gather, "financials", business_id, period, db_session, errors_during_prep
    )
    completeness_components["financials"] = bool(financials.get("available"))

    invoices_section = _safe_loader(
        invoices_loader.gather, "invoices", business_id, period, db_session, errors_during_prep
    )
    completeness_components["invoices"] = bool(invoices_section.get("available"))

    calls_section = _safe_loader(
        calls_loader.gather, "calls", business_id, period, db_session, errors_during_prep
    )
    completeness_components["calls"] = bool(calls_section.get("available"))

    emails_section = _safe_loader(
        emails_loader.gather, "emails", business_id, period, db_session, errors_during_prep
    )
    completeness_components["emails"] = bool(emails_section.get("available"))

    tasks_section = _safe_loader(
        tasks_loader.gather, "tasks", business_id, period, db_session, errors_during_prep
    )
    completeness_components["tasks"] = bool(tasks_section.get("available"))

    calendar_section = _safe_loader(
        calendar_loader.gather, "calendar", business_id, period, db_session, errors_during_prep
    )
    completeness_components["calendar"] = bool(calendar_section.get("available"))

    quotes_section = _safe_loader(
        quotes_loader.gather, "quotes", business_id, period, db_session, errors_during_prep
    )
    completeness_components["quotes"] = bool(quotes_section.get("available"))

    goals_actions = _safe_loader(
        goals_actions_loader.gather, "goals_actions", business_id, period, db_session, errors_during_prep
    )
    goals_section = goals_actions.get("goals", {"active_count": 0, "achieved_this_period": [], "at_risk": [], "active_goals": []})
    actions_section = goals_actions.get("action_items", {"open_total": 0, "overdue_count": 0, "completed_this_period_count": 0, "by_priority": {}, "open_items": [], "overdue_items": []})
    # Goals/actions are derived from our own tables — always considered "available"
    # if the prep didn't error, even if the lists are empty.
    completeness_components["goals_actions"] = "errors" not in (goals_section or {}) or not (goals_section or {}).get("errors")

    last_meeting = _safe_loader(
        last_meeting_loader.gather, "last_meeting", business_id, period, db_session, errors_during_prep
    )
    completeness_components["last_meeting"] = bool(last_meeting.get("exists"))

    # ---------------- Flagged concerns ----------------
    flagged_concerns = _detect_flagged_concerns(
        financials=financials,
        invoices_section=invoices_section,
        calls_section=calls_section,
        emails_section=emails_section,
        tasks_section=tasks_section,
        goals_section=goals_section,
        actions_section=actions_section,
        last_meeting=last_meeting,
        business_id=business_id,
        session=db_session,
    )

    # ---------------- Owner context ----------------
    owner_context = _build_owner_context(settings)

    # ---------------- Data quality ----------------
    expected_sources = [
        "business", "financials", "invoices", "calls", "emails",
        "tasks", "calendar", "quotes", "goals_actions", "last_meeting",
    ]
    available_count = sum(1 for k in expected_sources if completeness_components.get(k))
    completeness_score = round(available_count / len(expected_sources), 2)
    missing_sources = [k for k in expected_sources if not completeness_components.get(k)]

    stale_sources: List[str] = []
    fin_freshness = financials.get("data_freshness")
    if fin_freshness:
        try:
            ts = fin_freshness if isinstance(fin_freshness, datetime) else datetime.fromisoformat(str(fin_freshness).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_hours > 24:
                stale_sources.append("financials")
        except Exception:
            pass

    duration_ms = int((_time_module.monotonic() - started_at) * 1000)

    prep_data: Dict[str, Any] = {
        "schema_version": PREP_SCHEMA_VERSION,
        "generated_at": generated_at,
        "generation_duration_ms": duration_ms,
        "ai_model": EXECUTIVE_MEETING_AI_MODEL,
        "business": business_profile,
        "period": _serialise_period(period),
        "financials": financials,
        "invoices": invoices_section,
        "operations": {
            "calls": calls_section,
            "emails": emails_section,
            "tasks": tasks_section,
            "calendar": calendar_section,
            "quotes": quotes_section,
        },
        "goals": goals_section,
        "action_items": actions_section,
        "last_meeting": last_meeting,
        "flagged_concerns": flagged_concerns,
        "owner_context": owner_context,
        "data_quality": {
            "completeness_score": completeness_score,
            "missing_sources": missing_sources,
            "stale_sources": stale_sources,
            "errors_during_prep": errors_during_prep,
        },
    }

    # Token-budget heuristic warning (does not modify the dict)
    try:
        char_len = len(json.dumps(prep_data, default=str))
        token_estimate = char_len // _TOKEN_CHARS_PER_TOKEN
        if token_estimate > TOKEN_BUDGET_TARGET:
            logger.warning(
                "[Prep] PrepData exceeds token budget: ~%d tokens (~%d chars) "
                "for business_id=%s. Target=%d.",
                token_estimate, char_len, business_id, TOKEN_BUDGET_TARGET,
            )
    except Exception:
        pass

    logger.info(
        "[Prep] generated PrepData for business_id=%s in %dms "
        "(completeness=%.2f, missing=%s, errors=%d)",
        business_id, duration_ms, completeness_score,
        missing_sources, len(errors_during_prep),
    )
    return prep_data


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _safe_loader(loader_fn, loader_name: str, business_id: str, period, session, errors_acc: List[str]):
    """Call a loader, swallow exceptions, and return its empty/error structure."""
    try:
        result = loader_fn(business_id, period, session)
        if isinstance(result, dict) and result.get("errors"):
            for e in result["errors"]:
                errors_acc.append(f"{loader_name}: {e}")
        return result
    except Exception as e:
        logger.exception("[Prep] %s loader raised — caught at orchestrator", loader_name)
        errors_acc.append(f"{loader_name}: {e}")
        return {"available": False, "errors": [str(e)]}


def _load_settings(business_id: str, session: Session) -> Optional[Dict[str, Any]]:
    """Load executive_meeting_settings for a business."""
    row = session.execute(
        text(
            """
            SELECT enabled, frequency, day_of_week, day_of_month, meeting_time,
                   timezone, focus_areas, custom_agenda_items, attendees,
                   directness_level, include_disclaimers
            FROM executive_meeting_settings
            WHERE business_id = :business_id
            LIMIT 1
            """
        ),
        {"business_id": business_id},
    ).fetchone()
    if not row:
        return None

    return {
        "enabled": bool(row[0]),
        "frequency": row[1],
        "day_of_week": row[2],
        "day_of_month": row[3],
        "meeting_time": str(row[4]) if row[4] else None,
        "timezone": row[5] or "Europe/London",
        "focus_areas": _coerce_jsonb_list(row[6]),
        "custom_agenda_items": _coerce_jsonb_list(row[7]),
        "attendees": _coerce_jsonb_list(row[8]),
        "directness_level": row[9] or "balanced",
        "include_disclaimers": bool(row[10]) if row[10] is not None else True,
    }


def _coerce_jsonb_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except Exception:
            return []
    return []


def _load_business_profile(business_id: str, session: Session) -> tuple[Dict[str, Any], bool]:
    """
    Load the business profile block. Returns (profile_dict, ok).
    On failure, returns a stub with all fields None and ok=False.
    """
    profile = {
        "id": business_id,
        "name": None,
        "tier": None,
        "industry": None,
        "owner_name": None,
        "joined_at": None,
        "founded_or_joined_at": None,  # alias for spec parity
    }
    try:
        row = session.execute(
            text(
                """
                SELECT name, plan_tier, created_at
                FROM businesses
                WHERE id = :business_id
                LIMIT 1
                """
            ),
            {"business_id": business_id},
        ).fetchone()
        if not row:
            return profile, False
        profile["name"] = row[0]
        profile["tier"] = row[1]
        if row[2]:
            iso = row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2])
            profile["joined_at"] = iso
            profile["founded_or_joined_at"] = iso

        # Industry — best-effort from the latest onboarding session's wizard_data
        try:
            ob_row = session.execute(
                text(
                    """
                    SELECT wizard_data
                    FROM onboarding_sessions
                    WHERE business_id = :business_id
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                ),
                {"business_id": business_id},
            ).fetchone()
            if ob_row and ob_row[0]:
                wd = ob_row[0]
                if isinstance(wd, str):
                    wd = json.loads(wd)
                if isinstance(wd, dict):
                    bd = wd.get("business_details") or {}
                    if isinstance(bd, dict):
                        profile["industry"] = bd.get("industry") or bd.get("business_type") or bd.get("sector")
        except Exception:
            # Non-fatal — industry is optional context
            pass

        # Owner name — best-effort from onboarding wizard_data.owner_account
        try:
            if profile.get("industry") is None:
                # already fetched; reuse — but keep code simple by re-fetching
                pass
            ob_owner_row = session.execute(
                text(
                    """
                    SELECT wizard_data
                    FROM onboarding_sessions
                    WHERE business_id = :business_id
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                ),
                {"business_id": business_id},
            ).fetchone()
            if ob_owner_row and ob_owner_row[0]:
                wd = ob_owner_row[0]
                if isinstance(wd, str):
                    wd = json.loads(wd)
                if isinstance(wd, dict):
                    oa = wd.get("owner_account") or {}
                    if isinstance(oa, dict):
                        profile["owner_name"] = oa.get("owner_name")
        except Exception:
            pass

        return profile, True
    except Exception:
        logger.exception("[Prep] business profile load failed")
        return profile, False


def _build_owner_context(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Build the owner_context section from settings."""
    return {
        "directness_level": settings.get("directness_level", "balanced"),
        "include_disclaimers": settings.get("include_disclaimers", True),
        "focus_areas": settings.get("focus_areas") or ["financial", "operations", "team", "growth"],
        "custom_agenda_items": settings.get("custom_agenda_items") or [],
        "attendees": settings.get("attendees") or [],
    }


def _serialise_period(period: Dict[str, Any]) -> Dict[str, Any]:
    """Return the period dict with only JSON-friendly values (no datetimes)."""
    return {
        "type": period["type"],
        "timezone": period["timezone"],
        "comparison_label": period["comparison_label"],
        "current_start": period["current_start_iso"],
        "current_end": period["current_end_iso"],
        "previous_start": period["previous_start_iso"],
        "previous_end": period["previous_end_iso"],
    }


# ----------------------------------------------------------------------------
# Flagged concerns
# ----------------------------------------------------------------------------

def _detect_flagged_concerns(
    *,
    financials: Dict[str, Any],
    invoices_section: Dict[str, Any],
    calls_section: Dict[str, Any],
    emails_section: Dict[str, Any],
    tasks_section: Dict[str, Any],
    goals_section: Dict[str, Any],
    actions_section: Dict[str, Any],
    last_meeting: Dict[str, Any],
    business_id: str,
    session: Session,
) -> List[Dict[str, Any]]:
    flags: List[Dict[str, Any]] = []

    # accounting_disconnected
    if not financials.get("available"):
        flags.append({
            "type": "accounting_disconnected",
            "severity": "high",
            "headline": "Accounting integration is disconnected or stale",
            "detail": "No active accounting connection or no recent data. Financial figures cannot be reported with confidence.",
            "data_ref": {"table": "accounting_connections", "id": None},
            "suggested_action": "Reconnect Xero/FreeAgent/QuickBooks in Settings → Integrations.",
        })
    else:
        # Stale data >7 days
        try:
            ts_raw = financials.get("data_freshness")
            if ts_raw:
                ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
                if age_days > 7:
                    flags.append({
                        "type": "accounting_disconnected",
                        "severity": "high",
                        "headline": f"Accounting data is {int(age_days)} days old",
                        "detail": "The accounting integration hasn't synced in over a week — figures may be inaccurate.",
                        "data_ref": {"table": "accounting_connections", "id": None},
                        "suggested_action": "Trigger a manual sync or reconnect the integration.",
                    })
        except Exception:
            pass

    # overdue_invoice_critical (>60 days)
    if invoices_section.get("available"):
        oldest = invoices_section.get("oldest_overdue_days") or 0
        if oldest >= 90:
            top_debtor = (invoices_section.get("top_debtors") or [{}])[0]
            flags.append({
                "type": "overdue_invoice_critical",
                "severity": "critical",
                "headline": f"Invoice {oldest} days overdue from {top_debtor.get('name', 'a customer')}",
                "detail": f"At least one outstanding invoice is more than 90 days overdue (£{top_debtor.get('amount', 0):.2f}).",
                "data_ref": {"table": "invoices", "id": top_debtor.get("id")},
                "suggested_action": "Decide on escalation: legal letter, factoring, or write-off.",
            })
        elif oldest > 60:
            top_debtor = (invoices_section.get("top_debtors") or [{}])[0]
            flags.append({
                "type": "overdue_invoice_critical",
                "severity": "high",
                "headline": f"Invoice {oldest} days overdue from {top_debtor.get('name', 'a customer')}",
                "detail": f"An invoice is over 60 days overdue (£{top_debtor.get('amount', 0):.2f}).",
                "data_ref": {"table": "invoices", "id": top_debtor.get("id")},
                "suggested_action": "Send a final-warning chase or pick up the phone.",
            })

        # overdue_invoices_volume
        ov_count = invoices_section.get("overdue_count") or 0
        if ov_count > 5:
            flags.append({
                "type": "overdue_invoices_volume",
                "severity": "medium",
                "headline": f"{ov_count} invoices are currently overdue",
                "detail": f"Total overdue value is £{invoices_section.get('overdue_total', 0):.2f}.",
                "data_ref": {"table": "invoices", "id": None},
                "suggested_action": "Run a chase batch from the Invoices page.",
            })

    # cash_runway_short
    if financials.get("available"):
        cash_balance = (financials.get("cash_position") or {}).get("available_balance")
        monthly_expenses = _estimate_monthly_expenses(financials)
        if (
            cash_balance is not None
            and monthly_expenses is not None
            and monthly_expenses > 0
            and cash_balance < monthly_expenses * 2
        ):
            months_runway = round(cash_balance / monthly_expenses, 1) if monthly_expenses else 0
            flags.append({
                "type": "cash_runway_short",
                "severity": "high",
                "headline": f"Cash runway is approximately {months_runway} months",
                "detail": f"Cash position £{cash_balance:.2f} vs estimated monthly expenses £{monthly_expenses:.2f}.",
                "data_ref": {"table": "financial_summary_cache", "id": None},
                "suggested_action": "Consider invoice chasing, expense review, or financing options.",
            })

    # revenue_declining
    rev = financials.get("revenue") or {}
    rev_delta = rev.get("delta_pct")
    if rev_delta is not None:
        if rev_delta < -30:
            flags.append({
                "type": "revenue_declining_significant",
                "severity": "high",
                "headline": f"Revenue down {abs(rev_delta):.1f}% vs last period",
                "detail": "Significant revenue drop — investigate root cause urgently.",
                "data_ref": {"table": "accounting_transactions", "id": None},
                "suggested_action": "Review pipeline, lost customers, and pricing.",
            })
        elif rev_delta < -15:
            flags.append({
                "type": "revenue_declining",
                "severity": "medium",
                "headline": f"Revenue down {abs(rev_delta):.1f}% vs last period",
                "detail": "Notable revenue dip — may be seasonal or signal a pipeline issue.",
                "data_ref": {"table": "accounting_transactions", "id": None},
                "suggested_action": "Compare against marketing/sales activity for the period.",
            })

    # missed_calls_volume
    if calls_section.get("available"):
        total = calls_section.get("total_calls") or 0
        missed = calls_section.get("missed_calls") or 0
        if total > 0 and missed / total > 0.10:
            flags.append({
                "type": "missed_calls_volume",
                "severity": "medium",
                "headline": f"{missed} of {total} calls missed ({round(missed/total*100)}%)",
                "detail": "Missed-call rate is above 10% — opportunity loss is likely.",
                "data_ref": {"table": "calls", "id": None},
                "suggested_action": "Review receptionist hours, transfer rules, or after-hours config.",
            })

    # tasks_completion_low
    if tasks_section.get("available"):
        rate = tasks_section.get("completion_rate_pct")
        if rate is not None and rate < 50:
            flags.append({
                "type": "tasks_completion_low",
                "severity": "medium",
                "headline": f"Task completion rate at {rate}% this period",
                "detail": f"{tasks_section.get('open_total')} open tasks vs {tasks_section.get('completed_this_period')} completed.",
                "data_ref": {"table": "tasks", "id": None},
                "suggested_action": "Review the task backlog and reprioritise or close stale tasks.",
            })

    # goals_at_risk — already detected by loader
    for g in (goals_section.get("at_risk") or [])[:3]:
        flags.append({
            "type": "goals_at_risk",
            "severity": "high",
            "headline": f"Goal at risk: {g.get('title')}",
            "detail": f"Status={g.get('status')}, target_date={g.get('target_date')}.",
            "data_ref": {"table": "executive_meeting_goals", "id": g.get("id")},
            "suggested_action": "Review progress, adjust target, or commit to a corrective action.",
        })

    # action_items_overdue
    overdue_count = actions_section.get("overdue_count") or 0
    if overdue_count > 3:
        flags.append({
            "type": "action_items_overdue",
            "severity": "medium",
            "headline": f"{overdue_count} action items are overdue",
            "detail": "Action items committed in earlier meetings have slipped past their due dates.",
            "data_ref": {"table": "executive_meeting_action_items", "id": None},
            "suggested_action": "Triage: complete, defer with new date, or cancel.",
        })

    # email_response_slow — skipped: avg_response_time_hours intentionally null

    # no_recent_meetings
    try:
        if not last_meeting.get("exists"):
            flags.append({
                "type": "no_recent_meetings",
                "severity": "low",
                "headline": "No previous executive meetings on record",
                "detail": "This appears to be your first executive board meeting.",
                "data_ref": {"table": "executive_meetings", "id": None},
                "suggested_action": "Use this meeting to set initial goals and rhythms.",
            })
        else:
            last_date_iso = last_meeting.get("date")
            if last_date_iso:
                last_dt = datetime.fromisoformat(str(last_date_iso).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - last_dt).days
                if days > 42:
                    flags.append({
                        "type": "no_recent_meetings",
                        "severity": "low",
                        "headline": f"Last meeting was {days} days ago",
                        "detail": "More than 6 weeks have passed since the last completed meeting.",
                        "data_ref": {"table": "executive_meetings", "id": last_meeting.get("id")},
                        "suggested_action": "Consider whether the cadence needs adjusting.",
                    })
    except Exception:
        pass

    return flags


def _estimate_monthly_expenses(financials: Dict[str, Any]) -> Optional[float]:
    """
    Heuristic: scale current-period expenses to a 30-day month.
    For weekly periods that's ×30/7; for monthly periods we use as-is.
    """
    expenses = (financials.get("expenses") or {}).get("current")
    if expenses is None or expenses <= 0:
        return None
    # We don't have direct access to period type here; assume the orchestrator
    # gives us either ~week (×4.3) or ~month worth of expenses. Pick the larger
    # of the two scaled values to be conservative on runway warnings.
    scaled_week = float(expenses) * (30.0 / 7.0)
    scaled_month = float(expenses)
    return round(max(scaled_week, scaled_month), 2)
