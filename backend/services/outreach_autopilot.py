"""OUT-11 — auto-approve outreach (docs/OUT-11-TICKET.md).

A standing permission, per campaign, that the owner grants once trust is
earned (5 emails approved by hand and accepted). While valid, Aria prepares
due emails and approves them herself, one at a time and spread out. The
permission is re-read FRESH at the moment of every send: who granted it,
whether they are still the active owner, the campaign's wording and sender
versions, and the business's entitlement. Answers to replies are never
automatic. Every OUT-6 send rule still applies inside the claim.
"""

import random
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text

from services import aria_actions
from services import outreach_send as send
from services import outreach_setup as setup
from services.chase_replies import _parse

KEY, PACE_KEY = "outreach_autopilot", "outreach_autopilot_pace"
MARKER = "outreach_autopilot"
TRUST_NEEDED = 5                                   # decision A
MIN_GAP, RANDOM_GAP = timedelta(minutes=6), timedelta(minutes=6)   # decision C
LONDON = ZoneInfo("Europe/London")
refuse = setup.refuse


def now() -> datetime:
    return send.now()


def _grants(session, bid: str) -> dict:
    return dict(setup._settings_doc(session, bid).get(KEY) or {})


def manual_accepted(session, bid: str, campaign_id: str) -> int:
    """Sends in this campaign that the OWNER approved by hand and the
    provider accepted. Automatic sends never earn trust."""
    count = 0
    for (snapshot,) in session.execute(text(
            "SELECT authority_snapshot FROM outreach_messages WHERE business_id = :b AND campaign_id = :c "
            "AND direction = 'outbound' AND origin = 'live' AND state = 'accepted'"),
            {"b": bid, "c": str(campaign_id)}):
        snap = send.loads(snapshot) or {}
        if snap.get("user_id") and not snap.get("automation"):
            count += 1
    return count


def _entitled(session, bid: str) -> bool:
    row = session.execute(text(
        "SELECT plan_tier, feature_flags, subscription_status, is_active, trial_ends_at FROM businesses "
        "WHERE id = :b"), {"b": bid}).mappings().first()
    if row is None:
        return False
    business = SimpleNamespace(**row)
    business.feature_flags = send.loads(business.feature_flags) or {}
    business.trial_ends_at = _parse(business.trial_ends_at)
    from auth import assert_feature_access
    try:
        assert_feature_access(business, "outreach")
    except HTTPException:
        return False
    return True


def valid_grant(session, business, campaign_id, *, lock: bool = False):
    """(grant, None) when the permission still holds RIGHT NOW, else
    (None, reason). Never trusts anything cached."""
    bid = str(business.id)
    grant = _grants(session, bid).get(str(campaign_id))
    if not grant:
        return None, "Automatic sending is off for this campaign"
    found = send.rows(session, "outreach_campaigns", bid, "AND id = :c", {"c": str(campaign_id)}, lock)
    if not found:
        return None, "Campaign unavailable"
    c = found[0]
    if (int(c["version"]) != int(grant["campaign_version"])
            or int(c["sequence_version"]) != int(grant["sequence_version"])
            or str(c["mailbox_id"]) != str(grant["mailbox_id"])):
        return None, "The campaign's wording or sender changed: review it and switch automatic sending on again"
    owner = SimpleNamespace(id=bid)
    if not aria_actions._is_active_owner(session, owner, grant["granted_by"], lock=lock):
        return None, "The owner who allowed automatic sending is no longer the active owner"
    if not _entitled(session, bid):
        return None, "Outreach isn't switched on for this business"
    return grant, None


def grant(session, business, user, campaign_id, data: dict) -> dict:
    setup._authority(session, business, user)
    bid = str(business.id)
    c = send.one(session, "outreach_campaigns", bid, campaign_id, True)
    send.require(int(c["version"]) == int(data.get("version", -1))
                 and int(c["sequence_version"]) == int(data.get("sequence_version", -1)),
                 "The campaign changed since you looked: review it again", 409)
    earned = manual_accepted(session, bid, str(c["id"]))
    if earned < TRUST_NEEDED:
        refuse(409, f"Approve this campaign's first {TRUST_NEEDED} emails yourself first "
                    f"({TRUST_NEEDED - earned} to go)")
    doc = setup._settings_doc(session, bid)
    moment = now()
    doc.setdefault(KEY, {})[str(c["id"])] = {
        "granted_by": str(user), "granted_at": moment.isoformat(), "campaign_version": int(c["version"]),
        "sequence_version": int(c["sequence_version"]), "mailbox_id": str(c["mailbox_id"])}
    setup._save_settings_doc(session, bid, doc)
    session.commit()
    return {"campaign_id": str(c["id"]), "granted_at": moment.isoformat()}


def revoke(session, business, user, campaign_id) -> dict:
    setup._authority(session, business, user, growth=False)
    bid = str(business.id)
    doc = setup._settings_doc(session, bid)
    (doc.get(KEY) or {}).pop(str(campaign_id), None)
    setup._save_settings_doc(session, bid, doc)
    session.commit()
    return {"campaign_id": str(campaign_id), "enabled": False}


def status(session, business) -> dict:
    bid = str(business.id)
    grants = _grants(session, bid)
    out = {}
    for c in send.rows(session, "outreach_campaigns", bid):
        cid = str(c["id"])
        earned = manual_accepted(session, bid, cid)
        held, reason = valid_grant(session, business, cid)
        g = grants.get(cid) or {}
        out[cid] = {"enabled": bool(g), "valid": bool(held), "reason": None if held else (reason if g else None),
                    "manual_accepted": earned, "needed": max(0, TRUST_NEEDED - earned),
                    "granted_by": g.get("granted_by"), "granted_at": g.get("granted_at")}
    session.rollback()
    return out


def _lock(session, bid: str) -> None:
    """The shared business lock (OUT-6's order) for pace and settings writes."""
    if not send.pg(session):
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})
    send.lock_business(session, bid)


def _reserve_pace(session, bid: str, moment: datetime, gap: timedelta):
    """Claim the business's next automatic-send slot BEFORE sending, under the
    lock, changing only the pace key (Codex OUT-11 review 1: pace written
    after the send let two runs both send, and a whole-document write could
    restore a permission revoked meanwhile). Returns (token, previous) or
    (None, waiting message)."""
    import uuid as _uuid
    _lock(session, bid)
    doc = setup._settings_doc(session, bid)
    current = doc.get(PACE_KEY) or {}
    pace = _parse(current.get("next_at"))
    if pace and moment < pace:
        session.rollback()
        minutes = max(1, int((pace - moment).total_seconds() // 60) + 1)
        return None, f"Next automatic email in about {minutes} minute(s)"
    token = _uuid.uuid4().hex
    doc[PACE_KEY] = {"next_at": (moment + gap).isoformat(), "token": token}
    setup._save_settings_doc(session, bid, doc)
    session.commit()
    return token, current


def _release_pace(session, bid: str, token: str, previous: dict) -> None:
    """A send that did not happen gives its slot back, if still ours."""
    _lock(session, bid)
    doc = setup._settings_doc(session, bid)
    if (doc.get(PACE_KEY) or {}).get("token") == token:
        if previous:
            doc[PACE_KEY] = previous
        else:
            doc.pop(PACE_KEY, None)
        setup._save_settings_doc(session, bid, doc)
    session.commit()


def _due_enrolment(session, bid: str, campaign_id: str, moment: datetime):
    open_for = set()
    for action in send.rows(session, "aria_actions", bid,
                            "AND action_type = 'send_outreach' AND status IN ('proposed', 'executing')"):
        open_for.add(str((send.loads(action["payload"]) or {}).get("enrolment_id")))
    for e in send.rows(session, "outreach_enrolments", bid,
                       "AND campaign_id = :c AND state = 'active' AND takeover_at IS NULL ORDER BY next_due_at, id",
                       {"c": campaign_id}):
        due = _parse(e["next_due_at"])
        if due and due <= moment and str(e["id"]) not in open_for:
            return e
    return None


def send_next(session, business, campaign_id, *, moment: Optional[datetime] = None,
              rng: Callable = random.random) -> dict:
    """At most one automatic send for this campaign. Returns why not, if not."""
    moment = moment or now()
    bid, cid = str(business.id), str(campaign_id)
    held, reason = valid_grant(session, business, cid)
    if not held:
        session.rollback()
        return {"sent": None, "waiting": reason}
    settings = send.rows(session, "outreach_settings", bid)
    if not settings or settings[0]["pause_all"]:
        session.rollback()
        return {"sent": None, "waiting": "Outreach is paused"}
    local = moment.astimezone(LONDON)
    if local.weekday() >= 5 or not 9 <= local.hour < 17:
        session.rollback()
        return {"sent": None, "waiting": "Outside sending hours (weekdays 9–5 UK)"}
    pace = _parse((setup._settings_doc(session, bid).get(PACE_KEY) or {}).get("next_at"))
    if pace and moment < pace:
        minutes = max(1, int((pace - moment).total_seconds() // 60) + 1)
        session.rollback()
        return {"sent": None, "waiting": f"Next automatic email in about {minutes} minute(s)"}
    c = send.one(session, "outreach_campaigns", bid, cid)
    e = _due_enrolment(session, bid, cid, moment)
    if e is None:
        session.rollback()
        return {"sent": None, "waiting": "Nothing is due"}
    step = next((s for s in send.rows(session, "outreach_sequence_steps", bid,
                                      "AND campaign_id = :c AND sequence_version = :v",
                                      {"c": cid, "v": c["sequence_version"]})
                 if int(s["ordinal"]) == int(e["next_step"])), None)
    session.rollback()
    if step is None:
        return {"sent": None, "waiting": "No approved step is due"}
    # Reserve from the CURRENT time, never a moment captured earlier in the
    # run (Codex OUT-11 review 2: a stale moment could hand out an expired slot).
    token, previous = _reserve_pace(session, bid, max(moment, now()), MIN_GAP + RANDOM_GAP * float(rng()))
    if token is None:
        return {"sent": None, "waiting": previous}
    proposed = aria_actions.propose(session, business, None, "send_outreach",
                                    {"campaign_id": cid, "enrolment_id": str(e["id"]), "step_id": str(step["id"])},
                                    automation=MARKER)
    if "proposal" not in proposed:
        _release_pace(session, bid, token, previous)
        return {"sent": None, "waiting": proposed.get("error") or "Could not prepare the email"}
    card = proposed["proposal"]
    try:
        result = aria_actions.approve(session, business, card["id"], None, card["version"])
    except aria_actions.ActionRefused as exc:
        try:
            aria_actions.dismiss(session, business, card["id"])
        except aria_actions.ActionRefused:
            pass
        _release_pace(session, bid, token, previous)
        return {"sent": None, "waiting": exc.detail}
    went = result.get("status") in ("done", "executing")
    if not went:
        _release_pace(session, bid, token, previous)
    return {"sent": card["id"] if went else None,
            "waiting": None if went else f"Send {result.get('status')}"}


def run_due(session, *, moment: Optional[datetime] = None) -> list:
    """From the scheduler: one automatic send per business per call, at most,
    for any campaign with a valid permission. The pace does the spreading."""
    moment = moment or now()
    sent = []
    rows = session.execute(text("SELECT business_id, settings FROM business_settings")).fetchall()
    session.rollback()
    for bid, raw in rows:
        grants = (send.loads(raw) or {}).get(KEY) or {}
        if not grants:
            continue
        row = session.execute(text("SELECT * FROM businesses WHERE id = :b"), {"b": str(bid)}).mappings().first()
        session.rollback()
        if row is None:
            continue
        business = SimpleNamespace(**row)
        business.feature_flags = send.loads(business.feature_flags) or {}
        for cid in sorted(grants):
            try:
                out = send_next(session, business, cid)   # each reads the clock afresh
            except Exception:
                session.rollback()
                continue
            if out["sent"]:
                sent.append(out["sent"])
                break
    return sent
