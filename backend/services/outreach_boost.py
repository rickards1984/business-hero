"""OUT-19 G — boosting an inbox with a proven record (decision 5,
docs/OUT-19-TICKET.md). RED: sending limits and deliverability.

Mike, 30 Oct 2026: a boost is FREE (the brand's hidden AI ceiling still caps
our cost; extra research is bought with top-ups) and the OWNER OPTS IN when an
inbox qualifies. Dropping back is always automatic.

Steps: 20 → 30 → 40 → 50 cold emails a day per inbox. 50 is the ceiling.

Qualifying for 30: 28 days at 20 a day (from the owner's stage-20 review, or
from the inbox's last reset to 20, whichever is later), and over the last 28
UK days: at least 200 cold emails; bounces under 2%; unsubscribes under 1% (by
reply or by link, once per person); no complaints; no failed daily check; at
least one genuine reply; not paused and passing today. Each later step: 14 days
at the current level and the same measures over the last 14 days, with at
least 150 cold emails. After dropping back a step, 14 days before stepping up.

Dropping back, checked with the daily inbox check: missing ANY measure over
the last 14 days drops one step (at most one step per 14 days). A complaint or
any pause resets the inbox to 20 at once, in the transaction that pauses it,
and it qualifies again from the start (Codex review 1).

Reputation is judged from our own evidence only: Business Hero can't see
Google's or Microsoft's internal score.

State lives in the business settings document (no migration):
  outreach_boost = {mailbox_id: {"level": 30, "since": iso, "by": user,
                                 "dropped_at": iso, "reset_at": iso, "reason": text}}
An entry back at 20 is kept, so its reset or drop still counts.
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
    lvl = (_boosts(session, bid).get(str(mailbox_id)) or {}).get("level")
    return int(lvl) if lvl in STEPS else BASE


def _sending(box: Optional[dict]) -> bool:
    return bool(box) and box.get("warmup_stage") == BASE and bool(box.get("enabled")) and not box.get("pause_reason")


def follow(limit: int, cap: int) -> int:
    """An owner's limit left at the maximum (20) rises with a boost; a limit
    the owner set below 20 still binds."""
    return cap if int(limit) >= BASE else int(limit)


def brand_level(session, bid: str, brand_id) -> int:
    """The level a brand's own limit (and monthly allowance) follows: the
    highest boost among the brand's campaign inboxes that can send. One policy
    for the send path and research (Codex review 1)."""
    bid = str(bid)
    boosts = _boosts(session, bid)
    best = BASE
    for (mailbox_id,) in session.execute(text(
            "SELECT DISTINCT mailbox_id FROM outreach_campaigns WHERE business_id = :b AND brand_id = :br"),
            {"b": bid, "br": str(brand_id)}):
        lvl = (boosts.get(str(mailbox_id)) or {}).get("level")
        if lvl in STEPS and lvl > best and _sending(_mailbox(session, bid, mailbox_id)):
            best = int(lvl)
    return best


def provider_limit(health: dict) -> Optional[int]:
    """A sending limit the provider imposes on the inbox, if one is recorded.
    It binds everything the inbox sends, replies included."""
    value = (health or {}).get("provider_daily_cap")
    return int(value) if value is not None else None


def _local_date(moment: datetime) -> str:
    from services.metering import LONDON
    return moment.astimezone(LONDON).date().isoformat()


def record_check(session, bid: str, mailbox_id, moment: datetime, *, passed: bool) -> None:
    """From the inbox check: a failed check is counted for that inbox and UK
    day (a durable history the latest-check columns don't keep)."""
    if passed:
        return
    from services import outreach_research
    outreach_research._add_meter(session, str(bid), f"{CHECK_METER}:{mailbox_id}:{_local_date(moment)}", moment, 1)


def reset(session, bid: str, mailbox_id, moment: datetime, reason: str) -> None:
    """Back to 20 at once, in the caller's transaction (a complaint, a pause,
    a retirement). The reset is remembered: the inbox qualifies again from it."""
    boosts = _boosts(session, str(bid))
    entry = boosts.get(str(mailbox_id)) or {}
    entry.update(level=BASE, reset_at=moment.isoformat(), reason=str(reason)[:200])
    for k in ("since", "dropped_at"):
        entry.pop(k, None)
    boosts[str(mailbox_id)] = entry
    _save(session, str(bid), boosts)


def _mailbox(session, bid: str, mailbox_id) -> Optional[dict]:
    found = send.rows(session, "outreach_mailboxes", str(bid), "AND mailbox_id = :m", {"m": str(mailbox_id)})
    return found[0] if len(found) == 1 else None


def _window_start(moment: datetime, days: int) -> tuple:
    """The first UK day of the window, and its start as a moment: every
    measure uses the same whole UK days (Codex review 1)."""
    from services.metering import LONDON
    first = (moment.astimezone(LONDON) - timedelta(days=days)).date()
    start = datetime(first.year, first.month, first.day, tzinfo=LONDON)
    return first.isoformat(), start


def evidence(session, bid: str, mailbox_id, moment: datetime, *, days: int) -> dict:
    """Our own evidence for one inbox over the last `days` UK days and today."""
    bid, box = str(bid), str(mailbox_id)
    first_day, start = _window_start(moment, days)
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
    # Link unsubscribes carry no inbox: traced to the people this inbox
    # actually emailed (an accepted send), never a draft or a failed attempt.
    for prospect, suppressed in session.execute(text(
            "SELECT p.id, s.suppressed_at FROM outreach_suppressions s JOIN outreach_prospects p "
            "ON p.business_id = s.business_id AND p.email_key = s.key_digest "
            "WHERE s.business_id = :b AND s.key_type = 'email' AND s.reason = 'unsubscribe' "
            "AND EXISTS (SELECT 1 FROM outreach_messages m WHERE m.business_id = p.business_id "
            "AND m.prospect_id = p.id AND m.mailbox_id = :mb AND m.direction = 'outbound' AND m.state = 'accepted')"),
            {"b": bid, "mb": box}):
        if within(suppressed):
            unsubscribed.add(str(prospect))
    prefix = f"{CHECK_METER}:{box}:"
    failed_days = 0
    for meter, value in session.execute(text(
            "SELECT meter, value FROM usage_meters WHERE business_id = :b AND meter LIKE :m"),
            {"b": bid, "m": prefix + "%"}):
        if first_day <= meter[len(prefix):] <= _local_date(moment) and int(value or 0) > 0:
            failed_days += 1
    return {"cold": cold, "bounces": counts["bounce"], "complaints": counts["complaint"],
            "unsubscribes": len(unsubscribed), "failed_check_days": failed_days,
            "genuine_replies": counts["genuine"], "days": days}


def _rate(n: int, cold: int) -> float:
    return n / cold if cold else (1.0 if n else 0.0)


def _misses(ev: dict, minimum: int, *, quality_only: bool = False) -> list:
    """Every measure the window's record fails: the same list decides a step
    up and a drop back (Codex review 1: "miss ANY measure"). `quality_only`:
    the deliverability measures alone (bounces, unsubscribes, complaints,
    failed checks), for a level still in its first fortnight."""
    out = []
    if ev["cold"] < minimum and not quality_only:
        out.append(f"At least {minimum} cold emails in {ev['days']} days ({ev['cold']} so far)")
    if _rate(ev["bounces"], ev["cold"]) >= BOUNCE_LIMIT:
        out.append(f"Bounces must stay under 2% ({ev['bounces']} of {ev['cold']} cold emails)")
    if _rate(ev["unsubscribes"], ev["cold"]) >= UNSUBSCRIBE_LIMIT:
        out.append(f"Unsubscribes must stay under 1% ({ev['unsubscribes']} of {ev['cold']} cold emails)")
    if ev["complaints"]:
        out.append(f"No complaints ({ev['complaints']} in the last {ev['days']} days)")
    if ev["failed_check_days"]:
        out.append(f"No failed daily inbox check (failed on {ev['failed_check_days']} day"
                   f"{'' if ev['failed_check_days'] == 1 else 's'} in the last {ev['days']})")
    if not ev["genuine_replies"] and not quality_only:
        out.append(f"At least one genuine reply in {ev['days']} days")
    return out


def _passing_today(box: dict, moment: datetime) -> bool:
    checked = _parse(box.get("health_checked_at"))
    return (box.get("health_status") == "pass" and checked is not None and checked <= moment
            and _local_date(checked) == _local_date(moment))


def _evaluate(session, bid: str, mailbox_id, moment: datetime) -> dict:
    """The decision itself, in the caller's transaction (no rollback)."""
    from services import metering
    bid = str(bid)
    box = _mailbox(session, bid, mailbox_id)
    entry = _boosts(session, bid).get(str(mailbox_id)) or {}
    lvl = int(entry["level"]) if box and entry.get("level") in STEPS else BASE
    following = next((s for s in STEPS if s > lvl), None)
    first = lvl == BASE
    window = FIRST_WINDOW if first else LATER_WINDOW
    ev = evidence(session, bid, mailbox_id, moment, days=window.days) if box else {
        "cold": 0, "bounces": 0, "complaints": 0, "unsubscribes": 0, "failed_check_days": 0, "genuine_replies": 0,
        "days": window.days}
    unmet, effective = [], 0
    if box is None:
        unmet.append("This isn't one of this business's campaign inboxes")
    else:
        # What it can send TODAY: nothing while paused or without today's
        # passing check, as the send path (Codex review 2).
        effective = metering.mailbox_daily_cap(box, boost=lvl) if _passing_today(box, moment) else 0
        reviewed = _parse(box.get("health_reviewed_at"))
        if box.get("warmup_stage") != BASE or not box.get("health_reviewed_by") or reviewed is None:
            unmet.append("The inbox is still warming up: it must reach 20 a day first")
        elif first:
            began = max(t for t in (reviewed, _parse(entry.get("reset_at"))) if t is not None)
            if moment - began < FIRST_WINDOW:
                unmet.append(f"28 days at 20 a day ({max(0, (moment - began).days)} so far"
                             + (", counted from its reset" if began != reviewed else "") + ")")
        if box.get("pause_reason") or not box.get("enabled"):
            unmet.append("The inbox is paused")
        elif not _passing_today(box, moment):
            unmet.append("Today's inbox check must pass")
    if following is None:
        unmet.append("50 a day is the ceiling. For more, add a properly warmed second inbox")
    else:
        dropped = _parse(entry.get("dropped_at"))
        if dropped is not None and moment - dropped < HOLD:
            unmet.append(f"14 days since it dropped back ({(moment - dropped).days} so far)")
        if not first:
            since = _parse(entry.get("since"))
            if since is None or moment - since < HOLD:
                unmet.append(f"14 days at {lvl} a day ({(moment - since).days if since else 0} so far)")
    unmet += _misses(ev, FIRST_MINIMUM if first else LATER_MINIMUM)
    return {"mailbox_id": str(mailbox_id), "level": lvl, "effective": effective, "next": following,
            "eligible": following is not None and not unmet, "unmet": unmet, "evidence": ev, "notice": NOTICE}


def eligibility(session, bid: str, mailbox_id, moment: datetime) -> dict:
    """Whether the inbox may step up now, the measures not yet met, the
    evidence behind them, and what it can actually send today."""
    out = _evaluate(session, bid, mailbox_id, moment)
    session.rollback()
    return out


def boost(session, business, user, mailbox_id, *, moment: Optional[datetime] = None) -> dict:
    """The owner steps a qualifying inbox up one level. The whole decision is
    made under the business lock, in the transaction that saves it (Codex
    review 1: nothing can land between the check and the grant)."""
    from services import outreach_setup as setup
    bid = str(business.id)
    moment = moment or send.now()
    setup._authority(session, business, user, growth=False)   # the active owner, current entitlement, under lock
    check = _evaluate(session, bid, mailbox_id, moment)
    if not check["eligible"]:
        refuse(409, "This inbox doesn't qualify for a boost yet: " + "; ".join(check["unmet"]) + ".")
    boosts = _boosts(session, bid)
    entry = boosts.get(str(mailbox_id)) or {}
    entry.update(level=check["next"], since=moment.isoformat(), by=str(user))
    for k in ("dropped_at", "reason"):
        entry.pop(k, None)
    boosts[str(mailbox_id)] = entry
    _save(session, bid, boosts)
    session.commit()
    return {"mailbox_id": str(mailbox_id), "level": check["next"]}


def review(session, bid: str, mailbox_id, moment: datetime) -> int:
    """From the daily inbox check, in its transaction: drop back if the record
    has worsened. A complaint or any pause: straight back to 20. Otherwise
    missing any measure over the last 14 days drops one step, at most one step
    per 14 days."""
    bid = str(bid)
    boosts = _boosts(session, bid)
    entry = boosts.get(str(mailbox_id))
    if not entry or entry.get("level") not in STEPS or entry["level"] == BASE:
        return BASE
    box = _mailbox(session, bid, mailbox_id)
    ev = evidence(session, bid, mailbox_id, moment, days=LATER_WINDOW.days)
    if box is None or box.get("pause_reason") or not box.get("enabled") or ev["complaints"]:
        reset(session, bid, mailbox_id, moment, "complaint" if ev["complaints"] else "paused")
        return BASE
    dropped = _parse(entry.get("dropped_at"))
    if dropped is not None and moment - dropped < HOLD:
        return int(entry["level"])        # at most one step per 14 days
    since = _parse(entry.get("since"))
    fresh = since is not None and moment - since < HOLD
    # A level in its first fortnight hasn't had time to build volume or draw a
    # reply, but worsening deliverability drops it at once (Codex review 2).
    misses = _misses(ev, LATER_MINIMUM, quality_only=fresh)
    if not misses:
        return int(entry["level"])
    lowered = max(BASE, int(entry["level"]) - 10)
    entry.update(level=lowered, since=moment.isoformat(), dropped_at=moment.isoformat(), reason=misses[0])
    boosts[str(mailbox_id)] = entry
    _save(session, bid, boosts)
    return lowered
