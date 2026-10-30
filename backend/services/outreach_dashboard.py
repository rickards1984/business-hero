"""OUT-14 — the outreach dashboard (docs/OUT-14-TICKET.md). YELLOW.

Mike, 30 Oct 2026: the approved layout (brand switcher, Aria's summary, Needs
you, pipeline, results for a period, spend); meetings and wins are marked by
the owner and never inferred from interest; spend is the owner's only.

One function, `build`, computes every number for the screen and for Aria's
`get_outreach_dashboard` tool, by the design's definitions
(docs/OUT-1-DESIGN.md line 46):
  * "accepted" is the provider's acceptance, not delivery;
  * imported history never counts as contact;
  * a human reply is one of HUMAN (bounces, out-of-office, our own messages,
    complaints and unknown categories are not);
  * a rate with nobody contacted is unavailable (None), never 0%.
Reads are tenant-scoped by business_id on every table; nothing here sends.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from services import outreach_send as send

HUMAN = ("interested", "question", "not_now", "unsubscribe", "objection", "wrong_person", "referral")
POSITIVE = ("interested", "referral")
OUTCOMES = ("meeting", "won", "closed")
STAGES = ("found", "ready", "contacted", "replied", "interested", "meeting", "won", "closed")
PERIODS = ("week", "month", "all")
OUTCOMES_KEY = "outreach_outcomes"
APPROVAL_KINDS = ("send_outreach", "reply_outreach")
FAILURE_WINDOW = timedelta(days=7)


def now() -> datetime:
    return send.now()


def refuse(status: int, detail: str):
    raise send.ActionRefused(status, detail)


def _london():
    from services.metering import LONDON
    return LONDON


def _window(period: str, moment: datetime) -> Optional[datetime]:
    """The start of the period: the last 7 UK days, the UK calendar month, or
    None for all time."""
    if period not in PERIODS:
        refuse(422, "The period must be week, month or all.")
    local = moment.astimezone(_london())
    if period == "week":
        first = (local - timedelta(days=6)).date()
    elif period == "month":
        first = local.date().replace(day=1)
    else:
        return None
    return datetime(first.year, first.month, first.day, tzinfo=_london())


def _parse(value) -> Optional[datetime]:
    return send._parse(value)


def _in(value, start: Optional[datetime], moment: datetime) -> bool:
    when = _parse(value)
    return when is not None and when <= moment and (start is None or when >= start)


def _doc(session, bid: str) -> dict:
    from services import outreach_setup as setup
    return setup._settings_doc(session, bid)


def _outcomes(session, bid: str) -> dict:
    """{prospect_id: {"events": [{"outcome", "by", "at"}, ...]}}: each mark is
    a dated event, so marking Won after a Meeting keeps the meeting (Codex
    review 1). Undo removes the latest event only."""
    out = {}
    for k, v in (_doc(session, bid).get(OUTCOMES_KEY) or {}).items():
        if isinstance(v, dict) and isinstance(v.get("events"), list):
            out[k] = {"events": [e for e in v["events"] if isinstance(e, dict) and e.get("outcome") in OUTCOMES]}
    return out


def _records(session, bid: str) -> dict:
    """Everything the dashboard counts, for one business, in one pass."""
    q = lambda sql: [dict(r) for r in session.execute(text(sql), {"b": bid}).mappings()]   # noqa: E731
    brands = q("SELECT id, name FROM outreach_brands WHERE business_id = :b ORDER BY name, id")
    lia_brand = {str(r["id"]): str(r["brand_id"]) for r in q(
        "SELECT id, brand_id FROM outreach_compliance WHERE business_id = :b")}
    campaigns = {str(r["id"]): r for r in q(
        "SELECT id, brand_id, mailbox_id FROM outreach_campaigns WHERE business_id = :b")}
    prospects = q("SELECT id, company, name, role, eligibility, lia_id, stage, captured_at, retention_due_at "
                  "FROM outreach_prospects WHERE business_id = :b")
    messages = q("SELECT prospect_id, campaign_id, origin, direction, state, kind, accepted_at, created_at "
                 "FROM outreach_messages WHERE business_id = :b AND direction = 'outbound'")
    replies = q("SELECT prospect_id, category, resolution, received_at FROM outreach_replies WHERE business_id = :b")
    return {"brands": brands, "lia_brand": lia_brand, "campaigns": campaigns, "prospects": prospects,
            "messages": messages, "replies": replies}


def _accepted_live(m: dict) -> bool:
    return m["direction"] == "outbound" and m["origin"] == "live" and m["state"] == "accepted"


def _scope(rec: dict, brand_id: Optional[str]) -> tuple:
    """The prospects and messages in view: one brand's, or the business's."""
    by_id = {str(p["id"]): p for p in rec["prospects"]}

    def prospect_brand(p) -> Optional[str]:
        return rec["lia_brand"].get(str(p["lia_id"])) if p.get("lia_id") else None

    if brand_id is None:
        return by_id, rec["messages"]
    people = {k: p for k, p in by_id.items() if prospect_brand(p) == brand_id}
    sends = [m for m in rec["messages"]
             if str((rec["campaigns"].get(str(m["campaign_id"])) or {}).get("brand_id")) == brand_id]
    return people, sends


def _stages(people: dict, sends: list, replies: list) -> dict:
    """Each prospect's furthest stage."""
    contacted = {str(m["prospect_id"]) for m in sends if _accepted_live(m)}
    human, positive = set(), set()
    for r in replies:
        if r["category"] in HUMAN:
            human.add(str(r["prospect_id"]))
        if r["category"] in POSITIVE:
            positive.add(str(r["prospect_id"]))
    out = {}
    for pid, p in people.items():
        if p.get("stage") in OUTCOMES:
            out[pid] = p["stage"]
        elif pid in positive:
            out[pid] = "interested"
        elif pid in human:
            out[pid] = "replied"
        elif pid in contacted:
            out[pid] = "contacted"
        elif p.get("eligibility") == "eligible":
            out[pid] = "ready"
        else:
            out[pid] = "found"
    return out


def _check_brand(rec: dict, brand_id) -> Optional[str]:
    if brand_id in (None, "", "all"):
        return None
    brand_id = str(brand_id)
    if brand_id not in {str(b["id"]) for b in rec["brands"]}:
        refuse(404, "That brand isn't one of this business's brands.")
    return brand_id


def build(session, business, *, brand_id=None, period: str = "week", moment: Optional[datetime] = None,
          include_spend: bool = False) -> dict:
    """The dashboard: pipeline, results for the period, Needs you, Aria's
    summary, and (for the owner) spend this month. Read-only."""
    bid = str(business.id)
    moment = moment or now()
    start = _window(period, moment)
    rec = _records(session, bid)
    brand = _check_brand(rec, brand_id)
    people, sends = _scope(rec, brand)
    replies = [r for r in rec["replies"] if str(r["prospect_id"]) in people]
    stages = _stages(people, sends, replies)
    pipeline = {s: 0 for s in STAGES}
    for s in stages.values():
        pipeline[s] += 1

    # Results. The cohort is the people FIRST contacted in the period.
    first = {}
    for m in sends:
        if _accepted_live(m) and str(m["prospect_id"]) in people:
            when = _parse(m["accepted_at"])
            pid = str(m["prospect_id"])
            if when is not None and (pid not in first or when < first[pid]):
                first[pid] = when
    cohort = {pid for pid, when in first.items() if when <= moment and (start is None or when >= start)}
    replied = {str(r["prospect_id"]) for r in replies if r["category"] in HUMAN and str(r["prospect_id"]) in cohort}
    positive = {str(r["prospect_id"]) for r in replies if r["category"] in POSITIVE and str(r["prospect_id"]) in cohort}
    outcomes = _outcomes(session, bid)

    def marked(kind: str) -> int:
        """People with a `kind` mark dated in the period (still standing:
        undone marks are removed; a prospect deleted by retention drops out)."""
        return sum(1 for pid, o in outcomes.items() if pid in people
                   and any(e["outcome"] == kind and _in(e.get("at"), start, moment) for e in o["events"]))
    contacted = len(cohort)
    results = {
        "contacted": contacted,
        "emails_sent": sum(1 for m in sends if _accepted_live(m) and _in(m["accepted_at"], start, moment)),
        "replied": len(replied),
        "positive": len(positive),
        "reply_rate": len(replied) / contacted if contacted else None,
        "positive_rate": len(positive) / contacted if contacted else None,
        "objections": sum(1 for r in replies if r["category"] == "objection" and _in(r["received_at"], start, moment)),
        "bounces": sum(1 for r in replies if r["category"] == "bounce" and _in(r["received_at"], start, moment)),
        "meetings": marked("meeting"),
        "wins": marked("won"),
    }

    needs = _needs_you(session, bid, rec, brand, replies, sends, moment)
    out = {"brand_id": brand, "period": period, "as_of": moment.isoformat(),
           "brands": [{"id": str(b["id"]), "name": b["name"]} for b in rec["brands"]],
           "pipeline": pipeline, "results": results, "needs_you": needs,
           "summary": _summary(period, results, needs),
           "definitions": {
               "contacted": "People whose first accepted email falls in the period",
               "emails_sent": "Emails the provider accepted in the period (accepted, not necessarily delivered)",
               "replied": "Of those people, how many replied themselves (not bounces or auto-replies)",
               "positive": "Of those people, how many were interested or referred you on",
               "meetings": "Meetings you marked as booked in the period",
               "wins": "Wins you marked in the period"}}
    if include_spend:
        out["spend"] = _spend(session, business, rec, brand, moment)
    return out


def _needs_you(session, bid: str, rec: dict, brand: Optional[str], replies: list, sends: list,
               moment: datetime) -> dict:
    from services import outreach_billing
    waiting = sum(1 for r in replies if r["category"] in HUMAN and r["resolution"] in ("pending", "handed_over"))
    approvals = 0
    for kind, payload in session.execute(text(
            "SELECT action_type, payload FROM aria_actions WHERE business_id = :b AND status = 'proposed' "
            "AND action_type IN ('send_outreach', 'reply_outreach')"), {"b": bid}):
        if brand is None:
            approvals += 1
            continue
        campaign = (send.loads(payload) or {}).get("campaign_id")
        if str((rec["campaigns"].get(str(campaign)) or {}).get("brand_id")) == brand:
            approvals += 1
    since = moment - FAILURE_WINDOW
    failed = sum(1 for m in sends if m["origin"] == "live" and m["state"] in ("unknown", "failed")
                 and _in(m["created_at"], since, moment))
    inboxes = {str(c["mailbox_id"]) for c in rec["campaigns"].values()
               if brand is None or str(c["brand_id"]) == brand}
    paused = 0
    for mailbox_id, reason, enabled in session.execute(text(
            "SELECT mailbox_id, pause_reason, enabled FROM outreach_mailboxes WHERE business_id = :b"), {"b": bid}):
        if str(mailbox_id) in inboxes and reason:
            paused += 1
    # Only brands actually waiting for a payment (Codex review 1): a brand the
    # owner stopped, whose paid month has ended, isn't a payment problem.
    billing = outreach_billing._billing(outreach_billing._doc(session, bid))["brands"]
    awaiting = 0 if outreach_billing.free(session, bid) else sum(
        1 for b in rec["brands"] if (brand is None or str(b["id"]) == brand)
        and (billing.get(str(b["id"])) or {}).get("state") in ("awaiting_payment", "pending"))
    return {"replies_waiting": waiting, "approvals": approvals,
            "failures": {"emails": failed, "paused_inboxes": paused, "awaiting_payment": awaiting}}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _summary(period: str, results: dict, needs: dict) -> str:
    """Aria's one sentence, from the numbers alone (no AI call, no cost)."""
    when = {"week": "this week", "month": "this month", "all": "so far"}[period]
    parts = [f"{_plural(results['contacted'], 'person', 'people')} contacted {when}"]
    if results["contacted"]:
        parts.append(f"{results['replied']} replied")
        parts.append(f"{results['positive']} interested or referred you on")
    sentence = ", ".join(parts) + "."
    waiting = needs["replies_waiting"]
    if waiting:
        sentence += f" {_plural(waiting, 'reply needs', 'replies need')} you."
    elif needs["approvals"]:
        sentence += f" {_plural(needs['approvals'], 'email is', 'emails are')} waiting for your approval."
    elif sum(needs["failures"].values()):
        sentence += f" {_plural(sum(needs['failures'].values()), 'problem needs', 'problems need')} a look."
    else:
        sentence += " Nothing needs you right now."
    return sentence


def _spend(session, business, rec: dict, brand: Optional[str], moment: datetime) -> dict:
    """This month's money, for the owner: per brand, AI spend against its
    allowance, paid top-ups and billing; for the business, the budget."""
    from services import metering, outreach_allowance, outreach_billing
    bid = str(business.id)
    period = metering.period_for(moment)
    billing = outreach_billing._billing(outreach_billing._doc(session, bid))["brands"]
    prices = outreach_allowance.prices(session, bid)
    is_free = outreach_billing.free(session, bid)
    rows = []
    for b in rec["brands"]:
        brand_id = str(b["id"])
        if brand is not None and brand_id != brand:
            continue
        topups = float(session.execute(text(
            "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND period = :p AND meter = :m"),
            {"b": bid, "p": period, "m": f"outreach_topup_pence:{brand_id}"}).scalar() or 0)
        rows.append({"brand_id": brand_id, "name": b["name"],
                     "allowance_pence": outreach_allowance.allowance_pence(session, bid, brand_id, period),
                     "spent_pence": outreach_allowance.spent_pence(session, bid, brand_id, period),
                     "topups_pence": int(topups),
                     "billing": _billing_label(billing.get(brand_id), moment, prices.get(brand_id), is_free),
                     "live": outreach_billing.brand_live(session, bid, brand_id, moment)})
    return {"period": period, "brands": rows,
            "budget": outreach_allowance.budget_status(session, business, moment=moment)}


def _billing_label(entry: Optional[dict], moment: datetime, price: Optional[tuple] = None, free: bool = False) -> str:
    """As the billing service sees it (Codex review 2): free, included in the
    plan, an existing paid brand with no billing record, or its record."""
    if free:
        return "free"
    if not entry:                         # only brands outside the plan get a billing record
        if price and price[1]:
            return "included in the plan"
        return f"paid (existing brand, £{price[0] / 100:.0f} a month)" if price and price[0] else "existing brand"
    state = entry.get("state")
    if state == "ending":
        ends = _parse(entry.get("ends_at"))
        return "stopped" if ends is not None and moment >= ends else "stopping at the end of the paid month"
    return {"awaiting_payment": "waiting for payment", "pending": "payment being confirmed",
            "active": "paid"}.get(state, str(state))


def stage_list(session, bid: str, stage: str, *, brand_id=None, limit: int = 20, offset: int = 0,
               moment: Optional[datetime] = None) -> dict:
    """The people at one pipeline stage, most recent activity first. Past a
    prospect's retention date their details are withheld, as everywhere else
    (outreach_read._project; Codex review 1)."""
    moment = moment or now()
    if stage not in STAGES:
        refuse(422, "Unknown pipeline stage.")
    if not (1 <= int(limit) <= 50) or int(offset) < 0:
        refuse(422, "Invalid paging.")
    bid = str(bid)
    rec = _records(session, bid)
    brand = _check_brand(rec, brand_id)
    people, sends = _scope(rec, brand)
    replies = [r for r in rec["replies"] if str(r["prospect_id"]) in people]
    stages = _stages(people, sends, replies)
    last = {pid: _parse(p.get("captured_at")) for pid, p in people.items()}
    for m in sends:
        when, pid = _parse(m["accepted_at"]), str(m["prospect_id"])
        if pid in last and when and (last[pid] is None or when > last[pid]):
            last[pid] = when
    for r in replies:
        when, pid = _parse(r["received_at"]), str(r["prospect_id"])
        if pid in last and when and (last[pid] is None or when > last[pid]):
            last[pid] = when
    for pid, o in _outcomes(session, bid).items():
        for e in o["events"]:
            when = _parse(e.get("at"))
            if pid in last and when and (last[pid] is None or when > last[pid]):
                last[pid] = when
    chosen = sorted((pid for pid, s in stages.items() if s == stage),
                    key=lambda pid: (last[pid].isoformat() if last[pid] else "", pid), reverse=True)
    items = []
    for pid in chosen[int(offset):int(offset) + int(limit)]:
        due = _parse(people[pid].get("retention_due_at"))
        expired = due is not None and due <= moment
        items.append({"id": pid, "company": None if expired else people[pid].get("company"),
                      "name": None if expired else people[pid].get("name"),
                      "role": None if expired else people[pid].get("role"), "details_withheld": expired,
                      "last_activity_at": last[pid].isoformat() if last[pid] else None})
    return {"stage": stage, "items": items, "total": len(chosen)}


def _lock(session, bid: str) -> None:
    if send.pg(session):
        session.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b FOR UPDATE"), {"b": bid})
    else:
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})


def mark_outcome(session, business, user, prospect_id, outcome, *, moment: Optional[datetime] = None,
                 expected: Optional[str] = None) -> dict:
    """The owner marks a meeting, a win or a close, or undoes it (None).
    Who and when are recorded; no free text is kept. `expected` names the mark
    the owner is looking at; if it has changed (a second click, another tab),
    nothing happens (Codex review 2: one click undoes one mark)."""
    from services import aria_actions, outreach_setup as setup
    bid = str(business.id)
    moment = moment or now()
    if outcome is not None and outcome not in OUTCOMES:
        refuse(422, "Mark a meeting, a win or a close (or undo the mark).")
    if not user or not aria_actions._is_active_owner(session, business, user):
        session.rollback()
        refuse(403, "Only the business owner can mark meetings and wins.")
    _lock(session, bid)
    prospect = send.one(session, "outreach_prospects", bid, prospect_id, True)   # 404 for another business's
    doc = _doc(session, bid)
    marks = dict(doc.get(OUTCOMES_KEY) or {})
    events = list(((marks.get(str(prospect_id)) or {}).get("events")) or [])
    if expected is not None and (events[-1]["outcome"] if events else "none") != expected:
        session.rollback()
        refuse(409, "This person's mark changed just now. Please refresh and try again.")
    if outcome is None:
        if events:
            events.pop()                  # undo the latest mark; an earlier one stands
    elif not events or events[-1].get("outcome") != outcome:
        events.append({"outcome": outcome, "by": str(user), "at": moment.isoformat()})
    current = events[-1]["outcome"] if events else None
    stage = current or ("ready" if prospect.get("eligibility") == "eligible" else "new")
    session.execute(text("UPDATE outreach_prospects SET stage = :s, updated_at = :at "
                         "WHERE business_id = :b AND id = :p"),
                    {"s": stage, "at": moment, "b": bid, "p": str(prospect_id)})
    if events:
        marks[str(prospect_id)] = {"events": events}
    else:
        marks.pop(str(prospect_id), None)
    doc[OUTCOMES_KEY] = marks
    setup._save_settings_doc(session, bid, doc)
    session.commit()
    return {"prospect_id": str(prospect_id), "outcome": current}


# ------------------------------------------------------------------ Aria ---

def _session_and_business(business_id):
    """A session and the business, for Aria's tool, with outreach history access."""
    import json as _json
    from fastapi import HTTPException
    from sqlmodel import Session
    from auth import assert_feature_access
    from db import engine
    from services import outreach_setup
    session = Session(engine)
    business = outreach_setup.load_business_row(session, str(business_id))
    if business is None:
        session.close()
        refuse(404, "Business not found.")
    business.feature_flags = business.feature_flags if isinstance(business.feature_flags, dict) \
        else _json.loads(business.feature_flags or "{}")
    try:
        assert_feature_access(business, "outreach", retained_history=True)
    except HTTPException as exc:
        session.close()
        refuse(exc.status_code, str(exc.detail))
    return session, business


def aria(business_id, arguments: dict) -> dict:
    """Aria's `get_outreach_dashboard`: the same numbers, without spend."""
    arguments = arguments or {}
    if set(arguments) - {"brand_id", "period"}:
        return {"status_code": 422, "error": "Invalid arguments"}
    try:
        session, business = _session_and_business(business_id)
        try:
            return build(session, business, brand_id=arguments.get("brand_id"),
                         period=arguments.get("period", "week"), include_spend=False)
        finally:
            session.rollback()
    except send.ActionRefused as exc:
        return {"status_code": exc.status_code, "error": exc.detail}
