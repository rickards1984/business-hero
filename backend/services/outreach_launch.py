"""OUT-20: one Launch checklist per brand (Mike, 4 Nov 2026).

Mike finished setup for UKFI and saw "set up and ready", yet nothing was
researched: research is its own switch, OFF by default, on the Settings tab.
This puts every condition outreach needs for a brand in one place, each with
what to fix and where, plus one Launch and one Pause.

Launch switches on only what the owner has already approved: research for that
brand. It never approves an audience, a template, a notice or a mailbox, and
it refuses while anything else is missing. Research then adds the contacts it
finds to the brand's ready campaign, where every email still waits for the
owner's approval (or the campaign's auto-approve, if the owner granted it).
Pause switches the brand's research off; emails already in a sequence carry on
under their own approvals (Pause all, in Settings, stops everything).
"""
import os

from sqlalchemy import bindparam, text

from services import outreach_research as research
from services import outreach_send as send
from services import outreach_setup as setup

def _runnable_audiences(session, bid: str, brand_id: str, moment, sendable: set) -> dict:
    """Research's OWN rules, per approved audience of the brand (Codex OUT-20
    review 2): `research._audience` (the approval is current), a ready or
    running campaign of this brand for THIS audience, and (OUT-23) the room in
    its bank today, `research._bank_room`. An audience counts only if all hold."""
    out = {"any_approved": False, "current": False, "runnable": False, "room": 0, "no_room": None}
    for (cid,) in session.execute(text(
            "SELECT id FROM outreach_compliance WHERE business_id = :b AND brand_id = :br AND decision = 'approved'"),
            {"b": bid, "br": brand_id}):
        out["any_approved"] = True
        try:
            lia, _ = research._audience(session, bid, cid, moment)
        except send.ActionRefused:
            continue
        out["current"] = True
        # OUT-23: research's own gate is now the audience's bank (B3):
        # research._bank_room, the same function research runs.
        room = research._bank_room(session, bid, brand_id, lia["audience_hash"], moment)
        campaigns = session.execute(text(
            "SELECT count(*) FROM outreach_campaigns WHERE business_id = :b AND brand_id = :br "
            "AND target_hash = :h AND status IN ('ready', 'running')"),
            {"b": bid, "br": brand_id, "h": lia["audience_hash"]}).scalar()
        # Launch also needs that audience's campaign emails approved on a
        # healthy inbox (setup's rule), so whatever research finds can actually
        # be emailed. By audience (hash), not version: a newer draft never hides
        # an older approval research still uses (Codex OUT-20 review 3).
        if campaigns and lia["audience_hash"] in sendable:
            out["runnable"] = True
            out["room"] = max(out["room"], int(room["room"]))
            if not room["room"]:
                out["no_room"] = room["why"]
    return out


def _spend_gates(session, bid: str, brand_id: str, rb: dict, moment) -> dict:
    """Research's own reservation gates: a provider exists, the price is known,
    the platform limit, the brand's AI allowance, and its monthly budget, each
    for the WHOLE reservation one search takes."""
    from services import ai_costs, ai_router, outreach_allowance
    try:
        reserve = int(ai_router.reserve_pence())
    except ai_costs.Unpriced:
        return {"provider": False, "platform": True, "allowance": True, "budget": True}
    provider = reserve > 0
    return {"provider": provider,
            "platform": ai_costs.allowed(session, moment=moment, purpose="research"),
            "allowance": provider and outreach_allowance.may_research(session, bid, brand_id, moment, reserve),
            "budget": provider and int(rb.get("spent_pence") or 0) + reserve <= int(rb.get("monthly_cap_pence") or 0)}


def _item(key, label, done, fix, section):
    return {"key": key, "label": label, "done": bool(done), "fix": None if done else fix, "section": section}


def checklist(session, business) -> dict:
    """Every brand's launch checklist, built on the functions research itself
    runs (Codex OUT-20 reviews 1 and 2). Read only.

    Launch is deliberately STRICTER than research on what sending needs (a
    checked mailbox, the privacy notice): contacts found for a brand that can't
    email them would only age. Today's room is shown, never a launch blocker:
    a full inbox is a daily state, not a setup fault."""
    from fastapi import HTTPException
    from auth import assert_feature_access
    from services import outreach_billing
    bid = str(business.id)
    moment = research.now()
    state = setup.status(session, business)
    started = bool(state.get("started"))
    rows = send.rows(session, "outreach_settings", bid)
    paused_all = bool(rows and setup._truthy(rows[0]["pause_all"]))
    row = setup.load_business_row(session, bid)
    plan_ok = False
    if row is not None:
        row.feature_flags = send.loads(row.feature_flags) or {}
        row.trial_ends_at = research._parse(row.trial_ends_at)
        try:
            assert_feature_access(row, "outreach")
            plan_ok = True
        except HTTPException:
            plan_ok = False
    rstate = research.status(session, business)
    by_brand = {b["brand_id"]: b for b in rstate["brands"]}
    out = []
    for brand in state.get("brands") or []:
        rb = by_brand.get(brand["id"]) or {}
        ready_ids = [a["id"] for a in brand["audiences"] if a["campaign"] and a["campaign"]["ready"]]
        sendable = {h for (h,) in session.execute(text(
            "SELECT audience_hash FROM outreach_compliance WHERE business_id = :b AND id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)), {"b": bid, "ids": ready_ids})} if ready_ids else set()
        aud = _runnable_audiences(session, bid, brand["id"], moment, sendable)
        gates = _spend_gates(session, bid, brand["id"], rb, moment)
        paid = outreach_billing.brand_live(session, bid, brand["id"], moment)
        research_on = bool(rb.get("enabled")) and not rb.get("paused_reason")
        items = [
            _item("plan", "Outreach included on your plan", plan_ok, "Check your plan in Billing", "billing"),
            _item("started", "Outreach setup finished", started, "Finish the setup steps", "setup"),
            _item("not_paused", "Outreach isn't paused", not paused_all, "Unpause in Settings (Pause all is on)", "settings"),
            _item("paid", "Brand paid for", paid, "Pay for this brand in Settings", "settings"),
            _item("mailbox", "Sending mailbox checked" + (f": {brand['mailbox_address']}" if brand.get("mailbox_address") else ""),
                  brand["mailbox_ok"], "Check the brand's mailbox", "setup"),
            _item("privacy", "Privacy notice approved", brand["privacy"], "Approve the brand's privacy notice", "setup"),
            _item("audience", "An in-date audience with a running campaign", aud["runnable"],
                  ("The audience's approval is out of date: review it" if aud["any_approved"] and not aud["current"]
                   else "Approve the campaign's emails, or restart its paused campaign" if aud["current"]
                   else "Approve who this brand contacts"),
                  "campaigns" if aud["current"] else "setup"),
            # Research refuses before searching without it (no contact can be confirmed as a company).
            _item("companies_house", "Company checks available (Companies House)",
                  bool(os.environ.get("COMPANIES_HOUSE_API_KEY")),
                  "Company checks aren't configured on Business Hero yet; support has been told", "settings"),
            # Every contact found is checked against the opt-out list (OUT-21).
            _item("opt_out_checks", "Opt-out checks available", research.opt_out_checks_ready(),
                  "Opt-out checks aren't configured on Business Hero yet; support has been told", "settings"),
            _item("provider", "AI research available", gates["provider"] and gates["platform"],
                  "Research is unavailable right now (AI provider or platform limit); it resumes automatically",
                  "settings"),
            _item("allowance", "AI allowance left for a search", gates["allowance"],
                  "Top up the brand's AI allowance in Settings", "settings"),
            _item("budget", "Research budget left for a search", gates["budget"],
                  "Raise the brand's monthly research budget", "settings"),
            _item("research", "Aria researching new contacts each weekday", research_on,
                  f"Research paused: {rb['paused_reason']}" if rb.get("paused_reason") else "Press Launch to switch research on",
                  "settings"),
        ]
        ready = all(i["done"] for i in items if i["key"] != "research")
        out.append({"brand_id": brand["id"], "name": brand["name"], "items": items,
                    "can_launch": ready and not rb.get("paused_reason"),
                    "launched": ready and research_on,
                    "research_enabled": bool(rb.get("enabled")),
                    "room_today": aud["room"], "no_room_reason": aud["no_room"] if not aud["room"] else None,
                    "daily_target": rstate.get("daily_target_per_brand"),
                    "last_run": rstate.get("last_run")})
    session.rollback()
    return {"brands": out}


def _brand(session, business, brand_id) -> dict:
    send.require(brand_id, "Choose the brand to launch", 422)
    for b in checklist(session, business)["brands"]:
        if b["brand_id"] == str(brand_id):
            return b
    setup.refuse(404, "Brand not found")


def launch(session, business, user, data: dict) -> dict:
    """Owner-only: switch research on for a brand whose every approval is in
    place. Refuses (409) naming what's missing."""
    setup._authority(session, business, user)
    session.rollback()
    b = _brand(session, business, data.get("brand_id"))
    if not b["can_launch"]:
        missing = [i["label"] for i in b["items"] if not i["done"] and i["key"] != "research"]
        setup.refuse(409, "Before launching: " + "; ".join(missing or ["research is paused"]))
    research.configure(session, business, user, {"brand_id": b["brand_id"], "enabled": True})
    return {"brand_id": b["brand_id"], "launched": True}


def pause(session, business, user, data: dict) -> dict:
    """Owner-only: switch the brand's research off. Like research's own switch,
    it needs no current growth entitlement (an owner can always stop spend)."""
    setup._authority(session, business, user, growth=False)
    session.rollback()
    b = _brand(session, business, data.get("brand_id"))
    research.configure(session, business, user, {"brand_id": b["brand_id"], "enabled": False})
    return {"brand_id": b["brand_id"], "launched": False}
