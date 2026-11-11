"""OUT-26 — approving outreach with the business as a real ORM object, as
the API passes it (auth._load_business), on real PostgreSQL. The send
harness passes a SimpleNamespace, which never expires on commit. Mike, 11 Nov
2026: two approvals in production stopped with the claim committed and the
dispatch never started."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import pytest
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, OWNER, _count, _propose, pg  # noqa: F401
from test_outreach_send import A

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


def test_a_tapped_card_is_sent_with_the_business_as_the_api_loads_it(pg):
    import auth
    card = _propose(pg)
    with Session(pg.engine) as s:
        business = auth._load_business(s, A)            # an ORM Business, expired on commit
        out = pg.a.approve(s, business, card["id"], OWNER, version=card["version"])
    assert out["status"] == "done", out
    assert _count(pg, "SELECT state FROM outreach_messages WHERE business_id = :b", b=A) == "accepted"
