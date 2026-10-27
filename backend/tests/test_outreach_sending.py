# ruff: noqa: F811 - pytest fixtures imported from test_outreach_send are parameters by design
"""OUT-16 — outreach actually sends (RED: email transport and unsubscribe).

Until now neither provider could send outreach: a send raised, was recorded as
"unknown" and held capacity. Each provider now sends one real RFC 5322
message carrying our own Message-ID, the thread headers for follow-ups and
one-click unsubscribe headers (RFC 8058), and reports an honest outcome:
accepted, definitely not accepted, or unknown (a timeout or a server error,
which may still have been delivered). No network call happens here.
"""
import base64
import email
from email import policy
from types import SimpleNamespace

import httpx
import pytest

ACCOUNT = SimpleNamespace(id="box-1", provider="google", email_address="partners-ukfi@newbody.example",
                          display_name="Mike at FitFutures", token_ciphertext="enc")
MESSAGE = dict(operation_key="op-1", to_emails=["sam@studio1.example"], cc_emails=[], subject="A free intern for Studio 1",
               body_text="Hi Sam,\n\nShort, specific email.\n\nUnsubscribe: https://app.example/u/tok",
               body_html=None, rfc_message_id="<abc-123@newbody.example>", in_reply_to=None, references=[],
               provider_thread_id=None,
               headers={"List-Unsubscribe": "<https://app.example/u/tok>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})


class FakeHttp:
    """Stands in for httpx.Client; answers each request from a queue."""

    def __init__(self, answers, gets=None):
        self.answers, self.requests, self.gets = list(answers), [], gets

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _answer(self, method, url, **kw):
        self.requests.append((method, url, kw))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return SimpleNamespace(status_code=status, text=str(body), json=lambda: body,
                               headers={})

    def post(self, url, **kw):
        return self._answer("POST", url, **kw)

    def get(self, url, **kw):
        if self.gets is not None:                       # a fixed answer for every GET (mailbox searches)
            self.requests.append(("GET", url, kw))
            return SimpleNamespace(status_code=200, text="", json=lambda: self.gets, headers={})
        return self._answer("GET", url, **kw)


def gmail(monkeypatch, answers, gets=None):
    from providers import google_gmail
    fake = FakeHttp(answers, gets)
    monkeypatch.setattr(google_gmail, "get_valid_access_token", lambda account: "tok")
    monkeypatch.setattr(google_gmail.httpx, "Client", fake)
    return google_gmail.GoogleGmailProvider(), fake


def graph(monkeypatch, answers):
    from providers import microsoft_graph
    fake = FakeHttp(answers)
    monkeypatch.setattr(microsoft_graph, "get_valid_access_token", lambda account: "tok")
    monkeypatch.setattr(microsoft_graph.httpx, "Client", fake)
    monkeypatch.setattr(microsoft_graph.time, "sleep", lambda s: None)
    return microsoft_graph.MicrosoftGraphProvider(), fake


def sent_mime(fake):
    method, url, kw = next(r for r in fake.requests if r[0] == "POST")
    raw = kw["json"]["raw"] if "json" in kw else kw["content"]
    data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)) if "json" in kw else base64.b64decode(raw)
    return email.message_from_bytes(data, policy=policy.default)


# ------------------------------------------------------------------ Gmail ---

def test_gmail_sends_one_message_with_our_message_id_and_unsubscribe_headers(monkeypatch):
    provider, fake = gmail(monkeypatch, [(200, {"id": "g-1", "threadId": "t-1"})])
    out = provider.send_outreach(account=ACCOUNT, **MESSAGE)
    msg = sent_mime(fake)
    assert fake.requests[0][1].endswith("/users/me/messages/send")
    assert msg["Message-ID"] == "<abc-123@newbody.example>"
    assert msg["List-Unsubscribe"] == "<https://app.example/u/tok>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg["To"] == "sam@studio1.example" and "partners-ukfi@newbody.example" in msg["From"]
    assert msg["Subject"] == "A free intern for Studio 1" and "Short, specific email." in msg.get_content()
    assert out == {"outcome": "accepted", "provider": "google", "mailbox_id": "box-1", "provider_message_id": "g-1",
                   "provider_thread_id": "t-1", "rfc_message_id": "<abc-123@newbody.example>"}


def test_a_gmail_follow_up_stays_in_its_thread(monkeypatch):
    provider, fake = gmail(monkeypatch, [(200, {"id": "g-2", "threadId": "t-1"})])
    follow = dict(MESSAGE, rfc_message_id="<def-456@newbody.example>", in_reply_to="<abc-123@newbody.example>",
                  references=["<abc-123@newbody.example>"], provider_thread_id="t-1", subject="Re: A free intern")
    provider.send_outreach(account=ACCOUNT, **follow)
    msg = sent_mime(fake)
    assert fake.requests[0][2]["json"]["threadId"] == "t-1"
    assert msg["In-Reply-To"] == "<abc-123@newbody.example>" and msg["References"] == "<abc-123@newbody.example>"


@pytest.mark.parametrize("status,outcome", [(400, "definitely_not_accepted"), (401, "definitely_not_accepted"),
                                            (403, "definitely_not_accepted"), (429, "definitely_not_accepted"),
                                            (500, "unknown"), (503, "unknown"),
                                            # Only Gmail's documented 200 is acceptance; any other 2xx/3xx is unexplained.
                                            (201, "unknown"), (202, "unknown"), (204, "unknown"), (302, "unknown")])
def test_gmail_failures_are_reported_honestly(monkeypatch, status, outcome):
    provider, fake = gmail(monkeypatch, [(status, {"error": "x"})])
    out = provider.send_outreach(account=ACCOUNT, **MESSAGE)
    assert out["outcome"] == outcome and out["mailbox_id"] == "box-1" and out["provider"] == "google"


def test_a_gmail_timeout_is_unknown_never_a_retry(monkeypatch):
    provider, fake = gmail(monkeypatch, [httpx.ReadTimeout("slow")])
    assert provider.send_outreach(account=ACCOUNT, **MESSAGE)["outcome"] == "unknown"
    assert len(fake.requests) == 1


def test_no_header_can_be_smuggled_in_by_a_line_break(monkeypatch):
    provider, fake = gmail(monkeypatch, [(200, {"id": "g", "threadId": "t"})])
    bad = dict(MESSAGE, subject="Hello\r\nBcc: everyone@example.com")
    out = provider.send_outreach(account=ACCOUNT, **bad)
    assert out["outcome"] == "definitely_not_accepted" and fake.requests == []


# -------------------------------------------------------- Microsoft Graph ---

MS_ACCOUNT = SimpleNamespace(**{**vars(ACCOUNT), "provider": "microsoft"})


def test_graph_sends_the_full_message_and_finds_its_ids(monkeypatch):
    provider, fake = graph(monkeypatch, [(202, {}), (200, {"value": [{"id": "m-1", "conversationId": "c-1"}]})])
    out = provider.send_outreach(account=MS_ACCOUNT, **MESSAGE)
    method, url, kw = fake.requests[0]
    assert url.endswith("/me/sendMail") and kw["headers"]["Content-Type"] == "text/plain"
    msg = sent_mime(fake)
    assert msg["Message-ID"] == "<abc-123@newbody.example>" and msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    lookup = fake.requests[1]
    assert lookup[0] == "GET" and "internetMessageId" in lookup[2]["params"]["$filter"]
    assert out == {"outcome": "accepted", "provider": "microsoft", "mailbox_id": "box-1", "provider_message_id": "m-1",
                   "provider_thread_id": "c-1", "rfc_message_id": "<abc-123@newbody.example>"}


def test_graph_accepted_but_not_yet_findable_is_still_accepted(monkeypatch):
    provider, fake = graph(monkeypatch, [(202, {})] + [(200, {"value": []})] * 3)
    out = provider.send_outreach(account=MS_ACCOUNT, **MESSAGE)
    assert out["outcome"] == "accepted" and out["provider_message_id"] is None


@pytest.mark.parametrize("status,outcome", [(400, "definitely_not_accepted"), (401, "definitely_not_accepted"),
                                            (429, "definitely_not_accepted"), (500, "unknown"),
                                            # Graph documents 202 for sendMail; a 200 or 204 is not that contract.
                                            (200, "unknown"), (204, "unknown"), (302, "unknown")])
def test_graph_failures_are_reported_honestly(monkeypatch, status, outcome):
    provider, fake = graph(monkeypatch, [(status, {"error": "x"})])
    assert provider.send_outreach(account=MS_ACCOUNT, **MESSAGE)["outcome"] == outcome


def test_a_graph_follow_up_carries_thread_headers_and_confirms_its_conversation(monkeypatch):
    """Graph's MIME /reply would address our own mailbox (the original sender),
    so a follow-up is a sendMail carrying the thread headers and "Re:" subject;
    the conversation Outlook filed it in is then reported, not assumed."""
    follow = dict(MESSAGE, rfc_message_id="<def-456@newbody.example>", in_reply_to="<abc-123@newbody.example>",
                  references=["<abc-123@newbody.example>"], provider_thread_id="c-1", subject="Re: A free intern")
    provider, fake = graph(monkeypatch, [(202, {}), (200, {"value": [{"id": "m-2", "conversationId": "c-1"}]})])
    out = provider.send_outreach(account=MS_ACCOUNT, **follow)
    assert fake.requests[0][1].endswith("/me/sendMail")
    msg = sent_mime(fake)
    assert msg["In-Reply-To"] == "<abc-123@newbody.example>" and msg["References"] == "<abc-123@newbody.example>"
    assert msg["To"] == "sam@studio1.example" and msg["Subject"] == "Re: A free intern"
    assert out["provider_thread_id"] == "c-1" and "thread_note" not in out


def test_a_graph_follow_up_in_another_conversation_is_named_not_hidden(monkeypatch):
    follow = dict(MESSAGE, in_reply_to="<abc-123@newbody.example>", references=["<abc-123@newbody.example>"],
                  provider_thread_id="c-1", subject="Re: A free intern")
    provider, fake = graph(monkeypatch, [(202, {}), (200, {"value": [{"id": "m-2", "conversationId": "c-9"}]})])
    out = provider.send_outreach(account=MS_ACCOUNT, **follow)
    assert out["outcome"] == "accepted" and out["provider_thread_id"] == "c-9"
    assert "different Outlook conversation" in out["thread_note"]
    provider, fake = graph(monkeypatch, [(202, {})] + [(200, {"value": []})] * 3)
    assert "unconfirmed" in provider.send_outreach(account=MS_ACCOUNT, **follow)["thread_note"]


# ------------------------------------------------------------ unsubscribe ---

def test_the_unsubscribe_link_defaults_to_the_apps_own_address(monkeypatch):
    from services import outreach_send
    monkeypatch.delenv("OUTREACH_UNSUBSCRIBE_BASE_URL", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.businesshero.example")
    assert outreach_send.unsubscribe_base() == "https://api.businesshero.example/u"
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_BASE_URL", "https://unsub.example/x")
    assert outreach_send.unsubscribe_base() == "https://unsub.example/x"


@pytest.mark.parametrize("variable", ["OUTREACH_UNSUBSCRIBE_BASE_URL", "PUBLIC_BASE_URL"])
@pytest.mark.parametrize("value", ["https://api.example.com/#fragment", "https://api.example.com/x#", "https://api.example.com/?a=1"])
def test_an_unsubscribe_address_with_a_fragment_or_query_is_refused(h, variable, value, monkeypatch):
    """A fragment never reaches the server, so the token after it would be
    lost (Codex OUT-16 review 1); both configuration paths are refused."""
    from test_outreach_send import CAMPAIGN, ENROLMENT, OWNER, STEP
    monkeypatch.delenv("OUTREACH_UNSUBSCRIBE_BASE_URL", raising=False)
    monkeypatch.setenv(variable, value)
    result = h.a.propose(h.s, h.b, OWNER, "send_outreach", dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=STEP))
    assert "proposal" not in result and not h.p.sends


def test_the_unsubscribe_rate_limit_ignores_unverified_bearer_tokens(monkeypatch):
    """The page is public: a forged bearer token must not buy a fresh bucket."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler
    import outreach_unsubscribe_api as api
    from rate_limiting import limiter
    from services import outreach_send
    monkeypatch.setattr(outreach_send, "unsubscribe", lambda session, *, token, method: {"confirmation_required": True})
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(api.router)
    app.dependency_overrides[api.get_session] = lambda: iter([None])
    client = TestClient(app)

    def forged(sub):
        body = base64.urlsafe_b64encode(f'{{"sub":"{sub}"}}'.encode()).decode().rstrip("=")
        return {"Authorization": f"Bearer e30.{body}.sig"}
    try:
        codes = [client.get("/u/" + "t" * 43, headers=forged(f"user-{i}")).status_code for i in range(61)]
        limiter.reset()
        posts = [client.post("/u/" + "t" * 43, headers=forged(f"user-{i}")).status_code for i in range(61)]
    finally:
        limiter.reset()
    assert codes[:60] == [200] * 60 and codes[60] == 429
    assert posts[:60] == [200] * 60 and posts[60] == 429


def test_a_long_follow_up_subject_is_folded_not_cut(monkeypatch):
    provider, fake = gmail(monkeypatch, [(200, {"id": "g", "threadId": "t"})])
    subject = "Re: Fitness intern offer " + "word " * 195
    provider.send_outreach(account=ACCOUNT, **dict(MESSAGE, subject=subject))
    assert sent_mime(fake)["Subject"] == subject
    raw = fake.requests[0][2]["json"]["raw"]
    sent = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    assert all(len(line) <= 998 for line in sent.split(b"\r\n"))


def test_the_unsubscribe_page_confirms_on_get_and_unsubscribes_on_post(monkeypatch):
    """GET never changes anything (link scanners open links); POST — the
    one-click button mail apps use, or our page's button — unsubscribes."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import outreach_unsubscribe_api as api
    from services import outreach_send
    calls = []
    monkeypatch.setattr(outreach_send, "unsubscribe", lambda session, *, token, method: (calls.append(method) or
                        ({"confirmation_required": True} if method == "GET" else {"unsubscribed": True})))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_session] = lambda: iter([None])
    client = TestClient(app)
    token = "t" * 43
    page = client.get(f"/u/{token}")
    assert page.status_code == 200 and "Unsubscribe" in page.text and "<form" in page.text and calls == ["GET"]
    done = client.post(f"/u/{token}", data={"List-Unsubscribe": "One-Click"})
    assert done.status_code == 200 and calls == ["GET", "POST"] and "unsubscribed" in done.text.lower()


def test_an_unknown_unsubscribe_token_is_a_plain_404(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import outreach_unsubscribe_api as api
    from services import outreach_send
    from services.aria_actions import ActionRefused

    def refuse(session, *, token, method):
        raise ActionRefused(404, "Invalid unsubscribe token")
    monkeypatch.setattr(outreach_send, "unsubscribe", refuse)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_session] = lambda: iter([None])
    response = TestClient(app).post("/u/" + "x" * 43)
    assert response.status_code == 404 and "link" in response.text.lower()


# ------------------------------------------- end to end, through the real adapter ---

from test_outreach_send import BOX, EMAIL, h, propose, approve, database, real_aria_actions  # noqa: E402,F401


def test_an_approved_card_goes_out_through_the_real_gmail_adapter(h, monkeypatch):
    """The send path and the adapter agree: the card is sent once, as a real
    message with its unsubscribe headers, and recorded with Gmail's ids."""
    from providers.google_gmail import GoogleGmailProvider
    from sqlalchemy import text
    # The claim first searches the mailbox for a reply from the prospect (none), then sends.
    provider, fake = gmail(monkeypatch, [(200, {"id": "gmail-msg", "threadId": "gmail-thread"})], gets={"messages": []})
    seen = []

    class Watching(GoogleGmailProvider):
        def send_outreach(self, **kw):
            out = super().send_outreach(**kw)
            seen.append(out)
            return out
    monkeypatch.setattr(h.m, "get_provider_for_account", lambda account: Watching())
    card = propose(h)
    result = approve(h, card)
    assert result["status"] == "done", seen
    msg = sent_mime(fake)
    assert msg["To"] == EMAIL and msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg["Message-ID"] == card["preview"]["rfc_message_id"]
    row = h.s.execute(text("SELECT state, provider_message_id, provider_thread_id FROM outreach_messages "
                           "WHERE state='accepted'")).one()
    assert tuple(row) == ("accepted", "gmail-msg", "gmail-thread")
