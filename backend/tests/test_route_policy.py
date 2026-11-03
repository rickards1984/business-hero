"""TRADE-0 §1: every route the assembled app serves has a category, and goes
through the guard that category demands. A new route without a category, or
a tenant route that skips the owner guard, fails here."""
import inspect

import pytest

import route_policy

BUSINESS_GUARDS = {"dependencies.get_current_user_business", "dependencies.get_current_user_and_business",
                   "auth.get_user_business_context"}
PLATFORM_GUARD = "auth.get_platform_admin_context"


def _flat(routes):
    """Every route, including FastAPI's lazily included routers (0.141+)."""
    from starlette.routing import Mount
    for r in routes:
        kind = type(r).__name__
        if kind == "_IncludedRouter":
            yield from _flat(r.effective_candidates())
        elif isinstance(r, Mount):
            yield from _flat(r.routes or [])
        else:
            yield getattr(r, "original_route", None) or r


def _deps(route):
    out = set()

    def walk(dep):
        for sub in dep.dependencies:
            out.add(f"{getattr(sub.call, '__module__', '?')}.{getattr(sub.call, '__name__', '?')}")
            walk(sub)
    if getattr(route, "dependant", None):
        walk(route.dependant)
    return out


@pytest.fixture(scope="module")
def served():
    import main
    out = {}
    for r in _flat(main.app.routes):
        methods = getattr(r, "methods", None) or {"WS"}
        for m in methods:
            if m != "HEAD":
                out[(m, r.path)] = r
    return out


def test_every_served_route_has_exactly_one_known_category(served):
    assert set(served) == set(route_policy.POLICY), (
        f"unclassified: {sorted(set(served) - set(route_policy.POLICY))}; "
        f"stale: {sorted(set(route_policy.POLICY) - set(served))}")
    assert set(route_policy.POLICY.values()) <= route_policy.CATEGORIES


def test_tenant_owner_routes_go_through_the_owner_guard(served):
    missing = []
    for key, cat in route_policy.POLICY.items():
        if cat != "tenant_owner":
            continue
        route = served[key]
        if key[1] in route_policy.SELF_AUTHENTICATING_OWNER:
            src = inspect.getsource(route.endpoint)
            ok = any(n in src for n in ("get_business_for_user", "_assert_ai_access", "_resolve_business"))
        else:
            ok = bool(_deps(route) & BUSINESS_GUARDS)
        if not ok:
            missing.append(key)
    assert missing == []


def test_platform_admin_routes_go_through_the_platform_guard(served):
    assert [k for k, c in route_policy.POLICY.items()
            if c == "platform_admin" and PLATFORM_GUARD not in _deps(served[k])] == []


def test_every_exception_has_a_recorded_reason():
    exceptions = {p for (_, p), c in route_policy.POLICY.items() if c not in ("tenant_owner", "platform_admin")}
    assert exceptions <= set(route_policy.REASONS)


def test_no_exception_route_uses_a_tenant_guard(served):
    """A provider or public route that quietly resolves a business from a user
    JWT is mis-classified."""
    assert [k for k, c in route_policy.POLICY.items()
            if c in ("provider", "public", "oauth_continuation") and _deps(served[k]) & BUSINESS_GUARDS] == []
