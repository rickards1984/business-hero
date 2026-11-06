"""LOG-2: Xero refused the chart of accounts on every sync (Mike's logs, 4-5 Nov).

GET /Accounts returned 401 straight after a refresh whose token TrialBalance
accepted, logged as "token is expired or invalid". The token was fine: the
connection lacks the permission /Accounts needs (accounting.settings.read).
Xero access tokens are JWTs listing the granted scopes, so the refusal can say
exactly what is missing, and a sync need not ask Xero for what it will refuse.
"""
import asyncio
import base64
import json

import httpx
import pytest

from providers import xero as x


def token(scopes):
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return ".".join([part({"alg": "RS256"}), part({"scope": scopes, "exp": 0}), "sig"])


FULL = ["openid", "accounting.transactions.read", "accounting.reports.read", "accounting.settings.read",
        "offline_access"]
NO_SETTINGS = [s for s in FULL if s != "accounting.settings.read"]


def test_granted_scopes_are_read_from_the_token():
    assert x.XeroProvider(token(FULL), "t").granted_scopes() == set(FULL)
    assert x.XeroProvider(token("openid accounting.reports.read"), "t").granted_scopes() == {"openid", "accounting.reports.read"}


@pytest.mark.parametrize("raw", ["not-a-jwt", "a.b.c", ""])
def test_an_unreadable_token_means_unknown_never_a_guess(raw):
    assert x.XeroProvider(raw, "t").granted_scopes() is None


def _refusing(monkeypatch, status=401):
    def handler(request):
        return httpx.Response(status, json={"Title": "Unauthorized", "Detail": "AuthorizationUnsuccessful"})
    real = httpx.AsyncClient
    monkeypatch.setattr(x.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_a_refusal_without_the_permission_says_so(monkeypatch):
    _refusing(monkeypatch)
    with pytest.raises(x.XeroPermissionError) as err:
        asyncio.run(x.XeroProvider(token(NO_SETTINGS), "t").get_accounts())
    assert "accounting.settings.read" in str(err.value) and "reconnect" in str(err.value).lower()
    assert isinstance(err.value, x.XeroAuthError), "existing handlers still catch it"


def test_a_refusal_with_the_permission_is_still_an_auth_error(monkeypatch):
    _refusing(monkeypatch)
    with pytest.raises(x.XeroAuthError) as err:
        asyncio.run(x.XeroProvider(token(FULL), "t").get_accounts())
    assert not isinstance(err.value, x.XeroPermissionError)


def test_a_sync_does_not_ask_xero_for_what_it_will_refuse():
    from services import xero_sync
    calls = []

    class Provider(x.XeroProvider):
        async def get_trial_balance(self):
            calls.append("tb")
            return {"Reports": []}

        async def get_accounts(self):
            calls.append("accounts")
            return []
    chart = asyncio.run(xero_sync.fetch_chart(Provider(token(NO_SETTINGS), "t")))
    assert calls == ["tb"], "no request Xero is known to refuse"
    assert chart["ok"] is False and chart.get("missing_permission") == "accounting.settings.read"
    calls.clear()
    asyncio.run(xero_sync.fetch_chart(Provider(token(FULL), "t")))
    assert calls == ["tb", "accounts"]


def test_an_unreadable_token_still_asks_for_the_chart():
    """Unknown permissions are never treated as missing: the chart is still
    requested, as before LOG-2."""
    from services import xero_sync
    calls = []

    class Provider(x.XeroProvider):
        async def get_trial_balance(self):
            calls.append("tb")
            return {"Reports": []}

        async def get_accounts(self):
            calls.append("accounts")
            return []
    chart = asyncio.run(xero_sync.fetch_chart(Provider("opaque-token", "t")))
    assert calls == ["tb", "accounts"] and "missing_permission" not in chart


def test_the_broader_settings_scope_also_grants_the_chart():
    """Codex LOG-2 review 1: accounting.settings (read and write) covers the read."""
    broad = NO_SETTINGS + ["accounting.settings"]
    assert x.XeroProvider(token(broad), "t").lacks(x.ACCOUNTS_SCOPE) is False
    assert x.XeroProvider(token(NO_SETTINGS + ["accounting.settings.write"]), "t").lacks(x.ACCOUNTS_SCOPE) is True
