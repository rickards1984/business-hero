"""AUTO-2 (Codex review 1): the mailbox searches that find replies to chases.

They must be complete or raise — a partial answer would let an automatic
chase go over an unseen reply. Providers are exercised against a mocked HTTP
layer; nothing leaves the machine. Microsoft's live behaviour is UNVERIFIED
(19 Oct 2026); these tests pin what the code asks for and how it checks.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SINCE = datetime(2026, 9, 1, tzinfo=timezone.utc)
ACCOUNT = SimpleNamespace(id="acct", email_address="owner@biz.example", capabilities={})


def client_with(monkeypatch, module, handler):
    real = httpx.Client
    monkeypatch.setattr(module.httpx, "Client",
                        lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(module, "get_valid_access_token", lambda account: "token")


def gmail_message(mid, sender="pay@harper.example"):
    return {"id": mid, "threadId": f"t-{mid}", "snippet": "Paid", "internalDate": "1790000000000",
            "labelIds": ["INBOX"], "payload": {"headers": [
                {"name": "From", "value": f"Harper <{sender}>"},
                {"name": "Subject", "value": "Re: INV-0001"}]}}


def test_gmail_searches_the_whole_mailbox_for_the_senders_and_pages_to_the_end(monkeypatch):
    from providers import google_gmail as g
    seen = []

    def handler(request):
        if request.url.path.endswith("/messages"):
            q = parse_qs(urlparse(str(request.url)).query)
            seen.append(q)
            if "pageToken" not in q:
                return httpx.Response(200, json={"messages": [{"id": "m1"}], "nextPageToken": "p2"})
            return httpx.Response(200, json={"messages": [{"id": "m2"}]})
        return httpx.Response(200, json=gmail_message(request.url.path.rsplit("/", 1)[1]))
    client_with(monkeypatch, g, handler)
    found = g.GoogleGmailProvider().search_from(account=ACCOUNT, senders=["Pay@Harper.example"],
                                                since=SINCE)
    assert [m.provider_message_id for m in found] == ["m1", "m2"]
    assert seen[0]["q"] == [f"(from:pay@harper.example) after:{int(SINCE.timestamp())}"]
    assert "labelIds" not in seen[0], "the search covers every label, not only INBOX"


def test_gmail_raises_rather_than_return_a_partial_answer(monkeypatch):
    from providers import google_gmail as g

    def unreadable(request):
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        return httpx.Response(404, json={})
    client_with(monkeypatch, g, unreadable)
    with pytest.raises(RuntimeError):
        g.GoogleGmailProvider().search_from(account=ACCOUNT, senders=["pay@harper.example"],
                                            since=SINCE)

    def endless(request):
        return httpx.Response(200, json={"messages": [], "nextPageToken": "more"})
    client_with(monkeypatch, g, endless)
    with pytest.raises(RuntimeError):
        g.GoogleGmailProvider().search_from(account=ACCOUNT, senders=["pay@harper.example"],
                                            since=SINCE)

    client_with(monkeypatch, g, lambda request: httpx.Response(429, json={}))
    with pytest.raises(RuntimeError):
        g.GoogleGmailProvider().search_from(account=ACCOUNT, senders=["pay@harper.example"],
                                            since=SINCE)


def graph_message(mid, sender, minutes_after=60):
    return {"id": mid, "conversationId": f"c-{mid}", "subject": "Re: INV-0001",
            "bodyPreview": "Paid", "from": {"emailAddress": {"address": sender, "name": "Harper"}},
            "receivedDateTime": (SINCE + timedelta(minutes=minutes_after)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_graph_filters_by_sender_and_date_follows_pages_and_rechecks(monkeypatch):
    from providers import microsoft_graph as mg
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if "page2" in str(request.url):
            return httpx.Response(200, json={"value": [graph_message("m2", "pay@harper.example")]})
        return httpx.Response(200, json={
            "value": [graph_message("m1", "pay@harper.example"),
                      graph_message("x", "someone@else.example"),
                      graph_message("old", "pay@harper.example", minutes_after=-60)],
            "@odata.nextLink": f"{mg.GRAPH_BASE_URL}/me/messages?page2"})
    client_with(monkeypatch, mg, handler)
    found = mg.MicrosoftGraphProvider().search_from(account=ACCOUNT, senders=["o'neil@x.co.uk",
                                                    "pay@harper.example"], since=SINCE)
    assert [m.provider_message_id for m in found] == ["m1", "m2"]
    first = parse_qs(urlparse(seen[0]).query)["$filter"][0]
    assert "receivedDateTime ge 2026-09-01T00:00:00Z" in first
    assert "from/emailAddress/address eq 'o''neil@x.co.uk'" in first
    assert "/me/messages" in seen[0] and "mailFolders" not in seen[0]


def test_graph_raises_on_an_error_or_endless_pages(monkeypatch):
    from providers import microsoft_graph as mg
    client_with(monkeypatch, mg, lambda request: httpx.Response(400, json={}))
    with pytest.raises(RuntimeError):
        mg.MicrosoftGraphProvider().search_from(account=ACCOUNT, senders=["pay@harper.example"],
                                                since=SINCE)
    client_with(monkeypatch, mg, lambda request: httpx.Response(200, json={
        "value": [], "@odata.nextLink": f"{mg.GRAPH_BASE_URL}/me/messages?more"}))
    with pytest.raises(RuntimeError):
        mg.MicrosoftGraphProvider().search_from(account=ACCOUNT, senders=["pay@harper.example"],
                                                since=SINCE)


@pytest.mark.parametrize("bad", ["a@b.com) OR (from:x", "a b@c.com", "x'@y.com or 1 eq 1", ""])
def test_an_address_that_could_bend_a_query_is_refused(bad):
    from providers.base import checked_senders
    with pytest.raises(ValueError):
        checked_senders([bad])


def test_a_mailbox_that_cannot_search_says_so():
    from providers.smtp import SMTPProvider
    with pytest.raises(NotImplementedError):
        SMTPProvider.__new__(SMTPProvider).search_from(account=ACCOUNT, senders=["pay@harper.example"], since=SINCE)
