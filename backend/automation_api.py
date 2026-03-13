"""
Automation Rules API — CRUD for automation rules, templates, executions.
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from db import get_session
from auth import get_user_business_context

_logger = logging.getLogger("automation_api")

router = APIRouter(prefix="/v1/automation", tags=["Automation Rules"])


def _to_rule(row) -> dict:
    """Convert automation_rules row to dict. Columns: id, business_id, name, description, trigger_type, conditions, action_type, action_config, requires_approval, is_active, last_triggered_at, total_executions, created_at, updated_at"""
    conditions = row[5]
    action_config = row[7]
    if isinstance(conditions, str):
        try:
            conditions = json.loads(conditions)
        except Exception:
            conditions = {}
    if isinstance(action_config, str):
        try:
            action_config = json.loads(action_config)
        except Exception:
            action_config = {}
    return {
        "id": str(row[0]),
        "business_id": str(row[1]),
        "name": row[2],
        "description": row[3] or "",
        "trigger_type": row[4],
        "conditions": conditions,
        "action_type": row[6],
        "action_config": action_config,
        "requires_approval": row[8] if row[8] is not None else True,
        "is_active": row[9],
        "last_triggered_at": row[10].isoformat() if row[10] else None,
        "total_executions": row[11] or 0,
        "created_at": row[12].isoformat() if row[12] else None,
        "updated_at": row[13].isoformat() if row[13] else None,
    }


@router.get("/rules")
async def list_automation_rules(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List automation rules for the current business"""
    business_id = str(auth_ctx["business_id"])
    rows = session.execute(
        text("""
            SELECT id, business_id, name, description, trigger_type, conditions,
                   action_type, action_config, requires_approval, is_active,
                   last_triggered_at, total_executions, created_at, updated_at
            FROM automation_rules
            WHERE business_id = :business_id
            ORDER BY created_at
        """),
        {"business_id": business_id},
    ).fetchall()

    return [
        _to_rule(r)
        for r in rows
    ]


@router.get("/templates")
async def list_automation_templates(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List available automation rule templates"""
    rows = session.execute(
        text("""
            SELECT id, name, description, trigger_type, conditions,
                   action_type, action_config, requires_approval, is_default, sort_order
            FROM automation_rule_templates
            ORDER BY sort_order
        """)
    ).fetchall()

    return [
        {
            "id": str(r[0]),
            "name": r[1],
            "description": r[2] or "",
            "trigger_type": r[3],
            "conditions": json.loads(r[4]) if isinstance(r[4], str) else (r[4] or {}),
            "action_type": r[5],
            "action_config": json.loads(r[6]) if isinstance(r[6], str) else (r[6] or {}),
            "requires_approval": r[7] if r[7] is not None else True,
            "is_default": r[8],
            "sort_order": r[9] or 0,
        }
        for r in rows
    ]


@router.post("/rules")
async def create_automation_rule(
    rule: dict[str, Any],
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Create a new automation rule (or clone from template)"""
    business_id = str(auth_ctx["business_id"])
    now = datetime.utcnow().isoformat()

    conditions = rule.get("conditions", {})
    action_config = rule.get("action_config", {})
    conditions_json = json.dumps(conditions) if isinstance(conditions, dict) else "{}"
    action_config_json = json.dumps(action_config) if isinstance(action_config, dict) else "{}"

    session.execute(
        text("""
            INSERT INTO automation_rules
            (business_id, name, description, trigger_type, conditions,
             action_type, action_config, requires_approval, is_active, updated_at)
            VALUES (:business_id, :name, :description, :trigger_type,
                    CAST(:conditions AS jsonb), CAST(:action_config AS jsonb),
                    :requires_approval, :is_active, :updated_at)
        """),
        {
            "business_id": business_id,
            "name": rule.get("name", "New Rule"),
            "description": rule.get("description", ""),
            "trigger_type": rule.get("trigger_type", "invoice_overdue"),
            "conditions": conditions_json,
            "action_config": action_config_json,
            "requires_approval": rule.get("requires_approval", True),
            "is_active": rule.get("is_active", False),
            "updated_at": now,
        },
    )
    session.commit()

    row = session.execute(
        text("""
            SELECT id, business_id, name, description, trigger_type, conditions,
                   action_type, action_config, requires_approval, is_active,
                   last_triggered_at, total_executions, created_at, updated_at
            FROM automation_rules
            WHERE business_id = :business_id
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"business_id": business_id},
    ).fetchone()

    if row:
        return _to_rule(row)
    return {"status": "created"}


@router.put("/rules/{rule_id}")
async def update_automation_rule(
    rule_id: str,
    updates: dict[str, Any],
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Update an automation rule"""
    business_id = str(auth_ctx["business_id"])
    now = datetime.utcnow().isoformat()

    set_clauses = ["updated_at = :updated_at"]
    params = {"rule_id": rule_id, "business_id": business_id, "updated_at": now}

    if "name" in updates:
        set_clauses.append("name = :name")
        params["name"] = updates["name"]
    if "description" in updates:
        set_clauses.append("description = :description")
        params["description"] = updates["description"]
    if "trigger_type" in updates:
        set_clauses.append("trigger_type = :trigger_type")
        params["trigger_type"] = updates["trigger_type"]
    if "conditions" in updates:
        set_clauses.append("conditions = CAST(:conditions AS jsonb)")
        params["conditions"] = json.dumps(updates["conditions"])
    if "action_type" in updates:
        set_clauses.append("action_type = :action_type")
        params["action_type"] = updates["action_type"]
    if "action_config" in updates:
        set_clauses.append("action_config = CAST(:action_config AS jsonb)")
        params["action_config"] = json.dumps(updates["action_config"])
    if "requires_approval" in updates:
        set_clauses.append("requires_approval = :requires_approval")
        params["requires_approval"] = updates["requires_approval"]
    if "is_active" in updates:
        set_clauses.append("is_active = :is_active")
        params["is_active"] = updates["is_active"]

    session.execute(
        text(f"""
            UPDATE automation_rules
            SET {", ".join(set_clauses)}
            WHERE id = :rule_id AND business_id = :business_id
        """),
        params,
    )
    session.commit()

    row = session.execute(
        text("""
            SELECT id, business_id, name, description, trigger_type, conditions,
                   action_type, action_config, requires_approval, is_active,
                   last_triggered_at, total_executions, created_at, updated_at
            FROM automation_rules
            WHERE id = :rule_id AND business_id = :business_id
        """),
        {"rule_id": rule_id, "business_id": business_id},
    ).fetchone()

    if row:
        return _to_rule(row)
    return {"status": "updated"}


@router.delete("/rules/{rule_id}")
async def delete_automation_rule(
    rule_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Delete an automation rule"""
    business_id = str(auth_ctx["business_id"])
    session.execute(
        text("DELETE FROM automation_rules WHERE id = :rule_id AND business_id = :business_id"),
        {"rule_id": rule_id, "business_id": business_id},
    )
    session.commit()
    return {"status": "deleted"}


@router.get("/executions")
async def list_automation_executions(
    limit: int = 50,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List recent automation executions"""
    business_id = str(auth_ctx["business_id"])
    rows = session.execute(
        text("""
            SELECT e.id, e.rule_id, e.business_id, e.status, e.trigger_data,
                   e.action_result, e.executed_at, e.created_at,
                   r.name as rule_name, r.trigger_type, r.action_type
            FROM automation_executions e
            LEFT JOIN automation_rules r ON e.rule_id = r.id
            WHERE e.business_id = :business_id
            ORDER BY e.created_at DESC
            LIMIT :limit
        """),
        {"business_id": business_id, "limit": limit},
    ).fetchall()

    return [
        {
            "id": str(r[0]),
            "rule_id": str(r[1]),
            "business_id": str(r[2]),
            "status": r[3],
            "trigger_data": json.loads(r[4]) if isinstance(r[4], str) else r[4],
            "action_result": json.loads(r[5]) if isinstance(r[5], str) else r[5],
            "executed_at": r[6].isoformat() if r[6] else None,
            "created_at": r[7].isoformat() if r[7] else None,
            "rule_name": r[8],
            "trigger_type": r[9],
            "action_type": r[10],
        }
        for r in rows
    ]


@router.post("/provision-defaults")
async def provision_default_rules(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Clone default automation rule templates for this business"""
    business_id = str(auth_ctx["business_id"])

    existing = session.execute(
        text("SELECT id FROM automation_rules WHERE business_id = :business_id LIMIT 1"),
        {"business_id": business_id},
    ).fetchone()

    if existing:
        return {"status": "already_provisioned", "count": 0}

    templates = session.execute(
        text("""
            SELECT name, description, trigger_type, conditions, action_type,
                   action_config, requires_approval
            FROM automation_rule_templates
            WHERE is_default = true
            ORDER BY sort_order
        """)
    ).fetchall()

    count = 0
    for t in templates:
        conditions = t[3]
        action_config = t[5]
        conditions_json = json.dumps(conditions) if isinstance(conditions, dict) else (conditions or "{}")
        action_config_json = json.dumps(action_config) if isinstance(action_config, dict) else (action_config or "{}")

        session.execute(
            text("""
                INSERT INTO automation_rules
                (business_id, name, description, trigger_type, conditions,
                 action_type, action_config, requires_approval, is_active)
                VALUES (:business_id, :name, :description, :trigger_type,
                        CAST(:conditions AS jsonb), :action_type,
                        CAST(:action_config AS jsonb),
                        :requires_approval, false)
            """),
            {
                "business_id": business_id,
                "name": t[0],
                "description": t[1] or "",
                "trigger_type": t[2],
                "conditions": conditions_json,
                "action_type": t[4],
                "action_config": action_config_json,
                "requires_approval": t[6] if t[6] is not None else True,
            },
        )
        count += 1

    session.commit()
    return {"status": "provisioned", "count": count}
