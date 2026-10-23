"""MAIL-1 — several mailboxes per business, with a dependable default.

docs/MAIL-1-TICKET.md. Tests first (AMBER). Strict xfail may fail only
because `app.email.mailboxes` does not exist yet.

The contract (backend/app/email/mailboxes.py):
  set_default(session, business_id, account_id) -> {"id", "is_default"}
      one transaction; LookupError if the account is not this business's
  rename(session, business_id, account_id, label) -> {"id", "display_name"}
      1-60 characters after trimming, else ValueError; LookupError if foreign
  needs_default(session, business_id) -> bool
      two or more mailboxes and none is the default
  async ensure_default_after_connect(admin, business_id, email_address, provider)
      marks the just-connected mailbox default only if the business has none
Router: the Google sign-in asks which account to use; the OAuth callbacks
call ensure_default_after_connect; disconnect reports needs_default.
"""

import asyncio
import importlib
import importlib.util
import inspect
import os
from urllib.parse import parse_qs, urlparse

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402


class MissingMailboxes(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the implementation landed.

A, B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def mailboxes():
    if importlib.util.find_spec("app.email.mailboxes") is None:
        raise MissingMailboxes("backend/app/email/mailboxes.py does not exist yet")
    return importlib.import_module("app.email.mailboxes")


@pytest.fixture
def db():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            provider TEXT NOT NULL, email_address TEXT NOT NULL, display_name TEXT,
            is_default BOOLEAN NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT,
            UNIQUE (business_id, email_address, provider))"""))
        # Migration 037's rule, as SQLite can hold it: at most one default.
        c.execute(text("CREATE UNIQUE INDEX one_default ON email_accounts (business_id) "
                       "WHERE is_default = 1"))
        for i, (bid, addr, default) in enumerate((
                (A, "m.rickards@newbodyhf.co.uk", True),
                (A, "outreach@newbodyhf.co.uk", False),
                (A, "partners-ukfi@newbodyhf.co.uk", False),
                (B, "ops@msccompany.co.uk", True))):
            c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address, "
                           "is_default, created_at) VALUES (:id, :b, 'google', :e, :d, :t)"),
                      {"id": f"acct-{i}", "b": bid, "e": addr, "d": default, "t": f"2026-10-0{i + 1}"})
    yield eng
    eng.dispose()


def defaults(eng, bid=A):
    with eng.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT id FROM email_accounts WHERE business_id = :b AND is_default = 1"), {"b": bid})]


# ------------------------------------------------------------ the default ---

def test_make_default_switches_to_exactly_one(db):
    with Session(db) as s:
        out = mailboxes().set_default(s, A, "acct-1")
    assert out == {"id": "acct-1", "is_default": True}
    assert defaults(db) == ["acct-1"]
    assert defaults(db, B) == ["acct-3"], "another business is untouched"


def test_another_business_mailbox_is_not_found_and_nothing_changes(db):
    """Today's bug: the clearing ran before the ownership check, so a foreign
    id left the business with no default at all."""
    with Session(db) as s:
        with pytest.raises(LookupError):
            mailboxes().set_default(s, A, "acct-3")
    assert defaults(db) == ["acct-0"] and defaults(db, B) == ["acct-3"]


def test_an_unknown_mailbox_is_not_found_and_nothing_changes(db):
    with Session(db) as s:
        with pytest.raises(LookupError):
            mailboxes().set_default(s, A, "no-such-account")
    assert defaults(db) == ["acct-0"]


def test_a_failure_halfway_never_leaves_the_business_without_a_default(db, monkeypatch):
    """Clear and set are one transaction: if setting fails, the clearing is
    undone too."""
    m = mailboxes()
    with Session(db) as s:
        real_execute = s.execute
        calls = {"n": 0}

        def failing(statement, *a, **k):
            # The second UPDATE (setting the new default) fails.
            if str(statement).lstrip().upper().startswith("UPDATE"):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("database went away")
            return real_execute(statement, *a, **k)
        monkeypatch.setattr(s, "execute", failing)
        with pytest.raises(Exception):
            m.set_default(s, A, "acct-1")
    assert defaults(db) == ["acct-0"]


def test_making_the_current_default_default_again_is_harmless(db):
    with Session(db) as s:
        mailboxes().set_default(s, A, "acct-0")
    assert defaults(db) == ["acct-0"]


# ------------------------------------------------------------ connecting ---

class FakeAdmin:
    """The Supabase admin client, as the OAuth callbacks use it."""

    def __init__(self, rows):
        self.rows = rows

    async def fetch_email_accounts(self, business_id, *, fields):
        return [dict(r) for r in self.rows if r["business_id"] == business_id]

    async def fetch_email_account(self, *, business_id, fields, account_id=None, is_default=None):
        for r in self.rows:
            if r["business_id"] != business_id:
                continue
            if account_id and r["id"] != account_id:
                continue
            if is_default is not None and bool(r["is_default"]) != is_default:
                continue
            return dict(r)
        return None

    async def _update(self, table, values, filters):
        hit = [r for r in self.rows if all(str(r.get(k)) == str(v) for k, v in filters.items())]
        if values.get("is_default"):
            for r in hit:
                if any(o["business_id"] == r["business_id"] and o["is_default"] and o is not r
                       for o in self.rows):
                    raise RuntimeError("violates one_default")  # the 037 index
        for r in hit:
            r.update(values)
        return [dict(r) for r in hit]


def run(coro):
    return asyncio.run(coro)


def test_the_first_mailbox_a_business_connects_becomes_its_default():
    rows = [{"id": "n1", "business_id": A, "provider": "google",
             "email_address": "m.rickards@newbodyhf.co.uk", "is_default": False}]
    admin = FakeAdmin(rows)
    run(mailboxes().ensure_default_after_connect(admin, A, "m.rickards@newbodyhf.co.uk", "google"))
    assert rows[0]["is_default"] is True


def test_a_later_mailbox_never_takes_the_default():
    rows = [{"id": "n1", "business_id": A, "provider": "google",
             "email_address": "m.rickards@newbodyhf.co.uk", "is_default": True},
            {"id": "n2", "business_id": A, "provider": "google",
             "email_address": "outreach@newbodyhf.co.uk", "is_default": False}]
    admin = FakeAdmin(rows)
    run(mailboxes().ensure_default_after_connect(admin, A, "outreach@newbodyhf.co.uk", "google"))
    assert [r["is_default"] for r in rows] == [True, False]


def test_reconnecting_the_default_keeps_it_the_default():
    rows = [{"id": "n1", "business_id": A, "provider": "google",
             "email_address": "m.rickards@newbodyhf.co.uk", "is_default": True}]
    admin = FakeAdmin(rows)
    run(mailboxes().ensure_default_after_connect(admin, A, "M.Rickards@newbodyhf.co.uk", "google"))
    assert rows[0]["is_default"] is True and rows[0]["id"] == "n1"


def test_two_connections_at_once_still_leave_exactly_one_default():
    """Both callbacks see 'no default'; the 037 rule lets only one win, and
    the loser must not fail the connection."""
    rows = [{"id": "n1", "business_id": A, "provider": "google",
             "email_address": "one@newbodyhf.co.uk", "is_default": False},
            {"id": "n2", "business_id": A, "provider": "google",
             "email_address": "two@newbodyhf.co.uk", "is_default": False}]
    admin = FakeAdmin(rows)

    async def both():
        await asyncio.gather(
            mailboxes().ensure_default_after_connect(admin, A, "one@newbodyhf.co.uk", "google"),
            mailboxes().ensure_default_after_connect(admin, A, "two@newbodyhf.co.uk", "google"))
    run(both())
    assert sum(1 for r in rows if r["is_default"]) == 1


def test_the_oauth_callbacks_set_the_first_default():
    mailboxes()
    router = importlib.import_module("app.email.router")
    for name in ("google_oauth_callback", "microsoft_oauth_callback"):
        assert "ensure_default_after_connect" in inspect.getsource(getattr(router, name)), name


def test_the_google_sign_in_asks_which_account(monkeypatch):
    mailboxes()
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://example.invalid/cb")
    monkeypatch.setenv("EMAIL_OAUTH_STATE_SECRET", "test-only-secret")
    router = importlib.import_module("app.email.router")
    url = router.build_google_oauth_start_url({"user_id": "u", "business_id": A}, None)
    prompt = parse_qs(urlparse(url).query)["prompt"][0].split()
    assert "select_account" in prompt and "consent" in prompt


# ------------------------------------------------------------ labels ---

def test_a_mailbox_can_be_labelled(db):
    with Session(db) as s:
        out = mailboxes().rename(s, A, "acct-1", "  New Body outreach  ")
    assert out == {"id": "acct-1", "display_name": "New Body outreach"}


@pytest.mark.parametrize("label", ["", "   ", "x" * 61])
def test_a_label_must_be_one_to_sixty_characters(db, label):
    with Session(db) as s:
        with pytest.raises(ValueError):
            mailboxes().rename(s, A, "acct-1", label)


def test_another_business_mailbox_cannot_be_labelled(db):
    with Session(db) as s:
        with pytest.raises(LookupError):
            mailboxes().rename(s, A, "acct-3", "Mine now")
    with db.connect() as c:
        assert c.execute(text("SELECT display_name FROM email_accounts WHERE id='acct-3'")).scalar() is None


# ------------------------------------------------------------ disconnecting ---

def test_disconnecting_the_default_with_two_left_asks_for_a_new_one(db):
    with db.begin() as c:
        c.execute(text("DELETE FROM email_accounts WHERE id = 'acct-0'"))
    with Session(db) as s:
        assert mailboxes().needs_default(s, A) is True


def test_one_mailbox_left_needs_no_choice(db):
    with db.begin() as c:
        c.execute(text("DELETE FROM email_accounts WHERE id IN ('acct-0', 'acct-2')"))
    with Session(db) as s:
        assert mailboxes().needs_default(s, A) is False


def test_disconnect_reports_whether_a_default_is_needed():
    mailboxes()
    router = importlib.import_module("app.email.router")
    assert "needs_default" in inspect.getsource(router.delete_email_account)


# ------------------------------------------------------------ chasing ---

def test_chasing_keeps_its_mailbox_when_more_are_connected(db):
    """The point of the ticket: connecting outreach inboxes never moves
    invoice chasing off the owner's default mailbox."""
    mailboxes()
    from services.chase_replies import default_mailbox
    with Session(db) as s:
        assert default_mailbox(s, A) == "acct-0"
