"""
Admin Onboarding Wizard — Backend API

Step-by-step wizard for onboarding new businesses:
  1. Business details  →  creates the business record
  2. Owner account     →  stores owner email for manual invite
  3. Plan & features   →  sets feature_flags on the business
  4. Email setup       →  pending / skip (owner does OAuth)
  5. Receptionist      →  creates config + KB items
  6. Calendar setup    →  pending / skip (owner does OAuth)
  7. Accounting setup  →  pending / skip (owner does OAuth)
  8. Review & activate →  activates business, enables receptionist

All endpoints under /v1/admin/onboarding/, guarded by platform-admin auth.
"""

import logging
import secrets
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session
from sqlalchemy import text

from db import get_session
from auth import get_platform_admin_context, is_platform_admin_user, strip_plan_defaults

_logger = logging.getLogger("onboarding")

router = APIRouter(prefix="/v1/admin/onboarding", tags=["Admin Onboarding"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class BusinessDetailsStep(BaseModel):
    name: str
    timezone: str = "Europe/London"
    plan_tier: str = "starter"


class OwnerAccountStep(BaseModel):
    owner_email: str
    owner_name: Optional[str] = None
    send_invite: bool = True


class PlanFeaturesStep(BaseModel):
    feature_flags: Dict[str, bool]


class EmailSetupStep(BaseModel):
    status: str = "pending"
    notes: Optional[str] = None


class ReceptionistSetupStep(BaseModel):
    skip: bool = False
    twilio_phone_number: Optional[str] = None
    voice: str = "shimmer"
    greeting_message: str = "Hello, thank you for calling. How can I help you today?"
    tone: str = "professional"
    language: str = "en-GB"
    knowledge_base_items: Optional[List[Dict[str, str]]] = None


class CalendarSetupStep(BaseModel):
    status: str = "pending"
    notes: Optional[str] = None


class AccountingSetupStep(BaseModel):
    status: str = "pending"
    notes: Optional[str] = None


class ReviewActivateStep(BaseModel):
    activate_now: bool = True
    send_welcome_email: bool = True
    admin_notes: Optional[str] = None


class ChecklistUpdateBody(BaseModel):
    is_completed: bool = True
    notes: Optional[str] = None


STEP_ORDER = [
    "business_details",
    "owner_account",
    "plan_features",
    "email_setup",
    "receptionist_setup",
    "calendar_setup",
    "accounting_setup",
    "review_activate",
]

STEP_SKIP_FEATURE_MAP = {
    "receptionist_setup": "receptionist",
    "accounting_setup": "accounting",
}

DEFAULT_CHECKLIST = [
    {"item_key": "business_created", "label": "Business created", "category": "setup", "sort_order": 1},
    {"item_key": "owner_account_created", "label": "Owner account created", "category": "setup", "sort_order": 2},
    {"item_key": "plan_configured", "label": "Plan & features configured", "category": "setup", "sort_order": 3},
    {"item_key": "email_connected", "label": "Email connected", "category": "integration", "sort_order": 4},
    {"item_key": "receptionist_configured", "label": "AI Receptionist configured", "category": "integration", "sort_order": 5},
    {"item_key": "calendar_connected", "label": "Calendar connected", "category": "integration", "sort_order": 6},
    {"item_key": "accounting_connected", "label": "Accounting connected", "category": "integration", "sort_order": 7},
    {"item_key": "first_login", "label": "Business owner first login", "category": "activation", "sort_order": 8},
    {"item_key": "first_call", "label": "First receptionist call received", "category": "activation", "sort_order": 9},
    {"item_key": "first_email_synced", "label": "First email synced", "category": "activation", "sort_order": 10},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_admin(auth_ctx: dict, session: Session):
    if not is_platform_admin_user(auth_ctx["user_id"], session):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy Row/RowMapping to a plain dict."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Plan Definition Endpoints
# ---------------------------------------------------------------------------

@router.get("/plans")
async def get_plans(
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Get all active plan definitions."""
    _require_admin(auth_ctx, session)
    rows = session.execute(
        text("SELECT * FROM plan_definitions WHERE is_active = TRUE ORDER BY sort_order")
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    updates: dict,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Update a plan definition (prices, features, limits)."""
    _require_admin(auth_ctx, session)

    allowed_fields = {"name", "description", "monthly_price_gbp", "features", "limits", "sort_order", "is_active"}
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clauses = ", ".join(f"{k} = :{k}" for k in filtered)
    filtered["plan_id"] = plan_id
    filtered["updated_at"] = _now_iso()

    import json
    for k in ("features", "limits"):
        if k in filtered and isinstance(filtered[k], dict):
            filtered[k] = json.dumps(filtered[k])

    session.execute(
        text(f"UPDATE plan_definitions SET {set_clauses}, updated_at = :updated_at WHERE id = :plan_id"),
        filtered,
    )
    session.commit()

    row = session.execute(
        text("SELECT * FROM plan_definitions WHERE id = :plan_id"),
        {"plan_id": plan_id},
    ).fetchone()
    return _row_to_dict(row) if row else {"status": "updated"}


# ---------------------------------------------------------------------------
# Onboarding Wizard — Start
# ---------------------------------------------------------------------------

@router.post("/start", status_code=201)
async def start_onboarding(
    step: BusinessDetailsStep,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Step 1: Create a new business and start an onboarding session."""
    _require_admin(auth_ctx, session)
    admin_user_id = auth_ctx["user_id"]

    plan_row = session.execute(
        text("SELECT limits FROM plan_definitions WHERE id = :plan_id"),
        {"plan_id": step.plan_tier},
    ).fetchone()

    import json
    # `plan_row.features` is deliberately NOT read. `plan_definitions` is a
    # sixth plan -> feature authority, editable at runtime through
    # PUT /v1/admin/onboarding/plans and kept in step with nothing. It may
    # price a plan; it may not decide entitlement. See auth.PLAN_FEATURE_DEFAULTS.
    plan_limits = json.loads(plan_row.limits) if plan_row and isinstance(plan_row.limits, str) else (plan_row.limits if plan_row else {})

    # ENTITLEMENT-SPEC PART C — `feature_flags` is OMITTED, not set to '{}'.
    # The column is `jsonb NOT NULL DEFAULT '{}'::jsonb` (028 baseline), so the
    # schema already guarantees the empty object; naming it here would only
    # restate a default. A new business owns NO exceptions — its access comes
    # from `plan_tier`, resolved live at read time. Writing the plan's grants
    # in at creation, which is what this did, pinned them permanently: no later
    # downgrade could remove a feature the row already claimed explicitly.
    #
    # `limits` is deliberately still written from the plan. Nothing reads it
    # for enforcement, so blanking it would delete a record rather than
    # relocate one — out of scope here.
    biz_row = session.execute(
        text("""
            INSERT INTO businesses (name, timezone, plan_tier, is_active, limits, onboarding_completed, api_key)
            VALUES (:name, :timezone, :plan_tier, FALSE, :limits, FALSE, :api_key)
            RETURNING *
        """),
        {
            "api_key": f"sk_{secrets.token_urlsafe(32)}",
            "name": step.name,
            "timezone": step.timezone,
            "plan_tier": step.plan_tier,
            "limits": json.dumps(plan_limits),
        },
    ).fetchone()
    session.commit()

    if not biz_row:
        raise HTTPException(status_code=500, detail="Failed to create business")

    business = _row_to_dict(biz_row)
    business_id = str(business["id"])

    steps_completed = {s: (s == "business_details") for s in STEP_ORDER}
    wizard_data = {"business_details": step.model_dump()}

    sess_row = session.execute(
        text("""
            INSERT INTO onboarding_sessions
                (business_id, started_by, status, current_step, steps_completed, wizard_data)
            VALUES (:business_id, :started_by, 'in_progress', 'owner_account', :steps_completed, :wizard_data)
            RETURNING *
        """),
        {
            "business_id": business_id,
            "started_by": admin_user_id,
            "steps_completed": json.dumps(steps_completed),
            "wizard_data": json.dumps(wizard_data),
        },
    ).fetchone()

    now = _now_iso()
    for item in DEFAULT_CHECKLIST:
        is_done = item["item_key"] == "business_created"
        session.execute(
            text("""
                INSERT INTO onboarding_checklist
                    (business_id, item_key, label, category, is_completed, completed_at, completed_by, sort_order)
                VALUES (:biz, :key, :label, :cat, :done, :cat_ts, :cat_by, :so)
                ON CONFLICT (business_id, item_key) DO NOTHING
            """),
            {
                "biz": business_id,
                "key": item["item_key"],
                "label": item["label"],
                "cat": item["category"],
                "done": is_done,
                "cat_ts": now if is_done else None,
                "cat_by": "admin" if is_done else None,
                "so": item["sort_order"],
            },
        )

    session.commit()

    return {
        "business": business,
        "session": _row_to_dict(sess_row) if sess_row else None,
    }


# ---------------------------------------------------------------------------
# Onboarding Wizard — Session
# ---------------------------------------------------------------------------

@router.get("/session/{business_id}")
async def get_onboarding_session(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Get the active onboarding session for a business."""
    _require_admin(auth_ctx, session)
    row = session.execute(
        text("""
            SELECT * FROM onboarding_sessions
            WHERE business_id = :biz AND status = 'in_progress'
            ORDER BY started_at DESC LIMIT 1
        """),
        {"biz": business_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No active onboarding session found")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Onboarding Wizard — Save Step
# ---------------------------------------------------------------------------

@router.put("/session/{business_id}/step")
async def save_wizard_step(
    business_id: str,
    step_name: str = Query(...),
    step_data: dict = {},
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Save data for a wizard step and advance to the next one."""
    _require_admin(auth_ctx, session)
    import json

    sess_row = session.execute(
        text("""
            SELECT * FROM onboarding_sessions
            WHERE business_id = :biz AND status = 'in_progress'
            ORDER BY started_at DESC LIMIT 1
        """),
        {"biz": business_id},
    ).fetchone()

    if not sess_row:
        raise HTTPException(status_code=404, detail="No active onboarding session")

    ob_session = _row_to_dict(sess_row)
    session_id = str(ob_session["id"])
    steps_completed = ob_session.get("steps_completed") or {}
    if isinstance(steps_completed, str):
        steps_completed = json.loads(steps_completed)
    wizard_data = ob_session.get("wizard_data") or {}
    if isinstance(wizard_data, str):
        wizard_data = json.loads(wizard_data)

    now = _now_iso()

    # ---- Process individual steps ----

    if step_name == "owner_account":
        owner_email = step_data.get("owner_email", "")
        owner_name = step_data.get("owner_name", "")
        wizard_data["owner_account"] = step_data

        if owner_email:
            session.execute(
                text("""
                    UPDATE onboarding_checklist SET
                        is_completed = TRUE, completed_at = :now, completed_by = 'admin',
                        notes = :notes, updated_at = :now
                    WHERE business_id = :biz AND item_key = 'owner_account_created'
                """),
                {"biz": business_id, "now": now, "notes": f"Owner: {owner_name} ({owner_email})"},
            )

    elif step_name == "plan_features":
        submitted = step_data.get("feature_flags", {})
        # PART C: store only what DIFFERS from the plan. The wizard sends a
        # full copy of the tier's features plus whatever the admin toggled;
        # writing that verbatim put plan defaults into the column and undid
        # 033 SECTION 7 on the very first save. The strip keeps unknown keys,
        # non-booleans (`industry`) and any explicit value that contradicts
        # the plan — see auth.strip_plan_defaults.
        biz_row = session.execute(
            text("SELECT plan_tier FROM businesses WHERE id = :biz"),
            {"biz": business_id},
        ).fetchone()
        feature_flags = strip_plan_defaults(
            submitted, biz_row.plan_tier if biz_row else None
        )
        session.execute(
            text("UPDATE businesses SET feature_flags = :flags WHERE id = :biz"),
            {"biz": business_id, "flags": json.dumps(feature_flags)},
        )
        wizard_data["plan_features"] = step_data

        session.execute(
            text("""
                UPDATE onboarding_checklist SET
                    is_completed = TRUE, completed_at = :now, completed_by = 'admin', updated_at = :now
                WHERE business_id = :biz AND item_key = 'plan_configured'
            """),
            {"biz": business_id, "now": now},
        )

    elif step_name == "email_setup":
        wizard_data["email_setup"] = step_data
        if step_data.get("status") == "skip":
            session.execute(
                text("""
                    UPDATE onboarding_checklist SET
                        notes = 'Skipped during onboarding — business owner to connect later', updated_at = :now
                    WHERE business_id = :biz AND item_key = 'email_connected'
                """),
                {"biz": business_id, "now": now},
            )

    elif step_name == "receptionist_setup":
        wizard_data["receptionist_setup"] = step_data

        if not step_data.get("skip", False):
            phone = step_data.get("twilio_phone_number", "")
            if phone:
                phone = phone.replace(" ", "").strip()

            existing = session.execute(
                text("SELECT id FROM receptionist_configs WHERE business_id = CAST(:biz AS uuid)"),
                {"biz": business_id},
            ).fetchone()

            config_params = {
                "biz": business_id,
                "voice": step_data.get("voice", "shimmer"),
                "greeting": step_data.get("greeting_message", "Hello, thank you for calling. How can I help you today?"),
                "tone": step_data.get("tone", "professional"),
                "language": step_data.get("language", "en-GB"),
                "phone": phone or None,
                "now": now,
            }

            if existing:
                session.execute(
                    text("""
                        UPDATE receptionist_configs SET
                            voice = :voice, greeting_message = :greeting, tone = :tone,
                            language = :language, twilio_phone_number = :phone,
                            enabled = FALSE, updated_at = :now
                        WHERE business_id = CAST(:biz AS uuid)
                    """),
                    config_params,
                )
            else:
                session.execute(
                    text("""
                        INSERT INTO receptionist_configs
                            (business_id, voice, greeting_message, tone, language, twilio_phone_number, enabled, updated_at)
                        VALUES (CAST(:biz AS uuid), :voice, :greeting, :tone, :language, :phone, FALSE, :now)
                    """),
                    config_params,
                )

            for item in (step_data.get("knowledge_base_items") or []):
                if item.get("content"):
                    session.execute(
                        text("""
                            INSERT INTO knowledge_base_items
                                (business_id, category, title, content, is_active)
                            VALUES (CAST(:biz AS uuid), :cat, :title, :content, TRUE)
                        """),
                        {
                            "biz": business_id,
                            "cat": item.get("category", "general"),
                            "title": item.get("title", ""),
                            "content": item["content"],
                        },
                    )

            session.execute(
                text("""
                    UPDATE onboarding_checklist SET
                        is_completed = TRUE, completed_at = :now, completed_by = 'admin',
                        notes = :notes, updated_at = :now
                    WHERE business_id = :biz AND item_key = 'receptionist_configured'
                """),
                {"biz": business_id, "now": now, "notes": f"Phone: {phone or 'Not assigned'}, Voice: {step_data.get('voice', 'shimmer')}"},
            )
        else:
            session.execute(
                text("""
                    UPDATE onboarding_checklist SET
                        notes = 'Skipped — not included in plan or deferred', updated_at = :now
                    WHERE business_id = :biz AND item_key = 'receptionist_configured'
                """),
                {"biz": business_id, "now": now},
            )

    elif step_name == "calendar_setup":
        wizard_data["calendar_setup"] = step_data
        if step_data.get("status") == "skip":
            session.execute(
                text("""
                    UPDATE onboarding_checklist SET
                        notes = 'Skipped during onboarding', updated_at = :now
                    WHERE business_id = :biz AND item_key = 'calendar_connected'
                """),
                {"biz": business_id, "now": now},
            )

    elif step_name == "accounting_setup":
        wizard_data["accounting_setup"] = step_data
        if step_data.get("status") == "skip":
            session.execute(
                text("""
                    UPDATE onboarding_checklist SET
                        notes = 'Skipped during onboarding — not in plan or deferred', updated_at = :now
                    WHERE business_id = :biz AND item_key = 'accounting_connected'
                """),
                {"biz": business_id, "now": now},
            )

    elif step_name == "review_activate":
        wizard_data["review_activate"] = step_data

        if step_data.get("activate_now", True):
            session.execute(
                text("""
                    UPDATE businesses SET
                        is_active = TRUE,
                        onboarding_completed = TRUE,
                        onboarding_completed_at = :now
                    WHERE id = :biz
                """),
                {"biz": business_id, "now": now},
            )

            rc = session.execute(
                text("SELECT id, twilio_phone_number FROM receptionist_configs WHERE business_id = CAST(:biz AS uuid)"),
                {"biz": business_id},
            ).fetchone()
            if rc and rc.twilio_phone_number:
                session.execute(
                    text("UPDATE receptionist_configs SET enabled = TRUE, updated_at = :now WHERE business_id = CAST(:biz AS uuid)"),
                    {"biz": business_id, "now": now},
                )

        all_done = {k: True for k in steps_completed}
        session.execute(
            text("""
                UPDATE onboarding_sessions SET
                    status = 'completed', completed_at = :now, current_step = 'completed',
                    steps_completed = :steps, wizard_data = :wdata, updated_at = :now
                WHERE id = CAST(:sid AS uuid)
            """),
            {
                "sid": session_id,
                "now": now,
                "steps": json.dumps(all_done),
                "wdata": json.dumps(wizard_data),
            },
        )
        session.commit()

        return {
            "status": "completed",
            "business_id": business_id,
            "activated": step_data.get("activate_now", True),
        }

    else:
        raise HTTPException(status_code=400, detail=f"Unknown step: {step_name}")

    # ---- Mark step complete & advance ----

    steps_completed[step_name] = True

    current_idx = STEP_ORDER.index(step_name) if step_name in STEP_ORDER else -1
    next_step = STEP_ORDER[current_idx + 1] if current_idx + 1 < len(STEP_ORDER) else "review_activate"

    biz_row = session.execute(
        text("SELECT feature_flags FROM businesses WHERE id = :biz"),
        {"biz": business_id},
    ).fetchone()
    flags = {}
    if biz_row:
        raw = biz_row.feature_flags
        flags = json.loads(raw) if isinstance(raw, str) else (raw or {})

    while next_step in STEP_SKIP_FEATURE_MAP:
        required_feature = STEP_SKIP_FEATURE_MAP[next_step]
        if not flags.get(required_feature, False):
            steps_completed[next_step] = True
            current_idx += 1
            next_step = STEP_ORDER[current_idx + 1] if current_idx + 1 < len(STEP_ORDER) else "review_activate"
        else:
            break

    session.execute(
        text("""
            UPDATE onboarding_sessions SET
                current_step = :next_step, steps_completed = :steps,
                wizard_data = :wdata, updated_at = :now
            WHERE id = CAST(:sid AS uuid)
        """),
        {
            "sid": session_id,
            "next_step": next_step,
            "steps": json.dumps(steps_completed),
            "wdata": json.dumps(wizard_data),
            "now": now,
        },
    )
    session.commit()

    return {
        "status": "step_saved",
        "step_completed": step_name,
        "next_step": next_step,
        "steps_completed": steps_completed,
    }


# ---------------------------------------------------------------------------
# Checklist Endpoints
# ---------------------------------------------------------------------------

@router.get("/checklist/{business_id}")
async def get_onboarding_checklist(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Get the onboarding checklist for a business."""
    _require_admin(auth_ctx, session)
    rows = session.execute(
        text("SELECT * FROM onboarding_checklist WHERE business_id = :biz ORDER BY sort_order"),
        {"biz": business_id},
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.put("/checklist/{business_id}/{item_key}")
async def update_checklist_item(
    business_id: str,
    item_key: str,
    body: ChecklistUpdateBody,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Manually update a checklist item."""
    _require_admin(auth_ctx, session)

    now = _now_iso()
    params: Dict[str, Any] = {
        "biz": business_id,
        "key": item_key,
        "done": body.is_completed,
        "now": now,
        "cat_ts": now if body.is_completed else None,
        "cat_by": "admin" if body.is_completed else None,
        "notes": body.notes,
    }

    session.execute(
        text("""
            UPDATE onboarding_checklist SET
                is_completed = :done,
                completed_at = COALESCE(:cat_ts, completed_at),
                completed_by = COALESCE(:cat_by, completed_by),
                notes = COALESCE(:notes, notes),
                updated_at = :now
            WHERE business_id = :biz AND item_key = :key
        """),
        params,
    )
    session.commit()

    row = session.execute(
        text("SELECT * FROM onboarding_checklist WHERE business_id = :biz AND item_key = :key"),
        {"biz": business_id, "key": item_key},
    ).fetchone()
    return _row_to_dict(row) if row else {"status": "updated"}


# ---------------------------------------------------------------------------
# Onboarding Status Overview
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_all_onboarding_status(
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Get onboarding status for all businesses (for the admin businesses list)."""
    _require_admin(auth_ctx, session)

    businesses = session.execute(
        text("SELECT id, name, plan_tier, is_active, onboarding_completed FROM businesses ORDER BY created_at DESC")
    ).fetchall()

    checklists = session.execute(
        text("SELECT business_id, is_completed FROM onboarding_checklist")
    ).fetchall()

    completion_map: Dict[str, Dict[str, int]] = {}
    for row in checklists:
        biz_id = str(row.business_id)
        if biz_id not in completion_map:
            completion_map[biz_id] = {"total": 0, "completed": 0}
        completion_map[biz_id]["total"] += 1
        if row.is_completed:
            completion_map[biz_id]["completed"] += 1

    result = []
    for biz in businesses:
        biz_id = str(biz.id)
        comp = completion_map.get(biz_id, {"total": 0, "completed": 0})
        pct = round((comp["completed"] / comp["total"]) * 100) if comp["total"] > 0 else 0
        result.append({
            "business_id": biz_id,
            "business_name": biz.name,
            "plan_tier": biz.plan_tier,
            "is_active": biz.is_active,
            "onboarding_completed": getattr(biz, "onboarding_completed", False) or False,
            "checklist_progress": pct,
            "checklist_completed": comp["completed"],
            "checklist_total": comp["total"],
        })

    return result
