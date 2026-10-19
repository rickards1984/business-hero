"""Aria's standing permissions — the owner's switches (AUTO-1).

GET /v1/automations/invoice-chasing   the current rules (defaults merged)
PUT /v1/automations/invoice-chasing   switch on/off and change the rules

Stored in business_settings.settings.automations.invoice_chasing, merged so
nothing else in the document is touched. Every value is clamped by
services.automations.chase_settings, here and again wherever it is read.
Read-only and suspended accounts are refused by the shared context
dependency (DECISION 3) on PUT.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends
from sqlalchemy import text
from sqlmodel import Session

from auth import get_user_business_context, require_feature
from db import get_session
from services import automations

router = APIRouter(prefix="/v1/automations", tags=["Aria automations"],
                   dependencies=[Depends(require_feature("aria_chat")),
                                 Depends(require_feature("invoicing"))])


def _document(session: Session, business_id: str):
    # Locked for the read-modify-write, so two saves cannot interleave and a
    # switch-off cannot be undone by an earlier, slower save (Codex AUTO-1
    # review 1, finding 5). SQLite (tests) has no row locks.
    lock = " FOR UPDATE" if session.get_bind().dialect.name == "postgresql" else ""
    row = session.execute(text("SELECT id, settings FROM business_settings WHERE business_id = :b" + lock),
                          {"b": business_id}).fetchone()
    if row is None:
        return None, {}
    raw = row[1]
    return row[0], (raw if isinstance(raw, dict) else json.loads(raw or "{}"))


def _save(session: Session, business_id: str, row_id, document: dict) -> None:
    cast = "CAST(:s AS jsonb)" if session.get_bind().dialect.name == "postgresql" else ":s"
    moment = datetime.now(timezone.utc).replace(tzinfo=None)  # the column has no zone
    if row_id is None:
        session.execute(text(
            f"INSERT INTO business_settings (id, business_id, settings, created_at, updated_at) "
            f"VALUES (:id, :b, {cast}, :now, :now)"),
            {"id": str(uuid.uuid4()), "b": business_id, "s": json.dumps(document), "now": moment})
    else:
        session.execute(text(
            f"UPDATE business_settings SET settings = {cast}, updated_at = :now WHERE id = :id"),
            {"id": str(row_id), "s": json.dumps(document), "now": moment})
    session.commit()


@router.get("/invoice-chasing")
def get_invoice_chasing(auth_ctx: dict = Depends(get_user_business_context),
                        session: Session = Depends(get_session)):
    _, document = _document(session, str(auth_ctx["business_id"]))
    return automations.chase_settings((document.get("automations") or {}).get(automations.KIND))


@router.put("/invoice-chasing")
def put_invoice_chasing(changes: Dict[str, Any] = Body(...),
                        auth_ctx: dict = Depends(get_user_business_context),
                        session: Session = Depends(get_session)):
    business_id = str(auth_ctx["business_id"])
    row_id, document = _document(session, business_id)
    current = (document.get("automations") or {}).get(automations.KIND) or {}
    merged = automations.chase_settings({**current, **{k: v for k, v in changes.items()
                                                        if k in automations.CHASE_DEFAULTS}})
    document = {**document, "automations": {**(document.get("automations") or {}),
                                            automations.KIND: merged}}
    _save(session, business_id, row_id, document)
    return merged


# ------------------------------------------------- AUTO-2: replies to chases ---

def _business_ref(auth_ctx: dict):
    from types import SimpleNamespace
    return SimpleNamespace(id=str(auth_ctx["business_id"]))


@router.get("/replies")
def list_chase_replies(auth_ctx: dict = Depends(get_user_business_context),
                       session: Session = Depends(get_session)):
    """Replies to chases awaiting the owner. Chasing those customers is
    paused until the owner chooses Resume or Stop."""
    from services import chase_replies
    return chase_replies.open_replies(session, _business_ref(auth_ctx))


@router.post("/replies/{reply_id}/resolve")
def resolve_chase_reply(reply_id: str, decision: Dict[str, Any] = Body(...),
                        auth_ctx: dict = Depends(get_user_business_context),
                        session: Session = Depends(get_session)):
    """{"decision": "resume" | "stop"}. Stop ends automatic chasing of the
    invoices the reply is about; it never marks anything paid."""
    from fastapi import HTTPException
    from services import chase_replies
    try:
        return chase_replies.resolve(session, _business_ref(auth_ctx), reply_id,
                                     auth_ctx.get("user_id"), str(decision.get("decision") or ""))
    except LookupError:
        raise HTTPException(status_code=404, detail="Reply not found")
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already" in str(exc) else 422, detail=str(exc))
