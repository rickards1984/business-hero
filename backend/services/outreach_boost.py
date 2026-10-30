"""OUT-19 G — boosting an inbox with a proven record (decision 5,
docs/OUT-19-TICKET.md). RED: sending limits and deliverability.

Mike, 30 Oct 2026: a boost is FREE (the brand's hidden AI ceiling still caps
our cost; extra research is bought with top-ups) and the OWNER OPTS IN when an
inbox qualifies. Dropping back is always automatic.

Steps: 20 → 30 → 40 → 50 cold emails a day per inbox. 50 is the ceiling.

Qualifying for 30, over the last 28 days: 28 days at warm-up stage 20 (from
the owner's stage-20 review); at least 200 cold emails; bounces under 2%;
unsubscribes under 1% (by reply or by link, counted once per person); no
complaints; no failed daily check; at least one genuine reply; not paused and
passing today. Each later step: 14 days at the current level and the same
measures over the last 14 days with at least 150 cold emails.

Dropping back, checked with the daily inbox check: a miss over the last 14
days (bounces, unsubscribes, a failed check) drops one step, at most one step
per 14 days; a complaint or any pause goes straight back to 20.

Reputation is judged from our own evidence only: Business Hero can't see
Google's or Microsoft's internal score.

State lives in the business settings document (no migration):
  outreach_boost = {mailbox_id: {"level": 30, "since": iso, "by": user, ...}}
Failed daily checks are counted in usage_meters, one row per inbox per day.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text

from services import outreach_send as send

STEPS = (20, 30, 40, 50)
BASE, CEILING = 20, 50
FIRST_WINDOW, LATER_WINDOW = timedelta(days=28), timedelta(days=14)
FIRST_MINIMUM, LATER_MINIMUM = 200, 150
HOLD = timedelta(days=14)
BOUNCE_LIMIT, UNSUBSCRIBE_LIMIT = 0.02, 0.01        # each must stay UNDER its limit
GENUINE = ("interested", "question", "not_now", "objection", "referral", "wrong_person")
KEY = "outreach_boost"
CHECK_METER = "outreach_check_failed"
NOTICE = ("Reputation is judged from our own evidence: bounces, unsubscribes, complaints, replies and the daily "
          "inbox check. Business Hero can't see Google's or Microsoft's internal score.")


def refuse(status: int, detail: str):
    raise send.ActionRefused(status, detail)


def _doc(session, bid: str) -> dict:
    from services import outreach_setup as setup
    return setup._settings_doc(session, bid)


def _save(session, bid: str, boosts: dict) -> None:
    from services import outreach_setup as setup
    doc = _doc(session, bid)
    doc[KEY] = boosts
    setup._save_settings_doc(session, bid, doc)


def _boosts(session, bid: str) -> dict:
    return {k: dict(v) for k, v in (_doc(session, str(bid)).get(KEY) or {}).items() if isinstance(v, dict)}


def _parse(value) -> Optional[datetime]:
    return send._parse(value)


def level(session, bid: str, mailbox_id) -> int:
    """The inbox's granted level: 20 unless it has been boosted."""
    entry = _boosts(session, bid).get(str(mailbox_id)) or {}
    lvl = entry.get("level")
    return int(lvl) if lvl in STEPS else BASE


def follow(limit: int, cap: int) -> int:
    """An owner's limit left at the maximum (20) rises with a boost; a limit
    the owner set below 20 still binds."""
    return cap if int(limit) >= BASE else int(limit)


def _local_date(moment: datetime) -> str:
    from services.metering import LONDON
    return moment.astimezone(LONDON).date().isoformat()


def record_check(session, bid: str, mailbox_id, moment: datetime, *, passed: bool) -> None:
    """From the daily inbox check: a failed check is counted for that inbox
    and UK day (a durable history the latest-check columns don't keep)."""
    if passed:
        return
    from services import outreach_research
    outreach_research._add_meter(session, str(bid), f"{CHECK_METER}:{mailbox_id}:{_local_date(moment)}", moment, 1)


def _mailbox(session, bid: str, mailbox_id) -> Optional[dict]:
    found = send.rows(session, "outreach_mailboxes", str(bid), "AND mailbox_id = :m", {"m": str(mailbox_id)})
    return found[0] if len(found) == 1 else None


def evidence(session, bid: str, mailbox_id, moment: datetime, *, days: int) -> dict:
    """Our own evidence for one inbox over the last `days` days."""
    bid, box = str(bid), str(mailbox_id)
    start = moment - timedelta(days=days)
    first_day = _local_date(start)
    cold = int(session.execute(text(
        "SELECT count(*) FROM outreach_usage_events u JOIN outreach_messages m "
        "ON m.business_id = u.business_id AND m.id = u.message_id "
        "WHERE u.business_id = :b AND u.mailbox_id = :mb AND u.state = 'committed' "
        "AND u.local_send_date >= :first AND u.local_send_date <= :last "
        "AND (m.kind IS NULL OR m.kind <> 'bespoke')"),
        {"b": bid, "mb": box, "first": first_day, "last": _local_date(moment)}).scalar() or 0)

    def within(value) -> bool:
        when = _parse(value)
        return when is not None and start <= when <= moment

    counts = {"bounce": 0, "complaint": 0, "genuine": 0}
    unsubscribed = set()                  # people, once each, by reply or by link
    for category, prospect, received in session.execute(text(
            "SELECT category, prospect_id, received_at FROM outreach_replies "
            "WHERE business_id = :b AND mailbox_id = :mb"), {"b": bid, "mb": box}):
        if not within(received):
            continue
        if category in ("bounce", "complaint"):
            counts[category] += 1
        elif category == "unsubscribe":
            unsubscribed.add(str(prospect))
        elif category in GENUINE:
            counts["genuine"] += 1
    # Link unsubscribes carry no inbox: traced to the people this inbox emailed.
    for prospect, suppressed in session.execute(text(
            "SELECT p.id, s.suppressed_at FROM outreach_suppressions s JOIN outreach_prospects p "
            "ON p.business_id = s.business_id AND p.email_key = s.key_digest "
            "WHERE s.business_id = :b AND s.key_type = 'email' AND s.reason = 'unsubscribe' "
            "AND EXISTS (SELECT 1 FROM outreach_messages m WHERE m.business_id = p.business_id "
            "AND m.prospect_id = p.id AND m.mailbox_id = :mb AND m.direction = 'outbound')"),
            {"b": bid, "mb": box}):
        if within(suppressed):
            unsubscribed.add(str(prospect))
    prefix = f"{CHECK_METER}:{box}:"
    failed = 0
    for meter, value in session.execute(text(
            "SELECT meter, value FROM usage_meters WHERE business_id = :b AND meter LIKE :m"),
            {"b": bid, "m": prefix + "%"}):
        if first_day <= meter[len(prefix):] <= _local_date(moment):
            failed += int(value or 0)
    return {"cold": cold, "bounces": counts["bounce"], "complaints": counts["complaint"],
            "unsubscribes": len(unsubscribed), "failed_checks": failed, "genuine_replies": counts["genuine"],
            "days": days}


def _rate(n: int, cold: int) -> float:
    return n / cold if cold else (1.0 if n else 0.0)


def _quality_misses(ev: dict) -> list:
    """The measures a fortnight (or four weeks) can fail on its record."""
    out = []
    if _rate(ev["bounces"], ev["cold"]) >= BOUNCE_LIMIT:
        out.append(f"Bounces must stay under 2% ({ev['bounces']} of {ev['cold']} cold emails)")
    if _rate(ev["unsubscribes"], ev["cold"]) >= UNSUBSCRIBE_LIMIT:
        out.append(f"Unsubscribes must stay under 1% ({ev['unsubscribes']} of {ev['cold']} cold emails)")
    if ev["complaints"]:
        out.append(f"No complaints ({ev['complaints']} in the last {ev['days']} days)")
    if ev["failed_checks"]:
        out.append(f"No failed daily inbox check ({ev['failed_checks']} in the last {ev['days']} days)")
    return out


def _passing_today(box: dict, moment: datetime) -> bool:
    checked = _parse(box.get("health_checked_at"))
    return (box.get("health_status") == "pass" and checked is not None and checked <= moment
            and _local_date(checked) == _local_date(moment))


def eligibility(session, bid: str, mailbox_id, moment: datetime) -> dict:
    """Whether the inbox may step up now, the measures not yet met, and the
    evidence behind them."""
    bid = str(bid)
    box = _mailbox(session, bid, mailbox_id)
    lvl = level(session, bid, mailbox_id) if box else BASE
    following = next((s for s in STEPS if s > lvl), None)
    first = lvl == BASE
    window = FIRST_WINDOW if first else LATER_WINDOW
    minimum = FIRST_MINIMUM if first else LATER_MINIMUM
    ev = evidence(session, bid, mailbox_id, moment, days=window.days) if box else {
        "cold": 0, "bounces": 0, "complaints": 0, "unsubscribes": 0, "failed_checks": 0, "genuine_replies": 0,
        "days": window.days}
    unmet = []
    if box is None:
        unmet.append("This isn't one of this business's campaign inboxes")
    else:
        reviewed = _parse(box.get("health_reviewed_at"))
        if box.get("warmup_stage") != BASE or not box.get("health_reviewed_by") or reviewed is None:
            unmet.append("The inbox is still warming up: it must reach 20 a day first")
        elif first and moment - reviewed < FIRST_WINDOW:
            unmet.append(f"28 days at 20 a day ({(moment - reviewed).days} so far)")
        if box.get("pause_reason") or not box.get("enabled"):
            unmet.append("The inbox is paused")
        elif not _passing_today(box, moment):
            unmet.append("Today's inbox check must pass")
    if following is None:
        unmet.append("50 a day is the ceiling. For more, add a properly warmed second inbox")
    elif not first:
        since = _parse((_boosts(session, bid).get(str(mailbox_id)) or {}).get("since"))
        held = (moment - since).days if since else 0
        if since is None or moment - since < HOLD:
            unmet.append(f"14 days at {lvl} a day ({held} so far)")
    if ev["cold"] < minimum:
        unmet.append(f"At least {minimum} cold emails in {window.days} days ({ev['cold']} so far)")
    unmet += _quality_misses(ev)
    if not ev["genuine_replies"]:
        unmet.append(f"At least one genuine reply in {window.days} days")
    session.rollback()
    return {"mailbox_id": str(mailbox_id), "level": lvl, "next": following,
            "eligible": following is not None and not unmet, "unmet": unmet, "evidence": ev, "notice": NOTICE}


def boost(session, business, user, mailbox_id, *, moment: Optional[datetime] = None) -> dict:
    """The owner steps a qualifying inbox up one level."""
    from services import outreach_setup as setup
    bid = str(business.id)
    moment = moment or send.now()
    setup._authority(session, business, user, growth=False)   # the active owner, current entitlement, under lock
    check = eligibility(session, bid, mailbox_id, moment)       # (ends the read; the lock is retaken below)
    if not check["eligible"]:
        refuse(409, "This inbox doesn't qualify for a boost yet: " + "; ".join(check["unmet"]) + ".")
    setup._authority(session, business, user, growth=False)
    if level(session, bid, mailbox_id) != check["level"]:
        refuse(409, "This inbox's level changed just now. Please refresh and try again.")
    boosts = _boosts(session, bid)
    entry = boosts.get(str(mailbox_id)) or {}
    entry.update(level=check["next"], since=moment.isoformat(), by=str(user))
    entry.pop("dropped_at", None)
    boosts[str(mailbox_id)] = entry
    _save(session, bid, boosts)
    session.commit()
    return {"mailbox_id": str(mailbox_id), "level": check["next"]}


def review(session, bid: str, mailbox_id, moment: datetime) -> int:
    """From the daily inbox check, in its transaction: drop back if the record
    has worsened. A complaint or any pause: straight back to 20. Otherwise a
    miss over the last 14 days drops one step, at most one step per 14 days."""
    bid = str(bid)
    boosts = _boosts(session, bid)
    entry = boosts.get(str(mailbox_id))
    if not entry or entry.get("level") not in STEPS or entry["level"] == BASE:
        return BASE
    box = _mailbox(session, bid, mailbox_id)
    ev = evidence(session, bid, mailbox_id, moment, days=LATER_WINDOW.days)
    if box is None or box.get("pause_reason") or not box.get("enabled") or ev["complaints"]:
        boosts.pop(str(mailbox_id))
        _save(session, bid, boosts)
        return BASE
    dropped = _parse(entry.get("dropped_at"))
    if dropped is not None and moment - dropped < HOLD:
        return int(entry["level"])
    misses = _quality_misses(ev)
    if not misses:
        return int(entry["level"])
    lowered = int(entry["level"]) - 10
    if lowered <= BASE:
        boosts.pop(str(mailbox_id))
    else:
        entry.update(level=lowered, since=moment.isoformat(), dropped_at=moment.isoformat(), reason=misses[0])
        boosts[str(mailbox_id)] = entry
    _save(session, bid, boosts)
    return max(BASE, lowered)
