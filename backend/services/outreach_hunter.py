"""OUT-23 Part B — the Hunter.io add-on (docs/OUT-23-TICKET.md, Part B
revisions 1-4, design approved by Codex design review 4). RED: paid
third-party lookups and the collection of personal data.

Hunter supplies the named people at a company's domain. Only an address that
Hunter FOUND published, that we see on the page ourselves, and that verifies
VALID is ever kept (Mike, 11 Nov 2026). Everything here is fail-closed: an
unexpected shape is a rejection, never a fallback.

The key lives only in outreach_provider_accounts (migration 042), encrypted,
never in business_settings and never logged. Every billable call is reserved
first in outreach_provider_charges and settled after (R3.2, R4.3).

Lock order (R3.4): business_settings -> outreach_settings ->
outreach_provider_accounts -> outreach_provider_charges -> the rest.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional
from urllib.parse import urlparse

from sqlalchemy import text

from services import outreach_send as send

logger = logging.getLogger(__name__)

PROVIDER = "hunter"
BASE = "https://api.hunter.io/v2"
SETTINGS_KEY = "outreach_hunter"          # per-brand switches, caps and notice binding (not secret)
SOURCE_TAG = "hunter.io"                  # an assessment's `sources` vocabulary (R3.8)
SOURCES = ("public_websites", SOURCE_TAG)

SOURCE_DAYS = 90                          # a publication source seen within 90 days (R2.1)
VERIFIED_DAYS = 30                        # a verification within 30 days (R2.2, R3.6)
ACCOUNT_TTL = timedelta(hours=1)          # /account cached at most an hour (R2.6)
RESERVATION_STALE = timedelta(hours=1)    # the sweep (R3.2)
ENRICH_SECONDS = 180.0                    # the whole enrichment phase (R3.5)
MIN_SECONDS = 5.0                         # nothing starts with less left
CALL_TIMEOUT = 15.0
MAX_CALLS = 60                            # per run (R2.4)
MAX_VERIFY_PER_LEAD = 2
POLL_EVERY = 2.0
MAX_FETCHES_PER_PERSON = 2

SEARCH_CREDITS, VERIFY_CREDITS = Decimal("1"), Decimal("0.5")
POOLS = ("credit", "search", "verification")
STATUSES = ("valid", "invalid", "accept_all", "webmail", "disposable", "unknown")

NOTICE_WORDING = ("We obtain business contact details from public sources, including company websites, and "
                  "from business contact databases including Hunter.io. We keep a contact's name, role, work "
                  "email address and where we found it, and delete it after 28 days unless we have emailed "
                  "them.")


class HunterError(Exception):
    """kind: key | rate | quota | claimed | server | timeout | malformed | refused."""

    def __init__(self, kind: str, status: Optional[int] = None, credits: Optional[tuple] = None):
        super().__init__(kind)
        self.kind, self.status, self.credits = kind, status, credits

    def __repr__(self) -> str:              # never a key, an address or a body
        return f"HunterError({self.kind!r}, {self.status!r})"


def now() -> datetime:
    return send.now()


# ------------------------------------------------------------- transport ---

def _http(method: str, path: str, params: dict, key: str, timeout: float) -> tuple:
    """The default transport: a fixed host, the key in a header only, no
    redirects, and `timeout` as the call's TOTAL time (connect, wait and the
    streamed body), not an inactivity timeout (Codex code review 1).
    Returns (status, json or None, headers)."""
    import httpx
    from services.outreach_research import get_json_within
    assert method == "GET"
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)), follow_redirects=False) as client:
        return get_json_within(client, f"{BASE}/{path}", params=params, headers={"X-API-KEY": key},
                               end=time.monotonic() + timeout, limit=1_000_000, cap=timeout)


def _number(value) -> Optional[Decimal]:
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return n if n.is_finite() and n >= 0 else None


def _credits(headers: dict) -> Optional[tuple]:
    """(used, unit) from X-Credits-Used / X-Credits-Unit, or None if either is
    missing or malformed (R2.6: then the reservation is charged)."""
    lower = {str(k).lower(): v for k, v in (headers or {}).items()}
    used, unit = _number(lower.get("x-credits-used")), str(lower.get("x-credits-unit") or "").strip().lower()
    if used is None or unit not in POOLS:
        return None
    return used, unit


def call(transport: Callable, key: str, path: str, params: dict, timeout: float) -> tuple:
    """One Hunter call -> (data, credits). Raises HunterError, typed."""
    if timeout < 1:
        raise HunterError("timeout")
    try:
        status, body, headers = transport("GET", path, params, key, timeout)
    except HunterError:
        raise
    except Exception as exc:
        logger.warning("Hunter %s failed: %s", path, type(exc).__name__)
        raise HunterError("timeout") from None
    credits = _credits(headers)
    if status == 200 or status == 202:
        data = (body or {}).get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise HunterError("malformed", status, credits)
        return data, credits, status
    kind = {401: "key", 403: "rate", 429: "quota", 451: "claimed"}.get(status, "server" if status >= 500 else "refused")
    raise HunterError(kind, status, credits)


# ------------------------------------------------------------ the account ---

def _row(session, bid: str, lock: bool = False) -> Optional[dict]:
    rows = send.rows(session, "outreach_provider_accounts", bid, "AND provider = :p", {"p": PROVIDER}, lock)
    if not rows:
        return None
    r = dict(rows[0])
    r["pools"] = send.loads(r.get("pools")) or {}
    r["blocked"] = send.loads(r.get("blocked")) or {}
    return r


def _lock(session, bid: str) -> None:
    from services import outreach_research
    outreach_research._lock(session, bid)


def parse_account(data: dict) -> dict:
    """Only what is needed (R2.6): plan, per-pool used/available, reset date.
    `model` is 'single' (one credit pool), 'separate', or 'unknown'."""
    requests = data.get("requests") if isinstance(data.get("requests"), dict) else {}
    pools = {}
    for name, pool in (("credits", "credit"), ("searches", "search"), ("verifications", "verification")):
        entry = requests.get(name)
        if isinstance(entry, dict):
            used, available = _number(entry.get("used")), _number(entry.get("available"))
            if used is not None and available is not None:
                pools[pool] = {"used": str(used), "available": str(available)}
    model = "single" if "credit" in pools else ("separate" if {"search", "verification"} <= set(pools) else "unknown")
    reset = data.get("reset_date")
    reset = reset if isinstance(reset, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", reset) else None
    plan = str(data.get("plan_name") or data.get("plan") or "")[:40] or None
    return {"plan": plan, "pools": {**pools, "model": model, "reset_date": reset}}


def _key_shape(key: str) -> str:
    key = str(key or "").strip()
    send.require(re.fullmatch(r"[A-Za-z0-9_\-]{20,128}", key), "That doesn't look like a Hunter API key", 422)
    return key


def connect(session, business, user, key: str, *, transport: Optional[Callable] = None) -> dict:
    """R3.1/R4.1: validate the key (network, outside any transaction), then
    write it only if the connection's generation is still the one seen
    before the call. Active owner only."""
    from app.email.crypto import encrypt_secret
    from services import outreach_setup
    key = _key_shape(key)
    outreach_setup._authority(session, business, user)      # owns its rollback: before any lock
    bid = str(business.id)
    existing = _row(session, bid)
    seen = int(existing["generation"]) if existing else 0
    session.rollback()
    try:
        ciphertext = encrypt_secret(key)
    except ValueError:
        raise send.ActionRefused(503, "Hunter can't be connected yet: encryption isn't configured") from None
    try:
        data, _, _ = call(transport or _http, key, "account", {}, CALL_TIMEOUT)
    except HunterError as exc:
        raise send.ActionRefused(422 if exc.kind == "key" else 502,
                                 "Hunter didn't accept that key" if exc.kind == "key"
                                 else "Hunter couldn't be reached; try again in a minute") from None
    account = parse_account(data)
    moment = now()
    _lock(session, bid)
    fields = dict(key_ciphertext=ciphertext, key_last4=key[-4:], status="connected", plan=account["plan"],
                  pools=account["pools"], account_fetched_at=moment, blocked={}, connected_by=str(user),
                  connected_at=moment, updated_at=moment)
    if seen == 0:
        if _row(session, bid, lock=True) is not None:
            session.rollback()
            raise send.ActionRefused(409, "The Hunter connection changed meanwhile; try again")
        send.insert(session, "outreach_provider_accounts", bid, provider=PROVIDER, generation=1, **fields)
    else:
        _row(session, bid, lock=True)
        done = session.execute(text(
            "UPDATE outreach_provider_accounts SET key_ciphertext = :key_ciphertext, key_last4 = :key_last4, "
            "status = :status, plan = :plan, pools = " + _json(session, "pools") + ", account_fetched_at = :account_fetched_at, "
            "blocked = " + _json(session, "blocked") + ", connected_by = :connected_by, connected_at = :connected_at, "
            "updated_at = :updated_at, generation = generation + 1 "
            "WHERE business_id = :b AND provider = :p AND generation = :seen"),
            {**_jsonify(fields), "b": bid, "p": PROVIDER, "seen": seen}).rowcount
        if done != 1:
            session.rollback()
            raise send.ActionRefused(409, "The Hunter connection changed meanwhile; try again")
    session.commit()
    return status(session, business)


def disconnect(session, business, user) -> dict:
    """R4.1: always leaves a tombstone, so generation never repeats."""
    from services import outreach_setup
    outreach_setup._authority(session, business, user)
    bid = str(business.id)
    session.rollback()
    _lock(session, bid)
    moment = now()
    if _row(session, bid, lock=True) is None:
        send.insert(session, "outreach_provider_accounts", bid, provider=PROVIDER, generation=1, status="disconnected",
                    key_ciphertext=None, key_last4=None, pools={}, blocked={}, updated_at=moment)
    else:
        session.execute(text(
            "UPDATE outreach_provider_accounts SET key_ciphertext = NULL, key_last4 = NULL, status = 'disconnected', "
            "generation = generation + 1, updated_at = :t WHERE business_id = :b AND provider = :p"),
            {"t": moment, "b": bid, "p": PROVIDER})
    session.commit()
    return status(session, business)


def _json(session, name: str) -> str:
    return f"CAST(:{name} AS jsonb)" if send.pg(session) else f":{name}"


def _jsonify(fields: dict) -> dict:
    import json
    return {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in fields.items()}


@dataclass
class Connection:
    generation: int
    key: str
    pools: dict
    blocked: dict

    def __repr__(self) -> str:              # the key is never printed
        return f"Connection(generation={self.generation})"


def connection(session, bid: str) -> Optional[Connection]:
    """The current connection with its key decrypted, or None."""
    from app.email.crypto import decrypt_secret
    r = _row(session, bid)
    if not r or r["status"] != "connected" or not r["key_ciphertext"]:
        return None
    try:
        key = decrypt_secret(r["key_ciphertext"])
    except ValueError:
        logger.error("Hunter key for business %s could not be decrypted", bid)
        return None
    return Connection(int(r["generation"]), key, r["pools"], r["blocked"])


def _current_write(session, bid: str, generation: int, sql_set: str, params: dict) -> bool:
    """A current-connection write: only while the run's generation stands (R4.1)."""
    return session.execute(text(
        f"UPDATE outreach_provider_accounts SET {sql_set}, updated_at = :t "
        "WHERE business_id = :b AND provider = :p AND generation = :g AND status = 'connected'"),
        {**params, "t": now(), "b": bid, "p": PROVIDER, "g": generation}).rowcount == 1


def mark_invalid(session, bid: str, generation: int) -> None:
    _lock(session, bid)
    _current_write(session, bid, generation, "status = 'invalid'", {})
    session.commit()


def block(session, bid: str, generation: int, pool: str, reset: Optional[str], moment: datetime) -> bool:
    """R2.6: a 429 blocks that pool until Hunter's reset date (00:00 UTC);
    missing or past, for 24 hours. Persisted in the row, never only cached."""
    import json
    until, known = moment + timedelta(hours=24), False
    if reset and re.fullmatch(r"\d{4}-\d{2}-\d{2}", reset):
        at = datetime.combine(date.fromisoformat(reset), datetime.min.time(), tzinfo=timezone.utc)
        if at > moment:
            until, known = at, True
    _lock(session, bid)
    r = _row(session, bid, lock=True)
    if r and int(r["generation"]) == generation:
        blocked = dict(r["blocked"])
        blocked[pool] = until.isoformat()
        _current_write(session, bid, generation, "blocked = " + _json(session, "blocked"), {"blocked": json.dumps(blocked)})
    session.commit()
    return not known                        # a missing or past reset date: refresh /account (R2.6)


def refresh_account(session, bid: str, generation: int, transport: Callable, key: str, *, force: bool = False) -> None:
    """At most hourly, unless forced; network outside any transaction."""
    import json
    r = _row(session, bid)
    session.rollback()
    if not r or int(r["generation"]) != generation:
        return
    fetched = send._parse(r["account_fetched_at"]) if r.get("account_fetched_at") else None
    if not force and fetched and now() - fetched < ACCOUNT_TTL:
        return
    try:
        data, _, _ = call(transport, key, "account", {}, CALL_TIMEOUT)
    except HunterError:
        return                                  # a failed refresh keeps any block
    account = parse_account(data)
    _lock(session, bid)
    _current_write(session, bid, generation, "plan = :plan, pools = " + _json(session, "pools") + ", account_fetched_at = :f",
                   {"plan": account["plan"], "pools": json.dumps(account["pools"]), "f": now()})
    session.commit()


def status(session, business) -> dict:
    """What the owner sees: never the key, never a person."""
    bid = str(business.id)
    r = _row(session, bid)
    out = {"connected": False, "status": "not_connected", "last4": None, "plan": None, "pools": {}, "as_of": None,
           "blocked": {}, "brands": {}}
    if r:
        out.update(connected=r["status"] == "connected", status=r["status"], last4=r["key_last4"], plan=r["plan"],
                   pools={k: v for k, v in r["pools"].items() if k in POOLS + ("model", "reset_date")},
                   as_of=r["account_fetched_at"].isoformat() if hasattr(r["account_fetched_at"], "isoformat")
                   else r["account_fetched_at"], blocked=r["blocked"])
    moment = now()
    for brand in send.rows(session, "outreach_brands", bid, "ORDER BY created_at, id"):
        cfg = brand_config(session, bid, brand["id"])
        out["brands"][str(brand["id"])] = {
            "name": brand["name"], "enabled": cfg["enabled"], "cap_credits": cfg["cap_credits"],
            "used_credits": str(used_credits(session, bid, brand["id"], moment)),
            "notice_confirmed": notice_current(session, bid, brand["id"]),
            "suggested_wording": NOTICE_WORDING}
    session.rollback()
    return out


# --------------------------------------------------------- brand settings ---

def _doc(session, bid: str) -> dict:
    from services import outreach_setup
    return outreach_setup._settings_doc(session, bid)


def brand_config(session, bid: str, brand_id) -> dict:
    b = dict(((_doc(session, bid).get(SETTINGS_KEY) or {}).get("brands") or {}).get(str(brand_id)) or {})
    b.setdefault("enabled", False)
    b.setdefault("cap_credits", None)
    b.setdefault("notice", None)
    return b


def notice_hash(session, bid: str, brand_id) -> Optional[str]:
    import hashlib
    from services import outreach_setup
    notice = (_doc(session, bid).get(outreach_setup.PRIVACY_KEY) or {}).get(str(brand_id)) or {}
    body = notice.get("text")
    return hashlib.sha256(body.encode()).hexdigest() if body else None


def notice_current(session, bid: str, brand_id) -> bool:
    """R2.8/R3.9: the owner's confirmation still matches the published notice."""
    confirmed = (brand_config(session, bid, brand_id).get("notice") or {})
    current = notice_hash(session, bid, brand_id)
    return bool(current and confirmed.get("hash") == current and confirmed.get("by"))


def configure_brand(session, business, user, brand_id, data: dict) -> dict:
    """Switch Hunter on or off for a brand, set its optional monthly credit
    cap, and confirm its notice names Hunter (bound to the notice's hash)."""
    from services import outreach_setup
    outreach_setup._authority(session, business, user)
    bid = str(business.id)
    send.one(session, "outreach_brands", bid, brand_id)
    session.rollback()
    _lock(session, bid)
    doc = _doc(session, bid)
    section = doc.setdefault(SETTINGS_KEY, {})
    brands = section.setdefault("brands", {})
    b = dict(brands.get(str(brand_id)) or {"enabled": False, "cap_credits": None, "notice": None})
    if data.get("confirm_notice"):
        current = notice_hash(session, bid, brand_id)
        send.require(current, "Approve this brand's privacy notice first", 409)
        b["notice"] = {"by": str(user), "hash": current, "at": now().isoformat()}
    if "cap_credits" in data:
        cap = data.get("cap_credits")
        if cap in (None, ""):
            b["cap_credits"] = None
        else:
            n = _number(cap)
            send.require(n is not None and 0 < n <= 100000, "The credit cap must be between 1 and 100,000", 422)
            b["cap_credits"] = str(n)
    if "enabled" in data:
        want = bool(data.get("enabled"))
        if want:
            send.require(b.get("notice") and b["notice"].get("hash") == notice_hash(session, bid, brand_id),
                         "Confirm this brand's privacy notice names Hunter.io first", 409)
        b["enabled"] = want
    brands[str(brand_id)] = b
    outreach_setup._save_settings_doc(session, bid, doc)
    session.commit()
    return status(session, business)


def acquired_by_hunter(session, bid: str, prospect_id) -> bool:
    """From the immutable acquisition row only (R3.7)."""
    return bool(session.execute(text(
        "SELECT 1 FROM outreach_evidence WHERE business_id = :b AND prospect_id = :p AND fact_type = 'acquisition' "
        "AND source_type = 'hunter' AND fact_value = 'hunter' LIMIT 1"), {"b": bid, "p": str(prospect_id)}).first())


def lia_has_hunter(session, bid: str, lia_id) -> bool:
    rows = send.rows(session, "outreach_compliance", bid, "AND id = :l", {"l": str(lia_id)})
    return bool(rows) and SOURCE_TAG in (send.loads(rows[0]["sources"]) or [])


NOTICE_CHANGED = "This brand's privacy notice changed; confirm it still names Hunter.io"


def send_refused(session, bid: str, prospect: dict) -> Optional[str]:
    """R3.9: before a never-contacted Hunter contact's first email, at claim
    and again at dispatch's final gate: the brand's confirmation still
    matches its current notice, and the assessment the contact was
    collected under includes Hunter. None when allowed (or not a Hunter
    contact, or already contacted)."""
    if prospect.get("notice_provided_at") or not acquired_by_hunter(session, bid, prospect["id"]):
        return None
    lia = send.rows(session, "outreach_compliance", bid, "AND id = :l", {"l": str(prospect["lia_id"])})
    if not lia or SOURCE_TAG not in (send.loads(lia[0]["sources"]) or []):
        return "This contact's audience approval doesn't cover Hunter.io"
    if not notice_current(session, bid, lia[0]["brand_id"]):
        return NOTICE_CHANGED
    return None


# ------------------------------------------------------- the charge ledger ---

def to_credits(pool: str, native: Decimal) -> Decimal:
    """Native units -> brand credits (R4.3): a credit is a credit; a search
    request is 1; a verification request is 0.5."""
    return native * (VERIFY_CREDITS if pool == "verification" else Decimal("1"))


def _period(moment: datetime) -> str:
    from services.outreach_research import LONDON
    return moment.astimezone(LONDON).strftime("%Y-%m")


def used_credits(session, bid: str, brand_id, moment: datetime) -> Decimal:
    """Σ brand credits this UK month, every state (an outstanding reservation counts)."""
    value = session.execute(text(
        "SELECT COALESCE(SUM(brand_credits), 0) FROM outreach_provider_charges WHERE business_id = :b "
        "AND brand_id = :br AND period = :m"), {"b": bid, "br": str(brand_id), "m": _period(moment)}).scalar()
    return Decimal(str(value or 0))


def expected(pools: dict, operation: str) -> Optional[tuple]:
    """(pool, reserved_native, brand_credits) for an operation, or None if the
    account model is unknown (R3.3)."""
    model = (pools or {}).get("model")
    if model == "single":
        native = SEARCH_CREDITS if operation == "search" else VERIFY_CREDITS
        return "credit", native, native
    if model == "separate":
        return ("search" if operation == "search" else "verification"), Decimal("1"), \
            (SEARCH_CREDITS if operation == "search" else VERIFY_CREDITS)
    return None


def reserve(session, bid: str, brand_id, conn: Connection, operation: str, moment: datetime) -> tuple:
    """Under the caller's locks (business, then this account row): check the
    pool is not blocked, the account shows enough, and the brand cap has room;
    then insert a reserved charge. Returns (charge_id, None) or (None, why).
    The caller commits."""
    r = _row(session, bid, lock=True)
    if not r or r["status"] != "connected" or int(r["generation"]) != conn.generation:
        return None, "Hunter was disconnected"
    plan = expected(r["pools"], operation)
    if plan is None:
        return None, "Hunter's account details aren't known yet"
    pool, native, credits = plan
    until = r["blocked"].get(pool)
    if until and send._parse(until) and send._parse(until) > moment:
        return None, "Hunter's monthly credits are used"
    available = _number((r["pools"].get(pool) or {}).get("available"))
    if available is not None:
        # The snapshot's balance less everything this connection has used
        # since it was taken, and every reservation still open (Codex code
        # review 1: a settled call must not free its credit again).
        fetched = r.get("account_fetched_at")
        spent = Decimal(str(session.execute(text(
            "SELECT COALESCE(SUM(CASE WHEN state = 'settled' THEN COALESCE(used_native, 0) ELSE reserved_native END), 0) "
            "FROM outreach_provider_charges WHERE business_id = :b AND COALESCE(pool_actual, pool) = :pool "
            "AND generation = :g AND (state = 'reserved'" + (" OR created_at >= :f" if fetched else "") + ")"),
            {"b": bid, "pool": pool, "g": conn.generation, **({"f": fetched} if fetched else {})}).scalar() or 0))
        if available - spent < native:
            return None, "Hunter's monthly credits are used"
    cap = _number(brand_config(session, bid, brand_id).get("cap_credits"))
    if cap is not None and used_credits(session, bid, brand_id, moment) + credits > cap:
        return None, "This brand's Hunter credit cap for the month is reached"
    ident = send.insert(session, "outreach_provider_charges", bid, brand_id=str(brand_id), provider=PROVIDER,
                        generation=conn.generation, operation=operation, pool=pool, reserved_native=str(native),
                        brand_credits=str(credits), state="reserved", period=_period(moment))
    return ident, None


def settle(session, bid: str, charge_id: str, reported: Optional[tuple]) -> bool:
    """R4.3: one atomic, idempotent update, whatever the connection is now.
    `reported` is (used, unit) from the headers, or None (charged at the
    reservation)."""
    _lock(session, bid)
    row = session.execute(text(
        "SELECT pool, reserved_native, brand_credits FROM outreach_provider_charges WHERE business_id = :b "
        "AND id = :id AND state = 'reserved'" + (" FOR UPDATE" if send.pg(session) else "")),
        {"b": bid, "id": charge_id}).mappings().first()
    if row is None:
        session.rollback()
        return False
    refresh = False
    if reported is None:
        state, used, unit, credits = "charged", Decimal(str(row["reserved_native"])), row["pool"], Decimal(str(row["brand_credits"]))
    else:
        used, unit = reported
        credits = to_credits(unit, used)
        if unit != row["pool"]:
            # A mismatched unit: settle at the larger, in brand credits (R4.3).
            credits = max(credits, Decimal(str(row["brand_credits"])))
            logger.warning("Hunter charged in %s, expected %s", unit, row["pool"])
            refresh = True                  # the account model has proved wrong (R2.6)
        state = "settled"
    session.execute(text(
        "UPDATE outreach_provider_charges SET state = :s, used_native = :u, pool_actual = :pa, brand_credits = :c, "
        "settled_at = :t, updated_at = :t WHERE business_id = :b AND id = :id AND state = 'reserved'"),
        {"s": state, "u": str(used), "pa": unit, "c": str(credits), "t": now(), "b": bid, "id": charge_id})
    session.commit()
    return refresh


def sweep(session, moment: Optional[datetime] = None) -> int:
    """Hourly: a reservation older than an hour is charged as reserved."""
    moment = moment or now()
    cutoff = moment - RESERVATION_STALE
    bids = [str(r[0]) for r in session.execute(text(
        "SELECT DISTINCT business_id FROM outreach_provider_charges WHERE state = 'reserved' AND created_at < :c"),
        {"c": cutoff})]
    session.rollback()
    done = 0
    for bid in bids:
        try:
            _lock(session, bid)
            done += session.execute(text(
                "UPDATE outreach_provider_charges SET state = 'charged', settled_at = :t, updated_at = :t "
                "WHERE business_id = :b AND state = 'reserved' AND created_at < :c"),
                {"t": moment, "b": bid, "c": cutoff}).rowcount
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("Hunter reservation sweep failed for business %s: %s", bid, type(exc).__name__)
    return done


# ------------------------------------------------- the response contracts ---

def _day(value) -> Optional[date]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _fresh(day: Optional[date], moment: datetime, days: int) -> bool:
    today = moment.astimezone(timezone.utc).date()
    return day is not None and day <= today and (today - day).days <= days


def publication_sources(person: dict, domain: str, moment: datetime) -> list:
    """R2.1: sources that show the address now, own domain first. Each needs
    still_on_page true, last_seen_on parsed, not future, within 90 days, and
    an https uri."""
    good = []
    for s in person.get("sources") or []:
        if not isinstance(s, dict) or s.get("still_on_page") is not True:
            continue
        uri = s.get("uri")
        if not isinstance(uri, str) or urlparse(uri).scheme != "https" or not urlparse(uri).hostname:
            continue
        if not _fresh(_day(s.get("last_seen_on")), moment, SOURCE_DAYS):
            continue
        host = (urlparse(uri).hostname or "").lower()
        own = host == domain or host.endswith("." + domain)
        good.append((0 if own else 1, uri))
    good.sort(key=lambda g: g[0])
    return [uri for _, uri in good]


def searched_valid(person: dict, moment: datetime) -> Optional[date]:
    """R2.2 (a): Domain Search's own verification, valid within 30 days."""
    v = person.get("verification")
    if not isinstance(v, dict) or v.get("status") != "valid":
        return None
    day = _day(v.get("date"))
    return day if _fresh(day, moment, VERIFIED_DAYS) else None


def verifier_valid(data: dict, email: str, moment: datetime) -> Optional[date]:
    """R2.2 (b) / R3.6: every field, typed; anything else is no."""
    if str(data.get("email") or "").strip().lower() != email:
        return None
    if data.get("status") != "valid":
        return None
    v = data.get("verification")
    if not isinstance(v, dict) or v.get("status") != "valid":
        return None
    for flag in ("accept_all", "webmail", "disposable", "block", "gibberish"):
        if data.get(flag) is not False:
            return None
    if data.get("smtp_check") is not True:
        return None
    day = _day(v.get("date"))
    return day if _fresh(day, moment, VERIFIED_DAYS) else None


def candidates(data: dict, domain: str, moment: datetime) -> list:
    """R2.3 after the search, no charge: same domain, provenance found,
    personal, a fresh publication source. Not yet ranked or checked against
    our own lists (the caller does that)."""
    out = []
    for person in data.get("emails") or []:
        if not isinstance(person, dict):
            continue
        email = str(person.get("value") or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+", email) or email.split("@")[1] != domain:
            continue
        if person.get("provenance") != "found" or person.get("type") != "personal":
            continue
        sources = publication_sources(person, domain, moment)
        if not sources:
            continue
        first, last = str(person.get("first_name") or "").strip(), str(person.get("last_name") or "").strip()
        confidence = person.get("confidence")
        out.append({"email": email, "name": f"{first} {last}".strip()[:120], "role": str(person.get("position") or "")[:120],
                    "seniority": person.get("seniority"),
                    "confidence": int(confidence) if isinstance(confidence, int) and 0 <= confidence <= 100 else 0,
                    "sources": sources, "searched_valid": searched_valid(person, moment)})
    return out


def rank(people: list, contact_type: Callable) -> list:
    """Decision-makers first, then executive before senior, then confidence."""
    order = {"executive": 0, "senior": 1}
    return sorted(people, key=lambda p: (contact_type(p["email"], p["name"], p["role"]) != "decision_maker",
                                         order.get(p.get("seniority"), 2), -p["confidence"]))


# ------------------------------------------------------------ the deadline ---

class Budget:
    """R3.5: one monotonic deadline for all enrichment, and a call budget."""

    def __init__(self, seconds: float = ENRICH_SECONDS, calls: Optional[int] = None, clock: Optional[Callable] = None):
        self.clock = clock or time.monotonic
        self.end, self.calls = self.clock() + seconds, MAX_CALLS if calls is None else calls
        self.searches: Optional[int] = None   # set to 2 x room at the run's first lead (R2.4)
        self.tried: set = set()               # each domain once per run, across attempts

    def left(self) -> float:
        return self.end - self.clock()

    def ok(self) -> bool:
        return self.left() >= MIN_SECONDS

    def timeout(self, own: float = CALL_TIMEOUT) -> float:
        return max(0.0, min(own, self.left()))

    def take_call(self) -> bool:
        if self.calls <= 0 or not self.ok():
            return False
        self.calls -= 1
        return True

    def take_search(self) -> bool:
        if self.searches is not None:
            if self.searches <= 0:
                return False
            self.searches -= 1
        return True


# ---------------------------------------------------------- finding people ---

STOP = "stop"          # every Hunter call for the rest of this run stops


def _suppress_claimed(session, bid: str, email: str, moment: datetime) -> None:
    """R2.10: a 451 is a request to stop processing that person. Only the
    tenant-keyed digest is kept, so every acquisition path refuses it."""
    _lock(session, bid)
    digest = send.suppression_digest(bid, "email", email)
    if not send.rows(session, "outreach_suppressions", bid, "AND key_type = 'email' AND key_digest = :d", {"d": digest}):
        send.insert(session, "outreach_suppressions", bid, key_type="email", key_digest=digest, digest_version=1,
                    reason="provider_claimed", suppressed_at=moment)
    session.commit()


def _billable(session, bid: str, brand_id, conn: Connection, operation: str, path: str, params: dict, *,
              gate: Callable, transport: Callable, budget: Budget, sleep: Callable, email: Optional[str] = None) -> tuple:
    """R2.4: EVERY request (a 202 poll included) is gated and reserved under
    the locks and committed, called outside any transaction, then settled
    from its own headers (Codex code review 1). -> (data, None) or
    (None, (why, stop))."""
    while True:
        if not budget.take_call():
            return None, ("Hunter's time for this run is used", True)
        if operation == "search" and not budget.take_search():
            return None, ("enough companies were looked up in Hunter for this run", True)
        moment = now()
        _lock(session, bid)
        why = gate(session)
        if why:
            session.rollback()
            return None, (why, True)
        charge, why = reserve(session, bid, brand_id, conn, operation, moment)
        if charge is None:
            session.rollback()
            return None, (why, True)
        session.commit()
        plan = expected(conn.pools, operation)
        try:
            data, credits, status_code = call(transport, conn.key, path, params, budget.timeout())
        except HunterError as exc:
            if settle(session, bid, charge, exc.credits):
                refresh_account(session, bid, conn.generation, transport, conn.key, force=True)
            if exc.kind == "key":
                mark_invalid(session, bid, conn.generation)
                return None, ("Hunter no longer accepts the saved key; reconnect it in Outreach settings", True)
            if exc.kind == "quota":
                if block(session, bid, conn.generation, plan[0] if plan else "credit", conn.pools.get("reset_date"), moment):
                    refresh_account(session, bid, conn.generation, transport, conn.key, force=True)
                return None, ("Hunter's monthly credits are used", True)
            if exc.kind == "rate":
                return None, ("Hunter is busy; it carries on next run", True)
            if exc.kind == "claimed" and email:
                _suppress_claimed(session, bid, email, moment)
                return None, ("asked Hunter not to be contacted", False)
            return None, ("Hunter couldn't be reached for this company", False)
        if settle(session, bid, charge, credits):
            refresh_account(session, bid, conn.generation, transport, conn.key, force=True)
        if status_code != 202:
            return data, None
        # Still verifying: poll, each poll its own gated, reserved call.
        if budget.left() < POLL_EVERY + MIN_SECONDS:
            return None, ("Hunter couldn't finish verifying in time", False)
        sleep(POLL_EVERY)


def find_person(session, bid: str, brand_id, conn: Connection, domain: str, *, gate: Callable, transport: Callable,
                budget: Budget, fetch_text: Callable, address_on: Callable, allowed: Callable, contact_type: Callable,
                sleep: Callable = time.sleep) -> tuple:
    """One company -> (person, None) or (None, (why, stop)). A person has
    email, name, role, source_url (the page we saw the address on) and
    verified_on (Hunter's date). R2.1-R2.3, R3.6: free filters first, rank,
    then for each in turn: our own look at the page, then valid."""
    data, err = _billable(session, bid, brand_id, conn, "search", "domain-search",
                          {"domain": domain, "type": "personal", "seniority": "executive,senior", "limit": 10,
                           "provenance": "found"},
                          gate=gate, transport=transport, budget=budget, sleep=sleep)
    if err:
        return None, err
    moment = now()
    # Our own lists and today's gatekeeper allowance, before any fetch or
    # verification is spent on someone who could not be kept (Codex code review 1).
    people = [p for p in candidates(data, domain, moment)
              if allowed(p["email"], contact_type(p["email"], p["name"], p["role"]))]
    if not people:
        return None, ("Hunter had no one published and usable at this company", False)
    verifies = 0
    for person in rank(people, contact_type):
        if not budget.ok():
            return None, ("Hunter's time for this run is used", True)
        seen_on = None
        for uri in person["sources"][:MAX_FETCHES_PER_PERSON]:
            got = fetch_text(uri)
            if got and urlparse(got[1]).scheme == "https" and address_on(got[0], person["email"]):
                seen_on = got[1]
                break
        if not seen_on:
            continue                        # not published where Hunter says, now
        verified_on = person["searched_valid"]
        if verified_on is None:
            if verifies >= MAX_VERIFY_PER_LEAD:
                break
            verifies += 1
            data, err = _billable(session, bid, brand_id, conn, "verify", "email-verifier", {"email": person["email"]},
                                  gate=gate, transport=transport, budget=budget, sleep=sleep, email=person["email"])
            if err:
                if err[1]:
                    return None, err
                continue
            verified_on = verifier_valid(data, person["email"], now())
            if verified_on is None:
                continue
        return {"email": person["email"], "name": person["name"], "role": person["role"], "source_url": seen_on,
                "verified_on": verified_on}, None
    return None, ("Hunter had no one published and verified at this company", False)
