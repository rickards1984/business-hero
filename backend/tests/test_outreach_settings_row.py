"""OUT-22: MSC couldn't save a brand (Mike, 6 Nov 2026).

Setup locks the business's `business_settings` row before anything else, and
reported "Outreach record unavailable" (404) when the row didn't exist. New
Body had one only because connecting Xero created it; MSC never did. And the
"Tell Aria about it" answers were capped at 1,000 characters with no warning.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, db, grant, setup_module_or_missing  # noqa: F401


def _no_settings_row(db):
    with db.begin() as c:
        c.execute(text("DELETE FROM business_settings WHERE business_id = :b"), {"b": A})


def test_a_business_with_no_settings_row_can_begin_and_save_a_brand(db):
    m = setup_module_or_missing()
    biz = grant(db)
    _no_settings_row(db)
    with Session(db) as s:
        assert m.begin(s, biz, OWNER)["settings_id"]
        brand = m.save_brand(s, biz, OWNER, {"name": "MSC Ltd", "sender_identity": "MSC Ltd",
                                             "profile": {"offer": "Roofing and building work"}})
    assert brand["id"]
    with db.connect() as c:
        rows = c.execute(text("SELECT count(*) FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
        saved = c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
    assert rows == 1, "exactly one settings row is created"
    assert "Roofing and building work" in saved, "the brand's details are kept, not silently dropped"


def test_an_existing_settings_row_is_never_replaced(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
    with db.connect() as c:
        saved = c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
    assert '"automations"' in saved, "other features' settings survive"


def test_only_the_owner_gets_a_settings_row_created(db):
    from test_outreach_setup import STAFF
    m = setup_module_or_missing()
    biz = grant(db)
    _no_settings_row(db)
    with Session(db) as s, pytest.raises(Exception):
        m.begin(s, biz, STAFF)
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM business_settings WHERE business_id = :b"), {"b": A}).scalar() == 0


def test_brand_details_take_up_to_4000_characters(db):
    m = setup_module_or_missing()
    biz = grant(db)
    long = "x" * 4000
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "MSC Ltd", "sender_identity": "MSC Ltd",
                                             "profile": {k: long for k in ("offer", "audience", "proof", "tone", "ask")}})
    assert brand["id"]
    with Session(db) as s, pytest.raises(Exception):
        m.save_brand(s, biz, OWNER, {"name": "MSC Ltd", "sender_identity": "MSC Ltd", "profile": {"offer": long + "x"}})
    with Session(db) as s, pytest.raises(Exception):   # a website is an address, not an essay
        m.save_brand(s, biz, OWNER, {"name": "MSC Ltd", "sender_identity": "MSC Ltd", "profile": {"website": "x" * 1001}})


def test_the_api_accepts_4000_and_refuses_4001():
    from outreach_setup_api import BrandProfile
    assert BrandProfile(offer="x" * 4000, audience="x" * 4000, proof="x" * 4000, tone="x" * 4000, ask="x" * 4000)
    with pytest.raises(ValidationError):
        BrandProfile(offer="x" * 4001)
    with pytest.raises(ValidationError):
        BrandProfile(website="x" * 1001)


@pytest.mark.parametrize("locker", ["send", "dashboard", "billing"])
def test_every_settings_lock_creates_a_missing_row_before_anything_reads_it(db, locker):
    """Codex OUT-22 review 2: a writer that locked, read and saved a business
    with no row read an empty document, and its save could overwrite a row
    created meanwhile. Every lock helper now makes the row first."""
    from services import outreach_billing, outreach_dashboard, outreach_send
    biz = grant(db)
    m = setup_module_or_missing()
    with Session(db) as s:
        m.begin(s, biz, OWNER)            # outreach_settings, for the shared business lock
    _no_settings_row(db)
    lock = {"send": outreach_send.lock_business, "dashboard": outreach_dashboard._lock,
            "billing": outreach_billing._lock}[locker]
    with Session(db) as s:
        lock(s, A)
        assert s.execute(text("SELECT count(*) FROM business_settings WHERE business_id = :b"), {"b": A}).scalar() == 1
        s.commit()
