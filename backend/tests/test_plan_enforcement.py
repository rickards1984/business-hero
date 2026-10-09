"""BH-011 Stage 1: real router requests, synthetic identity, no database/provider.

BoundaryReached stops before domain I/O (including reads). An allowed test
proves gate passage, not endpoint success. Expected failures catch only a
named contract violation; validation errors and fixture bugs fail normally.
"""
import ast
import asyncio
import importlib
import os
from contextlib import contextmanager
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

# Must precede application imports: db.py connects during import for these URLs.
for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL", "SQLITE_DATABASE_URL"):
    _configured = os.getenv(_key, "")
    if _configured and not _configured.startswith("sqlite"):
        raise RuntimeError(f"REFUSING TO RUN: non-SQLite {_key}; clear it first")

import auth
import db
import dependencies
import httpx
import openai
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from sqlalchemy.engine import Engine

MODULE_FEATURES = {
    "quoting_api": "quoting", "whatsapp_briefing_api": "whatsapp",
    "accounting": "accounting", "booking_api": "calendar_booking",
    "receptionist_api": "receptionist", "executive_meeting_api": "board_meetings",
}
MODULES = {name: importlib.import_module(name) for name in MODULE_FEATURES}
ROUTES = [(name, route, method) for name, module in MODULES.items()
          for router_name in ("router", "admin_router")
          for route in getattr(module, router_name, SimpleNamespace(routes=[])).routes
          if isinstance(route, APIRoute) for method in sorted(route.methods)]

# Explicit endpoint inventory: a newly registered endpoint cannot inherit an
# xfail silently. It must first receive a reviewed policy here and in the design.
EXPECTED = {
    "quoting_api": "list_quotes get_quote create_quote update_quote delete_quote send_quote accept_quote decline_quote convert_to_invoice generate_pdf send_quote_email send_quote_whatsapp get_quote_settings update_quote_settings generate_ai_quote",
    "whatsapp_briefing_api": "get_whatsapp_config upsert_whatsapp_config trigger_daily_pulse trigger_weekly_briefing trigger_task_reminder get_whatsapp_messages whatsapp_webhook admin_whatsapp_overview admin_update_whatsapp_config",
    "accounting": "list_categories create_category list_transactions create_transaction update_transaction delete_transaction bulk_delete_transactions bulk_update_category analyze_spreadsheet import_spreadsheet get_accounting_summary get_ai_insights list_imports",
    "booking_api": "list_google_calendars get_booking_settings update_booking_settings",
    "receptionist_api": "get_receptionist_config upsert_receptionist_config toggle_receptionist list_knowledge_base_categories list_knowledge_base create_knowledge_base_item update_knowledge_base_item delete_knowledge_base_item list_voices preview_voice list_voice_presets preview_voice_preset list_receptionist_calls receptionist_stats admin_receptionist_overview admin_toggle_receptionist_flag admin_get_receptionist_config admin_update_receptionist_config admin_assign_phone_number admin_list_knowledge_base admin_create_knowledge_base_item",
    "executive_meeting_api": "get_meeting_settings update_meeting_settings check_meeting_access list_meetings list_action_items update_action_item list_goals update_goal admin_meeting_overview trigger_prep_now start_meeting_now get_meeting_prep_data start_meeting_endpoint send_owner_message end_meeting_endpoint list_meeting_messages extract_actions_endpoint",
}
PUBLIC = {"list_knowledge_base_categories", "list_voices", "list_voice_presets"}
SPECIAL = PUBLIC | {"check_meeting_access", "whatsapp_webhook"}
RECEPTIONIST_GATED = set(EXPECTED["receptionist_api"].split()) - PUBLIC - {
    "preview_voice", "preview_voice_preset"} - {
    n for n in EXPECTED["receptionist_api"].split() if n.startswith("admin_")}
READ_ALLOWED = {"list_quotes", "get_quote", "generate_pdf", "get_quote_settings",
                "list_categories", "list_transactions", "get_accounting_summary", "list_imports"}
BID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class GateContractMissing(AssertionError):
    """Only this known unmet entitlement contract may xfail."""


class LegacyGatePresent(AssertionError):
    """Only the named legacy gate call sites may xfail."""


class BoundaryReached(BaseException):
    """Cannot be swallowed by application except Exception handlers."""


def pending(reason):
    return pytest.mark.xfail(strict=True, raises=GateContractMissing, reason=reason)


def business(plan="pro", status="active", flags=None):
    return SimpleNamespace(id=BID, plan_tier=plan, subscription_status=status,
                           is_active=True, trial_ends_at=None, feature_flags=flags or {})


def features(name, endpoint):
    primary = MODULE_FEATURES[name]
    # Cross-department actions must not bypass a deliberately disabled channel.
    extra = {"send_quote_whatsapp": "whatsapp", "send_quote_email": "email",
             "convert_to_invoice": "invoicing"}.get(endpoint)
    return (primary, extra) if extra else (primary,)


@pytest.fixture
def harness(monkeypatch):
    state = SimpleNamespace(business=business(), boundary=[], admin=False)

    def stop(*args, **kwargs):
        state.boundary.append("domain I/O")
        raise BoundaryReached()

    # A missed stub cannot open a real connection or invoke an OpenAI client.
    def forbidden(*args, **kwargs):
        raise AssertionError("BH-011 attempted real database/network/provider access")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(openai, "OpenAI", stop)
    monkeypatch.setattr(openai, "AsyncOpenAI", stop)
    monkeypatch.setattr(MODULES["accounting"], "_detect_column_mapping", stop)
    # Booking calls into a separate engine helper before it reaches a provider.
    import assistant_tools
    monkeypatch.setattr(assistant_tools, "_get_google_calendar_token", stop)
    from rate_limiting import limiter
    monkeypatch.setattr(limiter, "enabled", False)

    class Session:
        def exec(self, statement, *args, **kwargs):
            if "FROM businesses" in str(statement) and "WHERE" in str(statement):
                return SimpleNamespace(first=lambda: state.business)
            return stop()

        def execute(self, statement, *args, **kwargs):
            if "SELECT plan_tier FROM businesses" in str(statement):
                return SimpleNamespace(fetchone=lambda: (state.business.plan_tier,))
            return stop()

        connection = add = commit = flush = refresh = delete = stop

    session = Session()
    state.session = session
    state.stop = stop
    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *a: state.admin)
    monkeypatch.setattr(MODULES["receptionist_api"], "is_platform_admin_user", lambda *a: state.admin)

    async def context(request: Request):
        if not state.admin:
            auth.enforce_access(request, state.business)
        return {"user_id": "synthetic-owner", "business_id": BID,
                "is_platform_admin": state.admin}

    async def current_business(request: Request):
        await context(request)
        return state.business

    async def user_business(request: Request):
        return (SimpleNamespace(id="synthetic-owner"), await current_business(request))

    async def admin_context():
        if not state.admin:
            raise HTTPException(403, "Platform admin required")
        return {"user_id": "synthetic-admin"}

    async def request_route(route, method, **kwargs):
        state.boundary.clear()
        app = FastAPI()
        single = APIRouter()
        single.routes.append(route)
        app.include_router(single)  # Preserve endpoint/dependencies; bind overrides to app.
        app.dependency_overrides = {
            auth.get_user_business_context: context,
            dependencies.get_current_user_business: current_business,
            dependencies.get_current_user_and_business: user_business,
            auth.get_platform_admin_context: admin_context,
            db.get_session: lambda: session,
        }
        path = route.path
        for parameter in route.param_convertors:
            value = "shimmer" if parameter == "voice_id" else BID
            path = path.replace("{" + parameter + "}", value)
        payload = {
            "name": "Synthetic", "type": "expense", "title": "Synthetic",
            "content": "Synthetic", "description": "Synthetic work",
            "transaction_date": "2026-10-09", "amount": 10,
            "transaction_ids": [BID], "phone_number": "+447700900000",
            "twilio_phone_number": "+447700900000",
            "voice_preset_id": MODULES["receptionist_api"].VOICE_PRESETS[0]["id"],
        }
        options = {"json": payload} if method in {"POST", "PUT", "PATCH"} else {}
        if "/upload/" in path:
            options = {"files": {"file": ("test.csv", b"date,description,amount\n2026-10-09,test,10\n", "text/csv")},
                       "data": {"mapping": '{"date_column":"date","description_column":"description","amount_column":"amount"}'}}
        options.update(kwargs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            try:
                response = await client.request(method, path, **options)
            except BoundaryReached:
                return None
        # Malformed fixtures must NEVER be hidden behind the xfail contract.
        assert response.status_code not in {400, 401, 404, 422, 500}, response.text
        return response

    state.request = lambda route, method, **kw: asyncio.run(request_route(route, method, **kw))
    return state


def test_inventory_covers_every_registered_route():
    for name in MODULES:
        actual = [r.endpoint.__name__ for n, r, _ in ROUTES if n == name]
        assert sorted(actual) == sorted(EXPECTED[name].split())
    assert len(ROUTES) == 78


def normal_routes():
    return [(n, r, m) for n, r, m in ROUTES
            if r.endpoint.__name__ not in SPECIAL and not r.endpoint.__name__.startswith("admin_")]


DENIED = [pytest.param(n, r, m, f, id=f"{m} {r.path} [{f}]",
                      marks=[] if r.endpoint.__name__ in RECEPTIONIST_GATED else pending("BH-011: missing canonical feature refusal"))
          for n, r, m in normal_routes() for f in features(n, r.endpoint.__name__)]


@pytest.mark.parametrize("name,route,method,feature", DENIED)
def test_disabled_feature_is_403_before_any_domain_io(harness, name, route, method, feature):
    harness.business = business(flags={feature: False})
    response = harness.request(route, method)
    if response is None or response.status_code != 403:
        raise GateContractMissing(f"{method} {route.path} must refuse disabled {feature}")
    assert harness.boundary == []


@pytest.mark.parametrize("name,route,method", normal_routes(), ids=lambda x: x.path if isinstance(x, APIRoute) else str(x))
@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_entitled_business_passes_gate(harness, name, route, method, status):
    harness.business = business(status=status)
    response = harness.request(route, method)
    assert response is None or 200 <= response.status_code < 300
    assert harness.boundary or response is not None


READ_CASES = []
for _n, _r, _m in normal_routes():
    _endpoint = _r.endpoint.__name__
    _allow = _endpoint in READ_ALLOWED
    _missing = not _allow and _m == "GET" and _endpoint != "preview_voice"
    READ_CASES.append(pytest.param(_n, _r, _m, _allow, id=f"{_m} {_r.path}",
                                  marks=pending("BH-011: read-only GET not protected") if _missing else []))


@pytest.mark.parametrize("name,route,method,allowed", READ_CASES)
@pytest.mark.parametrize("status", ["unpaid", "canceled"])
def test_read_only_per_route(harness, name, route, method, allowed, status):
    harness.business = business(status=status)
    response = harness.request(route, method)
    if allowed:
        assert response is None or 200 <= response.status_code < 300
    elif response is None or response.status_code != 403:
        raise GateContractMissing(f"Read-only must refuse {method} {route.path}")
    else:
        assert harness.boundary == []


@pytest.mark.parametrize("name,route,method", [x for x in ROUTES if x[1].endpoint.__name__ in PUBLIC])
def test_public_static_catalogue_is_available_without_plan(harness, name, route, method):
    harness.business = business(plan="starter", status="unpaid")
    response = harness.request(route, method)
    assert response.status_code == 200
    assert response.json()
    assert harness.boundary == []


@pytest.mark.parametrize("name,route,method", [x for x in ROUTES if x[1].endpoint.__name__.startswith("admin_")])
@pytest.mark.parametrize("admin", [False, True])
def test_admin_exception_requires_platform_admin_not_paid_plan(harness, name, route, method, admin):
    harness.admin = admin
    harness.business = business(plan="starter", status="unpaid")
    response = harness.request(route, method)
    if admin:
        assert response is None or response.status_code == 200
    else:
        assert response.status_code == 403
        assert harness.boundary == []


@pytest.mark.xfail(strict=True, raises=LegacyGatePresent, reason="BH-011: fold legacy gates into auth")
def test_no_legacy_gate_call_sites_remain():
    offenders = []
    for path in Path(__file__).parents[1].rglob("*.py"):
        if "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name in {"require_tier_feature", "_require_receptionist_flag"}:
                    offenders.append(f"{path.name}:{node.lineno}")
    if offenders:
        raise LegacyGatePresent(", ".join(offenders))


@pytest.mark.parametrize("feature", list(MODULE_FEATURES.values()))
@pytest.mark.parametrize("plan", list(auth.PLAN_FEATURE_DEFAULTS))
def test_canonical_plan_defaults_and_explicit_exceptions(feature, plan):
    assert feature in auth.CANONICAL_FEATURES
    b = business(plan=plan)
    if auth.PLAN_FEATURE_DEFAULTS[plan][feature]:
        auth.assert_feature_access(b, feature)
    else:
        with pytest.raises(HTTPException) as denied:
            auth.assert_feature_access(b, feature)
        assert denied.value.status_code == 403
    b.feature_flags = {feature: True}
    auth.assert_feature_access(b, feature)
    b.feature_flags = {feature: False}
    with pytest.raises(HTTPException) as denied:
        auth.assert_feature_access(b, feature)
    assert denied.value.status_code == 403


def test_missing_business_fails_closed():
    with pytest.raises(HTTPException) as denied:
        auth.assert_feature_access(None, "quoting")
    assert denied.value.status_code == 404


@pending("BH-011: unknown metadata key must never grant a feature")
def test_unknown_feature_fails_closed_even_if_metadata_is_truthy():
    try:
        auth.assert_feature_access(business(flags={"not_a_feature": True}), "not_a_feature")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise GateContractMissing("Unknown feature was granted")


STARTER_CASES = []
for _n, _r, _m in normal_routes():
    _granted = all(auth.PLAN_FEATURE_DEFAULTS["starter"][f] for f in features(_n, _r.endpoint.__name__))
    _existing_denial = _r.endpoint.__name__ in RECEPTIONIST_GATED or _n == "executive_meeting_api"
    STARTER_CASES.append(pytest.param(_n, _r, _m, _granted, id=f"{_m} {_r.path}",
                                     marks=pending("BH-011: Starter lacks this feature") if not _granted and not _existing_denial else []))


@pytest.mark.parametrize("name,route,method,granted", STARTER_CASES)
def test_starter_route_access_uses_actual_plan_matrix(harness, name, route, method, granted):
    harness.business = business(plan="starter")
    response = harness.request(route, method)
    if granted:
        assert response is None or 200 <= response.status_code < 300
    elif response is None or response.status_code != 403:
        raise GateContractMissing("Starter reached a feature absent from its plan")
    else:
        assert harness.boundary == []


@pytest.mark.parametrize("name,route,method", [
    pytest.param(n, r, m, id=f"{m} {r.path}", marks=pending("BH-011: legacy tier gate ignores explicit grant") if n == "executive_meeting_api" else [])
    for n, r, m in normal_routes()])
def test_explicit_grant_allows_starter(harness, name, route, method):
    harness.business = business(plan="starter", flags={f: True for f in features(name, route.endpoint.__name__)})
    response = harness.request(route, method)
    if response is not None and response.status_code == 403:
        raise GateContractMissing("Explicit grant was ignored")
    assert response is None or 200 <= response.status_code < 300


@pytest.mark.parametrize("plan", ["pro", "business"])
@pytest.mark.parametrize("flags", [{}, {"receptionist": True}])
def test_founder_stopgap_and_stripped_flags_both_allow_toggle(harness, plan, flags):
    harness.business = business(plan=plan, flags=flags)
    _, route, method = next(x for x in ROUTES if x[1].endpoint.__name__ == "toggle_receptionist")
    assert harness.request(route, method) is None
    assert harness.boundary


@pytest.mark.parametrize("flags,expected", [({}, True), pytest.param({"board_meetings": False}, False, marks=pending("BH-011: access-check ignores flag"))])
def test_access_check_reports_canonical_access(harness, flags, expected):
    harness.business = business(flags=flags)
    _, route, method = next(x for x in ROUTES if x[1].endpoint.__name__ == "check_meeting_access")
    response = harness.request(route, method)
    assert response.status_code == 200
    if response.json()["has_access"] is not expected:
        raise GateContractMissing("Access-check disagrees with canonical entitlement")


@pytest.mark.parametrize("status", ["unpaid", "canceled"])
@pending("BH-011: access-check must reflect read-only subscription status")
def test_access_check_read_only_reports_false(harness, status):
    harness.business = business(status=status)
    _, route, method = next(x for x in ROUTES if x[1].endpoint.__name__ == "check_meeting_access")
    response = harness.request(route, method)
    assert response.status_code == 200
    if response.json()["has_access"] is not False:
        raise GateContractMissing("Read-only access-check advertises paid AI access")
    assert response.json()["has_advanced"] is False


@pytest.fixture
def webhook(harness, monkeypatch):
    import twilio_security
    from twilio.request_validator import RequestValidator
    monkeypatch.setattr(twilio_security, "TWILIO_AUTH_TOKEN", "synthetic-test-token")
    monkeypatch.setattr(twilio_security, "PUBLIC_BASE_URL", "")
    monkeypatch.setenv("TWILIO_SIGNATURE_VALIDATION", "on")
    module = MODULES["whatsapp_briefing_api"]

    class WebhookSession:
        def execute(self, statement, *args, **kwargs):
            if "FROM whatsapp_configs" in str(statement):
                return SimpleNamespace(fetchone=lambda: (BID, "+447700900000", "Synthetic"))
            return harness.stop()

        def exec(self, statement, *args, **kwargs):
            return harness.session.exec(statement, *args, **kwargs)

        get = lambda self, *args, **kwargs: harness.business

    @contextmanager
    def session_context():
        yield WebhookSession()

    monkeypatch.setattr(db, "get_session_context", session_context)
    monkeypatch.setattr(db, "get_session_transactional", session_context)
    import services.whatsapp_service as service
    monkeypatch.setattr(service, "log_whatsapp_message", harness.stop)
    monkeypatch.setattr(module, "send_whatsapp_message", harness.stop)
    monkeypatch.setattr(module, "_execute_whatsapp_action", harness.stop)
    _, route, method = next(x for x in ROUTES if x[1].endpoint.__name__ == "whatsapp_webhook")

    def send(valid=True, body="1"):
        form = {"From": "whatsapp:+447700900000", "Body": body, "MessageSid": "synthetic"}
        signature = RequestValidator("synthetic-test-token").compute_signature("http://test" + route.path, form)
        return harness.request(route, method, json=None, data=form,
                               headers={"X-Twilio-Signature": signature if valid else "forged"})
    return send


def test_forged_webhook_is_403_before_domain_io(harness, webhook):
    response = webhook(valid=False)
    assert response.status_code == 403
    assert harness.boundary == []


@pytest.mark.parametrize("body", ["1", "hello"])
def test_entitled_signed_webhook_passes_gate(harness, webhook, body):
    assert webhook(body=body) is None
    assert harness.boundary


@pytest.mark.parametrize("status,flags", [("active", {"whatsapp": False}), ("unpaid", {}), ("canceled", {})])
@pytest.mark.parametrize("body", ["1", "hello"])
@pending("BH-011: signature authenticates sender, not business entitlement")
def test_signed_webhook_denied_before_logging_action_or_reply(harness, webhook, status, flags, body):
    harness.business = business(status=status, flags=flags)
    response = webhook(body=body)
    if response is None or response.status_code != 403:
        raise GateContractMissing("Signed webhook must check resolved business before any write/action/reply")
    assert harness.boundary == []


@pytest.mark.xfail(strict=True, raises=LegacyGatePresent, reason="BH-011: noncanonical board meeting feature names")
def test_route_gate_names_are_canonical():
    offenders = []
    for name in MODULES:
        tree = ast.parse(Path(MODULES[name].__file__).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if called not in {"require_feature", "assert_feature_access", "require_tier_feature", "check_feature_access"}:
                continue
            index = 0 if called == "require_feature" else 1
            if len(node.args) > index and isinstance(node.args[index], ast.Constant):
                feature = node.args[index].value
                if feature not in auth.CANONICAL_FEATURES:
                    offenders.append(f"{name}:{node.lineno}: {feature}")
    if offenders:
        raise LegacyGatePresent(", ".join(offenders))
