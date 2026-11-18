"""RCP-1 — a receptionist phone number, requested in the app and set up by
Mike's Approve (docs/RCP-1-TICKET.md). RED: it spends money with Twilio and
decides which business answers a phone line.

Twilio is a fake throughout (FakeTwilio). Every rule R1–R8 has a test here;
the real Twilio wrapper's calls are checked against a stub client at the end.
"""
import json
import re
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"      # pro: receptionist in the plan
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"      # starter + receptionist flag: an add-on
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"      # starter, no receptionist
OWNER, ADMIN = "11111111-1111-4111-8111-111111111111", "99999999-9999-4999-8999-999999999999"
NOW = datetime(2026, 11, 13, 15, tzinfo=timezone.utc)
BUNDLE, ADDRESS = "BU" + "a" * 32, "AD" + "b" * 32
NUMBER = "+441612345678"
VOICE_URL = "https://api.example.invalid/v1/receptionist/incoming-call"


def rn():
    from services import receptionist_numbers
    return receptionist_numbers


def refused():
    from services.aria_actions import ActionRefused
    return ActionRefused


# ------------------------------------------------------------------ fakes ---

class FakeTwilio:
    """Stands in for receptionist_numbers.TwilioNumbers."""

    def __init__(self):
        self.bundle = "twilio-approved"
        self.available = [NUMBER, "+441612345679", "+442071234567"]
        self.owned = {}                 # sid -> {"sid", "phone_number", "friendly_name", "voice_url", "voice_method"}
        self.bought = []                # every purchase, in order
        self.fail_buy = None            # None | "definite" | "unknown" | "unknown_after_buying"
        self.wrong_voice = False        # the bought number comes back with a different VoiceUrl
        self.stuck_voice = False        # ... and updating it doesn't take
        self.price = (Decimal("1.15"), "USD")   # Twilio's GB local price; 98p at the default rate
        self.created = None                     # Twilio's date_created for a bought number
        self.calls = []

    def bundle_status(self, sid):
        self.calls.append(("bundle_status", sid))
        return self.bundle

    def local_price(self):
        self.calls.append(("local_price",))
        return self.price

    def available_local(self, area_digits, limit=30):
        self.calls.append(("available_local", area_digits))
        return list(self.available)[:limit]

    def find_tagged(self, tag):
        self.calls.append(("find_tagged", tag))
        return [dict(n) for n in self.owned.values() if n["friendly_name"] == tag]

    def buy(self, *, phone_number, tag, voice_url, address_sid, bundle_sid):
        self.calls.append(("buy", phone_number))
        m = rn()
        if self.fail_buy == "definite":
            raise m.TwilioDefinite("That number is no longer available.")
        if self.fail_buy == "unknown":
            raise m.TwilioUnknown("Read timed out.")
        sid = "PN" + uuid.uuid4().hex
        number = {"sid": sid, "phone_number": phone_number, "friendly_name": tag,
                  "voice_url": "https://wrong.example.invalid/" if self.wrong_voice else voice_url,
                  "voice_method": "POST", "date_created": self.created}
        self.owned[sid] = number
        self.bought.append(phone_number)
        if self.fail_buy == "unknown_after_buying":
            raise m.TwilioUnknown("Read timed out after Twilio bought it.")
        return dict(number)

    def fetch(self, sid):
        self.calls.append(("fetch", sid))
        return dict(self.owned[sid])

    def set_voice(self, sid, voice_url):
        self.calls.append(("set_voice", sid))
        if not self.stuck_voice:
            self.owned[sid].update(voice_url=voice_url, voice_method="POST")
        return dict(self.owned[sid])


# --------------------------------------------------------------- database ---

def _insert(s, table, **values):
    s.execute(text(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join(':' + k for k in values)})"), values)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.invalid")
    monkeypatch.delenv("RECEPTIONIST_GBP_PER_USD", raising=False)
    engine = create_engine("sqlite:///" + str(tmp_path / "rcp1.sqlite"))
    sql = (Path(__file__).parents[1] / "migrations" / "043_receptionist_number_requests.sql").read_text()
    with Session(engine) as s:
        for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS public\.(\w+) \(\n(.*?)\n\);", sql, re.S):
            cols = []
            for line in body.splitlines():
                m = re.match(r"  ([a-z_0-9]+) (uuid|text|integer|boolean|timestamptz)\b", line)
                if m:
                    col, kind = m.groups()
                    cols.append(f"{col} {'NUMERIC' if kind in ('integer', 'boolean') else 'TEXT'}"
                                + (" PRIMARY KEY" if col == "id" else ""))
            s.execute(text(f"CREATE TABLE {table} ({','.join(cols)})"))
        for stmt in re.findall(r"(CREATE UNIQUE INDEX IF NOT EXISTS .*?;)", sql, re.S):
            if "receptionist_number_requests" in stmt:
                s.execute(text(stmt.replace("public.", "")))
        for ddl in (
            "CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, feature_flags TEXT, "
            "subscription_status TEXT, is_active BOOLEAN, trial_ends_at TIMESTAMP)",
            "CREATE TABLE platform_meters (period TEXT, meter TEXT, value NUMERIC, updated_at TEXT, "
            "UNIQUE (period, meter))",
        ):
            s.execute(text(ddl))
        for bid, plan, flags in ((A, "pro", {}), (B, "starter", {"receptionist": True}), (C, "starter", {})):
            _insert(s, "businesses", id=bid, name=f"Biz {bid[:4]}", plan_tier=plan, feature_flags=json.dumps(flags),
                    subscription_status="active", is_active=True)
        s.commit()
    # receptionist_configs as live (audits/live-schema-public.txt): every NOT NULL column but
    # business_id has a default; the unique index exactly as migration 043 adds it.
    with engine.begin() as c:
        c.execute(text("CREATE TABLE receptionist_configs (id TEXT PRIMARY KEY, business_id TEXT NOT NULL UNIQUE, "
                       "enabled BOOLEAN NOT NULL DEFAULT 0, twilio_phone_number TEXT, twilio_phone_sid TEXT, "
                       "created_at TEXT, updated_at TEXT)"))
        c.execute(text("CREATE UNIQUE INDEX uq_receptionist_configs_twilio_phone_number "
                       "ON receptionist_configs (twilio_phone_number) WHERE twilio_phone_number IS NOT NULL"))
    yield engine
    engine.dispose()


@pytest.fixture
def tw(monkeypatch):
    fake = FakeTwilio()
    fake.emails = []
    monkeypatch.setattr(rn(), "twilio", lambda: fake)
    monkeypatch.setattr(rn(), "_send_owner_email", lambda bid, subject, body: fake.emails.append((bid, body)) or True)
    return fake


def biz(engine, bid):
    with engine.connect() as c:
        r = c.execute(text("SELECT id, plan_tier, feature_flags, subscription_status, is_active, trial_ends_at "
                           "FROM businesses WHERE id = :b"), {"b": bid}).one()
    return SimpleNamespace(id=str(r[0]), plan_tier=r[1], feature_flags=r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}"),
                           subscription_status=r[3], is_active=bool(r[4]), trial_ends_at=r[5])


def details(**extra):
    base = {"mode": "new_local", "area_code": "0161", "legal_name": "Multi Skilled Contractors Ltd",
            "address_line1": "1 High Street", "city": "Manchester", "postcode": "M1 1AA", "setup": "self"}
    base.update(extra)
    return base


def request(engine, bid=A, **extra):
    with Session(engine) as s:
        return rn().request_number(s, biz(engine, bid), OWNER, details(**extra), now=NOW)


def prepare(engine, rid, **body):
    with Session(engine) as s:
        current = rn().admin_get(s, rid)
        payload = {"bundle_sid": BUNDLE, "address_sid": ADDRESS, "version": current["version"]}
        payload.update(body)
        return rn().admin_prepare(s, rid, payload, ADMIN, now=NOW)


def approve(engine, rid, *, number=NUMBER, version=None, now=NOW, check=True):
    """Mike's flow: Check (if the request hasn't been checked), then Buy."""
    if check and row(engine, rid)["state"] in ("requested", "waiting_bundle") and not row(engine, rid)["candidates"]:
        prepare(engine, rid)
    with Session(engine) as s:
        current = rn().admin_get(s, rid)
        body = {"phone_number": number, "version": current["version"] if version is None else version}
        return rn().admin_approve(s, rid, body, ADMIN, now=now)


def retry(engine, rid, *, now):
    with Session(engine) as s:
        current = rn().admin_get(s, rid)
        return rn().admin_retry(s, rid, {"version": current["version"]}, ADMIN, now=now)


def row(engine, rid):
    with Session(engine) as s:
        return rn().admin_get(s, rid)


def assigned(engine, bid):
    with engine.connect() as c:
        r = c.execute(text("SELECT twilio_phone_number, twilio_phone_sid, enabled FROM receptionist_configs "
                           "WHERE business_id = :b"), {"b": bid}).first()
    return r


# ---------------------------------------------------------- the owner side ---

def test_an_owner_requests_a_local_number(db, tw):
    out = request(db)
    assert out["state"] == "requested" and out["mode"] == "new_local" and out["area_code"] == "0161"
    assert out["in_plan"] is True and out["setup"] == "done_for_you" and out["setup_fee_pence"] == 0
    assert "claim_token" not in out and "candidates" not in out
    assert tw.calls == []                       # asking never calls Twilio, never spends


def test_an_add_on_owner_can_choose_the_paid_set_up(db, tw):
    paid = request(db, B, setup="done_for_you")
    assert paid["in_plan"] is False and paid["setup"] == "done_for_you" and paid["setup_fee_pence"] == 5000
    with Session(db) as s:
        rn().cancel(s, biz(db, B), OWNER, now=NOW)
    free = request(db, B, setup="self")
    assert free["setup"] == "self" and free["setup_fee_pence"] == 0


def test_keep_my_number_needs_the_existing_number_and_gives_forwarding_steps(db, tw):
    with pytest.raises(refused()) as exc:
        request(db, mode="keep_existing")
    assert exc.value.status_code == 422
    out = request(db, mode="keep_existing", existing_number="0161 496 0000")
    assert out["existing_number"] == "+441614960000"
    with Session(db) as s:
        current = rn().current(s, biz(db, A))
    assert current["request"]["id"] == out["id"]
    providers = {g["provider"] for g in current["forwarding"]}
    assert {"BT", "Virgin Media", "EE", "O2", "Vodafone", "Three"} <= providers
    assert all(g["steps"] and g["help_url"].startswith("https://") for g in current["forwarding"])


@pytest.mark.parametrize("bad", [
    {"mode": "fax"}, {"setup": "maybe"}, {"legal_name": ""}, {"postcode": ""}, {"city": ""},
    {"address_line1": ""}, {"area_code": "abc"}, {"area_code": "01612345678901"}, {"area_code": "0300"},
    {"area_code": "07700"}, {"existing_number": "12345", "mode": "keep_existing"}, {"legal_name": "x" * 201},
])
def test_bad_details_are_refused(db, tw, bad):
    with pytest.raises(refused()) as exc:
        request(db, **bad)
    assert exc.value.status_code == 422


def test_an_owner_can_never_choose_the_number(db, tw):
    """R2: a request carries a type and an area, never a number."""
    out = request(db, phone_number=NUMBER, twilio_phone_number=NUMBER, chosen_number=NUMBER, candidates=[NUMBER])
    assert out["chosen_number"] is None and out["phone_number"] is None
    assert row(db, out["id"])["candidates"] == [] and assigned(db, A) is None


def test_one_open_request_at_a_time(db, tw):
    request(db)
    with pytest.raises(refused()) as exc:
        request(db)
    assert exc.value.status_code == 409


def test_a_business_with_a_number_cannot_request_another(db, tw):
    with Session(db) as s:
        rn().assign(s, A, NUMBER, "PN" + "1" * 32)
        s.commit()
    with pytest.raises(refused()) as exc:
        request(db)
    assert exc.value.status_code == 409


def test_a_request_needs_the_receptionist(db, tw):
    """R5: no receptionist in the plan or as an add-on."""
    with pytest.raises(refused()) as exc:
        request(db, C)
    assert exc.value.status_code == 403


def _set(db, bid, **change):
    with db.begin() as c:
        for col, value in change.items():
            c.execute(text(f"UPDATE businesses SET {col} = :v WHERE id = :b"), {"v": value, "b": bid})


@pytest.mark.parametrize("change", [{"is_active": False}, {"subscription_status": "canceled"},
                                    {"subscription_status": "unpaid"}])
def test_a_business_that_isnt_paying_cannot_request(db, tw, change):
    """R5: DECISION 3's resolver decides, as everywhere else."""
    _set(db, A, **change)
    with pytest.raises(refused()) as exc:
        request(db)
    assert exc.value.status_code == 403


def test_an_owner_can_cancel_before_anything_is_bought(db, tw):
    out = request(db)
    with Session(db) as s:
        rn().cancel(s, biz(db, A), OWNER, now=NOW)
    assert row(db, out["id"])["state"] == "cancelled"
    request(db)                                  # and ask again


def test_an_owner_cannot_cancel_once_buying_has_started(db, tw):
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    with Session(db) as s, pytest.raises(refused()) as exc:
        rn().cancel(s, biz(db, A), OWNER, now=NOW)
    assert exc.value.status_code == 409


# ------------------------------------------------------------ Mike's Check ---

def test_check_lists_local_numbers_in_the_area_with_twilio_s_price(db, tw):
    out = request(db)
    tw.available = ["+442071234567", NUMBER, "+441612345679", "+4416123", "+443001234567", NUMBER]
    found = prepare(db, out["id"])
    assert found["bundle_status"] == "twilio-approved"
    assert found["numbers"] == [NUMBER, "+441612345679"]        # 0161 only, local only, valid, once
    assert found["monthly_pence"] == 98                          # $1.15 at 0.85, rounded up
    assert row(db, out["id"])["candidates"] == [NUMBER, "+441612345679"]
    assert ("available_local", "161") in tw.calls and not tw.bought


def test_check_leaves_out_numbers_another_business_has(db, tw):
    with Session(db) as s:
        rn().assign(s, B, NUMBER, None)
        s.commit()
    out = request(db)
    assert prepare(db, out["id"])["numbers"] == ["+441612345679"]


def test_a_number_type_over_five_pounds_is_never_offered(db, tw):
    out = request(db)
    tw.price = (Decimal("6.00"), "USD")                          # £5.10
    with pytest.raises(refused()) as exc:
        prepare(db, out["id"])
    assert exc.value.status_code == 409 and "£5" in exc.value.detail and not tw.bought


def test_an_unknown_currency_is_refused_not_guessed(db, tw):
    out = request(db)
    tw.price = (Decimal("1.00"), "EUR")
    with pytest.raises(refused()) as exc:
        prepare(db, out["id"])
    assert exc.value.status_code == 503


def test_a_gbp_price_is_used_as_it_is(db, tw):
    out = request(db)
    tw.price = (Decimal("0.90"), "GBP")
    assert prepare(db, out["id"])["monthly_pence"] == 90


def test_a_bundle_not_yet_approved_waits(db, tw):
    out = request(db)
    tw.bundle = "pending-review"
    found = prepare(db, out["id"])
    assert found["bundle_status"] == "pending-review" and found["request"]["state"] == "waiting_bundle"
    assert found["numbers"] == []
    with pytest.raises(refused()) as exc:
        approve(db, out["id"], check=False)
    assert exc.value.status_code == 409 and "Check" in exc.value.detail
    assert not tw.bought
    tw.bundle = "twilio-approved"
    prepare(db, out["id"])
    assert approve(db, out["id"])["state"] == "live"


# ------------------------------------------------------------ Mike's Buy ---

def test_buy_configures_checks_assigns_and_tells_the_owner(db, tw):
    out = request(db)
    done = approve(db, out["id"])
    assert done["state"] == "live" and done["phone_number"] == NUMBER and done["number_sid"].startswith("PN")
    assert done["monthly_pence"] == 98 and done["bought_at"] and done["live_at"]
    assert tw.bought == [NUMBER]
    number = tw.owned[done["number_sid"]]
    assert number["voice_url"] == VOICE_URL and number["voice_method"] == "POST"
    assert number["friendly_name"] == rn().tag(out["id"])
    assert ("fetch", done["number_sid"]) in tw.calls          # R4: read back, not assumed
    phone, sid, enabled = assigned(db, A)
    assert (phone, sid) == (NUMBER, done["number_sid"]) and not enabled   # the owner switches it on
    assert done["decided_by"] == ADMIN
    assert tw.emails and NUMBER in tw.emails[0][1] and done["owner_told_at"]


def test_an_owner_without_a_mailbox_can_be_told_again(db, tw, monkeypatch):
    monkeypatch.setattr(rn(), "_send_owner_email", lambda *a: False)
    out = request(db)
    done = approve(db, out["id"])
    assert done["state"] == "live" and done["owner_told_at"] is None
    with Session(db) as s, pytest.raises(refused()) as exc:
        rn().admin_notify(s, out["id"], {}, ADMIN, now=NOW)
    assert exc.value.status_code == 502
    monkeypatch.setattr(rn(), "_send_owner_email", lambda *a: True)
    with Session(db) as s:
        assert rn().admin_notify(s, out["id"], {}, ADMIN, now=NOW)["owner_told_at"]


def test_after_buy_the_owner_sees_the_number(db, tw):
    out = request(db)
    approve(db, out["id"])
    with Session(db) as s:
        current = rn().current(s, biz(db, A))
    assert current["request"]["state"] == "live" and current["phone_number"] == NUMBER


@pytest.mark.parametrize("number,status", [("+15005550006", 422), ("0161", 422),
                                           ("+441612345670", 422),      # valid, but not one Check listed
                                           ("+442071234567", 422)])     # listed by Twilio, wrong area
def test_buy_only_a_number_check_listed(db, tw, number, status):
    out = request(db)
    prepare(db, out["id"])
    with pytest.raises(refused()) as exc:
        approve(db, out["id"], number=number)
    assert exc.value.status_code == status and not tw.bought


def test_buy_needs_check_first(db, tw):
    out = request(db)
    with pytest.raises(refused()) as exc:
        approve(db, out["id"], check=False)
    assert exc.value.status_code == 409 and not tw.bought


def test_buy_needs_the_public_url_for_the_webhook(db, tw, monkeypatch):
    out = request(db)
    prepare(db, out["id"])
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 503 and not tw.bought


def test_buy_on_a_stale_version_is_refused(db, tw):
    out = request(db)
    prepare(db, out["id"])
    with pytest.raises(refused()) as exc:
        approve(db, out["id"], version=out["version"])           # the version before Check
    assert exc.value.status_code == 409 and not tw.bought


def test_buy_rechecks_the_business_is_entitled(db, tw):
    """R5 at the moment of spending, not only when asked."""
    out = request(db)
    prepare(db, out["id"])
    _set(db, A, subscription_status="canceled")
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 403 and not tw.bought


def test_a_price_rise_after_check_stops_the_purchase_and_check_recovers(db, tw):
    """Review 2, finding 2: the request went to 'buying' and stayed there."""
    out = request(db)
    prepare(db, out["id"])
    tw.price = (Decimal("1.50"), "USD")
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 409 and "price" in exc.value.detail and not tw.bought
    assert row(db, out["id"])["state"] == "requested"
    assert prepare(db, out["id"])["monthly_pence"] == 128              # Check again: the new price
    assert approve(db, out["id"])["state"] == "live" and tw.bought == [NUMBER]


def test_decline_tells_the_owner_why(db, tw):
    out = request(db)
    with Session(db) as s:
        rn().admin_decline(s, out["id"], {"reason": "Please add your trading address.", "version": out["version"]},
                           ADMIN, now=NOW)
    with Session(db) as s:
        current = rn().current(s, biz(db, A))
    assert current["request"]["state"] == "declined"
    assert current["request"]["decline_reason"] == "Please add your trading address."
    assert not tw.bought


# ----------------------------------------------------------- R1: uniqueness ---

def test_a_number_taken_after_check_is_never_bought(db, tw):
    out = request(db)
    prepare(db, out["id"])
    with Session(db) as s:
        rn().assign(s, B, NUMBER, "PN" + "2" * 32)
        s.commit()
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 409 and not tw.bought


def test_the_database_refuses_a_number_for_two_businesses(db, monkeypatch):
    with Session(db) as s:
        rn().assign(s, B, NUMBER, "PN" + "2" * 32)
        s.commit()
    monkeypatch.setattr(rn(), "number_taken", lambda *a: False)     # the check missed it: the index doesn't
    with Session(db) as s, pytest.raises(refused()) as exc:
        rn().assign(s, A, NUMBER, "PN" + "3" * 32)
    assert exc.value.status_code == 409


def test_onboarding_s_own_write_that_clashes_is_a_409(db):
    """Codex review 1, finding 7: onboarding writes the number with its own SQL."""
    with Session(db) as s:
        rn().assign(s, B, NUMBER, None)
        s.commit()
    with Session(db) as s, pytest.raises(refused()) as exc:
        with rn().number_writes(s):
            s.execute(text("INSERT INTO receptionist_configs (id, business_id, twilio_phone_number) "
                           "VALUES ('x', :b, :n)"), {"b": A, "n": NUMBER})
    assert exc.value.status_code == 409


def test_the_existing_admin_assign_refuses_a_taken_number(db, monkeypatch):
    """The admin endpoint and onboarding step used the same unchecked write."""
    import asyncio
    import receptionist_api as api
    from fastapi import HTTPException
    from receptionist_api import AssignPhoneNumberRequest
    monkeypatch.setattr(api, "is_platform_admin_user", lambda *a: True)
    with Session(db) as s:
        rn().assign(s, B, NUMBER, "PN" + "2" * 32)
        s.commit()
    with Session(db) as s, pytest.raises(HTTPException) as exc:
        asyncio.run(api.admin_assign_phone_number(A, AssignPhoneNumberRequest(twilio_phone_number=NUMBER),
                                                  auth_ctx={"user_id": ADMIN}, session=s))
    assert exc.value.status_code == 409
    with Session(db) as s:                          # the same business may be given its own number again
        asyncio.run(api.admin_assign_phone_number(B, AssignPhoneNumberRequest(twilio_phone_number="+44 161 234 5678"),
                                                  auth_ctx={"user_id": ADMIN}, session=s))


# --------------------------------------------------- R3: bought at most once ---

def test_a_double_click_buys_one_number(db, tw):
    out = request(db)
    prepare(db, out["id"])
    version = row(db, out["id"])["version"]
    approve(db, out["id"], version=version)
    with pytest.raises(refused()) as exc:
        approve(db, out["id"], version=version)
    assert exc.value.status_code == 409 and tw.bought == [NUMBER]


def test_a_refusal_with_nothing_tagged_resets_and_can_be_tried_again(db, tw):
    out = request(db)
    tw.fail_buy = "definite"
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 422 and "no longer available" in exc.value.detail
    after = row(db, out["id"])
    assert after["state"] == "requested" and after["last_error"] and not tw.bought
    assert ("find_tagged", rn().tag(out["id"])) in tw.calls[tw.calls.index(("buy", NUMBER)):]   # checked after
    tw.fail_buy = None
    assert approve(db, out["id"], number="+441612345679")["state"] == "live"
    assert tw.bought == ["+441612345679"]


def test_a_refusal_after_twilio_bought_it_adopts_the_number(db, tw):
    """Review 1: a 4xx is not proof nothing was bought."""
    out = request(db)
    real_buy = tw.buy

    def bought_then_refused(**kw):
        real_buy(**kw)
        raise rn().TwilioDefinite("synthetic 400 after the purchase")
    tw.buy = bought_then_refused
    done = approve(db, out["id"])
    assert done["state"] == "live" and tw.bought == [NUMBER]


def test_a_timeout_after_twilio_bought_it_adopts_the_number_on_retry(db, tw):
    out = request(db)
    tw.fail_buy = "unknown_after_buying"
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 503
    assert row(db, out["id"])["state"] == "buying" and tw.bought == [NUMBER]
    tw.fail_buy = None
    with pytest.raises(refused()) as early:             # too soon: the first call may still land
        retry(db, out["id"], now=NOW + timedelta(minutes=1))
    assert early.value.status_code == 409
    done = retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    assert done["state"] == "live" and tw.bought == [NUMBER]             # adopted, not bought twice
    assert assigned(db, A)[0] == NUMBER


def test_a_timeout_before_twilio_bought_it_buys_once_on_retry(db, tw):
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.fail_buy = None
    done = retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    assert done["state"] == "live" and tw.bought == [NUMBER]


def test_a_crashed_buy_is_adopted_by_retry(db, tw, monkeypatch):
    """The process died between Twilio buying and our saving it."""
    out = request(db)

    def die(*a, **k):
        raise KeyboardInterrupt("process killed")
    with monkeypatch.context() as patched:
        patched.setattr(rn(), "_save_bought", die)
        with pytest.raises(KeyboardInterrupt):
            approve(db, out["id"])
    assert row(db, out["id"])["state"] == "buying" and tw.bought == [NUMBER]
    done = retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    assert done["state"] == "live" and tw.bought == [NUMBER]


@pytest.mark.parametrize("change", [{"subscription_status": "canceled"}, {"is_active": False},
                                    {"feature_flags": json.dumps({"receptionist": False})}])
def test_retry_rechecks_entitlement_before_buying(db, tw, change):
    """Codex review 1, finding 1: a suspended business reached 'live' through Retry."""
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.fail_buy = None
    _set(db, A, **change)
    with pytest.raises(refused()) as exc:
        retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    assert exc.value.status_code == 403 and not tw.bought and assigned(db, A) is None


def test_retry_never_replaces_a_number_given_in_the_meantime(db, tw):
    """Codex review 1, finding 1: Retry overwrote an assignment made by hand."""
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.fail_buy = None
    with Session(db) as s:
        rn().assign(s, A, "+441619999999", None)
        s.commit()
    with pytest.raises(refused()) as exc:
        retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    assert exc.value.status_code == 409 and not tw.bought and assigned(db, A)[0] == "+441619999999"


def test_retry_rechecks_the_bundle_before_buying(db, tw):
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.fail_buy, tw.bundle = None, "twilio-rejected"
    with pytest.raises(refused()) as exc:
        retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    assert exc.value.status_code == 409 and not tw.bought


def test_a_paused_attempt_never_buys_after_another_has_taken_over(db, tw):
    """Codex review 1, finding 2: the claim must fence the purchase, not only the save."""
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    paused = row(db, out["id"])["claim_token"]         # attempt A, which will 'resume' later
    tw.fail_buy = "definite"
    with pytest.raises(refused()):                     # attempt B: refused, nothing tagged: reset
        retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    current = row(db, out["id"])
    with Session(db) as s:
        rn().admin_decline(s, out["id"], {"reason": "Not now.", "version": current["version"]}, ADMIN, now=NOW)
    tw.fail_buy = None
    with Session(db) as s, pytest.raises(refused()) as exc:
        rn()._complete(s, out["id"], paused, tw, VOICE_URL, now=NOW + timedelta(minutes=20))
    assert exc.value.status_code == 409 and not tw.bought
    assert row(db, out["id"])["state"] == "declined"


def test_a_stale_attempt_cannot_save_over_a_newer_one(db, tw):
    out = request(db)
    tw.fail_buy = "unknown"
    with pytest.raises(refused()):
        approve(db, out["id"])
    old_token = row(db, out["id"])["claim_token"]
    tw.fail_buy = None
    retry(db, out["id"], now=NOW + rn().RETRY_AFTER + timedelta(seconds=1))
    with Session(db) as s:
        assert rn()._save_bought(s, out["id"], old_token, {"sid": "PN" + "f" * 32, "phone_number": "+441619999999"},
                                 now=NOW) is False
    assert row(db, out["id"])["phone_number"] == NUMBER


@pytest.mark.parametrize("change", ["suspended", "another_number", "bundle_rejected", "price_rose"])
def test_a_number_twilio_already_bought_is_adopted_whatever_changed(db, tw, change):
    """Review 2, finding 3: a changed prerequisite stopped Retry from even looking,
    leaving a number on Mike's bill that the app didn't know about."""
    out = request(db)
    tw.fail_buy = "unknown_after_buying"
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.fail_buy = None
    if change == "suspended":
        _set(db, A, is_active=False)
    elif change == "another_number":
        with Session(db) as s:
            rn().assign(s, A, "+441619999999", None)
            s.commit()
    elif change == "bundle_rejected":
        tw.bundle = "twilio-rejected"
    else:
        tw.price = (Decimal("4.00"), "USD")
    later = NOW + rn().RETRY_AFTER + timedelta(seconds=1)
    if change in ("bundle_rejected", "price_rose"):
        assert retry(db, out["id"], now=later)["state"] == "live"       # nothing stops assigning it
    else:
        with pytest.raises(refused()) as exc:
            retry(db, out["id"], now=later)
        assert exc.value.status_code in (403, 409)
        after = row(db, out["id"])
        assert after["state"] == "bought" and after["number_sid"]        # adopted and recorded
        with Session(db) as s:                                           # and flagged for release review
            review = {r["id"]: r for r in rn().admin_list(s)}[out["id"]]["review"]
        assert review and "releasing it in Twilio" in review
        if change == "another_number":
            assert "+441619999999" in review
    assert tw.bought == [NUMBER] and _cost(db) == 98


def test_the_final_assignment_never_replaces_a_number_given_meanwhile(db, tw, monkeypatch):
    """Review 2, finding 1: the 'no other number' check and the write are
    separate steps; the write itself must refuse to replace."""
    out = request(db)
    tw.wrong_voice = tw.stuck_voice = True
    with pytest.raises(refused()):
        approve(db, out["id"])                                    # bought, not set up
    tw.stuck_voice = False
    with Session(db) as s:                                        # Mike assigns another by hand meanwhile
        rn().assign(s, A, "+441619999999", None)
        s.commit()
    real = rn().current_number
    monkeypatch.setattr(rn(), "current_number", lambda s, b: None)    # the check ran before that
    with pytest.raises(refused()) as exc:
        retry(db, out["id"], now=NOW + timedelta(seconds=5))
    monkeypatch.setattr(rn(), "current_number", real)
    assert exc.value.status_code == 409 and assigned(db, A)[0] == "+441619999999"
    assert row(db, out["id"])["state"] == "bought"


# ------------------------------------------------- R4: the webhook is checked ---

def test_a_wrong_voice_url_is_corrected_then_checked(db, tw):
    out = request(db)
    tw.wrong_voice = True
    done = approve(db, out["id"])
    assert done["state"] == "live" and tw.owned[done["number_sid"]]["voice_url"] == VOICE_URL
    assert ("set_voice", done["number_sid"]) in tw.calls


def test_a_voice_url_that_wont_take_leaves_it_bought_not_assigned(db, tw):
    out = request(db)
    tw.wrong_voice = tw.stuck_voice = True
    with pytest.raises(refused()) as exc:
        approve(db, out["id"])
    assert exc.value.status_code == 502
    after = row(db, out["id"])
    assert after["state"] == "bought" and "not configured" in after["last_error"]
    assert assigned(db, A) is None and tw.bought == [NUMBER]
    tw.stuck_voice = False
    done = retry(db, out["id"], now=NOW + timedelta(seconds=5))     # a bought number can be retried at once
    assert done["state"] == "live" and tw.bought == [NUMBER]


def test_a_bought_number_is_never_assigned_to_a_business_that_stopped_paying(db, tw):
    out = request(db)
    tw.wrong_voice = tw.stuck_voice = True
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.stuck_voice = False
    _set(db, A, subscription_status="canceled")
    with pytest.raises(refused()) as exc:
        retry(db, out["id"], now=NOW + timedelta(seconds=5))
    assert exc.value.status_code == 403 and assigned(db, A) is None
    with Session(db) as s:
        listed = {r["id"]: r for r in rn().admin_list(s)}
    assert listed[out["id"]]["review"]               # R7: flagged for Mike, not released


# ---------------------------------------------------------- R6: the costs ---

def _cost(db):
    with Session(db) as s:
        from services import running_costs
        return {i["name"]: i["pence"] for i in running_costs.items(s, "2026-11")}.get(rn().COST_NAME)


def test_every_number_we_pay_for_is_a_running_cost(db, tw):
    first = request(db)
    approve(db, first["id"])
    assert _cost(db) == 98
    second = request(db, B)
    tw.wrong_voice = tw.stuck_voice = True
    with pytest.raises(refused()):
        approve(db, second["id"], number="+441612345679")
    assert row(db, second["id"])["state"] == "bought"
    assert _cost(db) == 196                          # bought but not set up still costs (review 1, finding 4)


def test_a_number_adopted_next_month_is_costed_from_the_month_it_was_bought(db, tw):
    """Review 2, finding 4."""
    out = request(db)
    tw.created = NOW                                   # Twilio bought it on 13 November
    tw.fail_buy = "unknown_after_buying"
    with pytest.raises(refused()):
        approve(db, out["id"])
    tw.fail_buy = None
    december = datetime(2026, 12, 2, 9, tzinfo=timezone.utc)
    retry(db, out["id"], now=december)
    assert row(db, out["id"])["bought_at"].startswith("2026-11-13")
    with Session(db) as s:
        from services import running_costs
        for period, expected in (("2026-11", 98), ("2026-12", 98)):
            got = {i["name"]: i["pence"] for i in running_costs.items(s, period)}.get(rn().COST_NAME)
            assert got == expected, period
    second = request(db, B)                            # bought in December: not in November's total
    tw.created = None
    approve(db, second["id"], number="+441612345679", now=december)
    with Session(db) as s:
        from services import running_costs
        nov = {i["name"]: i["pence"] for i in running_costs.items(s, "2026-11")}[rn().COST_NAME]
        dec = {i["name"]: i["pence"] for i in running_costs.items(s, "2026-12")}[rn().COST_NAME]
    assert (nov, dec) == (98, 196)


@pytest.mark.parametrize("bought,expected", [
    (datetime(2027, 6, 30, 23, 30, tzinfo=timezone.utc), "2027-07"),    # 00:30 on 1 July in Britain (BST)
    (datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc), "2026-12"),   # GMT: still 31 December
])
def test_costs_go_in_the_uk_calendar_month(db, tw, bought, expected):
    """Review 3, finding 1: the running-costs ledger is in UK months."""
    tw.created = bought
    out = request(db)
    prepare(db, out["id"])
    approve(db, out["id"], now=bought)
    with Session(db) as s:
        from services import running_costs
        got = {i["name"]: i["pence"] for i in running_costs.items(s, expected)}.get(rn().COST_NAME)
    assert got == 98


def test_a_purchase_is_recorded_even_when_a_cost_month_is_refused(db, tw, monkeypatch):
    from services import running_costs
    real = running_costs.set_item

    def refusing(session, period, *a, **k):
        if period == "2026-11":
            raise refused()(422, "synthetic: that month can't be edited")
        return real(session, period, *a, **k)
    monkeypatch.setattr(running_costs, "set_item", refusing)
    out = request(db)
    assert approve(db, out["id"])["state"] == "live"


def test_months_are_clamped_to_what_running_costs_accepts():
    from services import running_costs
    now = datetime(2027, 6, 30, 23, 30, tzinfo=timezone.utc)
    months = rn()._months(datetime(2024, 1, 1, tzinfo=timezone.utc), now)
    assert months[-1] == "2027-07" and len(months) == running_costs.MONTHS_BACK + 1 and months[0] == "2025-07"


def test_a_failed_purchase_costs_nothing(db, tw):
    out = request(db)
    tw.fail_buy = "definite"
    with pytest.raises(refused()):
        approve(db, out["id"])
    assert _cost(db) is None


# ------------------------------------------------------ R7: never released ---

def test_nothing_here_releases_a_number(db):
    source = (Path(__file__).parents[1] / "services" / "receptionist_numbers.py").read_text()
    assert ".delete(" not in source and "incoming_phone_numbers(sid).delete" not in source


def test_a_live_number_of_a_business_that_stopped_paying_is_listed_for_review(db, tw):
    out = request(db)
    approve(db, out["id"])
    with Session(db) as s:
        assert {r["id"]: r for r in rn().admin_list(s)}[out["id"]]["review"] is None
    _set(db, A, is_active=False)
    with Session(db) as s:
        listed = {r["id"]: r for r in rn().admin_list(s)}[out["id"]]
    assert listed["review"] and "releasing it in Twilio" in listed["review"]
    assert listed["business_name"] and assigned(db, A)[0] == NUMBER      # flagged, nothing changed


# ----------------------------------------- the event loop is never held ---

@pytest.mark.parametrize("endpoint,service", [
    ("admin_prepare_number_request", "admin_prepare"), ("admin_approve_number_request", "admin_approve"),
    ("admin_retry_number_request", "admin_retry"), ("admin_notify_number_request", "admin_notify")])
def test_twilio_work_runs_off_the_event_loop(monkeypatch, endpoint, service):
    """Review 2, finding 5: a slow Twilio call must not stall live receptionist calls."""
    import asyncio
    import time
    import receptionist_api as api
    monkeypatch.setattr(api, "_require_platform_admin", lambda *a: None)
    monkeypatch.setattr(rn(), service, lambda *a, **k: time.sleep(0.4) or {"ok": True})

    async def scenario():
        delays = []

        async def heartbeat():
            for _ in range(20):
                start = time.monotonic()
                await asyncio.sleep(0.01)
                delays.append(time.monotonic() - start)
        beating = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.03)                      # the heartbeat is running before the request starts
        out = await getattr(api, endpoint)("r", {}, auth_ctx={"user_id": ADMIN}, session=None)
        await beating
        return out, max(delays)
    out, worst = asyncio.run(scenario())
    assert out == {"ok": True} and worst < 0.2


# ----------------------------------------------- Aria can read it (North Star) ---

def test_aria_reads_the_owner_s_own_number_request(db, tw, monkeypatch):
    """Review 2, finding 6 (AGENTS.md North Star rule 3): what the app records, Aria can read."""
    import assistant_tools
    monkeypatch.setattr(assistant_tools, "engine", db)
    assert "get_receptionist_number" in {t["function"]["name"] for t in assistant_tools.TOOL_DEFINITIONS}
    out = request(db, mode="keep_existing", existing_number="0161 496 0000")
    seen = assistant_tools.execute_tool("get_receptionist_number", {}, A)
    assert seen["request"]["id"] == out["id"] and seen["request"]["state"] == "requested"
    assert seen["phone_number"] is None and "forwarding" in seen
    assert "claim_token" not in seen["request"] and "candidates" not in seen["request"]
    approve(db, out["id"])
    assert assistant_tools.execute_tool("get_receptionist_number", {}, A)["phone_number"] == NUMBER
    other = assistant_tools.execute_tool("get_receptionist_number", {"business_id": A}, B)   # tenant-scoped
    assert other["request"] is None and other["phone_number"] is None


# ------------------------------------------------- R8: the real wrapper ---

def test_the_real_wrapper_asks_twilio_for_what_rcp1_needs():
    log = []

    class Number(SimpleNamespace):
        pass
    bought = Number(sid="PN" + "1" * 32, phone_number=NUMBER, friendly_name="t", voice_url=VOICE_URL, voice_method="POST")

    class Client:
        def __init__(self):
            self.available_phone_numbers = lambda country: SimpleNamespace(local=SimpleNamespace(
                list=lambda **kw: log.append(("search", country, kw)) or [Number(phone_number=NUMBER)]))
            self.incoming_phone_numbers = SimpleNamespace(
                create=lambda **kw: log.append(("create", kw)) or bought,
                list=lambda **kw: log.append(("list", kw)) or [bought])
            self.numbers = SimpleNamespace(v2=SimpleNamespace(regulatory_compliance=SimpleNamespace(
                bundles=lambda sid: SimpleNamespace(fetch=lambda: log.append(("bundle", sid)) or
                                                    SimpleNamespace(status="twilio-approved")))))
            self.pricing = SimpleNamespace(v1=SimpleNamespace(phone_numbers=SimpleNamespace(
                countries=lambda iso: SimpleNamespace(fetch=lambda: log.append(("price", iso)) or SimpleNamespace(
                    price_unit="USD", phone_number_prices=[{"number_type": "national", "current_price": "2.00"},
                                                           {"number_type": "local", "current_price": "1.15"}])))))
    wrapper = rn().TwilioNumbers(Client())
    assert wrapper.available_local("161") == [NUMBER]
    assert wrapper.bundle_status(BUNDLE) == "twilio-approved"
    assert wrapper.local_price() == (Decimal("1.15"), "USD")
    assert wrapper.find_tagged("bh-rcp-x")[0]["sid"] == bought.sid
    wrapper.buy(phone_number=NUMBER, tag="bh-rcp-x", voice_url=VOICE_URL, address_sid=ADDRESS, bundle_sid=BUNDLE)
    search = next(e for e in log if e[0] == "search")
    assert search[1] == "GB" and search[2] == {"contains": "+44161", "voice_enabled": True, "limit": 30}
    create = next(e for e in log if e[0] == "create")[1]
    assert create == {"phone_number": NUMBER, "friendly_name": "bh-rcp-x", "voice_url": VOICE_URL,
                      "voice_method": "POST", "address_sid": ADDRESS, "bundle_sid": BUNDLE}
    assert next(e for e in log if e[0] == "list")[1] == {"friendly_name": "bh-rcp-x"}
    assert ("price", "GB") in log


@pytest.mark.parametrize("status,kind", [(400, "TwilioDefinite"), (404, "TwilioDefinite"), (429, "TwilioUnknown"),
                                         (500, "TwilioUnknown"), (503, "TwilioUnknown")])
def test_twilio_errors_are_sorted_into_refused_and_unknown(status, kind):
    from twilio.base.exceptions import TwilioRestException

    class Client:
        incoming_phone_numbers = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(
            TwilioRestException(status, "https://api.twilio.com", msg="synthetic")))
    with pytest.raises(getattr(rn(), kind)):
        rn().TwilioNumbers(Client()).buy(phone_number=NUMBER, tag="t", voice_url=VOICE_URL,
                                         address_sid=ADDRESS, bundle_sid=BUNDLE)


def test_a_network_failure_is_unknown():
    class Client:
        incoming_phone_numbers = SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(TimeoutError("read")))
    with pytest.raises(rn().TwilioUnknown):
        rn().TwilioNumbers(Client()).buy(phone_number=NUMBER, tag="t", voice_url=VOICE_URL,
                                         address_sid=ADDRESS, bundle_sid=BUNDLE)


def test_without_migration_043_the_owner_is_told_it_is_not_ready(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "bare.sqlite"))
    with Session(engine) as s:
        assert rn().ready(s) is False


# ------------------------------------------- Mike hears about a new request (RCP-2) ---

def test_a_new_request_emails_mike_with_what_he_needs(db, tw, monkeypatch):
    """Mike, 14 Nov 2026: without an alert he'd only know if the customer told him."""
    from services import profit_guard
    sent = []
    monkeypatch.setattr(profit_guard, "send_alert", lambda subject, body: sent.append((subject, body)))
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.invalid")
    out = request(db, B, mode="keep_existing", existing_number="0161 496 0000", setup="done_for_you")
    rn().alert_new_request(out, "Multi Skilled Contractors LTD")
    (subject, body), = sent
    assert "Multi Skilled Contractors LTD" in subject and "receptionist number" in subject.lower()
    assert "https://app.example.invalid/admin" in body
    assert "+441614960000" in body and "0161" in body and "£50" in body
    assert "Regulatory Compliance" in body              # what to do next


def test_the_alert_never_breaks_the_request(db, tw, monkeypatch):
    from services import profit_guard

    def broken(*a):
        raise RuntimeError("mail down")
    monkeypatch.setattr(profit_guard, "send_alert", broken)
    out = request(db)
    rn().alert_new_request(out, "Biz")                 # logged, not raised
    assert row(db, out["id"])["state"] == "requested"


def test_the_endpoint_sends_the_alert_after_the_request_is_saved(monkeypatch):
    """In the background, after the response: never on the owner's click, never for a refusal."""
    import asyncio
    from fastapi import BackgroundTasks, HTTPException
    import receptionist_api as api
    monkeypatch.setattr(api, "assert_feature_access", lambda *a: None)
    saved = {"id": "r1", "state": "requested"}
    monkeypatch.setattr(rn(), "request_number", lambda *a, **k: saved)
    tasks = BackgroundTasks()
    business = SimpleNamespace(id=A, name="Biz A")
    out = asyncio.run(api.create_number_request(tasks, {}, auth_ctx={"user_id": OWNER}, business=business, session=None))
    assert out is saved
    assert [(t.func, t.args) for t in tasks.tasks] == [(rn().alert_new_request, (saved, "Biz A"))]

    def refuse(*a, **k):
        raise refused()(409, "already")
    monkeypatch.setattr(rn(), "request_number", refuse)
    tasks = BackgroundTasks()
    import pytest as _pytest
    with _pytest.raises(HTTPException):
        asyncio.run(api.create_number_request(tasks, {}, auth_ctx={"user_id": OWNER}, business=business, session=None))
    assert tasks.tasks == []


def test_fastapi_runs_the_alert_for_a_real_request(monkeypatch):
    """Through the real router: the alert runs after the 201 is sent."""
    import asyncio
    import httpx
    from fastapi import FastAPI
    import auth
    import db as dbmod
    import dependencies
    import receptionist_api as api
    from rate_limiting import limiter
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(api, "assert_feature_access", lambda *a: None)
    monkeypatch.setattr(rn(), "request_number", lambda *a, **k: {"id": "r1", "state": "requested"})
    alerted = []
    monkeypatch.setattr(rn(), "alert_new_request", lambda r, name: alerted.append((r["id"], name)))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides = {
        auth.get_user_business_context: lambda: {"user_id": OWNER, "business_id": A},
        dependencies.get_current_user_business: lambda: SimpleNamespace(id=A, name="Biz A"),
        dbmod.get_session: lambda: None,
    }

    async def post():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post("/v1/receptionist/number-request", json={"mode": "new_local"})
    response = asyncio.run(post())
    assert response.status_code == 201 and alerted == [("r1", "Biz A")]


def test_the_alert_never_links_to_the_api_host(db, tw, monkeypatch):
    """Codex RCP-2 review, nit: PUBLIC_BASE_URL is the API, not the dashboard."""
    from services import profit_guard
    sent = []
    monkeypatch.setattr(profit_guard, "send_alert", lambda subject, body: sent.append(body))
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    rn().alert_new_request(request(db), "Biz")
    assert "api.example.invalid" not in sent[0] and "Business Hero admin dashboard" in sent[0]
    monkeypatch.setenv("FRONTEND_URL", "https://front.example.invalid/")
    with Session(db) as s:
        r = rn().admin_list(s)[0]
    rn().alert_new_request(r, "Biz")
    assert "https://front.example.invalid/admin" in sent[1]
