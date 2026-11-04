"""OUT-20: one Launch checklist per brand (Mike, 4 Nov 2026).

Setup said UKFI was "set up and ready", but nothing was researched: research
is a separate switch that starts OFF, on another tab. The checklist shows
every condition outreach needs for a brand, with what to fix; Launch switches
on only what the owner has already approved (research for the brand) and
never skips an approval; Pause switches research off.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import OWNER, STAFF, db, grant, ready, setup_module_or_missing  # noqa: F401
from test_outreach_research import research, setup_clock


def launch():
    import importlib
    return importlib.import_module("services.outreach_launch")


def finished(db, *, approve=True):
    """Setup complete (or not), research NOT switched on: Mike's UKFI."""
    with setup_clock():
        m = setup_module_or_missing()
        biz = grant(db)
        brand, lia, campaign = ready(m, db, biz)
        with Session(db) as s:
            if approve:
                from services import outreach_manage
                c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
                outreach_manage.approve_templates(s, biz, OWNER, campaign["id"],
                                                  {"version": int(c[0]), "sequence_version": int(c[1])})
                m.finish(s, biz, OWNER)
    return biz, brand


def items(state, brand_id):
    b = next(b for b in state["brands"] if b["brand_id"] == str(brand_id))
    return b, {i["key"]: i for i in b["items"]}


def test_a_set_up_brand_with_research_off_shows_exactly_that(db):
    biz, brand = finished(db)
    with Session(db) as s:
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["research"]["done"] is False and it["research"]["fix"]
    assert all(i["done"] for k, i in it.items() if k != "research"), it
    assert b["can_launch"] is True and b["launched"] is False


def test_launch_switches_research_on_and_the_brand_is_launched(db):
    biz, brand = finished(db)
    with Session(db) as s:
        launch().launch(s, biz, OWNER, {"brand_id": brand["id"]})
    with Session(db) as s:
        b, it = items(launch().checklist(s, biz), brand["id"])
        assert research().status(s, biz)["brands"][0]["enabled"] is True
    assert it["research"]["done"] and b["launched"] is True


def test_pause_switches_research_off(db):
    biz, brand = finished(db)
    with Session(db) as s:
        launch().launch(s, biz, OWNER, {"brand_id": brand["id"]})
        launch().pause(s, biz, OWNER, {"brand_id": brand["id"]})
    with Session(db) as s:
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["research"]["done"] is False and b["launched"] is False


def test_launch_never_skips_an_approval(db):
    """Templates not approved: the checklist says so and Launch is refused."""
    biz, brand = finished(db, approve=False)
    with Session(db) as s:
        b, it = items(launch().checklist(s, biz), brand["id"])
        assert it["campaign"]["done"] is False and b["can_launch"] is False
        with pytest.raises(Exception) as caught:
            launch().launch(s, biz, OWNER, {"brand_id": brand["id"]})
    assert getattr(caught.value, "status_code", None) == 409
    with Session(db) as s:
        assert research().status(s, biz)["brands"][0]["enabled"] is False


def test_only_the_owner_can_launch_or_pause(db):
    biz, brand = finished(db)
    with Session(db) as s:
        for action in (launch().launch, launch().pause):
            with pytest.raises(Exception) as caught:
                action(s, biz, STAFF, {"brand_id": brand["id"]})
            assert getattr(caught.value, "status_code", None) == 403


def test_pause_all_is_shown_and_blocks_launch(db):
    biz, brand = finished(db)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_settings SET pause_all = :t"), {"t": True})
        s.commit()
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["not_paused"]["done"] is False and b["can_launch"] is False


@pytest.mark.parametrize("who,code", [(OWNER, 200), (STAFF, 403)])
def test_the_launch_endpoints(db, monkeypatch, who, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import auth
    import outreach_setup_api as api
    from auth import get_user_business_context
    from db import get_session
    from rate_limiting import limiter
    from test_outreach_setup import A
    biz, brand = finished(db)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz)
    monkeypatch.setattr(limiter, "enabled", False)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": who}
    app.dependency_overrides[get_session] = lambda: Session(db)
    with TestClient(app) as client:
        seen = client.get("/v1/outreach/setup/launch")
        started = client.post("/v1/outreach/setup/launch", json={"brand_id": brand["id"]})
        stopped = client.post("/v1/outreach/setup/launch/pause", json={"brand_id": brand["id"]})
    assert seen.status_code == 200 and seen.json()["brands"][0]["can_launch"] is True
    assert started.status_code == code and stopped.status_code == code


# --------------------------------- Codex OUT-20 review 1: runtime parity ---

def test_an_out_of_date_audience_approval_blocks_launch(db):
    biz, brand = finished(db)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_compliance SET review_due_at = :d"), {"d": "2000-01-01T00:00:00+00:00"})
        s.commit()
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["audience"]["done"] is False and "out of date" in it["audience"]["fix"]
    assert b["can_launch"] is False


def test_a_paused_campaign_blocks_launch(db):
    biz, brand = finished(db)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_campaigns SET status = 'paused'"))
        s.commit()
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["campaign"]["done"] is False and b["can_launch"] is False


def test_unapproved_templates_after_setup_block_launch(db):
    """The template gate on its own: setup finished, then the steps unapproved."""
    biz, brand = finished(db)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_sequence_steps SET approved_at = NULL"))
        s.commit()
        b, it = items(launch().checklist(s, biz), brand["id"])
        assert it["started"]["done"] and it["campaign"]["done"] is False and b["can_launch"] is False
        with pytest.raises(Exception) as caught:
            launch().launch(s, biz, OWNER, {"brand_id": brand["id"]})
    assert getattr(caught.value, "status_code", None) == 409


def test_an_unpaid_brand_and_a_used_allowance_block_launch(db, monkeypatch):
    from services import outreach_billing, outreach_research
    biz, brand = finished(db)
    monkeypatch.setattr(outreach_billing, "brand_live", lambda *a, **k: False)
    with Session(db) as s:
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["paid"]["done"] is False and b["can_launch"] is False
    monkeypatch.setattr(outreach_billing, "brand_live", lambda *a, **k: True)
    real = outreach_research.status

    def used_up(session, business):
        out = real(session, business)
        for b_ in out["brands"]:
            b_["allowance_used_percent"] = 100
        return out
    monkeypatch.setattr(outreach_research, "status", used_up)
    with Session(db) as s:
        b, it = items(launch().checklist(s, biz), brand["id"])
    assert it["allowance"]["done"] is False and b["can_launch"] is False


def test_pause_works_without_growth_entitlement(db, monkeypatch):
    """An owner can always stop research spending (like research's own switch)."""
    import auth
    biz, brand = finished(db)
    with Session(db) as s:
        launch().launch(s, biz, OWNER, {"brand_id": brand["id"]})
    real = auth.assert_feature_access

    def retained_only(business, feature, **kw):
        if not kw.get("retained_history"):
            from fastapi import HTTPException
            raise HTTPException(403, "growth lapsed")
        return real(business, feature, **kw)
    monkeypatch.setattr(auth, "assert_feature_access", retained_only)
    with Session(db) as s:
        launch().pause(s, biz, OWNER, {"brand_id": brand["id"]})
    with Session(db) as s:
        assert research().status(s, biz)["brands"][0]["enabled"] is False
