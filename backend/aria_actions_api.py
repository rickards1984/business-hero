"""Aria's approval cards — NS-B10.

GET   /v1/aria/actions               this business's cards awaiting approval
GET   /v1/aria/actions/{id}          one card's authoritative state (to reconcile)
POST  /v1/aria/actions/{id}/approve  the tap: do exactly what the card shows, once.
                                     The body names the `version` on screen; a card
                                     changed since is refused (409), never sent
PATCH /v1/aria/actions/{id}          edit a card before approving it
POST  /v1/aria/actions/{id}/dismiss  "Not now"

Every route is scoped to the caller's business; another business's card is
404, never 403, so its existence is not leaked. Read-only and suspended
accounts are refused on the mutating routes by the shared context
dependency (DECISION 3). The endpoints are plain `def`: FastAPI runs them in
a worker thread, where approve() may run a calendar booking to completion.
"""

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from auth import get_user_business_context, require_feature
from db import get_session
from services import aria_actions

router = APIRouter(prefix="/v1/aria/actions", tags=["Aria actions"],
                   dependencies=[Depends(require_feature("aria_chat"))])


def _load_business(session: Session, business_id: str):
    from auth import _load_business as load
    return load(session, business_id)


def _business(session: Session, auth_ctx: dict):
    business = _load_business(session, str(auth_ctx["business_id"]))
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def _refused(exc: aria_actions.ActionRefused) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("")
def list_actions(auth_ctx: dict = Depends(get_user_business_context),
                 session: Session = Depends(get_session)):
    return {"actions": aria_actions.list_open(session, _business(session, auth_ctx))}


class Approval(BaseModel):
    version: str


@router.get("/{action_id}")
def get_action(action_id: str,
               auth_ctx: dict = Depends(get_user_business_context),
               session: Session = Depends(get_session)):
    try:
        return aria_actions.get(session, _business(session, auth_ctx), action_id)
    except aria_actions.ActionRefused as exc:
        raise _refused(exc)


@router.post("/{action_id}/approve")
def approve_action(action_id: str, approval: Approval,
                   auth_ctx: dict = Depends(get_user_business_context),
                   session: Session = Depends(get_session)):
    try:
        return aria_actions.approve(session, _business(session, auth_ctx), action_id,
                                    auth_ctx.get("user_id"), approval.version)
    except aria_actions.ActionRefused as exc:
        raise _refused(exc)


@router.patch("/{action_id}")
def edit_action(action_id: str, changes: Dict[str, Any] = Body(...),
                auth_ctx: dict = Depends(get_user_business_context),
                session: Session = Depends(get_session)):
    try:
        return aria_actions.edit(session, _business(session, auth_ctx), action_id, changes)
    except aria_actions.ActionRefused as exc:
        raise _refused(exc)


@router.post("/{action_id}/dismiss")
def dismiss_action(action_id: str,
                   auth_ctx: dict = Depends(get_user_business_context),
                   session: Session = Depends(get_session)):
    try:
        return aria_actions.dismiss(session, _business(session, auth_ctx), action_id)
    except aria_actions.ActionRefused as exc:
        raise _refused(exc)
