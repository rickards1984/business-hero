"""BH-006 / ENTITLEMENT-SPEC DECISION 3 — the read-only resolver, enforced.

`test_stripe_webhook_correctness.py` pins the WEBHOOK half of DECISION 3: the
tier never moves on a payment event, and the status is recorded verbatim. Its
`NOT_PINNED` registry then said, correctly, that a faithful status with no
resolver behind it enforces nothing. This file is that resolver.

WHAT DECISION 3 REQUIRES, and what each part is tested by here:

  | requirement                                           | tested by |
  |-------------------------------------------------------|-----------|
  | one resolver, in one place, status -> access level     | `TestTheResolver` |
  | past_due = FULL access, plus a user-visible warning    | `TestPastDueKeepsAccess` |
  | unpaid/canceled = read-only, NOT a downgrade           | `TestReadOnlyRefusesWrites` |
  | read-only refuses create, edit, AI, outbound —         | `TestReadOnlyRefusesWrites` |
  |   SERVER-SIDE ("hiding the buttons is not enforcement")| |
  | read-only PERMITS login, view, PDF/CSV export          | `TestReadOnlyPermitsReads` |
  | returning to active restores from the unchanged tier   | `TestRestoringAccess` |

WHAT IS NOT HERE: the Twilio number release (its own ticket, by instruction)
and the invoice/quote CSV export endpoints, which **do not exist yet** — see
`MISSING_EXPORT_SURFACE` at the bottom. A promise DECISION 3 makes that no
endpoint keeps is recorded, not assumed.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import auth
from models import Business


def a_business(**overrides):
    fields = dict(
        name="Synthetic Ltd",
        plan_tier="business",
        subscription_status="active",
        is_active=True,
        trial_ends_at=None,
        feature_flags={},
        stripe_customer_id="cus_synthetic",
        stripe_subscription_id="sub_synthetic",
    )
    fields.update(overrides)
    return Business(**fields)


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class GateSession:
    """Answers the two queries `require_feature` makes, and nothing else.

    Same discipline as the webhook suite's fake: it refuses anything it cannot
    answer truthfully rather than guessing, and it answers the admin probe for
    the user actually bound.
    """

    def __init__(self, business, user_id, admin_user_ids=()):
        self.business = business
        self.user_id = user_id
        self.admin_user_ids = set(admin_user_ids)

    def execute(self, statement, params=None):
        sql = str(statement).lower()
        assert "platform_admins" in sql, f"unexpected raw SQL: {sql[:120]}"
        asked = (params or {}).get("user_id")
        assert asked is not None, "the admin probe did not bind :user_id"
        return FakeResult((1,) if asked in self.admin_user_ids else None)

    def exec(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        assert entity is Business, f"the gate queried {entity!r}"
        where = statement.whereclause
        assert where is not None, "an unfiltered lookup would match anything"
        expected = getattr(where.right, "value", object())
        return FakeResult(self.business if expected == self.business.id else None)


class FakeRequest:
    """Only what `enforce_read_only` reads: the method and the path."""

    class _URL:
        def __init__(self, path):
            self.path = path

    def __init__(self, method="POST", path="/v1/quotes"):
        self.method = method
        self.url = self._URL(path)


def call_gate(business, feature_name, *, admin=False):
    """Run the REAL `require_feature` dependency. Returns True or the HTTP detail."""
    user_id = "user-synthetic"
    dependency = auth.require_feature(feature_name)
    session = GateSession(business, user_id,
                          admin_user_ids={user_id} if admin else set())
    try:
        asyncio.run(dependency(
            auth_ctx={"user_id": user_id, "business_id": business.id},
            session=session,
        ))
        return True
    except HTTPException as exc:
        return exc.detail


# ── The resolver itself ──────────────────────────────────────────────────────

class TestTheResolver:

    @pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
    def test_full_access_statuses(self, status):
        assert auth.resolve_access_level(a_business(subscription_status=status)) \
            == auth.ACCESS_FULL

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    def test_read_only_statuses(self, status):
        assert auth.resolve_access_level(a_business(subscription_status=status)) \
            == auth.ACCESS_READ_ONLY

    def test_the_status_is_read_case_and_space_insensitively(self):
        """Stripe's value is stored verbatim, so a stray case difference must
        not silently become 'unrecognised' and fall through to the trial
        path."""
        assert auth.resolve_access_level(a_business(subscription_status=" Past_Due ")) \
            == auth.ACCESS_FULL
        assert auth.resolve_access_level(a_business(subscription_status="CANCELED")) \
            == auth.ACCESS_READ_ONLY

    @pytest.mark.parametrize("status", ["incomplete", "incomplete_expired",
                                       "paused", "", None, "something_new"])
    def test_an_unrecognised_status_falls_to_the_trial_window_not_to_paid(self, status):
        """Fail-closed, and PRECISELY what that means: a status nobody has
        taught this resolver about is treated as "Stripe has said nothing", so
        an expired or absent trial is SUSPENDED and a live trial still works.

        Codex's review called the fail-closed claim "qualified at best",
        because a future trial date plus an unknown status yields FULL. That is
        intended — a business mid-trial has no subscription yet and an unknown
        status must not cut its trial short — and it is why the claim is
        written out here rather than asserted in one word.
        """
        expired = a_business(subscription_status=status, trial_ends_at=None)
        assert auth.resolve_access_level(expired) == auth.ACCESS_SUSPENDED

        in_trial = a_business(
            subscription_status=status,
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=3))
        assert auth.resolve_access_level(in_trial) == auth.ACCESS_FULL

    @pytest.mark.parametrize("status", ["active", "trialing", "past_due",
                                       "incomplete", "", None, "junk"])
    @pytest.mark.parametrize("trial", ["past", "future", "none"])
    def test_admin_suspension_is_absolute_for_every_non_read_only_status(
            self, status, trial):
        """`is_active` is the admin's switch, and NOTHING but read-only
        overrides it.

        The first version fell through to the trial window here, so
        `is_active=False` plus a FUTURE `trial_ends_at` returned FULL — an
        admin suspension silently overruled by a trial date, while the
        docstring claimed that could not happen. Codex reproduced it with
        `subscription_status='active'`. Parametrised over the whole matrix so
        it cannot come back one status at a time.
        """
        trial_ends_at = {
            "past": datetime.now(timezone.utc) - timedelta(days=1),
            "future": datetime.now(timezone.utc) + timedelta(days=30),
            "none": None,
        }[trial]
        business = a_business(subscription_status=status, is_active=False,
                              trial_ends_at=trial_ends_at)
        assert auth.resolve_access_level(business) == auth.ACCESS_SUSPENDED

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    @pytest.mark.parametrize("trial", ["past", "future", "none"])
    def test_read_only_is_the_one_exception_to_suspension(self, status, trial):
        """Read-only is MORE permissive than suspended, so ordering it first is
        an EXCEPTION to the admin switch, not a narrowing of it — Codex
        corrected the first version's reasoning on that.

        It is deliberate: DECISION 3's whole argument for read-only rather than
        lockout is statutory. UK VAT records must be kept six years and GDPR
        Art. 20 portability does not lapse, so a cancelled customer reaches
        their own invoices even if an admin also switched them off.
        """
        trial_ends_at = {
            "past": datetime.now(timezone.utc) - timedelta(days=1),
            "future": datetime.now(timezone.utc) + timedelta(days=30),
            "none": None,
        }[trial]
        assert auth.resolve_access_level(a_business(
            subscription_status=status, is_active=False,
            trial_ends_at=trial_ends_at)) == auth.ACCESS_READ_ONLY

    @pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
    @pytest.mark.parametrize("trial", ["past", "future", "none"])
    def test_a_paid_business_keeps_access_whatever_its_trial_date_says(
            self, status, trial):
        """The mutation Codex wrote that passed all 113 tests:

            if status_value in FULL_ACCESS_STATUSES:
                return ACCESS_SUSPENDED if business.trial_ends_at is not None \
                       else ACCESS_FULL

        — which suspends every paying customer who has ever had a trial date,
        past or future. Nothing in the suite noticed, because no test combined
        a full-access status with a non-null trial. This is that test.
        """
        trial_ends_at = {
            "past": datetime.now(timezone.utc) - timedelta(days=1),
            "future": datetime.now(timezone.utc) + timedelta(days=30),
            "none": None,
        }[trial]
        business = a_business(subscription_status=status, is_active=True,
                              trial_ends_at=trial_ends_at)
        assert auth.resolve_access_level(business) == auth.ACCESS_FULL

    def test_the_whole_access_matrix_is_pinned(self):
        """Every (status, is_active, trial) combination, in one table, so a
        wrong resolver has nowhere to hide. Written after Codex demonstrated
        that a deliberately incorrect resolver passed all 113 tests."""
        past = datetime.now(timezone.utc) - timedelta(days=1)
        future = datetime.now(timezone.utc) + timedelta(days=30)
        F, R, S = auth.ACCESS_FULL, auth.ACCESS_READ_ONLY, auth.ACCESS_SUSPENDED
        matrix = {
            # (status, is_active, trial) -> expected
            ("active",    True,  None):   F, ("active",    True,  past): F,
            ("active",    True,  future): F, ("active",    False, None): S,
            ("active",    False, past):   S, ("active",    False, future): S,
            ("trialing",  True,  None):   F, ("trialing",  True,  future): F,
            ("trialing",  False, future): S,
            ("past_due",  True,  None):   F, ("past_due",  True,  past): F,
            ("past_due",  False, None):   S,
            ("unpaid",    True,  None):   R, ("unpaid",    False, None): R,
            ("unpaid",    False, future): R,
            ("canceled",  True,  None):   R, ("canceled",  False, past): R,
            (None,        True,  None):   S, (None,        True,  future): F,
            (None,        True,  past):   S, (None,        False, future): S,
            ("junk",      True,  None):   S, ("junk",      True,  future): F,
            ("incomplete", True, None):   S, ("incomplete", True, future): F,
        }
        wrong = []
        for (status, active, trial), expected in matrix.items():
            got = auth.resolve_access_level(a_business(
                subscription_status=status, is_active=active,
                trial_ends_at=trial))
            if got != expected:
                wrong.append(f"({status!r}, is_active={active}, trial={trial!r}): "
                             f"expected {expected}, got {got}")
        assert wrong == [], "\n".join(wrong)

    def test_no_business_is_suspended_not_permitted(self):
        assert auth.resolve_access_level(None) == auth.ACCESS_SUSPENDED
        assert auth.is_read_only(None) is False

    def test_the_warning_is_only_for_past_due(self):
        assert auth.needs_payment_warning(a_business(subscription_status="past_due"))
        for status in ("active", "trialing", "unpaid", "canceled", None):
            assert not auth.needs_payment_warning(
                a_business(subscription_status=status)), status

    def test_the_two_status_sets_do_not_overlap(self):
        assert not (auth.FULL_ACCESS_STATUSES & auth.READ_ONLY_STATUSES)
        assert auth.WARNING_STATUSES <= auth.FULL_ACCESS_STATUSES

    def test_every_plan_feature_is_classified_read_only_permitted_or_refused(self):
        """The one that stops a new feature defaulting to free-for-nonpayers.

        Add a key to PLAN_FEATURE_DEFAULTS and you must say which side of the
        read-only line it falls on. Without this, an unclassified feature is
        silently refused (or silently allowed) depending on which list the
        gate consults first.
        """
        vocabulary = set(auth.PLAN_FEATURE_DEFAULTS["business"])
        classified = auth.READ_ONLY_PERMITTED_FEATURES | auth.READ_ONLY_REFUSED_FEATURES
        assert vocabulary - classified == set(), (
            f"unclassified features: {sorted(vocabulary - classified)} — add each "
            "to READ_ONLY_PERMITTED_FEATURES or READ_ONLY_REFUSED_FEATURES")
        assert not (auth.READ_ONLY_PERMITTED_FEATURES & auth.READ_ONLY_REFUSED_FEATURES)


# ── past_due: the live customer-facing failure ───────────────────────────────

class TestPastDueKeepsAccess:
    """DECISION 3: "a card that expired on Tuesday should not take the
    receptionist off the phones on Wednesday."

    The failure this replaced: the webhook wrote
    `is_active = status in ('active','trialing')`, so past_due set it False;
    `require_feature` refused when `not is_active and _is_trial_expired(...)`,
    and `_is_trial_expired` returns True whenever `trial_ends_at IS NULL` —
    every customer who never had a trial. One failed card, and the next
    request lost the feature.
    """

    @pytest.mark.parametrize("feature", ["receptionist", "aria_voice", "email",
                                         "whatsapp", "outreach", "quoting"])
    def test_a_past_due_business_keeps_every_feature_its_plan_grants(self, feature):
        business = a_business(plan_tier="business",
                              subscription_status="past_due",
                              trial_ends_at=None)
        assert call_gate(business, feature) is True, (
            f"a past_due business lost {feature}")

    def test_past_due_with_a_stale_is_active_false_is_still_suspended(self):
        """The honest consequence of keeping `is_active` absolute.

        Rows the OLD webhook wrote carry `is_active = False` for past_due, and
        this resolver cannot tell those from a deliberate admin suspension. So
        they stay suspended until repaired. That repair is prod SQL — RED,
        Mike runs it, `audits/BH-006-PROD-RUNBOOK.md` — and this test exists so
        the need for it is impossible to forget: it documents the state, it
        does not bless it.
        """
        business = a_business(subscription_status="past_due", is_active=False,
                              trial_ends_at=None)
        assert auth.resolve_access_level(business) == auth.ACCESS_SUSPENDED

    def test_past_due_raises_the_warning_flag_a_banner_can_read(self):
        assert auth.needs_payment_warning(
            a_business(subscription_status="past_due")) is True


# ── read-only: refusals ──────────────────────────────────────────────────────

class TestReadOnlyRefusesWrites:

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    @pytest.mark.parametrize("feature", ["aria_chat", "aria_voice", "email",
                                         "whatsapp", "receptionist", "outreach",
                                         "board_meetings", "calendar_booking"])
    def test_every_ai_and_outbound_feature_is_refused(self, status, feature):
        """Four of DECISION 3's refusals at once: AI (`aria_*`), outbound
        (`email`, `whatsapp`, `outreach`), the phone (`receptionist`) and
        booking. Server-side, through the real gate."""
        business = a_business(subscription_status=status, plan_tier="business")
        detail = call_gate(business, feature)
        assert detail is not True, f"{status} was allowed {feature}"
        assert "read-only" in str(detail).lower()

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    def test_every_mutating_request_is_refused(self, method, status):
        """The create/edit refusal, keyed on the HTTP method so that a new
        endpoint is covered the day it is written."""
        business = a_business(subscription_status=status)
        with pytest.raises(HTTPException) as caught:
            auth.enforce_access(FakeRequest(method, "/v1/quotes"), business)
        assert caught.value.status_code == 403
        assert "read-only" in caught.value.detail.lower()

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_a_SUSPENDED_business_is_refused_every_mutation(self, method):
        """The gap a mutation found: `enforce_access` returned early for
        ACCESS_SUSPENDED and nothing failed. A business an admin switched off,
        or one whose trial lapsed with no subscription, could still write
        through any endpoint with no separate feature gate."""
        for business in (a_business(subscription_status="active", is_active=False),
                         a_business(subscription_status=None, trial_ends_at=None)):
            assert auth.resolve_access_level(business) == auth.ACCESS_SUSPENDED
            with pytest.raises(HTTPException) as caught:
                auth.enforce_access(FakeRequest(method, "/v1/tasks"), business)
            assert caught.value.status_code == 403
            assert caught.value.detail == auth.SUSPENDED_DETAIL

    def test_a_SUSPENDED_business_is_refused_even_the_export_exemptions(self):
        """Suspension is not the statutory-retention case — it is an admin
        decision or a lapsed trial — so the read-only export and billing
        exemptions do not apply to it."""
        business = a_business(subscription_status="active", is_active=False)
        for method, path in (("POST", "/v1/billing/portal"),
                             ("POST", "/v1/quotes/q-1/generate-pdf")):
            with pytest.raises(HTTPException):
                auth.enforce_access(FakeRequest(method, path), business)

    def test_a_SUSPENDED_business_may_still_GET(self):
        """Reads are left to the feature gate, which refuses them with the same
        message — so a suspended business sees one consistent 403 rather than
        being silently shown an empty product."""
        business = a_business(subscription_status="active", is_active=False)
        auth.enforce_access(FakeRequest("GET", "/v1/quotes"), business)
        assert call_gate(business, "quoting") == auth.SUSPENDED_DETAIL

    def test_a_request_with_no_request_object_fails_closed(self):
        """`enforce_read_only(None, business)` must refuse, not exempt. A
        caller that cannot say what it is asking for does not get the
        export exemption."""
        with pytest.raises(HTTPException):
            auth.enforce_access(None, a_business(subscription_status="unpaid"))

    def test_a_full_access_business_is_never_refused(self):
        for status in ("active", "trialing", "past_due"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                auth.enforce_access(FakeRequest(method, "/v1/quotes"),
                                       a_business(subscription_status=status))

    def test_the_refusal_names_the_way_back(self):
        """A 403 that does not say how to fix it generates a support ticket."""
        detail = auth.READ_ONLY_DETAIL.lower()
        assert "read-only" in detail
        assert "billing" in detail
        assert "export" in detail or "view" in detail


# ── read-only: what it must still permit ─────────────────────────────────────

class TestReadOnlyPermitsReads:

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    @pytest.mark.parametrize("feature", ["quoting", "invoicing", "accounting"])
    def test_viewing_quotes_invoices_and_accounting_is_permitted(self, status, feature):
        """UK VAT records must be kept six years (HMRC VAT Notice 700/21) and
        GDPR Art. 20 portability does not lapse with payment."""
        business = a_business(subscription_status=status, plan_tier="business")
        assert call_gate(business, feature) is True, (
            f"a {status} business could not reach {feature}")

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    @pytest.mark.parametrize("path", ["/v1/quotes", "/v1/invoices",
                                      "/v1/accounting/transactions",
                                      "/v1/business/settings"])
    def test_an_ordinary_GET_is_permitted(self, status, path):
        auth.enforce_access(FakeRequest("GET", path),
                            a_business(subscription_status=status))

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    @pytest.mark.parametrize("path", [
        "/v1/accounting/export/accountant-pack",
        "/v1/integrations/awaz",
        "/v1/receptionist/voices/alloy/preview",
    ])
    def test_a_GET_THAT_WRITES_OR_SPENDS_is_refused(self, status, path):
        """Read-only is about EFFECT, not about the HTTP verb.

        Codex found five GETs that write or spend money, and the first version
        of this file waved all three of these through because they are GETs —
        it even asserted the accounting export was permitted, which contradicts
        DECISION 3's own scope decision:

          * /v1/accounting/export/accountant-pack — the 8 Sep 2026 decision
            limits read-only export to QUOTES AND INVOICES. Accounting history
            reaches Business Hero from the customer's own Xero/QuickBooks
            subscription and stays available to them there; the statutory
            retention argument is about records this product ORIGINATES.
          * /v1/integrations/awaz — creates an integration row and a webhook
            secret on a cache miss. A write behind a GET.
          * /v1/receptionist/voices/{id}/preview — generates paid OpenAI
            speech on a cache miss. A non-paying account spending our money.
        """
        with pytest.raises(HTTPException) as caught:
            auth.enforce_access(FakeRequest("GET", path),
                                a_business(subscription_status=status))
        assert caught.value.status_code == 403

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    def test_the_pdf_export_is_permitted_though_it_is_a_POST(self, status):
        """`POST /v1/quotes/{id}/generate-pdf` is an export, not a write. A
        blanket method rule would have broken the one thing DECISION 3
        promises a non-paying customer."""
        auth.enforce_access(
            FakeRequest("POST", "/v1/quotes/q-123/generate-pdf"),
            a_business(subscription_status=status))

    @pytest.mark.parametrize("status", ["unpaid", "canceled"])
    @pytest.mark.parametrize("path", ["/v1/billing/checkout-session",
                                      "/v1/billing/portal"])
    def test_paying_to_restore_access_is_permitted(self, status, path):
        """If the route back through billing were refused, read-only would be
        a trap: the customer could not pay to get out of it."""
        auth.enforce_access(FakeRequest("POST", path),
                               a_business(subscription_status=status))

    def test_the_allowlist_is_exactly_two_billing_posts(self):
        """A guard on the allowlist itself: anything added to it is a hole in
        the write refusal, so it stays short and every entry is one of the two
        things DECISION 3 names. Method is part of the key."""
        assert auth.READ_ONLY_ALLOWED_EXACT == frozenset({
            ("POST", "/v1/billing/checkout-session"),
            ("POST", "/v1/billing/portal"),
        })

    @pytest.mark.parametrize("method,path", [
        # Codex defeated the first version's startswith/endswith matching with
        # the first two of these. The third would have matched the quote-DELETE
        # route while passing the guard.
        ("POST",   "/v1/billing/portal-anything"),
        ("POST",   "/v1/billing/checkout-session/../../admin/businesses"),
        ("DELETE", "/v1/quotes/generate-pdf"),
        ("DELETE", "/v1/billing/portal"),
        ("POST",   "/v1/quotes/generate-pdf/delete"),
        ("POST",   "/v1/admin/billing/portal/reset"),
        ("POST",   "/v1/quotes/q-1/generate-pdf/extra"),
        ("PUT",    "/v1/quotes/q-1/generate-pdf"),
    ])
    def test_a_near_miss_on_the_allowlist_is_refused(self, method, path):
        with pytest.raises(HTTPException):
            auth.enforce_access(FakeRequest(method, path),
                                a_business(subscription_status="unpaid"))

    def test_the_real_pdf_path_still_passes(self):
        auth.enforce_access(
            FakeRequest("POST", "/v1/quotes/8f14e45f-ceea-467a-9f5b-000000000001/generate-pdf"),
            a_business(subscription_status="unpaid"))


# ── platform admins, and getting back in ─────────────────────────────────────

class TestRestoringAccess:

    def test_a_platform_admin_is_not_read_only(self):
        """Admins are how a read-only account gets fixed, so the gate must let
        them through before it consults the subscription."""
        business = a_business(subscription_status="canceled")
        assert call_gate(business, "receptionist", admin=True) is True

    def test_returning_to_active_restores_the_original_tier_with_no_re_entry(self):
        """DECISION 3's payoff. Because `plan_tier` was never written by the
        payment event, restoring is a single status change — nothing has to
        remember what they had bought."""
        business = a_business(plan_tier="business", subscription_status="active")
        assert call_gate(business, "receptionist") is True

        business.subscription_status = "canceled"
        assert call_gate(business, "receptionist") is not True
        assert business.plan_tier == "business", "the purchase record was lost"

        business.subscription_status = "active"
        assert call_gate(business, "receptionist") is True
        assert auth.resolve_access_level(business) == auth.ACCESS_FULL

    def test_read_only_is_not_a_downgrade_to_starter(self):
        """The whole reason the tier is left alone. A cancelled Business
        customer is read-only ON BUSINESS — not a starter customer — so the
        export they are entitled to is scoped by what they bought."""
        business = a_business(plan_tier="business", subscription_status="canceled")
        assert business.plan_tier == "business"
        assert auth.resolve_access_level(business) == auth.ACCESS_READ_ONLY
        assert call_gate(business, "quoting") is True


# ─────────────────────────────────────────────────────────────────────────────
# A promise DECISION 3 makes that no endpoint currently keeps.
# ─────────────────────────────────────────────────────────────────────────────

MISSING_EXPORT_SURFACE = {
    "CSV export of quotes and invoices": (
        "DECISION 3 permits a read-only customer to 'export PDFs and CSV — "
        "quotes and invoices only', and RC1_SCOPE.md B3 asks who builds it. "
        "Searched on 24 Sep 2026: the only CSV endpoint on either resource is "
        "POST /v1/invoices/import/csv, an IMPORT. There is no CSV export of "
        "quotes or invoices anywhere, so the resolver permits a route that "
        "does not exist. The permission is right and the endpoint is missing; "
        "this is a gap in the product, not in this file."
    ),
    "PDF export of invoices": (
        "Only quotes have one (POST /v1/quotes/{id}/generate-pdf). DECISION 3 "
        "names invoices explicitly, and invoices are the records with the "
        "six-year HMRC retention obligation behind them — so this is the more "
        "consequential of the two gaps."
    ),
}


def test_the_missing_export_surface_is_recorded_with_its_reason():
    for area, reason in MISSING_EXPORT_SURFACE.items():
        assert len(reason) > 120, f"MISSING_EXPORT_SURFACE['{area}'] must say why"
