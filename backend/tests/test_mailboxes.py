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
  mailboxes_before(session, business_id) -> [{id, email_address, provider,
      is_default, display_name}]  -- the callback reads this BEFORE it saves
  ensure_default_after_connect(session, business_id, email_address, provider,
      before) -> the id it marked, or None. One transaction under a
      per-business lock; marks the mailbox AUTO-2 was already using (the
      sole one, or the new one if there was none); never chooses when the
      owner has not; restores a label the reconnect wiped; never raises
Router: the Google sign-in asks which account to use; the OAuth callbacks
read mailboxes_before, save, then call ensure_default_after_connect; disconnect reports needs_default.
"""

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
#
# Codex review 1 (P1): nothing ever marked a default, so a business's sole
# mailbox is usually UNMARKED and is AUTO-2's default only because it is
# alone. Connecting a second mailbox must mark the mailbox chasing was already
# using, never the newcomer. The callback therefore records the mailboxes
# BEFORE saving the new connection, and settles the default afterwards in one
# transaction under a per-business lock: main has no 037 index to lean on.

def connect(eng, bid, addr, provider="google", new_id=None, label=None):
    """What an OAuth callback does: look first, save the connection, then
    settle the default."""
    m = mailboxes()
    with Session(eng) as s:
        before = m.mailboxes_before(s, bid)
    with eng.begin() as c:
        hit = c.execute(text("SELECT id FROM email_accounts WHERE business_id = :b "
                             "AND lower(email_address) = lower(:e) AND provider = :p"),
                        {"b": bid, "e": addr, "p": provider}).fetchone()
        if hit:  # the upsert: a reconnect keeps the row, and wipes the label
            c.execute(text("UPDATE email_accounts SET display_name = :n WHERE id = :id"),
                      {"n": label, "id": hit[0]})
        else:
            c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address, "
                           "display_name, is_default) VALUES (:id, :b, :p, :e, :n, 0)"),
                      {"id": new_id, "b": bid, "p": provider, "e": addr, "n": label})
    with Session(eng) as s:
        return m.ensure_default_after_connect(s, bid, addr, provider, before)


@pytest.fixture
def empty():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            provider TEXT NOT NULL, email_address TEXT NOT NULL, display_name TEXT,
            is_default BOOLEAN NOT NULL DEFAULT 0, created_at TEXT, updated_at TEXT,
            UNIQUE (business_id, email_address, provider))"""))
    yield eng
    eng.dispose()


def add(eng, id_, addr, default=False, label=None, bid=A):
    with eng.begin() as c:
        c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address, "
                       "display_name, is_default) VALUES (:id, :b, 'google', :e, :n, :d)"),
                  {"id": id_, "b": bid, "e": addr, "n": label, "d": default})


def test_the_first_mailbox_a_business_connects_becomes_its_default(empty):
    assert connect(empty, A, "m.rickards@newbodyhf.co.uk", new_id="n1") == "n1"
    assert defaults(empty) == ["n1"]


def test_a_later_mailbox_never_takes_the_default(empty):
    add(empty, "n1", "m.rickards@newbodyhf.co.uk", default=True)
    connect(empty, A, "outreach@newbodyhf.co.uk", new_id="n2")
    assert defaults(empty) == ["n1"]


def test_an_unmarked_sole_mailbox_keeps_chasing_when_another_is_connected(empty):
    """Mike's own account today: m.rickards@ is alone and unmarked. Connecting
    outreach@ must mark m.rickards@, never outreach@."""
    from services.chase_replies import default_mailbox
    add(empty, "n1", "m.rickards@newbodyhf.co.uk", default=False)
    with Session(empty) as s:
        assert default_mailbox(s, A) == "n1"
    connect(empty, A, "outreach@newbodyhf.co.uk", new_id="n2")
    assert defaults(empty) == ["n1"]
    with Session(empty) as s:
        assert default_mailbox(s, A) == "n1"


def test_reconnecting_the_default_keeps_it_the_default(empty):
    add(empty, "n1", "m.rickards@newbodyhf.co.uk", default=True)
    connect(empty, A, "M.Rickards@newbodyhf.co.uk")
    connect(empty, A, "m.rickards@newbodyhf.co.uk")
    assert defaults(empty) == ["n1"]


def test_reconnecting_when_the_owner_has_not_chosen_does_not_choose_for_them(empty):
    """Two mailboxes, neither default (a disconnect left the choice open):
    reconnecting one of them must not settle it."""
    add(empty, "n1", "one@newbodyhf.co.uk")
    add(empty, "n2", "two@newbodyhf.co.uk")
    assert connect(empty, A, "two@newbodyhf.co.uk") is None
    assert defaults(empty) == []
    with Session(empty) as s:
        assert mailboxes().needs_default(s, A) is True


def test_a_new_mailbox_when_the_owner_has_not_chosen_does_not_choose_for_them(empty):
    add(empty, "n1", "one@newbodyhf.co.uk")
    add(empty, "n2", "two@newbodyhf.co.uk")
    connect(empty, A, "three@newbodyhf.co.uk", new_id="n3")
    assert defaults(empty) == []


def test_reconnecting_keeps_the_label(empty):
    """Review 1 backlog: the Google upsert writes display_name=None and
    Microsoft writes the provider's name, wiping the owner's label."""
    add(empty, "n1", "outreach@newbodyhf.co.uk", default=True, label="New Body outreach")
    connect(empty, A, "outreach@newbodyhf.co.uk", label=None)
    with empty.connect() as c:
        assert c.execute(text("SELECT display_name FROM email_accounts WHERE id = 'n1'")).scalar() \
            == "New Body outreach"


def test_connecting_never_touches_another_business(empty):
    add(empty, "b1", "ops@msccompany.co.uk", bid=B)
    connect(empty, A, "m.rickards@newbodyhf.co.uk", new_id="n1")
    assert defaults(empty, B) == [] and defaults(empty) == ["n1"]


def test_settling_the_default_never_fails_the_connection(empty, monkeypatch):
    """The mailbox is already saved; a failure to mark a default is logged,
    and the owner can still press Make default."""
    m = mailboxes()
    with Session(empty) as s:
        before = m.mailboxes_before(s, A)
    add(empty, "n1", "m.rickards@newbodyhf.co.uk")
    with Session(empty) as s:
        def boom(*a, **k):
            raise RuntimeError("database went away")
        monkeypatch.setattr(s, "execute", boom)
        assert m.ensure_default_after_connect(s, A, "m.rickards@newbodyhf.co.uk", "google", before) is None


def test_the_oauth_callbacks_set_the_first_default():
    mailboxes()
    router = importlib.import_module("app.email.router")
    for name in ("google_oauth_callback", "microsoft_oauth_callback"):
        src = inspect.getsource(getattr(router, name))
        # Look BEFORE saving (review 1, P1), then settle afterwards.
        assert src.index("_mailboxes_before_connect(") < src.index("upsert_email_accounts(") \
            < src.index("_settle_default_after_connect("), name
    assert "ensure_default_after_connect" in inspect.getsource(router._settle_default_after_connect)


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
