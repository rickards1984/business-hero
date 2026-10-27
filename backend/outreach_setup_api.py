"""OUT-15 setup wizard routes. The actor and tenant come from authentication,
never from the body; every write is owner-only in services.outreach_setup.
The public privacy page is the only unauthenticated route, and it shows an
approved notice and nothing else."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

import auth
from auth import get_user_business_context
from db import get_session
from services import outreach_autopilot as autopilot
from services import outreach_research as research
from services import outreach_setup as setup
from rate_limiting import limiter
from services.aria_actions import ActionRefused

router = APIRouter(prefix="/v1/outreach/setup", tags=["Outreach setup"])
public_router = APIRouter(tags=["Public"])


class Body(BaseModel):
    model_config = {"extra": "forbid"}


class BrandProfile(Body):
    """OUT-20: what Aria drafts from."""
    offer: Optional[str] = Field(default=None, max_length=1000)
    audience: Optional[str] = Field(default=None, max_length=1000)
    proof: Optional[str] = Field(default=None, max_length=1000)
    tone: Optional[str] = Field(default=None, max_length=1000)
    ask: Optional[str] = Field(default=None, max_length=1000)
    website: Optional[str] = Field(default=None, max_length=1000)


class Brand(Body):
    name: str = Field(min_length=1, max_length=120)
    sender_identity: str = Field(min_length=1, max_length=200)
    default_mailbox_id: Optional[UUID] = None
    profile: Optional[BrandProfile] = None


class BrandEdit(Body):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    sender_identity: Optional[str] = Field(default=None, min_length=1, max_length=200)
    profile: Optional[BrandProfile] = None


class EmailDraft(Body):
    subject: str = Field(max_length=200)
    body: str = Field(max_length=20000)


class Redraft(Body):
    notes: str = Field(min_length=1, max_length=4000)
    current: list[EmailDraft] = Field(min_length=3, max_length=3)


class Mailbox(Body):
    mailbox_id: UUID
    # Omitted on a recheck, so the owner's chosen limit is kept (review 4).
    daily_cap: Optional[int] = Field(default=None, ge=1, le=20, strict=True)


class Audience(Body):
    brand_id: UUID
    description: str = Field(min_length=1, max_length=2000)
    segments: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)


class AudienceApproval(Body):
    purpose: Optional[str] = Field(default=None, max_length=4000)
    necessity: Optional[str] = Field(default=None, max_length=4000)
    balancing_test: Optional[str] = Field(default=None, max_length=4000)
    safeguards: Optional[str] = Field(default=None, max_length=4000)
    review_due_at: Optional[datetime] = None


class Notice(Body):
    text: str = Field(min_length=1, max_length=20000)


class Campaign(Body):
    name: str = Field(min_length=1, max_length=120)
    brand_id: UUID
    mailbox_id: UUID
    compliance_id: UUID
    daily_cap: int = Field(default=5, ge=1, le=20, strict=True)


class Replace(Body):
    old_mailbox_id: UUID
    new_mailbox_id: UUID
    reason: str = Field(min_length=1, max_length=300)
    retire_old: bool = False


class Copy(Body):
    mailbox_id: UUID
    name: Optional[str] = Field(default=None, max_length=120)


def _run(fn, session, context, *args, **kwargs):
    business = auth._load_business(session, context["business_id"])
    try:
        return fn(session, business, context["user_id"], *args, **kwargs)
    except ActionRefused as exc:
        session.rollback()
        raise HTTPException(exc.status_code, exc.detail) from None
    except Exception:
        session.rollback()
        raise


def _body(body: Body) -> dict:
    return body.model_dump(mode="json", exclude_none=True)


@router.get("/status")
def get_status(context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return setup.status(session, auth._load_business(session, context["business_id"]))


@router.post("/begin")
def begin(context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.begin, session, context)


@router.post("/brands")
def brand(body: Brand, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.save_brand, session, context, _body(body))


@router.patch("/brands/{brand_id}")
def edit_brand(brand_id: UUID, body: BrandEdit, context=Depends(get_user_business_context),
               session: Session = Depends(get_session)):
    return _run(setup.update_brand, session, context, str(brand_id), _body(body))


@router.post("/campaigns/{campaign_id}/redraft")
def redraft(campaign_id: UUID, body: Redraft, context=Depends(get_user_business_context),
            session: Session = Depends(get_session)):
    return _run(setup.redraft_emails, session, context, str(campaign_id), _body(body))


@router.post("/mailboxes")
def register(body: Mailbox, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.register_mailbox, session, context, _body(body))


@router.post("/mailboxes/{mailbox_id}/check")
def check(mailbox_id: UUID, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.check_mailbox_health, session, context, str(mailbox_id))


@router.post("/audience/draft")
def draft_audience(body: Audience, context=Depends(get_user_business_context),
                   session: Session = Depends(get_session)):
    return _run(setup.draft_audience, session, context, _body(body))


@router.post("/audience/{compliance_id}/approve")
def approve_audience(compliance_id: UUID, body: AudienceApproval, context=Depends(get_user_business_context),
                     session: Session = Depends(get_session)):
    return _run(setup.approve_audience, session, context, str(compliance_id), _body(body))


@router.post("/brands/{brand_id}/privacy/draft")
def draft_notice(brand_id: UUID, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.draft_privacy_notice, session, context, str(brand_id))


@router.post("/brands/{brand_id}/privacy/approve")
def approve_notice(brand_id: UUID, body: Notice, context=Depends(get_user_business_context),
                   session: Session = Depends(get_session)):
    return _run(setup.approve_privacy_notice, session, context, str(brand_id), _body(body))


@router.post("/campaign")
def campaign(body: Campaign, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.create_first_campaign, session, context, _body(body))


@router.post("/finish")
def finish(context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.finish, session, context)


@router.post("/mailboxes/replace")
def replace(body: Replace, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(setup.replace_mailbox, session, context, _body(body))


@router.post("/campaigns/{campaign_id}/copy")
def copy(campaign_id: UUID, body: Copy, context=Depends(get_user_business_context),
         session: Session = Depends(get_session)):
    return _run(setup.copy_campaign_to_mailbox, session, context, str(campaign_id), _body(body))


class ResearchConfig(Body):
    brand_id: UUID                     # OUT-18: research is set per brand
    enabled: Optional[bool] = None
    monthly_cap_pence: Optional[int] = Field(default=None, ge=2000, le=100000, strict=True)


class Lessons(Body):
    brand_id: UUID
    lessons: list[str] = Field(default_factory=list, max_length=30)


@router.get("/research")
def research_status(context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return research.status(session, auth._load_business(session, context["business_id"]))


@router.post("/research")
def research_configure(body: ResearchConfig, context=Depends(get_user_business_context),
                       session: Session = Depends(get_session)):
    return _run(research.configure, session, context, _body(body))


@router.post("/research/lessons")
def research_lessons(body: Lessons, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return _run(research.save_lessons, session, context, body.lessons, brand_id=str(body.brand_id))


class Grant(Body):
    version: int = Field(ge=1, strict=True)
    sequence_version: int = Field(ge=1, strict=True)


@router.get("/autopilot")
def autopilot_status(context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return autopilot.status(session, auth._load_business(session, context["business_id"]))


@router.post("/autopilot/{campaign_id}")
def autopilot_grant(campaign_id: UUID, body: Grant, context=Depends(get_user_business_context),
                    session: Session = Depends(get_session)):
    return _run(autopilot.grant, session, context, str(campaign_id), _body(body))


@router.delete("/autopilot/{campaign_id}")
def autopilot_revoke(campaign_id: UUID, context=Depends(get_user_business_context),
                     session: Session = Depends(get_session)):
    return _run(autopilot.revoke, session, context, str(campaign_id))


@public_router.get("/p/outreach-privacy/{brand_id}", response_class=HTMLResponse)
@limiter.limit("60/minute")   # public and unauthenticated (Codex OUT-15 review 1)
def public_notice(request: Request, brand_id: str, session: Session = Depends(get_session)):
    body = setup.public_privacy_notice(session, brand_id)
    if not body:
        raise HTTPException(404, "Not found")
    return HTMLResponse(setup.render_public_notice(body), headers={"Cache-Control": "public, max-age=300"})
