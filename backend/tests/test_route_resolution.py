"""
Route resolution against the ASSEMBLED app.

WHY THIS FILE EXISTS: `GET /v1/admin/businesses/summary` returned 500 in prod.
`admin_business_api`'s `/{business_id}` route was registered before the literal
`/summary` endpoint, and FastAPI matches in registration order — so "summary"
was captured as a business id and the query failed.

Every unit test passed throughout. They call handler functions directly, or
inspect one router in isolation, and never mount the full route table. A
shadowing bug lives in the *relationship* between routes, so it is invisible
to any test that looks at one route at a time.

These tests import the real `main.app` and ask it to resolve paths the way a
request does.
"""
import unittest

from fastapi.routing import APIRoute
from starlette.routing import Match

from main import app


def _scope(method: str, path: str) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }


def _inner_router(route):
    """This FastAPI version wraps an included router in `_IncludedRouter`
    rather than splicing its routes into `app.routes`.

    So `app.routes` alone does NOT show everything the app serves, and any
    inspection that assumes a flat list silently misses whole routers. Both
    helpers below descend instead.
    """
    return getattr(route, "original_router", None)


def _walk(routes):
    """Flatten the route table, descending into included routers."""
    for route in routes:
        inner = _inner_router(route)
        if inner is not None:
            yield from _walk(inner.routes)
        elif isinstance(route, APIRoute):
            yield route


def resolve(method: str, path: str):
    """Return the concrete route that would serve this request.

    Matches in registration order exactly as the router does, then descends
    through any included router to the handler that actually runs.
    """
    scope = _scope(method, path)
    candidates = list(app.routes)
    while candidates:
        for route in candidates:
            match, _ = route.matches(scope)
            if match != Match.FULL:
                continue
            inner = _inner_router(route)
            if inner is None:
                return route
            candidates = list(inner.routes)
            break
        else:
            return None
    return None


def api_routes():
    return list(_walk(app.routes))


class TestSummaryIsNotShadowed(unittest.TestCase):
    """The specific regression."""

    def test_summary_resolves_to_the_summary_handler(self):
        route = resolve("GET", "/v1/admin/businesses/summary")
        self.assertIsNotNone(route, "/v1/admin/businesses/summary resolves to nothing")
        self.assertEqual(
            route.endpoint.__name__, "list_businesses_summary",
            f"'summary' was captured by {route.path} "
            f"({route.endpoint.__name__}) — the parameterised route is "
            f"registered first and is swallowing the literal one",
        )

    def test_a_real_id_still_reaches_the_detail_handler(self):
        # The fix must not solve shadowing by breaking the parameterised route.
        route = resolve("GET", "/v1/admin/businesses/3f2504e0-4f89-11d3-9a0c-0305e82c3301")
        self.assertIsNotNone(route)
        self.assertEqual(route.endpoint.__name__, "get_business_admin")

    def test_the_other_admin_business_routes_still_resolve(self):
        cases = [
            ("GET", "/v1/admin/businesses", "list_businesses"),
            ("POST", "/v1/admin/businesses", "create_business"),
            ("PUT", "/v1/admin/businesses/3f2504e0-4f89-11d3-9a0c-0305e82c3301/overview",
             "update_business_overview"),
            ("PUT", "/v1/admin/businesses/3f2504e0-4f89-11d3-9a0c-0305e82c3301/active",
             "set_business_active"),
            ("GET", "/v1/admin/businesses/3f2504e0-4f89-11d3-9a0c-0305e82c3301/health",
             "get_business_health"),
        ]
        wrong = []
        for method, path, expected in cases:
            route = resolve(method, path)
            actual = route.endpoint.__name__ if route else None
            if actual != expected:
                wrong.append(f"{method} {path} -> {actual}, expected {expected}")
        self.assertEqual(wrong, [], f"routes resolved to the wrong handler: {wrong}")


class TestNoLiteralPathIsShadowed(unittest.TestCase):
    """
    The general form of the bug, across the whole app.

    Any route whose path has no parameters must resolve to itself. If an
    earlier-registered parameterised route matches it first, that literal
    endpoint is unreachable — silently, and only in production.
    """

    def test_every_literal_route_resolves_to_itself(self):
        shadowed = []
        literals = [r for r in api_routes() if "{" not in r.path]
        self.assertTrue(literals, "no literal routes found — the filter is wrong")

        for route in literals:
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                winner = resolve(method, route.path)
                if winner is not route:
                    name = winner.endpoint.__name__ if winner else "nothing"
                    shadowed.append(
                        f"{method} {route.path} is shadowed by "
                        f"{getattr(winner, 'path', '?')} ({name})"
                    )
        self.assertEqual(shadowed, [], "literal routes are unreachable:\n  "
                                       + "\n  ".join(shadowed))

    def test_no_duplicate_method_and_path(self):
        # Two handlers on one path is the same class of problem: the second is
        # dead and nothing says so.
        seen, duplicates = {}, []
        for route in api_routes():
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                key = (method, route.path)
                if key in seen:
                    duplicates.append(
                        f"{method} {route.path}: {seen[key]} and {route.endpoint.__name__}")
                else:
                    seen[key] = route.endpoint.__name__
        self.assertEqual(duplicates, [], f"duplicate routes: {duplicates}")


class TestPathParamsAreTyped(unittest.TestCase):
    """
    Defence in depth: `business_id` typed as UUID means a non-UUID segment is a
    422 from FastAPI's own validation rather than reaching a query and failing
    as a 500. This is NOT the fix for shadowing — registration order is.
    """

    def test_business_id_is_a_uuid_on_the_new_admin_routes(self):
        import admin_business_api
        untyped = []
        for route in api_routes():
            if route.endpoint.__module__ != admin_business_api.__name__:
                continue
            for param in route.dependant.path_params:
                if param.name != "business_id":
                    continue
                # Pydantic v2: the annotation lives on field_info, not `type_`.
                annotation = getattr(param.field_info, "annotation", None)
                name = getattr(annotation, "__name__", repr(annotation))
                if name != "UUID":
                    untyped.append(f"{route.path}: business_id is {name}")
        self.assertEqual(untyped, [], f"path params not typed: {untyped}")

    def test_the_new_routes_declare_a_path_param_at_all(self):
        # Guards the test above against passing because nothing was inspected.
        import admin_business_api
        parameterised = [
            r for r in api_routes()
            if r.endpoint.__module__ == admin_business_api.__name__ and "{" in r.path
        ]
        self.assertTrue(parameterised,
                        "no parameterised routes found on admin_business_api")


if __name__ == "__main__":
    unittest.main()
