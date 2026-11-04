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
from sqlalchemy import text

from services import outreach_research as research
from services import outreach_send as send
from services import outreach_setup as setup

def _current_audiences(session, bid: str, brand_id: str, moment) -> tuple:
    """(any current approval, any approval at all) for the brand, by the same
    rule research uses at run time (research._audience: reviewer, dates)."""
    current = any_approved = False
    for (cid,) in session.execute(text(
            "SELECT id FROM outreach_compliance WHERE business_id = :b AND brand_id = :br AND decision = 'approved'"),
            {"b": bid, "br": brand_id}):
        any_approved = True
        try:
            research._audience(session, bid, cid, moment)
            current = True
        except send.ActionRefused:
            pass
    return current, any_approved


def _campaign_runs(session, bid: str, brand: dict) -> bool:
    """A campaign research can place contacts in (research.capacity): ready
    by setup's rule (templates approved, on the brand's healthy mailbox) AND
    its status ready or running (a paused or finished campaign takes nobody)."""
    ids = {a["campaign"]["id"] for a in brand["audiences"]
           if a["approved"] and a["campaign"] and a["campaign"]["ready"]}
    if not ids:
        return False
    return any(str(c["id"]) in ids and c["status"] in ("ready", "running")
               for c in send.rows(session, "outreach_campaigns", bid, "AND brand_id = :br", {"br": brand["id"]}))


def _item(key, label, done, fix, section):
    return {"key": key, "label": label, "done": bool(done), "fix": None if done else fix, "section": section}


def checklist(session, business) -> dict:
    """Every brand's launch checklist, by the rules research applies when it
    runs (Codex OUT-20 review 1). Read only."""
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
        current, any_approved = _current_audiences(session, bid, brand["id"], moment)
        paid = outreach_billing.brand_live(session, bid, brand["id"], moment)
        allowance_left = (rb.get("allowance_used_percent") or 0) < 100
        budget_left = int(rb.get("spent_pence") or 0) < int(rb.get("monthly_cap_pence") or 0)
        research_on = bool(rb.get("enabled")) and not rb.get("paused_reason")
        items = [
            _item("plan", "Outreach included on your plan", plan_ok, "Check your plan in Billing", "billing"),
            _item("started", "Outreach setup finished", started, "Finish the setup steps", "setup"),
            _item("not_paused", "Outreach isn't paused", not paused_all, "Unpause in Settings (Pause all is on)", "settings"),
            _item("paid", "Brand paid for", paid, "Pay for this brand in Settings", "settings"),
            _item("mailbox", "Sending mailbox checked" + (f": {brand['mailbox_address']}" if brand.get("mailbox_address") else ""),
                  brand["mailbox_ok"], "Check the brand's mailbox", "setup"),
            _item("audience", "Audience approved and in date", current,
                  "The audience's approval is out of date: review it" if any_approved
                  else "Approve who this brand contacts", "setup"),
            _item("privacy", "Privacy notice approved", brand["privacy"], "Approve the brand's privacy notice", "setup"),
            _item("campaign", "Campaign approved and running", _campaign_runs(session, bid, brand),
                  "Approve the campaign's emails, or restart a paused campaign", "campaigns"),
            _item("allowance", "AI allowance left this month", allowance_left, "Top up the brand's AI allowance in Settings",
                  "settings"),
            _item("budget", "Research budget left this month", budget_left, "Raise the brand's monthly research budget",
                  "settings"),
            _item("research", "Aria researching new contacts each weekday", research_on,
                  f"Research paused: {rb['paused_reason']}" if rb.get("paused_reason") else "Press Launch to switch research on",
                  "settings"),
        ]
        ready = all(i["done"] for i in items if i["key"] != "research")
        out.append({"brand_id": brand["id"], "name": brand["name"], "items": items,
                    "can_launch": ready and not rb.get("paused_reason"),
                    "launched": ready and research_on,
                    "research_enabled": bool(rb.get("enabled")),
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
