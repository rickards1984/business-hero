"""OUT-4: bounded, tenant-scoped reads shared by HTTP and Aria (P2/P8/P9).

Only fixed table/column/predicate literals enter SQL. Values always bind, and
no ORM tables are registered. Retention redaction is minimization, not erasure.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

import auth
from auth import assert_feature_access, get_user_business_context
from db import engine, get_session


@dataclass(frozen=True)
class Read:
    path: str
    tool: str
    table: str
    fields: str
    parent: str = ""
    detail: bool = False


PROSPECT_FIELDS = "id company name role domain stage eligibility subscriber_type fit_score confidence evidence_checked_at"
CAMPAIGN_FIELDS = "id brand_id mailbox_id name sequence_version version status timezone daily_cap"
READS = (
    Read("brands", "list_outreach_brands", "brands", "id name privacy_url sender_identity version"),
    Read("prospects", "list_outreach_prospects", "prospects", PROSPECT_FIELDS),
    Read("prospects/{prospect_id}", "get_outreach_prospect", "prospects", PROSPECT_FIELDS, "prospect_id", True),
    Read("prospects/{prospect_id}/evidence", "get_outreach_evidence", "evidence",
         "id prospect_id source_type source_url excerpt fact_type fact_value confidence fetched_at expires_at", "prospect_id"),
    Read("prospects/{prospect_id}/timeline", "get_outreach_prospect_timeline", "messages",
         "id prospect_id campaign_id mailbox_id kind origin direction state accepted_at created_at", "prospect_id"),
    Read("campaigns", "list_outreach_campaigns", "campaigns", CAMPAIGN_FIELDS),
    Read("campaigns/{campaign_id}", "get_outreach_campaign", "campaigns", CAMPAIGN_FIELDS, "campaign_id", True),
    Read("campaigns/{campaign_id}/sequence", "get_outreach_sequence", "sequence_steps",
         "id campaign_id sequence_version ordinal delay_business_days approved_at", "campaign_id"),
    Read("replies", "list_outreach_replies", "replies",
         "id prospect_id mailbox_id inbound_email_id matched_message_id owner_id category confidence resolution received_at"),
    Read("mailboxes", "list_outreach_mailboxes", "mailboxes",
         "id mailbox_id enabled daily_cap warmup_stage sending_days health_status health_checked_at"),
    Read("compliance", "get_outreach_compliance_status", "compliance",
         "id brand_id version decision reviewed_at review_due_at"),
    Read("settings", "get_outreach_settings_and_permissions", "settings",
         "id pause_all timezone business_daily_cap owner_cc_default retention_policy_version", detail=True),
    Read("summary", "outreach_summary", "", "", detail=True),
    Read("knowledge", "get_outreach_knowledge", "knowledge",
         "id brand_id topic answer source_reference version status approved_at review_due_at retired_at"),
    Read("reply-slots", "list_outreach_reply_slots", "reply_slots",
         "id prospect_id reply_id mailbox_id action_id state generation reserved_at dispatched_at settled_at released_at"),
)
READ_BY_TOOL = {read.tool: read for read in READS}


def now():
    return datetime.now(timezone.utc)


def _load_business(session, business_id):
    return auth._load_business(session, business_id)


def argument_schema(read):
    properties = {}
    if not read.detail:
        properties.update(limit={"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                          offset={"type": "integer", "minimum": 0, "maximum": 10000, "default": 0})
    if read.parent:
        properties[read.parent] = {"type": "string", "format": "uuid"}
    if read.table in ("replies", "reply_slots"):
        properties["mailbox_id"] = {"type": "string", "format": "uuid"}
    if read.table == "knowledge":
        properties["brand_id"] = {"type": "string", "format": "uuid"}
    return {"type": "object", "properties": properties,
            "required": [read.parent] if read.parent else [], "additionalProperties": False}


def _arguments(read, arguments, *, http=False):
    schema = argument_schema(read)
    if not isinstance(arguments, dict) or set(arguments) - set(schema["properties"]):
        raise HTTPException(422, "Invalid arguments")
    if any(key not in arguments for key in schema["required"]):
        raise HTTPException(422, "Invalid arguments")
    result = {}
    for key, spec in schema["properties"].items():
        if key not in arguments and "default" not in spec:
            continue
        value = arguments.get(key, spec.get("default"))
        if spec["type"] == "integer":
            if http and isinstance(value, str) and value.isascii() and value.isdecimal():
                value = int(value) if len(value) <= 10 else -1
            if type(value) is not int or not spec["minimum"] <= value <= spec["maximum"]:
                raise HTTPException(422, "Invalid pagination")
        else:
            try:
                if not isinstance(value, str):
                    raise ValueError
                value = str(UUID(value))
            except (ValueError, AttributeError):
                raise HTTPException(422, "Invalid identifier") from None
        result[key] = value
    return result


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


DATE_FIELDS = frozenset("evidence_checked_at fetched_at expires_at accepted_at created_at approved_at received_at health_checked_at reviewed_at review_due_at retired_at reserved_at dispatched_at settled_at released_at".split())
BOOL_FIELDS = frozenset(("enabled", "pause_all", "owner_cc_default"))
TEXT_FIELDS = frozenset("name privacy_url sender_identity company role domain stage eligibility subscriber_type source_type source_url excerpt fact_type fact_value kind origin direction state status timezone category resolution health_status decision topic answer source_reference".split())


def _project(read, row, clock):
    item = {}
    for field in read.fields.split():
        value = row[field]
        if value is not None:
            if field in DATE_FIELDS:
                value = _utc(value).isoformat()
            elif field in BOOL_FIELDS:
                value = bool(value)
            elif isinstance(value, UUID):
                value = str(value)
            elif isinstance(value, Decimal):
                value = float(value)
            if isinstance(value, str):
                value = value[:4000 if field == "answer" else 2000 if field in ("excerpt", "fact_value", "source_reference") else 1000]
        item[field] = value
    stale = False
    expiry = row.get("retention_due_at") if read.table == "prospects" else row.get("expires_at")
    if expiry is not None and _utc(expiry) <= clock:
        stale = True
        for field in (("company", "name", "role", "domain") if read.table == "prospects" else ("excerpt", "fact_value")):
            item[field] = None
    if read.table == "knowledge":
        stale = (row["status"] != "approved" or not row["approved_at"] or
                 _utc(row["approved_at"]) > clock or _utc(row["review_due_at"]) <= clock)
    return item, stale


def _count(session, table, where, params):
    return session.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), params).scalar_one()


def _owned(session, table, identifier, business_id, fields="id"):
    row = session.execute(text(
        f"SELECT {fields} FROM {table} WHERE business_id = :business_id AND id = :id LIMIT 1"
    ), {"business_id": business_id, "id": identifier}).mappings().first()
    if row is None:
        raise HTTPException(404, "Not found")
    return row


# Each fixed predicate is applied alongside business_id, including aggregates.
SUMMARY = {
    "prospects": ("prospects", "1=1", "prospects"),
    "campaigns": ("campaigns", "1=1", "campaigns"),
    "accepted_live": ("messages", "origin='live' AND direction='outbound' AND state='accepted'", "prospects"),
    "unknown_live": ("messages", "origin='live' AND direction='outbound' AND state='unknown'", "prospects"),
    "imported_messages": ("messages", "origin='import'", "prospects"),
    "human_replies": ("replies", "category IN ('interested','question','not_now','unsubscribe','objection','wrong_person','referral')", "replies"),
    "stage_meeting": ("prospects", "stage='meeting'", "prospects"),
    "stage_won": ("prospects", "stage='won'", "prospects"),
}


def _read(session, read, arguments, business_id):
    # This assertion also applies to platform admins, independently of the
    # HTTP dependency's existing bypass. Never accept a model-supplied grant.
    assert_feature_access(_load_business(session, business_id), "outreach", retained_history=read.table in ("replies", "reply_slots", "knowledge"))
    params = {"business_id": str(business_id), **arguments}
    where = "business_id = :business_id"
    if read.parent and not read.detail:
        parent_table = "outreach_prospects" if read.parent == "prospect_id" else "outreach_campaigns"
        parent = _owned(session, parent_table, arguments[read.parent], params["business_id"],
                        "sequence_version" if read.table == "sequence_steps" else "id")
        where += f" AND {read.parent} = :{read.parent}"
        if read.table == "sequence_steps":
            where += " AND sequence_version = :sequence_version"
            params["sequence_version"] = parent["sequence_version"]
    elif read.parent:
        where += f" AND id = :{read.parent}"
    if "mailbox_id" in arguments:
        _owned(session, "email_accounts", arguments["mailbox_id"], params["business_id"])
        where += " AND mailbox_id = :mailbox_id"

    if read.path == "summary":
        totals = {key: _count(session, "outreach_" + table,
                             where + " AND " + predicate, params)
                  for key, (table, predicate, _) in SUMMARY.items()}
        return {"totals": totals,
                "sources": {key: "/v1/outreach/" + source for key, (_, _, source) in SUMMARY.items()},
                "data_quality": "available" if any(totals.values()) else "none",
                "message": "Stored outreach counts available." if any(totals.values()) else "None available."}
    if "brand_id" in arguments:
        _owned(session, "outreach_brands", arguments["brand_id"], params["business_id"])
        where += " AND brand_id = :brand_id"

    # Cap text in SQL as well as at serialization, so large source text cannot
    # turn a bounded row count into an unbounded response/context allocation.
    columns = [f"substr({field}, 1, {4000 if field == 'answer' else 2000 if field in ('excerpt', 'fact_value', 'source_reference') else 1000}) AS {field}"
               if field in TEXT_FIELDS else field for field in read.fields.split()]
    if read.table == "prospects":
        columns.append("retention_due_at")  # Internal expiry input, never returned.
    order = "ordinal ASC, id ASC" if read.table == "sequence_steps" else "created_at DESC, id ASC"
    total = None if read.detail else _count(session, "outreach_" + read.table, where, params)
    params.update(limit=1 if read.detail else arguments["limit"],
                  offset=0 if read.detail else arguments["offset"])
    rows = session.execute(text(
        f"SELECT {', '.join(columns)} FROM outreach_{read.table} WHERE {where} "
        f"ORDER BY {order} LIMIT :limit OFFSET :offset"
    ), params).mappings().all()
    if read.parent and read.detail and not rows:
        raise HTTPException(404, "Not found")
    projected = [_project(read, row, now()) for row in rows]
    quality = "stale" if any(stale for _, stale in projected) else "available" if rows else "none"
    result = {"data_quality": quality, "message": "Outreach records available." if rows else "None available."}
    if read.detail:
        result["item"] = projected[0][0] if projected else None
        if read.path == "settings":
            result["permissions"] = {"status": "not_available",
                                     "message": "None available: outreach permission projection awaits OUT-6/OUT-11."}
    else:
        result.update(items=[item for item, _ in projected], total=total,
                      limit=arguments["limit"], offset=arguments["offset"])
    return result


# Told only "not enabled for your plan", Aria invented an "Outreach add-on"
# with dashboards (Mike, 23 Oct 2026). State the facts and forbid the rest.
_NOT_ON_PLAN = {"Feature 'outreach' not enabled for your plan", "Feature 'outreach' disabled"}
NOT_ON_PLAN_ERROR = ("Outreach isn't switched on for this business. It comes with the Business "
                     "plan, and it is still being built: it is not available yet.")
NOT_ON_PLAN_GUIDANCE = (
    "Tell the owner plainly that Business Hero's outreach feature isn't on their account: it comes "
    "with the Business plan, and it is still being built. Do not invent an add-on, dashboards or "
    "sequence statistics. If they send outreach emails themselves, offer to check their inbox for "
    "replies to those emails (for example, from a person or company they name, or over the last "
    "week) and flag any that need a response. Do not offer unrelated checks such as calls.")


def execute_read_tool(tool_name, arguments, business_id):
    """Dispatcher boundary: business_id comes only from trusted tool context."""
    try:
        read = READ_BY_TOOL[tool_name]
        validated = _arguments(read, arguments)
        with Session(engine) as session:
            return _read(session, read, validated, business_id)
    except HTTPException as exc:
        if exc.status_code == 403 and str(exc.detail) in _NOT_ON_PLAN:
            return {"status_code": 403, "error": NOT_ON_PLAN_ERROR, "aria_guidance": NOT_ON_PLAN_GUIDANCE}
        return {"status_code": exc.status_code, "error": exc.detail}
    except SQLAlchemyError:
        return {"status_code": 500, "error": "Outreach records unavailable"}


router = APIRouter(prefix="/v1/outreach", tags=["Outreach"])


def _endpoint(read):
    def endpoint(request: Request, context: dict = Depends(get_user_business_context),
                 session: Session = Depends(get_session)):
        query = request.query_params
        if any(len(query.getlist(key)) != 1 for key in query) or set(query) & set(request.path_params):
            raise HTTPException(422, "Invalid arguments")
        arguments = _arguments(read, {**dict(query), **request.path_params}, http=True)
        try:
            return _read(session, read, arguments, context["business_id"])
        except SQLAlchemyError:
            raise HTTPException(500, "Outreach records unavailable") from None
    return endpoint


for _spec in READS:
    router.add_api_route("/" + _spec.path, _endpoint(_spec), methods=["GET"], name=_spec.tool)
