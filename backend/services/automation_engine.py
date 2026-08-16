"""
Automation rule engine.
Evaluates trigger conditions and executes configured actions.
"""

import json
import logging
from datetime import datetime, timezone, date, timedelta

from sqlalchemy import text

from db import get_session_context, get_session_transactional

logger = logging.getLogger(__name__)


async def evaluate_automation_rules(business_id: str) -> None:
    """
    Evaluate all active automation rules for a business.
    Called by the scheduler periodically (every 5 minutes).
    """
    with get_session_context() as session:
        rows = session.execute(
            text("""
                SELECT id, name, description, trigger_type, conditions,
                       action_type, action_config, requires_approval
                FROM automation_rules
                WHERE business_id = :business_id AND is_active = true
            """),
            {"business_id": business_id},
        ).fetchall()

    for row in rows:
        rule = {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "trigger_type": row[3],
            "conditions": row[4] or {},
            "action_type": row[5],
            "action_config": row[6] or {},
            "requires_approval": row[7] if row[7] is not None else True,
        }
        if isinstance(rule["conditions"], str):
            try:
                rule["conditions"] = json.loads(rule["conditions"])
            except Exception:
                rule["conditions"] = {}
        if isinstance(rule["action_config"], str):
            try:
                rule["action_config"] = json.loads(rule["action_config"])
            except Exception:
                rule["action_config"] = {}

        try:
            should_trigger = await _check_rule_trigger(rule, business_id)
            if should_trigger:
                await _execute_automation_rule(rule, business_id)
        except Exception as e:
            logger.error(f"[Automation] Error evaluating rule {rule['id']}: {e}")


async def _check_rule_trigger(rule: dict, business_id: str) -> bool:
    """Check if a rule's trigger conditions are met"""
    trigger_type = rule.get("trigger_type")
    conditions = rule.get("conditions", {})

    if trigger_type == "invoice_overdue":
        days = conditions.get("days_overdue", 7)
        min_amount = float(conditions.get("min_amount", 0))
        cutoff_date = (date.today() - timedelta(days=days)).isoformat()

        with get_session_context() as session:
            overdue = session.execute(
                text("""
                    SELECT id, amount_due, due_date
                    FROM invoices
                    WHERE business_id = :business_id
                      AND status IN ('unpaid', 'authorised', 'sent')
                      AND due_date < :cutoff
                      AND (archived IS NULL OR archived = false)
                """),
                {"business_id": business_id, "cutoff": cutoff_date},
            ).fetchall()

        qualifying = [
            r for r in overdue
            if float(r[1] or 0) >= min_amount
        ]
        if not qualifying:
            return False

        # Check if we already actioned this rule today
        today = date.today().isoformat()
        with get_session_context() as session:
            already = session.execute(
                text("""
                    SELECT id FROM automation_executions
                    WHERE rule_id = :rule_id
                      AND created_at >= :today
                    LIMIT 1
                """),
                {"rule_id": rule["id"], "today": today},
            ).fetchone()
        return not bool(already)

    elif trigger_type == "email_action_required":
        with get_session_context() as session:
            row = session.execute(
                text("""
                    SELECT id FROM email_messages
                    WHERE business_id = :business_id
                      AND ai_category = 'Action Required'
                      AND is_unread = true
                    LIMIT 1
                """),
                {"business_id": business_id},
            ).fetchone()
        return bool(row)

    elif trigger_type == "kb_gap_detected":
        # KB gap detection happens during briefing generation
        return False

    return False


async def _execute_automation_rule(rule: dict, business_id: str) -> None:
    """Execute an automation rule's action"""
    action_type = rule.get("action_type")
    action_config = rule.get("action_config", {})
    requires_approval = rule.get("requires_approval", True)

    logger.info(f"[Automation] Executing rule: {rule.get('name')} ({action_type})")

    execution_id = None
    with get_session_transactional() as session:
        row = session.execute(
            text("""
                INSERT INTO automation_executions
                (rule_id, business_id, status, trigger_data)
                VALUES (:rule_id, :business_id, :status, :trigger_data)
                RETURNING id
            """),
            {
                "rule_id": rule["id"],
                "business_id": business_id,
                "status": "pending" if requires_approval else "executed",
                "trigger_data": json.dumps({"triggered_at": datetime.now(timezone.utc).isoformat()}),
            },
        ).fetchone()
        if row:
            execution_id = str(row[0])

    if requires_approval:
        with get_session_context() as session:
            cfg = session.execute(
                text("SELECT phone_number FROM whatsapp_configs WHERE business_id = :bid AND enabled = true"),
                {"bid": business_id},
            ).fetchone()

        if cfg:
            from services.whatsapp_service import (
                send_whatsapp_message,
                get_business_name,
            )

            rule_name = (rule.get("name") or "").strip() or "Unknown automation"
            rule_desc = (rule.get("description") or "").strip() or "No description provided"

            # Send as `alert` (3-variable template), not `automation_report`
            # (4-variable summary template). For per-rule approval requests,
            # the alert template is the semantically correct choice.
            business_name = get_business_name(business_id)
            alert_content = f"🤖 Automation: {rule_name}\n\n{rule_desc}"
            action_options = "Reply 1️⃣ to approve or 2️⃣ to skip"

            await send_whatsapp_message(
                to_number=cfg[0],
                body=json.dumps({
                    "1": business_name,
                    "2": alert_content,
                    "3": action_options,
                }),
                business_id=business_id,
                message_type="alert",
            )

            if execution_id:
                with get_session_transactional() as session:
                    for num, lbl, atype, aconfig in [
                        (1, "Approve", "approve_automation", {"execution_id": execution_id, "action_type": action_type, "action_config": action_config}),
                        (2, "Skip", "reject_automation", {"execution_id": execution_id}),
                    ]:
                        session.execute(
                            text("""
                                INSERT INTO whatsapp_pending_actions
                                (business_id, action_number, action_label, action_type, action_config, status)
                                VALUES (:business_id, :action_number, :label, :atype, :config, 'pending')
                            """),
                            {
                                "business_id": business_id,
                                "action_number": num,
                                "label": lbl,
                                "atype": atype,
                                "config": json.dumps(aconfig),
                            },
                        )
        return

    await _do_execute_action(action_type, action_config, business_id, execution_id, rule["id"])


async def _do_execute_action(
    action_type: str,
    config: dict,
    business_id: str,
    execution_id: str | None,
    rule_id: str | None,
) -> None:
    """Execute the actual automation action"""
    if action_type == "send_chase_email":
        stage = config.get("stage", 1)
        logger.info(f"[Automation] Would send Stage {stage} chase for business {business_id}")

    elif action_type == "create_task":
        with get_session_transactional() as session:
            session.execute(
                text("""
                    INSERT INTO tasks (business_id, title, description, status, priority, category, source)
                    VALUES (:business_id, :title, :description, 'open', :priority, :category, 'automation')
                """),
                {
                    "business_id": business_id,
                    "title": config.get("title", "Automated task"),
                    "description": config.get("description", "Created by automation rule"),
                    "priority": config.get("priority", "medium"),
                    "category": config.get("category", "General"),
                },
            )
        logger.info(f"[Automation] Created task: {config.get('title', 'Automated task')}")

    elif action_type == "send_whatsapp_alert":
        from services.alert_dispatcher import dispatch_alert
        await dispatch_alert(business_id, config.get("template", "general"), config)

    if execution_id:
        with get_session_transactional() as session:
            session.execute(
                text("""
                    UPDATE automation_executions
                    SET status = 'executed', executed_at = :now,
                        action_result = :result
                    WHERE id = :execution_id
                """),
                {
                    "execution_id": execution_id,
                    "now": datetime.now(timezone.utc).isoformat(),
                    "result": json.dumps({"action_type": action_type, "success": True}),
                },
            )

    if rule_id:
        with get_session_transactional() as session:
            session.execute(
                text("""
                    UPDATE automation_rules
                    SET last_triggered_at = :now
                    WHERE id = :rule_id
                """),
                {"rule_id": rule_id, "now": datetime.now(timezone.utc).isoformat()},
            )
