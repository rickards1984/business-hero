"""RCP-1 — receptionist phone numbers, requested in the app and set up by Mike's
Approve (docs/RCP-1-TICKET.md). RED: it spends money with Twilio, and it
decides which business answers a phone line.

The owner asks for a number TYPE and AREA, never a number (R2). Mike's side:
  * Check (prepare) saves the regulatory bundle, checks it, and lists local
    numbers in the area with Twilio's own monthly price. Spends nothing.
  * Approve claims the request for one attempt, then completes it.
  * Retry completes an attempt that didn't finish, never buying twice.

Completing an attempt (_complete):
  1. Before any purchase, every time (Codex review 1, finding 1): the business
     is entitled and paying (R5), has no other number (R1), the bundle is
     approved, and the number is one Check listed, at a price under the cap.
  2. The purchase is FENCED (finding 2): the attempt holds a lock on the
     request row from just before it asks Twilio until the result is saved.
     Another attempt, a decline or a cancel waits on that lock, and then finds
     the request moved on. A crash releases the lock with the request still
     'buying', and Retry looks for the tagged number before buying.
  3. Twilio already holding a number tagged for this request (FriendlyName =
     tag(request)) is adopted, not bought again (R3).
  4. The number's webhook is read back, corrected once and checked (R4).
  5. It is assigned only if the business is still entitled and has no other
     number.

A number is never released here (R7); numbers of businesses that stop paying
are listed for Mike to review. Twilio is called only from the backend with the
existing credentials (R8).

Twilio outcomes: UNKNOWN (timeout, 5xx, 429) keeps the attempt 'buying', and
Retry waits RETRY_AFTER so a late purchase is visible before it looks. A 4xx is
treated as a refusal only after checking that Twilio holds no number tagged for
this request (finding 5 of review 1 on the 4xx classification).
"""
import json
import logging
import math
from contextlib import contextmanager
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from services.aria_actions import ActionRefused

logger = logging.getLogger(__name__)

TABLE = "receptionist_number_requests"
OPEN = ("requested", "waiting_bundle", "buying", "bought")
STARTABLE = ("requested", "waiting_bundle")
OWNED = ("bought", "live")             # a number we pay for
SETUP_FEE_PENCE = 5000                 # Mike, 13 Nov 2026: £50, add-on customers only
MAX_MONTHLY_PENCE = 500                # Mike, 13 Nov 2026: no number type over £5 a month
GBP_PER_USD_DEFAULT = "0.85"           # deliberately high, so a cost is never understated
RETRY_AFTER = timedelta(minutes=5)     # well past the Twilio client timeout below
TWILIO_TIMEOUT_SECONDS = 30
SEARCH_LIMIT = 30
COST_NAME = "Receptionist numbers"
WEBHOOK_PATH = "/v1/receptionist/incoming-call"
INDEX_NAME = "uq_receptionist_configs_twilio_phone_number"

UK_NUMBER = re.compile(r"^\+44[1-9][0-9]{8,9}$")
GEOGRAPHIC = re.compile(r"^\+44[12][0-9]{8,9}$")      # 01 and 02: local numbers (Mike's decision 4)
AREA = re.compile(r"^0?([12][0-9]{1,4})$")
SID = {"bundle": re.compile(r"^BU[0-9a-f]{32}$"), "address": re.compile(r"^AD[0-9a-f]{32}$")}
LIMITS = {"legal_name": 200, "address_line1": 200, "address_line2": 200, "city": 100, "postcode": 12}

# "Keep my number": forward the existing line to the new number. Standard UK
# call-diversion codes; each provider's own help page has the details and any
# charge for diverted calls.
FORWARDING = [
    {"provider": "BT", "kind": "landline", "help_url": "https://www.bt.com/help",
     "steps": ["All calls: dial *21*{number}#", "When you don't answer: dial *61*{number}#",
               "When you're busy: dial *67*{number}#", "To stop: dial #21#, #61# or #67#"]},
    {"provider": "Virgin Media", "kind": "landline", "help_url": "https://www.virginmedia.com/help",
     "steps": ["All calls: dial *21*{number}#", "When you don't answer: dial *61*{number}#",
               "To stop: dial #21# or #61#"]},
    {"provider": "EE", "kind": "mobile", "help_url": "https://ee.co.uk/help",
     "steps": ["All calls: dial **21*{number}#", "When you don't answer: dial **61*{number}#",
               "When you're busy: dial **67*{number}#", "To stop: dial ##002#"]},
    {"provider": "O2", "kind": "mobile", "help_url": "https://www.o2.co.uk/help",
     "steps": ["All calls: dial **21*{number}#", "When you don't answer: dial **61*{number}#",
               "When you're busy: dial **67*{number}#", "To stop: dial ##002#"]},
    {"provider": "Vodafone", "kind": "mobile", "help_url": "https://www.vodafone.co.uk/help",
     "steps": ["All calls: dial **21*{number}#", "When you don't answer: dial **61*{number}#",
               "When you're busy: dial **67*{number}#", "To stop: dial ##002#"]},
    {"provider": "Three", "kind": "mobile", "help_url": "https://www.three.co.uk/support",
     "steps": ["All calls: dial **21*{number}#", "When you don't answer: dial **61*{number}#",
               "When you're busy: dial **67*{number}#", "To stop: dial ##002#"]},
    {"provider": "Office phone system (VoIP)", "kind": "voip", "help_url": "https://www.ofcom.org.uk/phones-and-broadband",
     "steps": ["In your phone system's admin page, find call forwarding or diversion",
               "Forward to {number}, for all calls or after a few rings"]},
]


def refuse(status: int, detail: str):
    raise ActionRefused(status, detail)


class TwilioDefinite(Exception):
    """Twilio answered with a refusal (4xx, not 429)."""


class TwilioUnknown(Exception):
    """No answer we can trust: it may have happened."""


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _as_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def tag(request_id: str) -> str:
    return f"bh-rcp-{request_id}"


def uk_number(value) -> Optional[str]:
    """'0161 496 0000' or '+44 161 496 0000' -> '+441614960000'; None if not a UK number."""
    if not isinstance(value, str):
        return None
    digits = re.sub(r"[\s()-]", "", value)
    if digits.startswith("0044"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = "+44" + digits[1:]
    return digits if UK_NUMBER.match(digits) else None


def pence_for(price: Decimal, unit: str) -> int:
    """Twilio's monthly price in whole pence, rounded up. Refuses an unknown currency."""
    unit = (unit or "").upper()
    if unit == "GBP":
        rate = Decimal(1)
    elif unit == "USD":
        try:
            rate = Decimal(os.environ.get("RECEPTIONIST_GBP_PER_USD", GBP_PER_USD_DEFAULT))
        except InvalidOperation:
            rate = Decimal(GBP_PER_USD_DEFAULT)
    else:
        refuse(503, f"Twilio prices this account in {unit or 'an unknown currency'}; set up a conversion first.")
    return int(math.ceil(price * rate * 100))


# ----------------------------------------------------------------- Twilio ---

class TwilioNumbers:
    """The only code that talks to Twilio's number API."""

    def __init__(self, client):
        self.client = client

    @staticmethod
    def _call(fn):
        try:
            return fn()
        except Exception as exc:                        # sorted, never swallowed
            status = getattr(exc, "status", None)
            if isinstance(status, int) and 400 <= status < 500 and status != 429:
                raise TwilioDefinite(getattr(exc, "msg", None) or str(exc)) from exc
            raise TwilioUnknown(str(exc) or type(exc).__name__) from exc

    @staticmethod
    def _number(n) -> dict:
        return {"sid": n.sid, "phone_number": n.phone_number, "friendly_name": getattr(n, "friendly_name", None),
                "voice_url": getattr(n, "voice_url", None), "voice_method": getattr(n, "voice_method", None),
                "date_created": getattr(n, "date_created", None)}

    def bundle_status(self, sid: str) -> str:
        return str(self._call(lambda: self.client.numbers.v2.regulatory_compliance.bundles(sid).fetch()).status)

    def local_price(self) -> tuple:
        """(monthly price, currency) for a GB local number, from Twilio's price list."""
        country = self._call(lambda: self.client.pricing.v1.phone_numbers.countries("GB").fetch())
        for p in country.phone_number_prices or []:
            if (p.get("number_type") or "").lower() == "local":
                return Decimal(str(p.get("current_price") or p.get("base_price"))), str(country.price_unit)
        raise TwilioDefinite("Twilio has no price for GB local numbers.")

    def available_local(self, area_digits: str, limit: int = SEARCH_LIMIT) -> list:
        kwargs = {"voice_enabled": True, "limit": limit}
        if area_digits:
            kwargs["contains"] = f"+44{area_digits}"            # '+' anchors the match at the start
        return [n.phone_number for n in self._call(
            lambda: self.client.available_phone_numbers("GB").local.list(**kwargs))]

    def find_tagged(self, tag_: str) -> list:
        return [self._number(n) for n in self._call(lambda: self.client.incoming_phone_numbers.list(friendly_name=tag_))]

    def buy(self, *, phone_number, tag, voice_url, address_sid, bundle_sid) -> dict:
        return self._number(self._call(lambda: self.client.incoming_phone_numbers.create(
            phone_number=phone_number, friendly_name=tag, voice_url=voice_url, voice_method="POST",
            address_sid=address_sid, bundle_sid=bundle_sid)))

    def fetch(self, sid: str) -> dict:
        return self._number(self._call(lambda: self.client.incoming_phone_numbers(sid).fetch()))

    def set_voice(self, sid: str, voice_url: str) -> dict:
        return self._number(self._call(lambda: self.client.incoming_phone_numbers(sid).update(
            voice_url=voice_url, voice_method="POST")))


def twilio() -> TwilioNumbers:
    sid, token = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        refuse(503, "Twilio isn't configured on the server (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN).")
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client
    return TwilioNumbers(Client(sid, token, http_client=TwilioHttpClient(timeout=TWILIO_TIMEOUT_SECONDS)))


def voice_url() -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base.startswith("https://"):
        refuse(503, "PUBLIC_BASE_URL isn't set to the API's https address, so the number's calls couldn't reach us.")
    return base + WEBHOOK_PATH


def _verified_price(tw: TwilioNumbers) -> int:
    try:
        price, unit = tw.local_price()
    except (TwilioDefinite, TwilioUnknown) as exc:
        refuse(503, f"Couldn't get Twilio's price for a local number, so nothing was bought: {exc}")
    pence = pence_for(price, unit)
    if pence > MAX_MONTHLY_PENCE:
        refuse(409, f"Twilio charges about £{pence / 100:.2f} a month for a local number, over the £5 limit. "
                    "Nothing was bought.")
    return pence


# --------------------------------------------------------------- database ---

_READY: dict = {}


def ready(session) -> bool:
    """Whether migration 043 has been applied (checked once per database)."""
    try:
        key = str(session.get_bind().url)
    except AttributeError:
        key = None
    if key is None or key not in _READY:
        from sqlalchemy import inspect as _inspect
        try:
            found = _inspect(session.connection()).has_table(TABLE)
        except Exception:
            return False
        if key is None:
            return found
        _READY[key] = found
    return _READY[key]


def _require_ready(session):
    if not ready(session):
        refuse(503, "Phone number requests aren't switched on yet. Please contact support.")


COLUMNS = ("id", "business_id", "created_at", "updated_at", "requested_by", "state", "version", "mode",
           "area_code", "existing_number", "legal_name", "address_line1", "address_line2", "city", "postcode",
           "setup", "in_plan", "setup_fee_pence", "bundle_sid", "address_sid", "candidates", "chosen_number",
           "monthly_pence", "number_sid", "phone_number", "claim_token", "claimed_at", "last_error", "decided_by",
           "decided_at", "decline_reason", "bought_at", "live_at", "owner_told_at")
OWNER_HIDDEN = ("claim_token", "claimed_at", "requested_by", "decided_by", "bundle_sid", "address_sid", "number_sid",
                "candidates", "last_error", "monthly_pence")


def _row(session, rid: str) -> Optional[dict]:
    r = session.execute(text(f"SELECT {', '.join(COLUMNS)} FROM {TABLE} WHERE id = :i"), {"i": str(rid)}).first()
    return _shape(r) if r else None


def _shape(r) -> dict:
    out = dict(zip(COLUMNS, r))
    for k in ("id", "business_id", "requested_by", "decided_by"):
        out[k] = str(out[k]) if out[k] is not None else None
    for k in ("created_at", "updated_at", "claimed_at", "decided_at", "bought_at", "live_at", "owner_told_at"):
        out[k] = _iso(_as_dt(out[k])) if out[k] is not None else None
    for k in ("version", "setup_fee_pence", "monthly_pence"):
        out[k] = int(out[k]) if out[k] is not None else None
    out["in_plan"] = bool(out["in_plan"])
    out["candidates"] = json.loads(out["candidates"]) if out["candidates"] else []
    return out


def _for_owner(r: Optional[dict]) -> Optional[dict]:
    return None if r is None else {k: v for k, v in r.items() if k not in OWNER_HIDDEN}


def _business(session, bid: str):
    """The business as the entitlement resolver reads it (auth._is_feature_enabled)."""
    from types import SimpleNamespace
    entitlement_row = session.execute(text(
        "SELECT id, name, plan_tier, feature_flags, subscription_status, is_active, trial_ends_at "
        "FROM businesses WHERE id = :b"), {"b": str(bid)}).first()
    if entitlement_row is None:
        refuse(404, "Business not found.")
    business_entitlement = SimpleNamespace(**dict(entitlement_row._mapping))
    if isinstance(business_entitlement.feature_flags, str):        # SQLite
        business_entitlement.feature_flags = json.loads(business_entitlement.feature_flags or "{}")
    business_entitlement.id = str(business_entitlement.id)
    business_entitlement.is_active = bool(business_entitlement.is_active)
    business_entitlement.trial_ends_at = _as_dt(business_entitlement.trial_ends_at)
    return business_entitlement


def _entitled(business) -> bool:
    """R5: the receptionist (plan or add-on) and a paying business, by DECISION 3's resolver."""
    from auth import ACCESS_FULL, _is_feature_enabled, resolve_access_level
    return resolve_access_level(business) == ACCESS_FULL and _is_feature_enabled(business, "receptionist")


def _in_plan(business) -> bool:
    from auth import _plan_feature_defaults
    return bool(_plan_feature_defaults(business.plan_tier).get("receptionist", False))


def current_number(session, bid: str) -> Optional[str]:
    return session.execute(text("SELECT twilio_phone_number FROM receptionist_configs WHERE business_id = :b"),
                           {"b": str(bid)}).scalar()


def number_taken(session, number: str, bid: str) -> bool:
    """R1: is this number another business's?"""
    return session.execute(text("SELECT 1 FROM receptionist_configs WHERE twilio_phone_number = :n "
                                "AND business_id <> :b"), {"n": number, "b": str(bid)}).first() is not None


def is_number_clash(exc: IntegrityError) -> bool:
    return INDEX_NAME in str(getattr(exc, "orig", exc)) or "twilio_phone_number" in str(getattr(exc, "orig", exc))


@contextmanager
def number_writes(session):
    """Around a write that may give a business a number (onboarding's own SQL):
    a clash with another business (migration 043's index) is a 409, never a
    500 (R1). PostgreSQL and SQLite both raise at the write itself."""
    try:
        yield
    except IntegrityError as exc:
        session.rollback()
        if is_number_clash(exc):
            refuse(409, "That number belongs to another business.")
        raise


def assign(session, bid: str, number: str, number_sid: Optional[str], *, replace: bool = True) -> None:
    """Give a business its number. Refuses (409) a number another business has.
    The database's unique index (migration 043) is the guarantee; the check
    first gives a clear message. Doesn't commit.

    replace=False (an Approve or Retry finishing): the write itself refuses if
    the business has, or is given meanwhile, a different number (review 2,
    finding 1): the UPDATE only matches an empty or identical number, and
    receptionist_configs.business_id is unique, so a row made meanwhile
    can't be overwritten either. replace=True is Mike's manual assign."""
    if number_taken(session, number, bid):
        refuse(409, "That number belongs to another business.")
    at = _iso(datetime.now(timezone.utc))
    params = {"n": number, "s": number_sid, "at": at, "b": str(bid)}
    try:
        if replace:
            updated = session.execute(text(
                "UPDATE receptionist_configs SET twilio_phone_number = :n, twilio_phone_sid = :s, updated_at = :at "
                "WHERE business_id = :b"), params).rowcount
        else:
            updated = session.execute(text(
                "UPDATE receptionist_configs SET twilio_phone_number = :n, twilio_phone_sid = :s, updated_at = :at "
                "WHERE business_id = :b AND (twilio_phone_number IS NULL OR twilio_phone_number = :n)"),
                params).rowcount
            if not updated and session.execute(text(
                    "SELECT 1 FROM receptionist_configs WHERE business_id = :b"), params).first():
                session.rollback()
                refuse(409, "This business has been given another number; this one wasn't assigned.")
        if not updated:
            session.execute(text(
                "INSERT INTO receptionist_configs (id, business_id, twilio_phone_number, twilio_phone_sid, "
                "created_at, updated_at) VALUES (:i, :b, :n, :s, :at, :at)"), dict(params, i=str(uuid.uuid4())))
    except IntegrityError as exc:
        session.rollback()          # the whole transaction: callers write nothing before this
        if is_number_clash(exc):
            refuse(409, "That number belongs to another business.")
        if not replace:             # the business's row was made meanwhile
            refuse(409, "This business's receptionist settings changed meanwhile; this number wasn't assigned.")
        raise


# -------------------------------------------------------------- the owner ---

def _clean(payload: dict, key: str, required: bool) -> Optional[str]:
    value = payload.get(key)
    value = value.strip() if isinstance(value, str) else None
    if not value:
        if required:
            refuse(422, f"Please fill in {key.replace('_', ' ')}.")
        return None
    if len(value) > LIMITS[key]:
        refuse(422, f"{key.replace('_', ' ').capitalize()} is too long.")
    return value


def _in(states) -> str:
    return ", ".join(f"'{s}'" for s in states)


def request_number(session, business, user_id: str, payload: dict, *, now: Optional[datetime] = None) -> dict:
    _require_ready(session)
    now = _now(now)
    bid = str(business.id)
    if not _entitled(business):
        refuse(403, "Your plan doesn't include the AI receptionist.")
    if not isinstance(payload, dict):
        refuse(422, "Send the request's details.")
    mode = payload.get("mode")
    if mode not in ("new_local", "keep_existing"):
        refuse(422, "Choose a new local number, or keep your existing number.")
    area = payload.get("area_code")
    area_digits = None
    if area not in (None, ""):
        m = AREA.match(re.sub(r"\s", "", str(area)))
        if not m:
            refuse(422, "A local area code looks like 0161 or 020.")
        area_digits = m.group(1)
    existing = None
    if mode == "keep_existing":
        existing = uk_number(payload.get("existing_number"))
        if not existing:
            refuse(422, "Enter the UK number your callers ring now, for example 0161 496 0000.")
    in_plan = _in_plan(business)
    setup = payload.get("setup")
    if setup not in ("self", "done_for_you"):
        refuse(422, "Choose who sets the receptionist up.")
    if in_plan:
        setup = "done_for_you"                # covered by the plan's setup
    fee = SETUP_FEE_PENCE if setup == "done_for_you" and not in_plan else 0
    fields = {k: _clean(payload, k, k != "address_line2") for k in LIMITS}
    if current_number(session, bid):
        refuse(409, "Your receptionist already has a number.")
    if session.execute(text(f"SELECT 1 FROM {TABLE} WHERE business_id = :b AND state IN ({_in(OPEN)})"),
                       {"b": bid}).first():
        refuse(409, "You already have a number request in progress.")
    rid = str(uuid.uuid4())
    try:
        session.execute(text(
            f"INSERT INTO {TABLE} (id, business_id, created_at, updated_at, requested_by, state, version, mode, "
            "area_code, existing_number, legal_name, address_line1, address_line2, city, postcode, setup, "
            "in_plan, setup_fee_pence) VALUES (:id, :b, :at, :at, :u, 'requested', 1, :mode, :area, :existing, "
            ":legal_name, :address_line1, :address_line2, :city, :postcode, :setup, :in_plan, :fee)"),
            {"id": rid, "b": bid, "at": _iso(now), "u": str(user_id), "mode": mode,
             "area": ("0" + area_digits) if area_digits else None, "existing": existing, "setup": setup,
             "in_plan": in_plan, "fee": fee, **fields})
        session.commit()
    except IntegrityError:            # the open-request index: two requests at once
        session.rollback()
        refuse(409, "You already have a number request in progress.")
    logger.info("[RCP-1] business %s requested a %s number (setup %s)", bid, mode, setup)
    return _for_owner(_row(session, rid))


def current(session, business) -> dict:
    """What the receptionist settings page shows: the latest request, the
    number if there is one, and the forwarding guides."""
    bid = str(business.id)
    out = {"ready": ready(session), "phone_number": current_number(session, bid),
           "in_plan": _in_plan(business), "setup_fee_pence": SETUP_FEE_PENCE, "forwarding": FORWARDING,
           "request": None}
    if out["ready"]:
        r = session.execute(text(f"SELECT {', '.join(COLUMNS)} FROM {TABLE} WHERE business_id = :b "
                                 "ORDER BY created_at DESC LIMIT 1"), {"b": bid}).first()
        out["request"] = _for_owner(_shape(r)) if r else None
    return out


def cancel(session, business, user_id: str, *, now: Optional[datetime] = None) -> dict:
    _require_ready(session)
    bid = str(business.id)
    r = session.execute(text(f"SELECT id, state FROM {TABLE} WHERE business_id = :b AND state IN ({_in(OPEN)})"),
                        {"b": bid}).first()
    if not r:
        refuse(404, "There's no request to cancel.")
    done = session.execute(text(f"UPDATE {TABLE} SET state = 'cancelled', version = version + 1, updated_at = :at "
                                f"WHERE id = :i AND state IN ({_in(STARTABLE)})"),
                           {"i": str(r[0]), "at": _iso(_now(now))}).rowcount
    if not done:
        session.rollback()
        refuse(409, "Your number is being set up, so this request can't be cancelled now.")
    session.commit()
    return _for_owner(_row(session, str(r[0])))


# ------------------------------------------------------------------- Mike ---

def _review(r: dict, business, assigned: Optional[str]) -> Optional[str]:
    """R7: an owned number Mike may want to release in Twilio: its business has
    stopped paying or lost the receptionist, or is using a different number
    (review 3, finding 2). Never automatic."""
    if r["state"] not in OWNED:
        return None
    if not _entitled(business):
        return ("This business isn't paying or no longer has the receptionist. Its number is still on your "
                "Twilio bill: consider releasing it in Twilio.")
    if assigned and r["phone_number"] and assigned != r["phone_number"]:
        return (f"This business uses {assigned}, not {r['phone_number']}, which is still on your Twilio bill: "
                "consider releasing it in Twilio.")
    return None


def admin_list(session) -> list:
    _require_ready(session)
    rows = session.execute(text(
        f"SELECT {', '.join('r.' + c for c in COLUMNS)} FROM {TABLE} r "
        f"ORDER BY CASE WHEN r.state IN ({_in(OPEN)}) THEN 0 ELSE 1 END, r.created_at DESC LIMIT 200")).all()
    out, businesses = [], {}
    for raw in rows:
        r = _shape(raw)
        if r["business_id"] not in businesses:
            businesses[r["business_id"]] = _business(session, r["business_id"])
        b = businesses[r["business_id"]]
        out.append(dict(r, business_name=b.name, review=_review(r, b, current_number(session, r["business_id"]))))
    return out


def admin_get(session, rid: str) -> dict:
    _require_ready(session)
    r = _row(session, rid)
    if not r:
        refuse(404, "Request not found.")
    return r


def _version(payload) -> int:
    v = payload.get("version") if isinstance(payload, dict) else None
    if isinstance(v, bool) or not isinstance(v, int):
        refuse(422, "The request's version is missing; reload and try again.")
    return v


def _sid(payload: dict, kind: str) -> str:
    value = payload.get(f"{kind}_sid")
    if not isinstance(value, str) or not SID[kind].match(value.strip()):
        refuse(422, f"Enter the Twilio {kind} SID ({'BU' if kind == 'bundle' else 'AD'}…, 34 characters).")
    return value.strip()


def _approved_bundle(tw: TwilioNumbers, bundle: str) -> str:
    try:
        return tw.bundle_status(bundle)
    except TwilioDefinite as exc:
        refuse(422, f"Twilio doesn't recognise that bundle: {exc}")
    except TwilioUnknown as exc:
        refuse(503, f"Twilio didn't answer: {exc}")


def _spend_checks(session, r: dict) -> None:
    """R5 and R1 at the moment of spending (and of assigning)."""
    if not _entitled(_business(session, r["business_id"])):
        refuse(403, "This business no longer has the receptionist, or isn't paying.")
    held = current_number(session, r["business_id"])
    if held and held != r.get("phone_number"):
        refuse(409, "This business already has a number.")


def _area_ok(r: dict, number: str) -> bool:
    digits = (r["area_code"] or "")[1:]
    return bool(GEOGRAPHIC.match(number or "")) and number.startswith("+44" + digits)


def admin_prepare(session, rid: str, payload: dict, admin_id: str, *, now: Optional[datetime] = None) -> dict:
    """Save the regulatory bundle and address, check the bundle, and list local
    numbers in the area with Twilio's monthly price. Spends nothing."""
    r = admin_get(session, rid)
    version = _version(payload)
    bundle, address = _sid(payload, "bundle"), _sid(payload, "address")
    if r["version"] != version:
        refuse(409, "This request has changed since you opened it; reload it.")
    if r["state"] not in STARTABLE:
        refuse(409, f"This request is {r['state'].replace('_', ' ')}.")
    _spend_checks(session, r)
    tw = twilio()
    status = _approved_bundle(tw, bundle)
    numbers, monthly = [], None
    if status == "twilio-approved":
        monthly = _verified_price(tw)
        try:
            found = tw.available_local((r["area_code"] or "")[1:])
        except (TwilioDefinite, TwilioUnknown) as exc:
            refuse(503, f"Twilio didn't list numbers: {exc}")
        numbers = [n for n in dict.fromkeys(found) if _area_ok(r, n) and not number_taken(session, n, r["business_id"])]
    state = "requested" if status == "twilio-approved" else "waiting_bundle"
    moved = session.execute(text(
        f"UPDATE {TABLE} SET bundle_sid = :bu, address_sid = :ad, state = :st, candidates = :c, monthly_pence = :m, "
        f"version = version + 1, updated_at = :at, last_error = NULL "
        f"WHERE id = :i AND version = :v AND state IN ({_in(STARTABLE)})"),
        {"bu": bundle, "ad": address, "st": state, "c": json.dumps(numbers), "m": monthly,
         "at": _iso(_now(now)), "i": rid, "v": version}).rowcount
    if not moved:
        session.rollback()
        refuse(409, "This request has changed since you opened it; reload it.")
    session.commit()
    return {"request": admin_get(session, rid), "bundle_status": status, "numbers": numbers,
            "monthly_pence": monthly}


def admin_approve(session, rid: str, payload: dict, admin_id: str, *, now: Optional[datetime] = None) -> dict:
    """Claim the request for one attempt and complete it. The number must be
    one Check listed; every refusal before the claim spends nothing."""
    now = _now(now)
    r = admin_get(session, rid)
    if not isinstance(payload, dict):
        refuse(422, "Send the approval's details.")
    version = _version(payload)
    number = uk_number(payload.get("phone_number"))
    if not number:
        refuse(422, "Choose a UK number from the list.")
    url = voice_url()
    if r["version"] != version:
        refuse(409, "This request has changed since you opened it; reload it.")
    if r["state"] != "requested" or not r["bundle_sid"]:
        refuse(409, "Check the regulatory bundle first: the request must be approved by Twilio and listed.")
    if number not in r["candidates"] or not _area_ok(r, number):
        refuse(422, "Choose one of the local numbers Check listed for this request.")
    _spend_checks(session, r)
    if number_taken(session, number, r["business_id"]):
        refuse(409, "That number belongs to another business.")
    tw = twilio()
    token = uuid.uuid4().hex
    claimed = session.execute(text(
        f"UPDATE {TABLE} SET state = 'buying', claim_token = :t, claimed_at = :at, chosen_number = :n, "
        "decided_by = :by, decided_at = :at, last_error = NULL, version = version + 1, updated_at = :at "
        "WHERE id = :i AND version = :v AND state = 'requested'"),
        {"t": token, "at": _iso(now), "n": number, "by": str(admin_id), "i": rid, "v": version}).rowcount
    if not claimed:
        session.rollback()
        refuse(409, "This request has changed since you opened it; reload it.")
    session.commit()
    return _complete(session, rid, token, tw, url, now=now)


def admin_retry(session, rid: str, payload: dict, admin_id: str, *, now: Optional[datetime] = None) -> dict:
    """Finish an attempt that didn't complete. 'buying': only RETRY_AFTER after
    the last attempt, so a late purchase is visible; the tagged number is
    adopted if Twilio has it. 'bought': at once (it only configures and
    assigns). Every check _complete makes before spending applies here too."""
    now = _now(now)
    r = admin_get(session, rid)
    version = _version(payload)
    if r["version"] != version:
        refuse(409, "This request has changed since you opened it; reload it.")
    if r["state"] == "buying":
        started = _as_dt(r["claimed_at"])
        if started and now - started < RETRY_AFTER:
            minutes = int(RETRY_AFTER.total_seconds() // 60)
            refuse(409, f"Twilio may still be answering the last attempt. Retry {minutes} minutes after it.")
    elif r["state"] != "bought":
        refuse(409, f"This request is {r['state'].replace('_', ' ')}; there's nothing to retry.")
    url = voice_url()
    tw = twilio()
    token = uuid.uuid4().hex
    claimed = session.execute(text(
        f"UPDATE {TABLE} SET claim_token = :t, claimed_at = :at, version = version + 1, updated_at = :at "
        "WHERE id = :i AND version = :v AND state IN ('buying', 'bought')"),
        {"t": token, "at": _iso(now), "i": rid, "v": version}).rowcount
    if not claimed:
        session.rollback()
        refuse(409, "This request has changed since you opened it; reload it.")
    session.commit()
    return _complete(session, rid, token, tw, url, now=now)


def admin_decline(session, rid: str, payload: dict, admin_id: str, *, now: Optional[datetime] = None) -> dict:
    r = admin_get(session, rid)
    version = _version(payload)
    reason = payload.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 1 <= len(reason) <= 500:
        refuse(422, "Give the owner a reason (up to 500 characters).")
    if r["state"] not in STARTABLE:
        refuse(409, f"This request is {r['state'].replace('_', ' ')}, so it can't be declined.")
    moved = session.execute(text(
        f"UPDATE {TABLE} SET state = 'declined', decline_reason = :why, decided_by = :by, decided_at = :at, "
        f"version = version + 1, updated_at = :at WHERE id = :i AND version = :v AND state IN ({_in(STARTABLE)})"),
        {"why": reason, "by": str(admin_id), "at": _iso(_now(now)), "i": rid, "v": version}).rowcount
    if not moved:
        session.rollback()
        refuse(409, "This request has changed since you opened it; reload it.")
    session.commit()
    return admin_get(session, rid)


def admin_notify(session, rid: str, payload: dict, admin_id: str, *, now: Optional[datetime] = None) -> dict:
    """Send the owner their 'your number is live' email again."""
    r = admin_get(session, rid)
    if r["state"] != "live":
        refuse(409, "Only a live number's owner can be told.")
    if not tell_owner(session, r, now=_now(now)):
        refuse(502, "The email couldn't be sent: the business has no connected mailbox, or sending failed.")
    return admin_get(session, rid)


# --------------------------------------------------- completing an attempt ---

def _note(session, rid: str, token: str, error: str, *, now: datetime, state: Optional[str] = None) -> None:
    """Record what went wrong, against this attempt only. Ends the open transaction."""
    session.rollback()
    sets = "last_error = :e, updated_at = :at" + (", state = :st, claim_token = NULL, claimed_at = NULL" if state else "")
    session.execute(text(f"UPDATE {TABLE} SET {sets}, version = version + 1 WHERE id = :i AND claim_token = :t"),
                    {"e": error[:500], "at": _iso(now), "st": state, "i": rid, "t": token})
    session.commit()


def _fence(session, rid: str, token: str, now: datetime) -> bool:
    """Lock the request for this attempt, until the caller commits or rolls back.
    False (and nothing held) if another attempt, a decline or a cancel has moved
    it on. PostgreSQL: the UPDATE's row lock; SQLite: its single writer."""
    held = session.execute(text(
        f"UPDATE {TABLE} SET claimed_at = :at, updated_at = :at WHERE id = :i AND claim_token = :t "
        "AND state = 'buying'"), {"at": _iso(now), "i": rid, "t": token}).rowcount
    if not held:
        session.rollback()
    return bool(held)


def _save_bought(session, rid: str, token: str, number: dict, *, now: datetime) -> bool:
    """Record the number against this attempt only, with its cost, in the fenced
    transaction. False if the attempt has moved on."""
    bought_at = _as_dt(number.get("date_created")) or now      # Twilio's date: an adoption may be later
    bought_at = min(bought_at, now)
    saved = session.execute(text(
        f"UPDATE {TABLE} SET state = 'bought', number_sid = :s, phone_number = :n, bought_at = :b, "
        "version = version + 1, updated_at = :at WHERE id = :i AND claim_token = :t AND state = 'buying'"),
        {"s": number["sid"], "n": number["phone_number"], "b": _iso(bought_at), "at": _iso(now), "i": rid,
         "t": token}).rowcount
    if not saved:
        session.rollback()
        return False
    _record_cost(session, now, since=bought_at)
    session.commit()
    return True


def _new_purchase_checks(session, r: dict, tw: TwilioNumbers) -> None:
    """Before buying a NEW number (never before adopting one Twilio already holds)."""
    _spend_checks(session, r)
    if not r["bundle_sid"] or _approved_bundle(tw, r["bundle_sid"]) != "twilio-approved":
        refuse(409, "The regulatory bundle is not approved. Nothing was bought: run Check again.")
    if r["chosen_number"] not in r["candidates"] or not _area_ok(r, r["chosen_number"]):
        refuse(409, "The chosen number isn't one Check listed. Nothing was bought: run Check again.")
    if number_taken(session, r["chosen_number"], r["business_id"]):
        refuse(409, "That number belongs to another business. Nothing was bought: run Check again.")
    price = _verified_price(tw)
    if r["monthly_pence"] is None or price > r["monthly_pence"]:
        refuse(409, f"Twilio's price has changed (now {price}p a month). Nothing was bought: run Check again.")


def _purchase(session, rid: str, token: str, r: dict, tw: TwilioNumbers, url: str, *, now: datetime) -> dict:
    """Adopt or buy, fenced. Returns the number, saved as 'bought'.

    Under the fence, first ask Twilio for a number already bought for this
    request: one is adopted whatever has changed since (review 2, finding 3),
    because it is already on Mike's bill; whether it may be ASSIGNED is checked
    later. Only if there is none do the checks for a new purchase run. If they
    fail, nothing is outstanding (Twilio holds nothing, and a Retry of an
    unknown outcome waits RETRY_AFTER first), so the request goes back to
    'requested' for Check to refresh (finding 2)."""
    if not _fence(session, rid, token, now):
        refuse(409, "This request has moved on since this attempt started; reload it. Nothing was bought.")
    try:                                            # the fence is held from here until commit or rollback
        held = tw.find_tagged(tag(rid))
    except (TwilioDefinite, TwilioUnknown) as exc:
        _note(session, rid, token, f"Couldn't check Twilio for this request's number: {exc}", now=now)
        refuse(503, "Twilio didn't answer, so nothing was bought. Retry in a few minutes.")
    if held:
        if len(held) > 1:
            logger.error("[RCP-1] request %s has %d tagged numbers: %s", rid, len(held), [h["sid"] for h in held])
        number = held[0]
    else:
        try:
            _new_purchase_checks(session, r, tw)
        except ActionRefused as exc:
            _note(session, rid, token, exc.detail, now=now, state="requested")
            raise
        try:
            number = tw.buy(phone_number=r["chosen_number"], tag=tag(rid), voice_url=url,
                            address_sid=r["address_sid"], bundle_sid=r["bundle_sid"])
        except TwilioUnknown as exc:
            _note(session, rid, token, f"Twilio didn't confirm the purchase: {exc}", now=now)
            minutes = int(RETRY_AFTER.total_seconds() // 60)
            refuse(503, "Twilio didn't confirm the purchase. It may have gone through: Retry after "
                        f"{minutes} minutes checks first, and never buys a second number.")
        except TwilioDefinite as exc:
            # A refusal, but confirm Twilio holds nothing for this request before saying so.
            try:
                after = tw.find_tagged(tag(rid))
            except (TwilioDefinite, TwilioUnknown):
                after = None
            if after is None:
                _note(session, rid, token, f"Twilio refused ({exc}), and couldn't be checked afterwards.", now=now)
                refuse(503, f"Twilio refused ({exc}). Retry after a few minutes checks whether anything was bought.")
            if not after:
                _note(session, rid, token, f"Twilio refused: {exc}", now=now, state="requested")
                refuse(422, f"Twilio refused, so nothing was bought: {exc}. Run Check again for another number.")
            number = after[0]
    if not _save_bought(session, rid, token, number, now=now):
        logger.error("[RCP-1] request %s: number %s held but the attempt moved on", rid, number.get("sid"))
        refuse(409, "Another attempt has taken over this request; reload it.")
    return number


def _complete(session, rid: str, token: str, tw: TwilioNumbers, url: str, *, now: datetime) -> dict:
    r = admin_get(session, rid)
    if r["state"] == "bought" and r["number_sid"]:
        number = {"sid": r["number_sid"], "phone_number": r["phone_number"]}
    else:
        number = _purchase(session, rid, token, r, tw, url, now=now)
        r = admin_get(session, rid)
    # R4: read it back; correct the webhook once; check again.
    try:
        seen = tw.fetch(number["sid"])
        if seen.get("voice_url") != url or (seen.get("voice_method") or "").upper() != "POST":
            tw.set_voice(number["sid"], url)
            seen = tw.fetch(number["sid"])
    except (TwilioDefinite, TwilioUnknown) as exc:
        _note(session, rid, token, f"Bought, not configured: couldn't check the number's webhook ({exc}).", now=now)
        refuse(502, "The number was bought but its call settings couldn't be checked. Retry finishes it.")
    if seen.get("voice_url") != url or (seen.get("voice_method") or "").upper() != "POST":
        _note(session, rid, token, f"Bought, not configured: its webhook is {seen.get('voice_url')!r}.", now=now)
        refuse(502, "The number was bought, but its call settings didn't save. Retry finishes it.")
    # Assign only to a business still entitled and without another number.
    try:
        _spend_checks(session, r)
        assign(session, r["business_id"], number["phone_number"], number["sid"], replace=False)
        went_live = session.execute(text(
            f"UPDATE {TABLE} SET state = 'live', live_at = :at, claim_token = NULL, claimed_at = NULL, "
            "last_error = NULL, version = version + 1, updated_at = :at "
            "WHERE id = :i AND claim_token = :t AND state = 'bought'"),
            {"at": _iso(now), "i": rid, "t": token}).rowcount
        if not went_live:
            session.rollback()
            refuse(409, "Another attempt has taken over this request; reload it.")
        session.commit()
    except ActionRefused as exc:
        if "taken over" not in exc.detail:
            _note(session, rid, token, f"Bought, not assigned: {exc.detail}", now=now)
        raise
    logger.info("[RCP-1] request %s live: %s", rid, number["phone_number"])
    live = admin_get(session, rid)
    tell_owner(session, live, now=now)
    return admin_get(session, rid)


def _send_owner_email(business_id: str, subject: str, body: str) -> bool:
    """The owner's own connected mailbox, as the usage notices (metering_notify)."""
    from services.metering_notify import _send_email
    return _send_email(business_id, subject, body)


def tell_owner(session, r: dict, *, now: datetime) -> bool:
    """Email the owner that their number is live. Best effort: the settings page
    shows it either way, and Mike can send it again (admin_notify)."""
    try:
        sent = _send_owner_email(r["business_id"], "Your AI receptionist's number is ready",
                           f"Your receptionist's phone number is {r['phone_number']}.\n\n"
                           "Switch the receptionist on in AI hub → Receptionist, then ring the number to test it."
                           + ("\n\nThe same page shows how to forward your existing number to it."
                              if r["mode"] == "keep_existing" else ""))
    except Exception as exc:
        logger.error("[RCP-1] couldn't email the owner of request %s: %s", r["id"], exc)
        sent = False
    if sent:
        session.execute(text(f"UPDATE {TABLE} SET owner_told_at = :at WHERE id = :i"),
                        {"at": _iso(now), "i": r["id"]})
        session.commit()
    return bool(sent)


def _months(since: datetime, now: datetime) -> list:
    """UK calendar months ('YYYY-MM', as running_costs and metering.period_for
    use) from since's to now's, clamped to the months running_costs accepts
    (review 3, finding 1: UTC months put a BST-night purchase in the wrong month)."""
    from services import running_costs
    from services.metering import period_for
    first, last = period_for(since), period_for(now)
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out[-(running_costs.MONTHS_BACK + 1):]


def _uk_month_end(period: str) -> datetime:
    """The first moment after a UK calendar month, in UTC."""
    from services.metering import LONDON
    y, m = map(int, period.split("-"))
    return datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=LONDON).astimezone(timezone.utc)


def _record_cost(session, now: datetime, *, since: Optional[datetime] = None) -> None:
    """R6: every number we pay for (bought or live), as one running-costs line,
    for each month from the one it was bought in (review 2, finding 4). A month
    counts only numbers bought by its end. Per business, each request row
    carries its business, price and purchase date. The running-costs lock is
    taken BEFORE the totals are read (review 1, finding 3), so two purchases
    can't each write a total missing the other. Doesn't commit."""
    from services import ai_costs, running_costs
    if not ai_costs.has_platform_table(session):
        logger.warning("[RCP-1] no platform_meters table; number cost not recorded")
        return
    running_costs._serialise(session)
    owned = [(int(p or 0), _as_dt(at)) for p, at in session.execute(text(
        f"SELECT monthly_pence, bought_at FROM {TABLE} WHERE state IN ({_in(OWNED)})")).all()]
    for period in _months(since or now, now):
        month_end = _uk_month_end(period)
        total = sum(p for p, at in owned if at is None or at < month_end)
        try:
            running_costs.set_item(session, period, COST_NAME, total, moment=now)
        except ActionRefused as exc:          # a cost line must never stop a purchase being recorded
            logger.error("[RCP-1] couldn't record %s for %s: %s", COST_NAME, period, exc.detail)
