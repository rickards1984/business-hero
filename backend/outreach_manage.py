"""Typed OUT-8 controls; authenticated actor/tenant never come from the body."""
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator, field_validator
from sqlmodel import Session

import auth
from auth import get_user_business_context
from db import get_session
from services import outreach_manage as manage
from services.aria_actions import ActionRefused

router = APIRouter(prefix='/v1/outreach', tags=['Outreach'])


class Body(BaseModel):
    model_config = {'extra': 'forbid'}


def email(value):
    if not isinstance(value, str) or not re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', value) or len(value) > 254:
        raise ValueError('An exact email address is required')
    return value.lower()


class CampaignCreate(Body):
    name: str = Field(min_length=1, max_length=200)
    brand_id: UUID
    mailbox_id: UUID
    daily_cap: int = Field(ge=1, le=20, strict=True)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Name required')
        return value.strip()


class CampaignPatch(Body):
    version: int = Field(ge=1, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    mailbox_id: UUID | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=20, strict=True)

    @model_validator(mode='after')
    def present(self):
        if any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError('Null values are not accepted')
        if self.name is not None and not self.name.strip():
            raise ValueError('Name required')
        return self


class Step(Body):
    ordinal: int = Field(ge=0, le=2, strict=True)
    delay_business_days: int = Field(ge=0, le=7, strict=True)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=20000)

    @model_validator(mode='after')
    def valid(self):
        if not self.subject.strip() or not self.body.strip() or '\r' in self.subject or '\n' in self.subject:
            raise ValueError('Nonempty body and one-line subject required')
        if any(token in self.subject + self.body for token in ('{', '}', '${', '<%')):
            raise ValueError('Template interpolation is not supported')
        if self.delay_business_days != (0, 5, 7)[self.ordinal]:
            raise ValueError('Delays must be 0/5/7 business days')
        return self


class Sequence(Body):
    version: int = Field(ge=1, strict=True)
    steps: list[Step] = Field(min_length=3, max_length=3)

    @model_validator(mode='after')
    def ordered(self):
        if [s.ordinal for s in self.steps] != [0, 1, 2]:
            raise ValueError('Three ordered steps required')
        return self


class Approval(Body):
    version: int = Field(ge=1, strict=True)
    sequence_version: int = Field(ge=1, strict=True)


class Settings(Body):
    pause_all: bool | None = Field(default=None, strict=True)
    business_daily_cap: int | None = Field(default=None, ge=1, le=20, strict=True)
    owner_cc_default: bool | None = Field(default=None, strict=True)
    owner_cc_address: str | None = None

    @model_validator(mode='after')
    def valid(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError('Provide non-null settings')
        if self.owner_cc_address is not None:
            self.owner_cc_address = email(self.owner_cc_address)
        if self.owner_cc_default and not self.owner_cc_address:
            raise ValueError('Enabling CC requires an explicit address')
        return self


class MailboxCap(Body):
    daily_cap: int = Field(ge=1, le=20, strict=True)


class Suppression(Body):
    email: str
    reason: Literal['manual_opt_out']

    @field_validator('email')
    @classmethod
    def valid(cls, value):
        return email(value)


class Enrolment(Body):
    prospect_ids: list[UUID] = Field(min_length=1, max_length=50)


def execute(fn, session, context, body, ident=None):
    business = auth._load_business(session, context['business_id'])
    try:
        args = [session, business, context['user_id']]
        if ident is not None:
            args.append(str(ident))
        return fn(*args, body.model_dump(mode='json', exclude_unset=True))
    except ActionRefused as exc:
        session.rollback()
        raise HTTPException(exc.status_code, exc.detail) from None
    except Exception:
        session.rollback()
        raise


@router.post('/campaigns')
def create(body: CampaignCreate, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.create_campaign, session, context, body)


@router.patch('/campaigns/{campaign_id}')
def edit(campaign_id: UUID, body: CampaignPatch, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.edit_campaign, session, context, body, campaign_id)


@router.put('/campaigns/{campaign_id}/sequence')
def sequence(campaign_id: UUID, body: Sequence, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.sequence, session, context, body, campaign_id)


@router.post('/campaigns/{campaign_id}/approve-templates')
def approve(campaign_id: UUID, body: Approval, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.approve_templates, session, context, body, campaign_id)


@router.patch('/settings')
def settings(body: Settings, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.settings, session, context, body)


@router.patch('/mailboxes/{mailbox_id}')
def mailbox(mailbox_id: UUID, body: MailboxCap, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.mailbox_cap, session, context, body, mailbox_id)


@router.post('/suppressions')
def suppress(body: Suppression, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.suppress, session, context, body)


@router.post('/replies/{reply_id}/resolve')
def resolve(reply_id: UUID, body: Body, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.resolve, session, context, body, reply_id)


@router.post('/campaigns/{campaign_id}/enrolments')
def enrol(campaign_id: UUID, body: Enrolment, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.enrol, session, context, body, campaign_id)


@router.post('/campaigns/{campaign_id}/prepare')
def prepare(campaign_id: UUID, body: Body, context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    return execute(manage.prepare, session, context, body, campaign_id)
