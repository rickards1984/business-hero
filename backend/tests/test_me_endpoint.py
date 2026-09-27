"""GET /v1/me — the endpoint the whole frontend bootstraps from.

WHY THIS FILE EXISTS. On 27 Sep 2026 `/v1/me` returned 500 to every
logged-in customer for about eight hours. Login worked and then nothing
loaded, because every page calls this endpoint first. The cause:

    AttributeError: 'BusinessContext' object has no attribute
                    'subscription_status'

`get_business_for_user()` returns a `BusinessContext` — a four-field dataclass
(`id`, `name`, `timezone`, `logo_url`). BH-006 added
`resolve_access_level(business)` to this endpoint on the assumption that
`business` was the `Business` ORM row. It is not.

**Nothing in 619 passing tests caught it**, and the reason is worth stating
because it generalises: BH-006's resolver suite called
`resolve_access_level()` directly, with a real `Business` built by its own
fixture. It proved the resolver correct and said nothing about whether the
CALLER hands it the right object. `./check.sh` cannot catch this either —
`docs/TESTING.md` records that there are no end-to-end tests, and this is
exactly the gap that sentence describes.

So these tests go through the real FastAPI app with the real dependency
wiring, and assert the SHAPE of the response the frontend depends on. They
would have failed on the broken code with a 500.

The second bug, which the crash was hiding, is `test_the_plan_tier_is_the_real_one`:
the lines that read `plan_tier`, `feature_flags` and `brand_color` used
`getattr(business, name, default)` against that same `BusinessContext`, so
they never raised — they silently returned the DEFAULT. `/v1/me` had been
reporting `plan_tier: "starter"` and `feature_flags: {}` for every business,
whatever they actually had, and `AppShell` gates the Quotes nav on those
values. A silent default is worse than a crash: the crash was found in hours,
that had been wrong for as long as the code existed.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

import main
from assistant_chat import BusinessContext
from auth import get_user_auth_context
from db import get_session
from models import Business

USER_ID = "user-me-test"
BUSINESS_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class MeSession:
    """Answers the one query the endpoint makes, and refuses anything else."""

    def __init__(self, business):
        self.business = business
        self.queries = 0

    def exec(self, statement):
        self.queries += 1
        entity = statement.column_descriptions[0]["entity"]
        assert entity is Business, f"/v1/me queried {entity!r}"
        where = statement.whereclause
        assert where is not None, "an unfiltered lookup would match anything"
        expected = getattr(where.right, "value", None)
        if self.business is None:
            return FakeResult(None)
        # Postgres coerces a string to uuid against a uuid column.
        if str(self.business.id) == str(expected):
            return FakeResult(self.business)
        return FakeResult(None)

    def execute(self, statement, params=None):
        # the platform_admins probe, if anything reaches for it
        return FakeResult(None)


def a_business(**overrides):
    fields = dict(
        id=BUSINESS_ID,
        name="New Body Gym LTD",
        timezone="Europe/London",
        logo_url="https://example.invalid/logo.png",
        brand_color="#123456",
        plan_tier="business",
        feature_flags={"receptionist": True},
        subscription_status="active",
        is_active=True,
        trial_ends_at=None,
        api_key="bh_test",
    )
    fields.update(overrides)
    return Business(**fields)


@pytest.fixture
def call_me(monkeypatch):
    """Call the REAL endpoint through the REAL app, with only auth stubbed.

    `get_business_for_user` is patched to return a `BusinessContext`, which is
    what it genuinely returns in production — that fidelity is the whole point
    of this file.
    """
    def _call(business, *, has_membership=True, is_platform_admin=False):
        if has_membership:
            ctx = BusinessContext(
                id=str(BUSINESS_ID), name="New Body Gym LTD",
                timezone="Europe/London", logo_url="https://example.invalid/logo.png")
            monkeypatch.setattr(main, "get_business_for_user", lambda _uid: ctx)
        else:
            def _raise(_uid):
                raise ValueError("NO_BUSINESS", "no business for this user")
            monkeypatch.setattr(main, "get_business_for_user", _raise)

        session = MeSession(business)
        main.app.dependency_overrides[get_user_auth_context] = lambda: {
            "user_id": USER_ID, "email": "owner@example.invalid",
            "is_platform_admin": is_platform_admin,
        }
        main.app.dependency_overrides[get_session] = lambda: session
        try:
            return TestClient(main.app).get("/v1/me")
        finally:
            main.app.dependency_overrides.pop(get_user_auth_context, None)
            main.app.dependency_overrides.pop(get_session, None)

    return _call


# ── the outage itself ────────────────────────────────────────────────────────

def test_me_returns_200_for_a_normal_business(call_me):
    """THE REGRESSION. This returned 500 in production on 27 Sep 2026."""
    response = call_me(a_business())
    assert response.status_code == 200, (
        f"/v1/me is {response.status_code}; every page in the app bootstraps "
        f"from it, so this is a total outage. Body: {response.text[:400]}")


@pytest.mark.parametrize("status_value,expected_level,expected_warning,expected_ro", [
    ("active",   "full",      False, False),
    ("trialing", "full",      False, False),
    ("past_due", "full",      True,  False),
    ("unpaid",   "read_only", False, True),
    ("canceled", "read_only", False, True),
])
def test_the_access_fields_are_the_resolver_s_answer(
        call_me, status_value, expected_level, expected_warning, expected_ro):
    """The banner renders from these, so they must be the server's own answer
    rather than a second derivation in the client."""
    response = call_me(a_business(subscription_status=status_value))
    assert response.status_code == 200
    body = response.json()
    assert body["subscription_status"] == status_value
    assert body["access_level"] == expected_level
    assert body["payment_warning"] is expected_warning
    assert body["read_only"] is expected_ro


def test_the_plan_tier_is_the_real_one_not_a_getattr_default(call_me):
    """The bug the crash was hiding.

    The old code read these through `getattr(business, name, default)` against
    a BusinessContext that has none of them, so it silently returned
    `plan_tier: "starter"`, `feature_flags: {}`, `brand_color: None` for every
    business in the product. AppShell gates navigation on those values.
    """
    response = call_me(a_business(
        plan_tier="business",
        feature_flags={"receptionist": True},
        brand_color="#123456",
    ))
    body = response.json()
    assert body["plan_tier"] == "business", (
        "plan_tier came back as the getattr default instead of the real column")
    assert body["feature_flags"] == {"receptionist": True}
    assert body["brand_color"] == "#123456"


def test_the_identity_fields_are_present(call_me):
    body = call_me(a_business()).json()
    assert body["user_id"] == USER_ID
    assert body["email"] == "owner@example.invalid"
    assert body["business_id"] == str(BUSINESS_ID)
    assert body["id"] == str(BUSINESS_ID)
    assert body["name"] == "New Body Gym LTD"
    assert body["timezone"] == "Europe/London"


def test_the_business_row_is_actually_loaded(call_me):
    """Guards the fix rather than its symptom: if a later change went back to
    reading the BusinessContext, no query would be made and the access fields
    would be wrong or absent."""
    business = a_business()
    ctx = BusinessContext(id=str(BUSINESS_ID), name="x", timezone="x", logo_url=None)
    session = MeSession(business)
    import main as main_module
    main_module.app.dependency_overrides[get_user_auth_context] = lambda: {
        "user_id": USER_ID, "email": "e", "is_platform_admin": False}
    main_module.app.dependency_overrides[get_session] = lambda: session
    original = main_module.get_business_for_user
    main_module.get_business_for_user = lambda _uid: ctx
    try:
        response = TestClient(main_module.app).get("/v1/me")
    finally:
        main_module.get_business_for_user = original
        main_module.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert session.queries == 1, (
        "/v1/me did not load the Business row; the access fields cannot be "
        "correct without it")


# ── the cases that must not 500 either ───────────────────────────────────────

def test_a_user_with_no_business_gets_200_and_nulls(call_me):
    """A brand-new user, or an admin with no business of their own. Must not
    500 and must not invent a business."""
    response = call_me(None, has_membership=False)
    assert response.status_code == 200
    body = response.json()
    assert body["business_id"] is None
    assert "access_level" not in body
    assert body["user_id"] == USER_ID


def test_a_membership_pointing_at_a_missing_business_degrades(call_me):
    """`business_members` names a business with no `businesses` row. Should not
    happen; must not take the app down if it does — which is precisely the
    failure mode this file was written after."""
    response = call_me(None, has_membership=True)
    assert response.status_code == 200
    body = response.json()
    assert body["business_id"] == str(BUSINESS_ID)
    assert body["name"] == "New Body Gym LTD"
    # Nothing that needs the row is invented.
    assert "access_level" not in body
    assert "plan_tier" not in body


def test_a_business_with_no_stripe_subscription_is_not_a_500(call_me):
    """subscription_status IS NULL is the normal state for a business the admin
    created. The resolver must cope and the endpoint must answer."""
    response = call_me(a_business(subscription_status=None, trial_ends_at=None))
    assert response.status_code == 200
    body = response.json()
    assert body["subscription_status"] is None
    assert body["access_level"] in ("full", "suspended")


def test_an_admin_suspended_business_still_answers(call_me):
    response = call_me(a_business(is_active=False, subscription_status="active"))
    assert response.status_code == 200
    assert response.json()["access_level"] == "suspended"
