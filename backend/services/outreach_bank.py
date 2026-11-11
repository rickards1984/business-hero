"""OUT-23 — the prospect bank (docs/OUT-23-TICKET.md, Part A revision 4,
design approved by Codex design review 5). RED: paid research and personal
data.

Research fills a bank of good contacts, about three weeks of sending, ahead of
what the inboxes can email today (Mike, 10 Nov 2026). The drain is the only
automatic path from the bank into a campaign: every hour, oldest first, only
into places the send path will admit, bounded by one commitment ledger. OUT-13
core owns the deadline, hiding and erasure; this module adds none of its own.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from services import outreach_erasure, outreach_send as send

logger = logging.getLogger(__name__)

BANK_DAYS_FACTOR = 5          # 15 weekdays x a third of sends being first emails
DRAIN_MARGIN = timedelta(days=5)
DRAIN_HOURS = range(7, 19)    # weekdays 07:00-18:59 UK, after the morning health checks
COLD = "AND (m.kind IS NULL OR m.kind <> 'bespoke') "   # as metering: anything not known to be a reply


def now() -> datetime:
    return send.now()


def _local(moment: datetime):
    from services.outreach_research import LONDON
    return moment.astimezone(LONDON)


# --------------------------------------------------------- the send limits ---

def _brand_limit(session, bid: str, settings, brand_id) -> int:
    """Exactly the send path's (metering._cold_limits): an owner cap left at
    20 rises with the brand's boost; a lower one binds (design review 4)."""
    from services import outreach_boost
    return outreach_boost.follow(min(20, int(settings["business_daily_cap"])),
                                 outreach_boost.brand_level(session, bid, brand_id))


def _box_caps(session, bid: str, campaigns: list) -> dict:
    from services import metering, outreach_boost
    caps = {}
    for mailbox_id in {str(c["mailbox_id"]) for c in campaigns}:
        boxes = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": mailbox_id})
        caps[mailbox_id] = (metering.mailbox_daily_cap(boxes[0], boost=outreach_boost.level(session, bid, mailbox_id))
                            if len(boxes) == 1 else 0)
    return caps


def _ready(session, bid: str) -> list:
    return send.rows(session, "outreach_campaigns", bid, "AND status IN ('ready', 'running') ORDER BY created_at, id")


# ------------------------------------------------------------ bank sizing ---

def audience_caps(session, bid: str, moment: datetime) -> dict:
    """{(brand_id, audience_hash): daily first-email capacity}, for SIZING only.
    Each inbox's cap is water-filled across its campaigns (equal integer
    shares, remainder to the oldest), clipped by each campaign's cap and by
    the brand's limit across all its inboxes, repeated until stable (R4.4)."""
    from services import outreach_boost
    settings = send.one(session, "outreach_settings", bid) if send.rows(session, "outreach_settings", bid) else None
    campaigns = _ready(session, bid)
    if not settings or not campaigns:
        return {}
    box_left = _box_caps(session, bid, campaigns)
    brand_left = {str(b): _brand_limit(session, bid, settings, b) for b in {c["brand_id"] for c in campaigns}}
    want = {str(c["id"]): outreach_boost.follow(int(c["daily_cap"]),
                                                outreach_boost.level(session, bid, c["mailbox_id"])) for c in campaigns}
    got = {cid: 0 for cid in want}
    changed = True
    while changed:
        changed = False
        for mailbox_id in sorted(box_left):
            hungry = [c for c in campaigns if str(c["mailbox_id"]) == mailbox_id
                      and got[str(c["id"])] < want[str(c["id"])] and brand_left[str(c["brand_id"])] > 0]
            if not hungry or box_left[mailbox_id] <= 0:
                continue
            share, extra = divmod(box_left[mailbox_id], len(hungry))
            for i, c in enumerate(hungry):          # oldest first take the remainder
                cid, br = str(c["id"]), str(c["brand_id"])
                give = min(share + (1 if i < extra else 0), want[cid] - got[cid], brand_left[br], box_left[mailbox_id])
                if give > 0:
                    got[cid] += give
                    brand_left[br] -= give
                    box_left[mailbox_id] -= give
                    changed = True
    out = {}
    for c in campaigns:
        key = (str(c["brand_id"]), str(c["target_hash"]))
        out[key] = out.get(key, 0) + got[str(c["id"])]
    return out


def _stock(session, bid: str, lia_ids: list, moment: datetime) -> dict:
    """Banked contacts of these audience approvals: drainable (at least five
    days left) and held (fewer), and step-0 enrolments never contacted."""
    if not lia_ids:
        return {"drainable": 0, "held": 0, "waiting": 0, "oldest_days_left": None}
    names = {f"l{i}": v for i, v in enumerate(lia_ids)}
    rows = session.execute(text(
        "SELECT p.captured_at, p.notice_due_at, p.notice_provided_at FROM outreach_prospects p "
        f"WHERE p.business_id = :b AND p.lia_id IN ({', '.join(':' + n for n in names)}) "
        "AND p.eligibility = 'eligible' AND NOT EXISTS (SELECT 1 FROM outreach_enrolments e "
        "WHERE e.business_id = p.business_id AND e.prospect_id = p.id) AND NOT EXISTS (SELECT 1 FROM "
        "outreach_messages m WHERE m.business_id = p.business_id AND m.prospect_id = p.id)"),
        {"b": bid, **names}).mappings().all()
    drainable = held = 0
    oldest = None
    for p in rows:
        left = outreach_erasure.deadline(p) - moment
        if left <= timedelta(0):
            continue                       # past the deadline: OUT-13 core erases it
        if left >= DRAIN_MARGIN:
            drainable += 1
        else:
            held += 1
        days = left.days
        oldest = days if oldest is None else min(oldest, days)
    waiting = session.execute(text(
        "SELECT count(*) FROM outreach_enrolments e JOIN outreach_prospects p ON p.business_id = e.business_id "
        f"AND p.id = e.prospect_id WHERE e.business_id = :b AND p.lia_id IN ({', '.join(':' + n for n in names)}) "
        "AND e.state IN ('pending', 'active') AND e.next_step = 0 AND NOT EXISTS (SELECT 1 FROM outreach_messages m "
        "WHERE m.business_id = e.business_id AND m.enrolment_id = e.id AND m.direction = 'outbound')"),
        {"b": bid, **names}).scalar()
    return {"drainable": drainable, "held": held, "waiting": int(waiting or 0), "oldest_days_left": oldest}


def _lias_for(session, bid: str, brand_id, audience_hash) -> list:
    return [str(r[0]) for r in session.execute(text(
        "SELECT id FROM outreach_compliance WHERE business_id = :b AND brand_id = :br AND audience_hash = :h "
        "ORDER BY version"),
        {"b": bid, "br": str(brand_id), "h": str(audience_hash)})]


def bank(session, bid: str, brand_id, audience_hash, moment: Optional[datetime] = None) -> dict:
    """The bank for one audience: its estimated target, stock and room."""
    moment = moment or now()
    cap = audience_caps(session, bid, moment).get((str(brand_id), str(audience_hash)), 0)
    stock = _stock(session, bid, _lias_for(session, bid, brand_id, audience_hash), moment)
    target = BANK_DAYS_FACTOR * cap
    return {"target": target, "daily_capacity": cap, **stock,
            "room": max(0, target - stock["drainable"] - stock["waiting"])}


# -------------------------------------------------------- the drain ledger ---

def _ledger(session, bid: str, settings, campaigns: list, moment: datetime) -> dict:
    """R4.2: every bound's starting balance. Each queued, unreserved item (a
    follow-up due by tonight, or a step-0 enrolment not yet claimed) counts
    once against every bound it will use; reserved and unknown usage already
    counts as a send and is not added again."""
    from services import metering, outreach_boost
    local = _local(moment)
    today = local.date().isoformat()
    tomorrow = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    first, following, weekdays = metering.month_bounds(local.date())
    by_id = {str(c["id"]): c for c in campaigns}
    sent_c, sent_box, sent_brand, month_brand = {}, {}, {}, {}
    for cid, mailbox_id, brand_id, day in session.execute(text(
            "SELECT m.campaign_id, u.mailbox_id, c.brand_id, u.local_send_date FROM outreach_usage_events u "
            "JOIN outreach_messages m ON m.business_id = u.business_id AND m.id = u.message_id "
            "JOIN outreach_campaigns c ON c.business_id = m.business_id AND c.id = m.campaign_id "
            "WHERE u.business_id = :b AND u.kind = 'outreach_emails_sent' AND u.state IN ('reserved', 'committed', 'unknown') "
            "AND u.local_send_date >= :first AND u.local_send_date < :following " + COLD),
            {"b": bid, "first": first.isoformat(), "following": following.isoformat()}):
        month_brand[str(brand_id)] = month_brand.get(str(brand_id), 0) + 1
        if str(day)[:10] == today:
            sent_c[str(cid)] = sent_c.get(str(cid), 0) + 1
            sent_box[str(mailbox_id)] = sent_box.get(str(mailbox_id), 0) + 1
            sent_brand[str(brand_id)] = sent_brand.get(str(brand_id), 0) + 1
    queued_c = {}
    for cid, step, due in session.execute(text(
            "SELECT e.campaign_id, e.next_step, e.next_due_at FROM outreach_enrolments e WHERE e.business_id = :b "
            "AND e.state IN ('pending', 'active') AND e.next_step IS NOT NULL"), {"b": bid}):
        due_at = outreach_erasure._ts(due)
        if int(step) == 0 or (due_at is not None and due_at < tomorrow):
            queued_c[str(cid)] = queued_c.get(str(cid), 0) + 1
    # A queued item already being sent has a reserved usage event, counted
    # above as a send: remove it from the queue so it counts once.
    for cid, n in session.execute(text(
            "SELECT e.campaign_id, count(*) FROM outreach_enrolments e JOIN outreach_messages m "
            "ON m.business_id = e.business_id AND m.enrolment_id = e.id AND m.direction = 'outbound' "
            "AND m.state IN ('claimed', 'unknown') WHERE e.business_id = :b AND e.state IN ('pending', 'active') "
            "GROUP BY e.campaign_id"), {"b": bid}):
        if str(cid) in queued_c:
            queued_c[str(cid)] = max(0, queued_c[str(cid)] - int(n))
    queued_box, queued_brand = {}, {}
    for cid, n in queued_c.items():
        c = by_id.get(cid)
        if c is None:
            continue
        queued_box[str(c["mailbox_id"])] = queued_box.get(str(c["mailbox_id"]), 0) + n
        queued_brand[str(c["brand_id"])] = queued_brand.get(str(c["brand_id"]), 0) + n
    box_caps = _box_caps(session, bid, campaigns)
    ledger = {"campaign": {}, "cold": {}, "total": {}, "brand_day": {}, "brand_month": {}, "pilot": {},
              "blocked": {}}
    from services import outreach_research
    pilot = outreach_research.pilot_enrolments()      # 0 = no pilot limit (OUT-24)
    members = {str(r[0]): int(r[1]) for r in session.execute(text(
        "SELECT campaign_id, count(*) FROM outreach_enrolments WHERE business_id = :b "
        "AND state IN ('pending', 'active') GROUP BY campaign_id"), {"b": bid})}
    for c in campaigns:
        cid = str(c["id"])
        limit = outreach_boost.follow(int(c["daily_cap"]), outreach_boost.level(session, bid, c["mailbox_id"]))
        ledger["campaign"][cid] = limit - sent_c.get(cid, 0) - queued_c.get(cid, 0)
        # The pilot limit of active contacts per campaign, while it lasts (R4.1).
        ledger["pilot"][cid] = (pilot - members.get(cid, 0)) if pilot else 10 ** 6
    for mailbox_id, cap in box_caps.items():
        ledger["cold"][mailbox_id] = cap - sent_box.get(mailbox_id, 0) - queued_box.get(mailbox_id, 0)
        head = metering.reply_headroom(session, bid, mailbox_id, moment)
        ledger["blocked"][mailbox_id] = head["blocked"]
        ledger["total"][mailbox_id] = 0 if head["blocked"] else head["left"] - queued_box.get(mailbox_id, 0)
    for brand_id in {str(c["brand_id"]) for c in campaigns}:
        daily = _brand_limit(session, bid, settings, brand_id)
        ledger["brand_day"][brand_id] = daily - sent_brand.get(brand_id, 0) - queued_brand.get(brand_id, 0)
        ledger["brand_month"][brand_id] = daily * weekdays - month_brand.get(brand_id, 0) - queued_brand.get(brand_id, 0)
    return ledger


def _room(ledger: dict, c) -> bool:
    cid, box, br = str(c["id"]), str(c["mailbox_id"]), str(c["brand_id"])
    return min(ledger["campaign"].get(cid, 0), ledger["cold"].get(box, 0), ledger["total"].get(box, 0),
               ledger["brand_day"].get(br, 0), ledger["brand_month"].get(br, 0), ledger["pilot"].get(cid, 0)) > 0


def _take(ledger: dict, c) -> None:
    cid, box, br = str(c["id"]), str(c["mailbox_id"]), str(c["brand_id"])
    for key, k in (("campaign", cid), ("cold", box), ("total", box), ("brand_day", br), ("brand_month", br),
                   ("pilot", cid)):
        ledger[key][k] = ledger[key].get(k, 0) - 1


# ------------------------------------------------------------- the drain ---

def _owner(session, bid: str) -> Optional[str]:
    row = session.execute(text("SELECT user_id FROM business_members WHERE business_id = :b AND role = 'owner' "
                               "AND is_active = :t ORDER BY user_id LIMIT 1"), {"b": bid, "t": True}).first()
    return str(row[0]) if row else None


def drain_business(session, business, moment: Optional[datetime] = None) -> dict:
    """R4.7: owner and authority first (start() rolls back, then locks); then,
    with no further rollback until commit, everything is re-read and the
    oldest banked contacts are enrolled into admitted places. Commits."""
    from services import outreach_billing, outreach_manage
    moment = moment or now()
    bid = str(business.id)
    out = {"enrolled": [], "skipped": None}
    owner = _owner(session, bid)
    session.rollback()
    if owner is None:
        out["skipped"] = "no active owner"
        return out
    try:
        fresh = outreach_manage.start(session, business, owner)
        outreach_manage.growth(business, fresh)
    except Exception as exc:          # ActionRefused, or the entitlement check's HTTPException
        session.rollback()
        out["skipped"] = str(getattr(exc, "detail", None) or type(exc).__name__)
        return out
    settings = send.one(session, "outreach_settings", bid, lock=True)
    if settings["pause_all"]:
        session.rollback()
        out["skipped"] = "paused"
        return out
    campaigns = [c for c in _ready(session, bid)
                 if outreach_billing.brand_live(session, bid, c["brand_id"], moment)]
    if not campaigns:
        session.rollback()
        out["skipped"] = "no ready, paid campaign"
        return out
    ledger = _ledger(session, bid, settings, campaigns, moment)
    candidates = session.execute(text(
        "SELECT p.id, p.lia_id, p.captured_at, p.notice_due_at, p.notice_provided_at FROM outreach_prospects p "
        "WHERE p.business_id = :b AND p.eligibility = 'eligible' AND NOT EXISTS (SELECT 1 FROM outreach_enrolments e "
        "WHERE e.business_id = p.business_id AND e.prospect_id = p.id) AND NOT EXISTS (SELECT 1 FROM "
        "outreach_messages m WHERE m.business_id = p.business_id AND m.prospect_id = p.id) "
        "ORDER BY p.captured_at, p.id"), {"b": bid}).mappings().all()
    lia_audience = {str(r[0]): (str(r[1]), str(r[2])) for r in session.execute(text(
        "SELECT id, brand_id, audience_hash FROM outreach_compliance WHERE business_id = :b"), {"b": bid})}
    for p in candidates:
        if outreach_erasure.deadline(p) - moment < DRAIN_MARGIN:
            continue                       # too close to approve in time; erased at its deadline
        brand_id, audience = lia_audience.get(str(p["lia_id"]), (None, None))
        for c in campaigns:
            if str(c["brand_id"]) != brand_id or str(c["target_hash"]) != audience or not _room(ledger, c):
                continue
            row = send.one(session, "outreach_prospects", bid, str(p["id"]), True)
            try:
                outreach_manage.qualified(session, bid, c, row)
            except send.ActionRefused:
                continue                   # not for this campaign: another of the audience may take it
            send.insert(session, "outreach_enrolments", bid, prospect_id=str(p["id"]), campaign_id=str(c["id"]),
                        sequence_version=c["sequence_version"], state="active", next_step=0, next_due_at=moment)
            _take(ledger, c)
            out["enrolled"].append(str(p["id"]))
            break
    session.commit()
    return out


# --------------------------------------------------------- what the owner sees ---

def _blocked(session, bid: str, brand_id, audience_hash, moment: datetime) -> Optional[str]:
    """B6: why the drain would enrol none of this audience now, or None.
    Read-only: the drain's own checks that need no lock."""
    from services import outreach_billing
    settings = send.one(session, "outreach_settings", bid) if send.rows(session, "outreach_settings", bid) else None
    if not settings or settings["pause_all"]:
        return "Outreach is paused"
    if _owner(session, bid) is None:
        return "The business has no active owner"
    campaigns = [c for c in _ready(session, bid)
                 if str(c["brand_id"]) == str(brand_id) and str(c["target_hash"]) == str(audience_hash)]
    if not campaigns:
        return "No ready campaign for this audience"
    if not outreach_billing.brand_live(session, bid, brand_id, moment):
        return "This brand's outreach isn't paid for"
    ledger = _ledger(session, bid, settings, campaigns, moment)
    if ledger["brand_month"].get(str(brand_id), 0) <= 0:
        return "This month's sending for this brand is used"
    reasons = [ledger["blocked"].get(str(c["mailbox_id"])) for c in campaigns]
    if all(reasons):
        return reasons[0]
    return None


def audiences(session, business, brand_id, moment: Optional[datetime] = None) -> list:
    """B6, per approved audience of a brand: the bank's estimated size, what
    is in it, and whatever stops it being emailed. Counts only, never a contact."""
    moment = moment or now()
    bid = str(business.id)
    hashes = list(dict.fromkeys(str(r[0]) for r in session.execute(text(
        "SELECT audience_hash FROM outreach_compliance WHERE business_id = :b AND brand_id = :br "
        "AND decision = 'approved' ORDER BY reviewed_at"), {"b": bid, "br": str(brand_id)})))
    from services import outreach_research, outreach_setup
    rules = outreach_research._doc(session, bid).get(outreach_setup.AUDIENCE_KEY) or {}
    out = []
    for h in hashes:
        b = bank(session, bid, brand_id, h, moment)
        lias = _lias_for(session, bid, brand_id, h)
        label = next((((rules.get(i) or {}).get("description") or "") for i in reversed(lias)
                      if (rules.get(i) or {}).get("description")), "")
        names = {f"l{i}": v for i, v in enumerate(lias)}
        review = session.execute(text(
            f"SELECT count(*) FROM outreach_prospects p WHERE p.business_id = :b AND p.lia_id IN "
            f"({', '.join(':' + n for n in names)}) AND p.eligibility = 'review' AND NOT EXISTS (SELECT 1 FROM "
            "outreach_enrolments e WHERE e.business_id = p.business_id AND e.prospect_id = p.id)"),
            {"b": bid, **names}).scalar() if lias else 0
        out.append({"audience_hash": h, "description": label[:120], "target": b["target"], "banked": b["drainable"] + b["held"],
                    "drainable": b["drainable"], "held": b["held"], "review_held": int(review or 0),
                    "waiting": b["waiting"], "oldest_days_left": b["oldest_days_left"],
                    "blocked": _blocked(session, bid, brand_id, h, moment)})
    return out


def _business(session, bid: str):
    """The business as a system job sees it, with its flags and trial date
    parsed as outreach_manage.start does (a JSON string on some drivers)."""
    from services import outreach_setup
    from services.chase_replies import _parse
    business = outreach_setup.load_business_row(session, bid)
    if business is not None:
        business.feature_flags = send.loads(business.feature_flags) or {}
        business.trial_ends_at = _parse(business.trial_ends_at)
    return business


def drain_due(session, moment: Optional[datetime] = None) -> dict:
    """Every hourly pass, weekdays 07:00-18:59 UK: each business with banked
    contacts. No day-claim: a late health check never strands the bank."""
    moment = moment or now()
    local = _local(moment)
    out = {"businesses": 0, "enrolled": 0}
    if local.weekday() >= 5 or local.hour not in DRAIN_HOURS:
        return out
    rows = session.execute(text(
        "SELECT DISTINCT p.business_id FROM outreach_prospects p WHERE p.eligibility = 'eligible' "
        "AND NOT EXISTS (SELECT 1 FROM outreach_enrolments e WHERE e.business_id = p.business_id "
        "AND e.prospect_id = p.id)")).fetchall()
    session.rollback()
    for (bid,) in rows:
        business = _business(session, str(bid))
        session.rollback()
        if business is None:
            continue
        try:
            done = drain_business(session, business, moment)
        except Exception as exc:
            session.rollback()
            logger.error("[Bank] drain failed for business %s: %s", bid, type(exc).__name__)
            continue
        out["businesses"] += 1
        out["enrolled"] += len(done["enrolled"])
    if out["enrolled"]:
        logger.info("[Bank] enrolled %d banked contact(s) across %d business(es)", out["enrolled"], out["businesses"])
    return out


def prepare_all_due(session, moment: Optional[datetime] = None) -> int:
    """R4.3: every business with a due active enrolment gets its cards,
    whatever its bank, research toggle or new placements. Outside any drain
    transaction; retried every pass; autopilot grants are skipped there."""
    from services import outreach_research
    moment = moment or now()
    rows = session.execute(text(
        "SELECT DISTINCT business_id FROM outreach_enrolments WHERE state = 'active' AND takeover_at IS NULL "
        "AND next_due_at <= :now"), {"now": moment}).fetchall()
    session.rollback()
    made = 0
    for (bid,) in rows:
        business = _business(session, str(bid))
        session.rollback()
        if business is None:
            continue
        try:
            made += len(outreach_research.prepare_due_cards(session, business, moment) or [])
        except Exception as exc:
            session.rollback()
            logger.error("[Bank] card preparation failed for business %s: %s", bid, type(exc).__name__)
    return made
