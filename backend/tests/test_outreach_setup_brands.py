"""OUT-18 part B — setup per brand (docs/OUT-18-TICKET.md).

Each brand has its own sending mailbox, its own audiences and one email
sequence per audience. Setup is finished when ONE brand is ready; another
brand is set up by repeating the steps, at any time. New Body's real shape:
FitFutures (partners-ukfi@) contacts gyms only; New Body gym (outreach@)
contacts schools and charities, each with its own email.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import (A, NOW, OWNER, WORKSPACE, GOOD_GOOGLE, _insert, db, dns, draft_emails,  # noqa: F401
                                 draft_lia, draft_notice, grant, ready, setup_module_or_missing, uid)

PARTNERS = uid("partners-box")


@pytest.fixture
def biz(db):
    with Session(db) as s:
        _insert(s, "email_accounts", id=PARTNERS, business_id=A, user_id=OWNER, provider="google",
                email_address="partners-ukfi@newbody.example", is_default=False, capabilities="{}",
                token_ciphertext="fake", created_at=NOW.isoformat())
        s.commit()
    return grant(db)


def approve_emails(s, biz, campaign_id):
    from services import outreach_manage
    c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns WHERE id = :c"),
                  {"c": campaign_id}).one()
    outreach_manage.approve_templates(s, biz, OWNER, campaign_id, {"version": int(c[0]), "sequence_version": int(c[1])})


def audience(m, s, biz, brand, description, segment):
    lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": description,
                                          "segments": [segment], "regions": ["Essex"]}, draft=draft_lia)
    m.approve_audience(s, biz, OWNER, lia["id"], {})
    return lia


def campaign(m, s, biz, brand, lia, box, name):
    out = m.create_first_campaign(s, biz, OWNER, {"name": name, "brand_id": brand["id"], "mailbox_id": box,
                                                  "compliance_id": lia["id"], "daily_cap": 5}, draft=draft_emails)
    approve_emails(s, biz, out["id"])
    return out


def fitfutures(m, s, biz, *, notice=True, emails=True):
    m.register_mailbox(s, biz, OWNER, {"mailbox_id": PARTNERS, "daily_cap": 5})
    m.check_mailbox_health(s, biz, OWNER, PARTNERS, resolve=dns(GOOD_GOOGLE))
    brand = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "FitFutures by UKFI",
                                         "default_mailbox_id": PARTNERS})
    lia = audience(m, s, biz, brand, "Gyms and health centres that could host an intern", "gym")
    if notice:
        m.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": draft_notice({})})
    if emails:
        campaign(m, s, biz, brand, lia, PARTNERS, "Host a FitFutures intern")
    return brand, lia


def brand_row(state, brand):
    return next(b for b in state["brands"] if b["id"] == brand["id"])


def test_status_lists_each_brand_with_its_own_mailbox_audiences_and_readiness(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        fit, fit_lia = fitfutures(m, s, biz)
        state = m.status(s, biz)
    row = brand_row(state, fit)
    assert row["name"] == "FitFutures" and row["mailbox_id"] == PARTNERS
    assert row["mailbox_address"] == "partners-ukfi@newbody.example" and row["mailbox_ok"] is True
    assert row["privacy"] is True and row["ready"] is True
    assert [a["id"] for a in row["audiences"]] == [fit_lia["id"]]
    assert row["audiences"][0]["description"].startswith("Gyms") and row["audiences"][0]["approved"] is True
    assert row["audiences"][0]["campaign"]["ready"] is True
    assert row["audiences"][0]["campaign"]["name"] == "Host a FitFutures intern"


def test_one_ready_brand_finishes_setup_while_another_is_still_being_set_up(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        fit, _ = fitfutures(m, s, biz)
        gym = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        state = m.status(s, biz)
        assert brand_row(state, gym)["ready"] is False
        assert state["complete"] is True
        m.finish(s, biz, OWNER)
        assert m.status(s, biz)["started"] is True


def test_a_brand_without_its_own_privacy_notice_is_not_ready(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        fit, _ = fitfutures(m, s, biz, notice=False)
        state = m.status(s, biz)
    assert brand_row(state, fit)["ready"] is False and state["complete"] is False


def test_a_brand_whose_emails_are_not_approved_is_not_ready(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        fit, fit_lia = fitfutures(m, s, biz, emails=False)
        m.create_first_campaign(s, biz, OWNER, {"name": "Draft", "brand_id": fit["id"], "mailbox_id": PARTNERS,
                                                "compliance_id": fit_lia["id"], "daily_cap": 5}, draft=draft_emails)
        state = m.status(s, biz)
    row = brand_row(state, fit)
    assert row["ready"] is False and row["audiences"][0]["campaign"]["ready"] is False


def test_another_brands_ready_campaign_never_makes_a_brand_ready(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        fitfutures(m, s, biz)
        gym = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        m.approve_privacy_notice(s, biz, OWNER, gym["id"], {"text": draft_notice({})})
        audience(m, s, biz, gym, "Secondary schools needing PE support", "school")
        state = m.status(s, biz)
    assert brand_row(state, gym)["ready"] is False


def test_each_audience_of_a_brand_has_its_own_email(db, biz):
    """New Body gym: schools get a PE provision email, charities a collaboration email."""
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(GOOD_GOOGLE))
        gym = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd",
                                           "default_mailbox_id": WORKSPACE})
        m.approve_privacy_notice(s, biz, OWNER, gym["id"], {"text": draft_notice({})})
        schools = audience(m, s, biz, gym, "Secondary schools needing PE support", "school")
        charities = audience(m, s, biz, gym, "Youth charities", "charity")
        campaign(m, s, biz, gym, schools, WORKSPACE, "PE provision")
        campaign(m, s, biz, gym, charities, WORKSPACE, "Collaboration")
        row = brand_row(m.status(s, biz), gym)
    names = {a["description"]: a["campaign"]["name"] for a in row["audiences"]}
    assert names == {"Secondary schools needing PE support": "PE provision", "Youth charities": "Collaboration"}
    assert row["ready"] is True


def test_a_brand_mailbox_that_fails_its_check_is_not_ready(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        fit, _ = fitfutures(m, s, biz)
        s.execute(text("UPDATE outreach_mailboxes SET health_status = 'fail' WHERE mailbox_id = :m"), {"m": PARTNERS})
        s.commit()
        state = m.status(s, biz)
    row = brand_row(state, fit)
    assert row["mailbox_ok"] is False and row["ready"] is False


def test_a_brand_set_up_before_out18_without_a_chosen_mailbox_shows_its_campaign_mailbox(db, biz):
    """The original single-brand wizard never stored a brand mailbox."""
    m = setup_module_or_missing()
    brand, lia, first = ready(m, db, biz)
    with Session(db) as s:
        approve_emails(s, biz, first["id"])
        row = brand_row(m.status(s, biz), brand)
    assert row["mailbox_id"] == WORKSPACE and row["ready"] is True


def test_choosing_a_brand_mailbox_later_keeps_the_brand(db, biz):
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        gym = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        again = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd",
                                             "default_mailbox_id": WORKSPACE})
        row = brand_row(m.status(s, biz), gym)
    assert again["id"] == gym["id"] and row["mailbox_id"] == WORKSPACE
