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
    row = session.execute(text("SELECT id, settings FROM business_settings WHERE business_id = :b"),
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
