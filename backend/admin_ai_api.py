"""AI-1c: the admin page for Aria's models (docs/AI-1-TICKET.md, M2).
Platform admins only. Every route is a plain `def`, so FastAPI runs it in its
threadpool: the database work and a model test never block the event loop."""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from auth import get_platform_admin_context
from db import get_session
from services import ai_model_admin
from services.aria_actions import ActionRefused

router = APIRouter(prefix="/v1/admin/ai", tags=["Admin"])


class Choice(BaseModel):
    model_config = {"extra": "forbid"}
    chain: List[Dict[str, Any]] = Field(..., max_length=ai_model_admin.MAX_CHAIN)


class Candidate(BaseModel):
    model_config = {"extra": "forbid"}
    provider: str = Field(..., min_length=1, max_length=40)
    model: str = Field(..., min_length=1, max_length=120)


def _run(fn, *args):
    try:
        return fn(*args)
    except ActionRefused as exc:
        raise HTTPException(exc.status_code, exc.detail) from None


@router.get("/models")
def admin_ai_models(auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    return ai_model_admin.overview(session)


@router.put("/models/{task}")
def admin_ai_choose(task: str, body: Choice, auth_ctx: dict = Depends(get_platform_admin_context),
                    session: Session = Depends(get_session)):
    return _run(ai_model_admin.choose, session, task, body.chain, auth_ctx.get("user_id"))


@router.post("/models/{task}/revert")
def admin_ai_revert(task: str, auth_ctx: dict = Depends(get_platform_admin_context),
                    session: Session = Depends(get_session)):
    return _run(ai_model_admin.revert, session, task, auth_ctx.get("user_id"))


@router.post("/models/{task}/reset")
def admin_ai_reset(task: str, auth_ctx: dict = Depends(get_platform_admin_context),
                   session: Session = Depends(get_session)):
    return _run(ai_model_admin.reset, session, task, auth_ctx.get("user_id"))


@router.post("/models/{task}/test")
def admin_ai_test(task: str, body: Candidate, auth_ctx: dict = Depends(get_platform_admin_context),
                  session: Session = Depends(get_session)):
    return _run(ai_model_admin.test, session, task, body.provider, body.model)
