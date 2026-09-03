"""
Do ERROR responses carry the same CORS headers as successful ones?

WHY THIS FILE EXISTS: `PUT /v1/admin/businesses/{id}/overview` was returning
500 (it wrote a `businesses.updated_at` that does not exist). In the browser
that arrived as `TypeError: Failed to fetch` — no status, no body. Chrome had
blocked the response because it carried no `Access-Control-Allow-Origin`, so
the frontend's `catch` saw a network failure and reported one. The actual
error was unreachable from the client for as long as it existed.

THE MECHANISM, from starlette.applications.build_middleware_stack:

    [ServerErrorMiddleware]  <- handles Exception/500. OUTERMOST, index 0.
      [user middleware]      <- CORSMiddleware lives here
        [ExceptionMiddleware] <- handles HTTPException & registered classes

Handlers registered for `Exception` (or 500) are pulled out and given to
ServerErrorMiddleware, which sits ABOVE CORSMiddleware — so its response never
passes back through CORS. Every other error (HTTPException, so all 400/404/422,
plus RateLimitExceeded) is handled BELOW it and is wrapped normally.

That asymmetry is the bug: exactly one class of response — the unhandled 500,
the one that most needs reading — is the one the browser cannot read.

THE FIX: `main.CORSSafeErrorMiddleware`, a user middleware added BEFORE
CORSMiddleware so that CORS wraps it. It converts the exception to a 500
inside the CORS layer. `test_cors_middleware_is_outside_the_error_middleware`
is what stops the two `add_middleware` calls being reordered later.

These tests drive the REAL assembled app. A replica would test the replica.
"""
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from main import CORSSafeErrorMiddleware, app

ALLOWED_ORIGIN = "https://business-hero.vercel.app"
FOREIGN_ORIGIN = "https://not-our-frontend.example.com"

BOOM = "/v1/_test_error_cors/boom"
BAD_REQUEST = "/v1/_test_error_cors/http400"


def setUpModule():
    """Mount throwaway routes on the real app, and take them off again.

    The app object is shared with the other suites in this process (notably
    test_route_resolution, which walks the whole route table), so these must
    not outlive the module.
    """
    @app.get(BOOM)
    async def _boom():
        raise RuntimeError("unhandled — this is the point of the test")

    @app.get(BAD_REQUEST)
    async def _http400():
        raise HTTPException(status_code=400, detail="a message worth reading")


def tearDownModule():
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", None) not in (BOOM, BAD_REQUEST)
    ]


class ErrorResponsesCarryCORS(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def _get(self, path, origin=ALLOWED_ORIGIN):
        return self.client.get(path, headers={"Origin": origin})

    def test_unhandled_500_carries_the_allow_origin_header(self):
        """The incident. Without this header Chrome discards the response."""
        r = self._get(BOOM)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN,
            "a 500 reached the browser with no Access-Control-Allow-Origin. "
            "Chrome blocks it and fetch() raises 'Failed to fetch', so the "
            "status and body are invisible to the frontend. Check that "
            "CORSSafeErrorMiddleware is still added BEFORE CORSMiddleware.",
        )

    def test_unhandled_500_still_carries_credentials_header(self):
        """allow_credentials=True, so the frontend sends cookies/authorization
        and the response must be readable on the same terms as a 200."""
        r = self._get(BOOM)
        self.assertEqual(
            r.headers.get("access-control-allow-credentials"), "true")

    def test_500_body_is_still_generic(self):
        """Readable must not mean leaky — the fix changes reachability only."""
        r = self._get(BOOM)
        self.assertEqual(r.json(), {"detail": "Internal Server Error"})
        self.assertNotIn("Traceback", r.text)
        self.assertNotIn("unhandled — this is the point", r.text)

    def test_http_400_carries_the_header_too(self):
        """400s go through ExceptionMiddleware, BELOW CORS, so they were never
        broken. Asserted so the fix cannot regress the path that worked."""
        r = self._get(BAD_REQUEST)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN)
        self.assertEqual(r.json()["detail"], "a message worth reading")

    def test_404_carries_the_header(self):
        r = self._get("/v1/_test_error_cors/definitely-not-a-route")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN)

    def test_success_is_unchanged(self):
        r = self._get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN)

    def test_a_foreign_origin_is_still_refused_on_errors(self):
        """The fix must not become 'always send the header'. An origin that
        would be refused on a 200 must be refused on a 500."""
        ok = self._get("/health", origin=FOREIGN_ORIGIN)
        boom = self._get(BOOM, origin=FOREIGN_ORIGIN)
        self.assertIsNone(ok.headers.get("access-control-allow-origin"))
        self.assertIsNone(
            boom.headers.get("access-control-allow-origin"),
            "an unlisted origin was granted CORS on an error response — the "
            "error path is more permissive than the success path",
        )

    def test_preflight_still_works(self):
        r = self.client.options(
            BOOM,
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.headers.get("access-control-allow-origin"), ALLOWED_ORIGIN)


class MiddlewareOrdering(unittest.TestCase):
    """The behavioural tests above pass only because of this ordering. Assert
    it directly so a reordering fails with a message that says why."""

    def _classes(self):
        return [m.cls for m in app.user_middleware]

    def test_both_middlewares_are_installed(self):
        classes = self._classes()
        self.assertIn(CORSMiddleware, classes)
        self.assertIn(CORSSafeErrorMiddleware, classes)

    def test_cors_middleware_is_outside_the_error_middleware(self):
        """`add_middleware` inserts at index 0, so index 0 is OUTERMOST and a
        LOWER index means further out. CORS must be outside the error
        middleware, or it cannot add headers to the error response."""
        classes = self._classes()
        cors = classes.index(CORSMiddleware)
        safe = classes.index(CORSSafeErrorMiddleware)
        self.assertLess(
            cors, safe,
            f"CORSMiddleware (index {cors}) must sit OUTSIDE "
            f"CORSSafeErrorMiddleware (index {safe}). user_middleware is "
            f"ordered outermost-first, and add_middleware inserts at 0 — so "
            f"CORSMiddleware must be the LAST of the two added in main.py. "
            f"Swapped, every 500 loses its CORS headers again.",
        )

    def test_exception_handler_registry_matches_the_documented_split(self):
        """The premise of the whole file: `Exception` is routed away from the
        middleware stack, everything else is not. If a future Starlette
        changes that, this tells us before the comments mislead anyone."""
        import starlette.applications as starlette_app
        import inspect
        src = inspect.getsource(starlette_app.Starlette.build_middleware_stack)
        self.assertIn("if key in (500, Exception):", src)
        self.assertIn(
            "middleware = [Middleware(ServerErrorMiddleware", src,
            "ServerErrorMiddleware is no longer the outermost middleware; the "
            "reasoning recorded in this file needs rechecking.",
        )
        self.assertIn(Exception, app.exception_handlers)


class MiddlewareUnit(unittest.TestCase):
    """The two branches TestClient cannot easily reach."""

    def test_non_http_scopes_pass_straight_through(self):
        import asyncio
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        mw = CORSSafeErrorMiddleware(inner)
        asyncio.run(mw({"type": "websocket"}, None, None))
        asyncio.run(mw({"type": "lifespan"}, None, None))
        self.assertEqual(seen, ["websocket", "lifespan"])

    def test_exception_after_response_started_is_re_raised(self):
        """Once headers are on the wire a second response would corrupt the
        stream, so the exception must propagate rather than be swallowed."""
        import asyncio

        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": []})
            raise RuntimeError("failed mid-stream")

        sent = []

        async def send(message):
            sent.append(message)

        mw = CORSSafeErrorMiddleware(inner)
        with self.assertRaises(RuntimeError):
            asyncio.run(mw({"type": "http"}, None, send))
        self.assertEqual([m["type"] for m in sent], ["http.response.start"])


if __name__ == "__main__":
    unittest.main()
