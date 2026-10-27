"""OUT-10 — Aria-led prospect research (docs/OUT-10-TICKET.md).

The pattern is Mike's local Byron system: plain, predictable code around ONE
creative step. Aria builds a tight brief per business (approved audience,
today's area from a rotation wheel, an exclusion list, lessons from the
business's own results); the model searches the web; then every candidate is
VERIFIED BY CODE before anything is stored:

  * the email appears on the page the model cited (Business Hero fetches it);
  * the domain has a mail server; it is not free webmail;
  * nobody already held, contacted or opted out (email and company domain);
  * an active company at Companies House of a corporate type. PECR lets a
    business email corporate subscribers with an opt-out; sole traders and
    ordinary partnerships are individuals and need consent, so they are kept
    for review and never made eligible (decision A).

Mike's quota: 20 new contacts a business a weekday, at least 10 named
decision-makers — decision-makers first, gatekeepers only fill, never more
than 10. Spend is capped per month (default £20). Nothing here sends.
"""

import ipaddress
import logging
import os
import re
import socket
from datetime import datetime, timedelta
from typing import Callable, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import text

from services import outreach_send as send
from services import outreach_setup as setup
from services.chase_replies import _address, _parse
from services import ai_costs, ai_router
from services.metering import period_for

logger = logging.getLogger(__name__)
LONDON = ZoneInfo("Europe/London")
KEY = "outreach_research"
DAILY_TARGET, MIN_DECISION_MAKERS, MAX_GATEKEEPERS = 20, 10, 10
MAX_ATTEMPTS = 3
DEFAULT_CAP_PENCE = 2000                 # decision C: £20 a month, editable
MIN_CAP_PENCE, MAX_CAP_PENCE = 2000, 100000   # OUT-18 (Mike): per brand, never below £20
# Every search attempt reserves a realistic amount before it is sent and is
# settled to its real cost after (Mike's option B, 25 Oct 2026). Reserving the
# THEORETICAL maximum of an agentic search (each search can trigger another
# pass over a million-token context) would leave a brand's £20 budget unusable;
# instead an overrun is recorded, the brand stops naturally once its budget is
# used, and only a cost beyond the theoretical maximum (a bug or a price
# change) pauses it. A search that fails keeps its reservation.


def research_model() -> str:
    return ai_router.models("research").get("openai", "gpt-6.1-sol")


def max_search_pence(model: Optional[str] = None) -> int:
    """The theoretical maximum of one search on OpenAI's research model."""
    return ai_router.max_search_pence("openai", model or research_model())


def search_reserve_pence() -> int:
    return ai_router.search_reserve_pence()


def impossible_search_pence() -> int:
    """More than any search could cost; with no provider configured, the
    primary research model's theoretical maximum."""
    return ai_router.impossible_pence() or max_search_pence()


SEARCH_RESERVE_PENCE = search_reserve_pence()   # the default, for readers and tests
METER = "outreach_research_pence"
PILOT_ENROLMENTS = 5                     # decision E: OUT-8's pilot limit for now


def pilot_enrolments() -> int:
    """Decision E: 5 active contacts per campaign for the first week of the
    restart, then raised to match capacity. OUTREACH_PILOT_ENROLMENTS sets it
    without a deploy; 0 lifts it (the inbox's capacity then decides). Before
    lifting it, index `prepare`'s scan of open cards (OUT-8 ticket, note 2)."""
    raw = os.environ.get("OUTREACH_PILOT_ENROLMENTS", "").strip()
    try:
        value = int(raw) if raw else PILOT_ENROLMENTS
    except ValueError:
        value = PILOT_ENROLMENTS
    return value if value >= 0 else PILOT_ENROLMENTS
EXCLUSION_CAP = 400                      # steers the model; code checks guarantee
NOTICE_WITHIN = timedelta(days=30)       # UK GDPR Article 14: within a month
RETENTION = timedelta(days=365)
EVIDENCE_LIFE = timedelta(days=90)
ROLE_LOCALS = {"info", "hello", "contact", "enquiries", "enquiry", "admin", "office", "reception", "sales",
               "team", "mail", "studio", "bookings", "booking", "support", "accounts", "general", "gym"}
SENIOR = ("director", "owner", "founder", "co-founder", "managing", "md", "ceo", "chief", "manager", "head",
          "partner", "principal", "proprietor", "chair", "president", "lead")
# Corporate bodies only. A limited partnership is not one (Codex OUT-10 review 1).
CORPORATE_TYPES = {"ltd", "plc", "llp", "private-unlimited", "private-limited-guarant-nsc",
                   "private-limited-guarant-nsc-limited-exemption", "private-limited-shares-section-30-exemption",
                   "old-public-company", "royal-charter", "industrial-and-provident-society",
                   "registered-society-non-jurisdictional", "charitable-incorporated-organisation",
                   "scottish-charitable-incorporated-organisation", "uk-establishment"}


def now() -> datetime:
    return send.now()


# ----------------------------------------------------------- settings doc ---

def _doc(session, bid: str) -> dict:
    return setup._settings_doc(session, bid)


def _config(doc: dict) -> dict:
    cfg = dict(doc.get(KEY) or {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("monthly_cap_pence", DEFAULT_CAP_PENCE)
    cfg.setdefault("rotation", {})
    cfg.setdefault("lessons", [])
    return cfg


def _save_config(session, bid: str, cfg: dict) -> None:
    doc = _doc(session, bid)
    doc[KEY] = cfg
    setup._save_settings_doc(session, bid, doc)


def _brand_config(cfg: dict, brand_id) -> dict:
    """One brand's research settings (OUT-18). A business-level setting from
    before OUT-18 is the starting value, never below the £20 minimum."""
    b = dict((cfg.get("brands") or {}).get(str(brand_id)) or {})
    b.setdefault("enabled", bool(cfg.get("enabled", False)))
    b.setdefault("monthly_cap_pence", max(MIN_CAP_PENCE, int(cfg.get("monthly_cap_pence") or DEFAULT_CAP_PENCE)))
    b.setdefault("lessons", list(cfg.get("lessons") or []))
    return b


def _put_brand(cfg: dict, brand_id, values: dict) -> None:
    cfg.setdefault("brands", {})[str(brand_id)] = values


def _brands(session, bid: str) -> list:
    return send.rows(session, "outreach_brands", bid, "ORDER BY created_at, id")


def configure(session, business, user, data: dict) -> dict:
    """Owner-only: one brand's research switch and monthly budget."""
    setup._authority(session, business, user, growth=bool(data.get("enabled", True)))
    bid = str(business.id)
    send.require(data.get("brand_id"), "Choose the brand this research is for", 422)
    brand = send.one(session, "outreach_brands", bid, data["brand_id"])
    _lock(session, bid)   # read-modify-write of the shared config, serialised with research's own saves
    cfg = _config(_doc(session, bid))
    b = _brand_config(cfg, brand["id"])
    if "enabled" in data:
        b["enabled"] = bool(data["enabled"])
        if b["enabled"]:
            b.pop("paused_reason", None)
    if "monthly_cap_pence" in data:
        cap = int(data["monthly_cap_pence"])
        send.require(MIN_CAP_PENCE <= cap <= MAX_CAP_PENCE,
                     "A brand's monthly research budget is £20–£1,000", 422)
        b["monthly_cap_pence"] = cap
    _put_brand(cfg, brand["id"], b)
    _save_config(session, bid, cfg)
    session.commit()
    return {"brand_id": str(brand["id"]), "enabled": b["enabled"], "monthly_cap_pence": b["monthly_cap_pence"]}


def save_lessons(session, business, user, notes: list, *, brand_id) -> dict:
    """Owner-only: Aria's notes for one brand, edited by the owner."""
    setup._authority(session, business, user, growth=False)
    bid = str(business.id)
    brand = send.one(session, "outreach_brands", bid, brand_id)
    cleaned = [str(n).strip()[:300] for n in (notes or []) if str(n).strip()][:30]
    _lock(session, bid)
    cfg = _config(_doc(session, bid))
    b = _brand_config(cfg, brand["id"])
    b["lessons"] = cleaned
    _put_brand(cfg, brand["id"], b)
    _save_config(session, bid, cfg)
    session.commit()
    return {"brand_id": str(brand["id"]), "lessons": cleaned}


def status(session, business) -> dict:
    from services import outreach_allowance
    bid = str(business.id)
    cfg = _config(_doc(session, bid))
    moment = now()
    brands = []
    for brand in _brands(session, bid):
        b = _brand_config(cfg, brand["id"])
        brands.append({"brand_id": str(brand["id"]), "name": brand["name"], "enabled": b["enabled"],
                       "monthly_cap_pence": b["monthly_cap_pence"], "spent_pence": _spent(session, bid, moment, brand["id"]),
                       "paused_reason": b.get("paused_reason"), "lessons": b["lessons"],
                       # OUT-19 B: how much of the hidden allowance is used, never the figure
                       "allowance_used_percent": outreach_allowance.used_percent(session, bid, brand["id"], moment),
                       "lessons_from_results": lessons(session, business, brand["id"])[:10]})
    session.rollback()
    return {"brands": brands, "enabled": any(b["enabled"] for b in brands),
            "daily_target_per_brand": DAILY_TARGET, "min_cap_pence": MIN_CAP_PENCE,
            "last_run": cfg.get("last_run"), "summary": cfg.get("summary")}


# ------------------------------------------------------------ the learning ---

def performance(session, business, brand_id=None) -> list:
    """The business's own outcomes by sector, area and contact type, from
    existing tables only — the "training table". With a brand, only the
    contacts found for that brand's audiences (OUT-18)."""
    bid = str(business.id)
    mine = None
    if brand_id:
        mine = {str(r[0]) for r in session.execute(text(
            "SELECT p.id FROM outreach_prospects p JOIN outreach_compliance c ON c.business_id = p.business_id "
            "AND c.id = p.lia_id WHERE p.business_id = :b AND c.brand_id = :br"), {"b": bid, "br": str(brand_id)})}
    facts = {}
    for pid, kind, value in session.execute(text(
            "SELECT prospect_id, fact_type, fact_value FROM outreach_evidence WHERE business_id = :b "
            "AND fact_type IN ('segment', 'region', 'contact_type')"), {"b": bid}):
        facts.setdefault(str(pid), {})[kind] = value
    sent = {str(r[0]) for r in session.execute(text(
        "SELECT DISTINCT prospect_id FROM outreach_messages WHERE business_id = :b AND direction = 'outbound' "
        "AND state IN ('accepted', 'unknown')"), {"b": bid})}
    replies = {}
    for pid, category in session.execute(text(
            "SELECT prospect_id, category FROM outreach_replies WHERE business_id = :b"), {"b": bid}):
        replies.setdefault(str(pid), []).append(category or "")
    rows = {}
    for pid in sent:
        if mine is not None and pid not in mine:
            continue
        f = facts.get(pid, {})
        key = (f.get("segment") or "unknown", f.get("region") or "unknown", f.get("contact_type") or "unknown")
        row = rows.setdefault(key, {"segment": key[0], "region": key[1], "contact_type": key[2],
                                    "sent": 0, "replied": 0, "positive": 0, "bounced": 0})
        row["sent"] += 1
        cats = replies.get(pid, [])
        row["replied"] += 1 if any(c not in ("bounce", "out_of_office") for c in cats) else 0
        row["positive"] += 1 if any(c in ("interested", "question", "referral") for c in cats) else 0
        row["bounced"] += 1 if "bounce" in cats else 0
    session.rollback()
    return sorted(rows.values(), key=lambda r: (-r["positive"], -r["replied"], -r["sent"]))


def lessons(session, business, brand_id=None) -> list:
    out = []
    for r in performance(session, business, brand_id):
        where = f"{r['segment']} in {r['region']} ({r['contact_type'].replace('_', ' ')})"
        if r["positive"]:
            out.append(f"Do more of: {where} — {r['positive']} of {r['sent']} replied with interest.")
        elif r["sent"] >= 5 and not r["replied"]:
            out.append(f"Avoid: {where} — {r['sent']} contacted, no replies.")
        elif r["bounced"] >= 2:
            out.append(f"Check addresses for: {where} — {r['bounced']} bounced.")
    notes = _brand_config(_config(_doc(session, str(business.id))), brand_id)["lessons"] if brand_id else []
    session.rollback()
    return out[:10] + [f"Owner note: {n}" for n in notes]


# ---------------------------------------------------------------- the plan ---

def _audience(session, bid: str, compliance_id, moment: Optional[datetime] = None) -> tuple:
    """The approved audience, only while its approval is CURRENT."""
    moment = moment or now()
    lia = send.one(session, "outreach_compliance", bid, compliance_id)
    send.require(lia["decision"] == "approved" and lia["reviewer"] and _parse(lia["reviewed_at"])
                 and _parse(lia["reviewed_at"]) <= moment
                 and _parse(lia["review_due_at"]) and moment < _parse(lia["review_due_at"]),
                 "This audience's approval is missing or out of date", 409)
    rules = (_doc(session, bid).get(setup.AUDIENCE_KEY) or {}).get(str(lia["id"])) or {}
    return lia, rules


def _still_allowed(session, bid: str, compliance_id, moment: datetime) -> Optional[str]:
    """Why research may not run or store right now, or None. Read FRESH
    (Codex OUT-10 review 1): an active business with current outreach
    access, setup finished, outreach not paused, research on, and a current
    audience approval."""
    from fastapi import HTTPException
    from auth import assert_feature_access
    business = setup.load_business_row(session, bid)
    if business is None:
        return "Business unavailable"
    business.feature_flags = send.loads(business.feature_flags) or {}
    business.trial_ends_at = _parse(business.trial_ends_at)
    try:
        assert_feature_access(business, "outreach")
    except HTTPException:
        return "Outreach isn't available on this account"
    doc = _doc(session, bid)
    if not (doc.get(setup.SETUP_KEY) or {}).get("finished_at"):
        return "Outreach setup isn't finished"
    settings = send.rows(session, "outreach_settings", bid)
    if not settings or settings[0]["pause_all"]:
        return "Outreach is paused"
    try:
        lia, _ = _audience(session, bid, compliance_id, moment)
    except send.ActionRefused as exc:
        return exc.detail
    if not _brand_config(_config(doc), lia["brand_id"])["enabled"]:
        return "Research is switched off for this brand"
    return None


def _wheel(rules: dict) -> list:
    regions = [r for r in (rules.get("regions") or []) if r] or ["the UK"]
    return regions + [f"areas neighbouring {r}" for r in regions if r != "the UK"]


def _held(session, bid: str) -> tuple:
    rows = session.execute(text("SELECT company, domain, email FROM outreach_prospects WHERE business_id = :b"),
                           {"b": bid}).fetchall()
    domains, companies = set(), set()
    for company, domain, email in rows:
        d = (domain or (_address(email).split("@")[-1] if email else "")).lower()
        if d and d not in setup.FREE_WEBMAIL:
            domains.add(d)
        if company:
            companies.add(str(company).strip())
    return domains, companies


def plan(session, business, compliance_id, *, moment: Optional[datetime] = None, attempt: int = 1,
         wanted: Optional[int] = None) -> dict:
    """`wanted`: how many new contacts the brand's inbox has room for today
    (OUT-19 D). The brief asks for some spare, since verification turns some
    away; only `wanted` are kept."""
    bid = str(business.id)
    target = DAILY_TARGET if wanted is None else max(1, min(DAILY_TARGET, wanted * 2, wanted + 5))
    named = max(1, min(MIN_DECISION_MAKERS, (target + 1) // 2))
    lia, rules = _audience(session, bid, compliance_id, moment)
    brand = send.one(session, "outreach_brands", bid, lia["brand_id"])
    cfg = _config(_doc(session, bid))
    wheel = _wheel(rules)
    base = wheel[int(cfg["rotation"].get(str(lia["id"]), 0)) % len(wheel)]
    area = base if attempt == 1 else (f"{base} and the surrounding region" if attempt == 2 else "anywhere in the UK")
    domains, companies = _held(session, bid)
    learned = lessons(session, business, lia["brand_id"])
    excluded = sorted(domains)[:EXCLUSION_CAP]
    brief = f"""RESEARCH — find up to {target} NEW business contacts for {brand['name']} ({getattr(business, 'name', 'this business')}).

Who: {rules.get('description', '')}
Sectors: {', '.join(rules.get('segments') or []) or 'as described'}
Area for this search: {area}

QUALITY BAR (mandatory):
- Real organisations only. The contact email MUST be shown on the organisation's own website; give the exact
  page URL where it appears. NEVER guess, construct or invent an email address.
- Prefer NAMED decision-makers: owner, director, founder, managing director, practice/operations manager,
  head of department. At least {named} should be named decision-makers.
- A role address (info@, hello@, reception@) is acceptable only when the organisation is highly relevant and no
  named decision-maker is findable; mark it contact_type "gatekeeper".
- Limited companies, LLPs and PLCs only (give the Companies House number when you can find it). Skip sole
  traders and partnerships.
- Prefer smaller, independent organisations over national chains.

ALREADY HELD OR CONTACTED — do NOT return these domains:
{chr(10).join(excluded) if excluded else '(none yet)'}

WHAT HAS WORKED FOR THIS BRAND:
{chr(10).join(learned) if learned else '(no results yet)'}

Return ONLY a JSON object: {{"candidates": [{{"company", "company_number", "contact_name", "role",
"contact_email", "contact_type" ("decision_maker" or "gatekeeper"), "source_url", "region", "segment",
"fit_reason" (one sentence)}}]}}"""
    session.rollback()
    return {"area": area, "attempt": attempt, "exclusions": excluded, "lessons": learned, "brief": brief,
            "target": target, "min_decision_makers": named}


# ---------------------------------------------------------------- spending ---

def meter_for(brand_id) -> str:
    """Each brand's own monthly research meter (OUT-18)."""
    return f"{METER}:{brand_id}"


def _spent(session, bid: str, moment: datetime, brand_id) -> int:
    """This month's spend for one brand. Spend on the business-wide meter
    from before OUT-18 counts against every brand (fail closed)."""
    value = session.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                                 "AND meter IN (:m, :legacy) AND period = :p"),
                            {"b": bid, "m": meter_for(brand_id), "legacy": METER, "p": period_for(moment)}).scalar()
    return int(float(value or 0))


def _spend(session, bid: str, moment: datetime, pence: int, brand_id) -> None:
    """Add (or, to settle a reservation, subtract) one brand's spend this month."""
    if pence == 0:
        return
    params = {"b": bid, "m": meter_for(brand_id), "p": period_for(moment), "v": int(pence), "at": moment}
    updated = session.execute(text("UPDATE usage_meters SET value = value + :v, updated_at = :at "
                                   "WHERE business_id = :b AND meter = :m AND period = :p"), params)
    if not updated.rowcount:
        session.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                             "VALUES (:b, :m, :p, :v, :at)"), params)


# ------------------------------------------------------------ verification ---

def _contact_type(email: str, name: str, role: str) -> str:
    local = email.split("@")[0].lower()
    if local in ROLE_LOCALS or not name.strip():
        return "gatekeeper"
    words = re.findall(r"[a-z\-]+", role.lower())
    return "decision_maker" if any(w in SENIOR for w in words) else "gatekeeper"


def _name_tokens(value: str) -> set:
    # Companies House officers read "TAYLOR, Sam James"; people read "Sam Taylor".
    return {t for t in re.findall(r"[a-z]+", value.lower()) if len(t) > 1}


def _officer_match(name: str, officers: list) -> bool:
    """A role is verified only when the contact's SURNAME is the officer's
    surname and their first name is among the officer's forenames (Companies
    House writes "SURNAME, Forenames"). Codex OUT-10 reviews 1 and 2."""
    def whole(value: str) -> str:   # a surname compared as a whole, hyphens kept
        return " ".join(re.sub(r"[^a-z\- ]", " ", value.lower()).split())
    words = whole(name).split()
    if len(words) < 2:
        return False
    first, last = words[0], words[-1]
    for officer in officers or []:
        surname_part, _, forename_part = str(officer).partition(",")
        if not forename_part:   # no comma: treat the last word as the surname
            parts = surname_part.split()
            surname_part, forename_part = (parts[-1] if parts else ""), " ".join(parts[:-1])
        if whole(surname_part) == last and first in whole(forename_part).split():
            return True
    return False


EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+'-])([A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?![A-Za-z0-9-])")


# Every character legal in an address's local part (RFC 5322 atext, plus '.').
ATEXT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'*+-/=?^_`{|}~.")
# A quote or backslash before the address means a quoted local part
# ("x@y"@z): the address is part of a different mailbox (review 3).
ATEXT |= {'"', "\\"}


def _address_on(page: str, email: str) -> bool:
    """The COMPLETE address appears: the character before it cannot belong to
    a longer local part, and the domain does not continue after it (Codex
    OUT-10 reviews 1 and 2)."""
    text_, wanted = (page or "").lower(), email.lower()
    start = text_.find(wanted)
    while start != -1:
        end = start + len(wanted)
        before = text_[start - 1] if start else ""
        after = text_[end:end + 2]
        continues = bool(after) and (after[0].isalnum() or after[0] == "-"
                                     or (after[0] == "." and len(after) > 1 and (after[1].isalnum() or after[1] == "-")))
        if before not in ATEXT and not continues:
            return True
        start = text_.find(wanted, start + 1)
    return False


def _owns(host: str, domain: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def _page(fetch: Callable, url: str) -> tuple:
    """(text, final url) from a fetcher returning text or {"url", "text"}."""
    got = fetch(url) if url else None
    if isinstance(got, dict):
        return got.get("text") or "", got.get("url") or url
    return got or "", url


def _legal_name(value: str) -> str:
    out = re.sub(r"[^a-z0-9 ]", " ", str(value or "").lower().replace("&", " and "))
    out = re.sub(r"\b(limited|ltd|plc|llp|the|company|co)\b", " ", out)
    return " ".join(out.split())


def _verify(session, bid: str, c: dict, held: dict, fetch: Callable, mx: Callable, companies: Callable) -> dict:
    """One candidate -> {"ok": bool, "review": bool, "reason", ...facts}. Never trusts the model."""
    email = _address(c.get("contact_email") or "")
    company = str(c.get("company") or "").strip()[:200]
    if "@" not in email or not company:
        return {"ok": False, "reason": "no usable company or email"}
    domain = email.split("@")[-1]
    if domain in setup.FREE_WEBMAIL:
        return {"ok": False, "reason": "a business email address is needed, not free webmail"}
    key = send.suppression_digest(bid, "email", email)
    if key in held["keys"] or email in held["seen"]:
        return {"ok": False, "reason": "already held"}
    if domain in held["domains"]:
        return {"ok": False, "reason": "company already held or contacted"}
    if _suppressed(session, bid, key, domain):
        return {"ok": False, "reason": "opted out"}
    source = str(c.get("source_url") or "")
    if not _owns(urlparse(source).hostname or "", domain):
        return {"ok": False, "reason": "the source isn't the company's own website"}
    page, final = _page(fetch, source)
    if not _owns(urlparse(final).hostname or "", domain):
        return {"ok": False, "reason": "the source isn't the company's own website (redirected away)"}
    if not _address_on(page, email):
        return {"ok": False, "reason": "email not on the cited page"}
    if not mx(domain):
        return {"ok": False, "reason": f"no mail server for {domain}"}
    name, role = str(c.get("contact_name") or "").strip()[:120], str(c.get("role") or "").strip()[:120]
    base = {"email": email, "email_key": key, "domain": domain, "company": company, "name": name, "role": role,
            "contact_type": _contact_type(email, name, role), "source_url": source}
    review = {"ok": False, "review": True, **base,
              "reason": "kept for review: couldn't confirm a registered company that matches this website "
                        "(sole traders and partnerships need consent under PECR)"}
    number = str(c.get("company_number") or "").strip().upper()
    record = companies(number) if re.fullmatch(r"[A-Z0-9]{8}", number) else None
    if not record or _legal_name(record.get("name")) != _legal_name(company):
        record = companies(company)   # never trust a model-supplied number for a different name
    if record and str(record.get("status") or "").lower() != "active":
        return {"ok": False, "reason": f"company is not active ({record.get('status') or 'no status'})"}
    if not record or str(record.get("type", "")).lower() not in CORPORATE_TYPES \
            or _legal_name(record.get("name")) != _legal_name(company):
        return review
    # The company's own website must carry a proper legal disclosure binding
    # the REGISTERED NAME to the REGISTERED NUMBER in a registration statement
    # ("registered in England…, company number…"), in its VISIBLE text; and
    # must not describe a sole trader or partnership. Anything less is review
    # (Codex OUT-10 reviews 2 and 3).
    registered_number = str(record.get("number") or "").upper()
    registered_name = _legal_name(record.get("name"))
    def discloses(raw):
        if not re.fullmatch(r"[A-Z0-9]{8}", registered_number) or not registered_name:
            return False
        text_ = _visible_text(raw)
        flat = text_.lower()
        if SOLE_TRADER.search(flat):
            return False
        for m in TRADING_AS.finditer(flat):
            # "Studio 1 Ltd trading as Fitness Club" is the company's own
            # brand; any other "trading as" is someone else trading.
            if not re.search(re.escape(registered_name), _legal_name(flat[max(0, m.start() - 80): m.start()])):
                return False
        short = registered_number.lstrip("0")
        for m in re.finditer(r"(?<![A-Za-z0-9])(" + re.escape(registered_number)
                             + (("|" + re.escape(short)) if short and short.isdigit() else "") + r")(?![A-Za-z0-9])", text_,
                             flags=re.I):
            window = flat[max(0, m.start() - 250): m.end() + 100]
            # Only a credit LEADING UP TO the number makes it a third party's;
            # a designer credit after the company's own disclosure doesn't.
            if CREDIT.search(flat[max(0, m.start() - 150): m.end()]):
                continue
            if REGISTRATION.search(window) and re.search(r"(?<![a-z0-9])" + re.escape(registered_name)
                                                         + r"(?![a-z0-9])", _legal_name(window)):
                return True
        return False
    if not discloses(page):
        home, home_final = _page(fetch, f"https://{urlparse(final).hostname}/")
        if not (_owns(urlparse(home_final).hostname or "", domain) and discloses(home)):
            return review
    def trading_names(raw):
        return [m.group(2).strip() for m in re.finditer(
            r"(trading as|t/a)\s+([A-Za-z0-9][A-Za-z0-9 &'\-]{1,60}?)(?=[.,;:]|\s+(registered|company)\b|$)",
            _visible_text(raw), flags=re.I)]
    trading = trading_names(page)
    if not _domain_fits(domain, record.get("name") or company, trading):
        # The trading name may be disclosed on the home page instead.
        home, home_final = _page(fetch, f"https://{urlparse(final).hostname}/")
        if _owns(urlparse(home_final).hostname or "", domain):
            trading += trading_names(home)
        if not _domain_fits(domain, record.get("name") or company, trading):
            return review
    return {"ok": True, **base, "number": registered_number,
            "role_verified": _officer_match(name, record.get("officers") or []) if name else False,
            "company_type": record.get("type")}


# The business describing ITSELF as unincorporated — not ordinary wording such
# as "in partnership with local schools" (Codex OUT-10 review 5).
SOLE_TRADER = re.compile(r"\bsole trader\b|\bself[- ]employed\b"
                         r"|\b(we are|we're|is|are)\s+(a|an)\s+(\w+\s+)?partnership\b"
                         r"|\b(general|ordinary|limited)\s+partnership\b")
TRADING_AS = re.compile(r"\btrading as\b|\bt/a\b")
# A third party's credit (the web designer, host or platform) is about THEM,
# never the site's operator (Codex OUT-10 review 4).
CREDIT = re.compile(r"\b(designed|built|developed|created|hosted|made|maintained|managed|powered|produced)"
                    r"(\s+(and|&)\s+\w+)?\s+by\b|\bsite\s+by\b|\bweb\s*(site\s+)?design(ed)?\s*(by\b|:)"
                    r"|\bdesign(ed)?\s+by\b|\bwebsite\s+by\b|\bhosting\s*(by\b|:)")
GENERIC = {"ltd", "limited", "plc", "llp", "the", "company", "co", "group", "uk", "and", "of", "services"}


def _significant(name: str) -> list:
    return [t for t in re.findall(r"[a-z0-9]+", str(name or "").lower()) if t not in GENERIC]


def _domain_fits(domain: str, company: str, trading_names: list) -> bool:
    """Mike's sanity check (24 Oct 2026): the email's domain must fit the
    company's name or a trading name it discloses, e.g. studio1.example for
    Studio 1 Ltd. A personal domain that fits neither goes to review."""
    labels = [l for l in domain.lower().split(".") if l not in ("www", "mail")]
    label = re.sub(r"[^a-z0-9]", "", labels[0] if labels else "")
    if not label:
        return False
    for name in [company, *trading_names]:
        words = _significant(name)
        if not words:
            continue
        joined = "".join(words)
        if joined and joined in label:
            return True
        if len(words) >= 2 and "".join(words[:2]) in label:
            return True
        if any(len(w) >= 5 and w in label for w in words):
            return True
        initials = "".join(w[0] for w in words)
        if len(words) >= 2 and label.startswith(initials) and len(initials) >= 2:
            return True
    return False
REGISTRATION = re.compile(r"registered in (england|wales|scotland|northern ireland)|company (registration )?(number|no\b)"
                          r"|registration (number|no\b)|registered (number|no\b)|registered office|companies house")


def _visible_text(raw: str) -> str:
    """What a visitor reads: scripts, styles and markup (attributes such as
    image file names) removed, entities decoded."""
    import html as _html
    out = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw or "")
    out = re.sub(r"(?s)<[^>]+>", " ", out)
    return " ".join(_html.unescape(out).split())


def _suppressed(session, bid: str, key: str, domain: str) -> bool:
    return bool(send.rows(session, "outreach_suppressions", bid,
                          "AND ((key_type = 'email' AND key_digest = :e) OR (key_type = 'domain' AND key_digest = :d))",
                          {"e": key, "d": send.suppression_digest(bid, "domain", domain)}))


def _today_counts(session, bid: str, moment: datetime, brand_id) -> dict:
    """Contacts research kept this UK day for one brand (eligible or held for
    review: both are personal data collected), by type —
    shared by every audience of that brand (OUT-18: 20 a day per brand), read
    from the database (Codex OUT-10 review 1)."""
    local = moment.astimezone(LONDON)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(LONDON).isoformat()
    counts = {"decision_maker": 0, "gatekeeper": 0}
    for (kind,) in session.execute(text(
            "SELECT e.fact_value FROM outreach_prospects p JOIN outreach_evidence e "
            "ON e.business_id = p.business_id AND e.prospect_id = p.id AND e.fact_type = 'contact_type' "
            "JOIN outreach_compliance c ON c.business_id = p.business_id AND c.id = p.lia_id "
            "WHERE p.business_id = :b AND c.brand_id = :br AND p.eligibility IN ('eligible', 'review') "
            "AND p.captured_at >= :start"),
            {"b": bid, "br": str(brand_id), "start": _parse(start)}):
        if kind in counts:
            counts[kind] += 1
    return counts


def capacity(session, bid: str, brand_id, moment: datetime, audience_hash: Optional[str] = None) -> dict:
    """OUT-19 D (Mike's decision 1): research finds only as many new contacts
    as can be emailed for the first time today, and each one it keeps takes a
    place in a campaign for its audience at once (Codex OUT-19 D review 1).

    Everything already spoken for today is counted first, whatever the state
    of its campaign now: cold emails sent or held today, follow-ups due by the
    end of today and contacts waiting for their first email (an email already
    being sent is counted once, as a send). Then, for each ready campaign of
    this brand and audience, its free places are the smallest of:
    its own cap less its use; the pilot enrolment limit less its contacts;
    and what its inbox has left (an inbox is shared by every campaign and
    brand on it). `room` is the sum, never above the brand's 20 (or the
    owner's lower cap) less the brand's use, nor above the daily target less
    the contacts found today. Replies are outside all of this (OUT-19 E).
    Read-only; the caller holds the business lock when it must not change."""
    from services import metering
    local = moment.astimezone(LONDON)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = start + timedelta(days=1)
    br = str(brand_id)
    found = _today_counts(session, bid, moment, brand_id)
    out = {"room": 0, "places": [], "campaigns": 0, "found_today": found, "sent_today": 0,
           "followups_due": 0, "waiting": 0, "inbox_left": 0}
    settings = send.one(session, "outreach_settings", bid)
    if not settings or settings["pause_all"]:
        return out
    campaigns = send.rows(session, "outreach_campaigns", bid, "ORDER BY created_at, id")
    by_id = {str(c["id"]): c for c in campaigns}
    sent, sent_on_box = {}, {}
    for cid, mailbox_id, n in session.execute(text(
            "SELECT m.campaign_id, u.mailbox_id, count(*) FROM outreach_usage_events u JOIN outreach_messages m "
            "ON m.business_id = u.business_id AND m.id = u.message_id WHERE u.business_id = :b "
            "AND u.kind = 'outreach_emails_sent' AND (m.kind IS NULL OR m.kind <> 'bespoke') AND u.local_send_date = :d "
            "AND u.state IN ('reserved', 'committed', 'unknown') GROUP BY m.campaign_id, u.mailbox_id"),
            {"b": bid, "d": local.date().isoformat()}):
        sent[str(cid)] = sent.get(str(cid), 0) + int(n)
        sent_on_box[str(mailbox_id)] = sent_on_box.get(str(mailbox_id), 0) + int(n)
    queued, members = {}, {}
    for eid, cid, step, due, busy in session.execute(text(
            "SELECT e.id, e.campaign_id, e.next_step, e.next_due_at, EXISTS (SELECT 1 FROM outreach_messages m "
            "WHERE m.business_id = e.business_id AND m.enrolment_id = e.id AND m.direction = 'outbound' "
            "AND m.state IN ('claimed', 'unknown')) FROM outreach_enrolments e WHERE e.business_id = :b "
            "AND e.state IN ('pending', 'active')"), {"b": bid}):
        members[str(cid)] = members.get(str(cid), 0) + 1
        if busy or step is None:
            continue                      # being sent now: already counted as a send
        q = queued.setdefault(str(cid), [0, 0])
        if int(step) == 0:
            q[1] += 1
        elif due is not None and _parse(due) < tomorrow:
            q[0] += 1
    def used(cid):
        due, waiting = queued.get(cid, [0, 0])
        return sent.get(cid, 0) + due + waiting
    mine = [c for c in campaigns if str(c["brand_id"]) == br]
    out.update(sent_today=sum(sent.get(str(c["id"]), 0) for c in mine),
               followups_due=sum(queued.get(str(c["id"]), [0, 0])[0] for c in mine),
               waiting=sum(queued.get(str(c["id"]), [0, 0])[1] for c in mine))
    brand_left = min(20, int(settings["business_daily_cap"])) - sum(used(str(c["id"])) for c in mine)
    inbox_left = {}
    for mailbox_id in {str(c["mailbox_id"]) for c in campaigns}:
        boxes = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": mailbox_id})
        cap = metering.mailbox_daily_cap(boxes[0]) if len(boxes) == 1 else 0
        queued_here = sum(sum(queued.get(cid, [0, 0])) for cid, c in by_id.items() if str(c["mailbox_id"]) == mailbox_id)
        inbox_left[mailbox_id] = max(0, cap - sent_on_box.get(mailbox_id, 0) - queued_here)
    # Contacts kept today that hold no place (held for the owner's review), of
    # EVERY brand, use the inbox of a ready campaign for their audience, so a
    # brand sharing that inbox sees them too (Codex OUT-19 D review 3).
    unplaced, mine_unplaced, on_campaign = 0, 0, {}
    for p_brand, audience in session.execute(text(
            "SELECT l.brand_id, l.audience_hash FROM outreach_prospects p JOIN outreach_compliance l "
            "ON l.business_id = p.business_id AND l.id = p.lia_id WHERE p.business_id = :b AND p.captured_at >= :start "
            "AND p.eligibility IN ('eligible', 'review') AND NOT EXISTS (SELECT 1 FROM outreach_enrolments e "
            "WHERE e.business_id = p.business_id AND e.prospect_id = p.id)"), {"b": bid, "start": start}):
        unplaced += 1
        if str(p_brand) == br:
            mine_unplaced += 1
        ready = [c for c in campaigns if str(c["brand_id"]) == str(p_brand) and c["status"] in ("ready", "running")]
        home = next((c for c in ready if c["target_hash"] == audience), ready[0] if ready else None)
        if home is not None:
            # It holds that campaign's place too: its daily cap and its pilot
            # places (Codex OUT-19 D review 4), each counted once.
            on_campaign[str(home["id"])] = on_campaign.get(str(home["id"]), 0) + 1
            if inbox_left.get(str(home["mailbox_id"]), 0) > 0:
                inbox_left[str(home["mailbox_id"])] -= 1
    limit = pilot_enrolments()
    matching = [c for c in mine if c["status"] in ("ready", "running")
                and (audience_hash is None or c["target_hash"] == audience_hash)]
    out["campaigns"] = len(matching)
    for c in matching:
        cid, mailbox_id = str(c["id"]), str(c["mailbox_id"])
        held = on_campaign.get(cid, 0)
        free = max(0, int(c["daily_cap"]) - used(cid) - held)
        if limit:
            free = min(free, max(0, limit - members.get(cid, 0) - held))
        free = min(free, inbox_left[mailbox_id])
        inbox_left[mailbox_id] -= free
        if free:
            out["places"].append([c, free])
    out["inbox_left"] = sum(inbox_left.values())
    out["unplaced_today"] = mine_unplaced
    # The brand's own unplaced contacts also use its 20, whichever inbox they sit on.
    out["room"] = max(0, min(DAILY_TARGET - found["decision_maker"] - found["gatekeeper"], brand_left - mine_unplaced,
                             sum(f for _, f in out["places"])))
    return out


def _no_room_reason(room: dict) -> str:
    if not room["campaigns"]:
        return "No search: this audience has no ready campaign on a healthy inbox to email new contacts"
    return "No search today: this brand's inbox is already full with follow-ups and contacts waiting for their first email"


def _take_place(session, bid: str, room: dict, prospect_id: str, moment: datetime) -> Optional[str]:
    """Enrol a contact just stored into a campaign with a free place, in the
    same transaction (Codex OUT-19 D review 1: a place is taken as the contact
    is kept, never later). Returns the campaign id, or None."""
    from services import outreach_manage
    p = send.one(session, "outreach_prospects", bid, prospect_id, True)
    for place in room["places"]:
        c, free = place
        if free <= 0:
            continue
        try:
            outreach_manage.qualified(session, bid, c, p)
        except send.ActionRefused:
            continue
        send.insert(session, "outreach_enrolments", bid, prospect_id=prospect_id, campaign_id=str(c["id"]),
                    sequence_version=c["sequence_version"], state="active", next_step=0, next_due_at=moment)
        place[1] -= 1
        return str(c["id"])
    return None


def _unstore(session, bid: str, prospect_id: str) -> None:
    """Undo _store in the same transaction (nothing was committed)."""
    session.execute(text("DELETE FROM outreach_evidence WHERE business_id = :b AND prospect_id = :p"),
                    {"b": bid, "p": prospect_id})
    session.execute(text("DELETE FROM outreach_prospects WHERE business_id = :b AND id = :p"), {"b": bid, "p": prospect_id})


SEARCH_KEY = "outreach_research_search"     # one paid search per business at a time
SEARCH_CLAIM = timedelta(minutes=15)


def _claim_search(session, bid: str, mine: Optional[str] = None) -> Optional[str]:
    """Under the business lock: another run's search in progress means this
    one waits, so two runs never pay for the same places (Codex OUT-19 D
    review 1). Taken, and renewed by its owner before each paid search and
    before storing, on the real clock (never a run's fixed moment), and lost
    only if its owner went quiet for 15 minutes (Codex OUT-19 D review 2)."""
    import uuid as _uuid
    moment = now()
    doc = _doc(session, bid)
    held = doc.get(SEARCH_KEY) or {}
    until = _parse(held.get("until"))
    if mine is not None:
        if held.get("token") != mine:
            return None              # lost: another run took it (and may have finished); never taken back
    elif until and moment < until and held.get("token"):
        return None
    token = mine or _uuid.uuid4().hex
    doc[SEARCH_KEY] = {"token": token, "until": (moment + SEARCH_CLAIM).isoformat()}
    setup._save_settings_doc(session, bid, doc)
    return token


def _release_search(session, bid: str, token: Optional[str]) -> None:
    """Under the business lock, in the caller's transaction."""
    if not token:
        return
    doc = _doc(session, bid)
    if (doc.get(SEARCH_KEY) or {}).get("token") == token:
        doc.pop(SEARCH_KEY, None)
        setup._save_settings_doc(session, bid, doc)


def _lock(session, bid: str) -> None:
    """The shared business lock (OUT-6's order) for the store step."""
    if not send.pg(session):
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})
    send.lock_business(session, bid)


def _store(session, bid: str, lia_id: str, c: dict, v: dict, moment: datetime, *, review: bool = False) -> str:
    ident = send.insert(
        session, "outreach_prospects", bid, company=v["company"], name=v["name"] or None, role=v["role"] or None,
        domain=v["domain"], number=v.get("number"), email=v["email"], email_key=v["email_key"],
        subscriber_type="unknown" if review else "corporate", eligibility="review" if review else "eligible",
        lawful_basis=None if review else "legitimate_interests", lia_id=lia_id, stage="new" if review else "ready",
        confidence=None if review else (85 if v.get("role_verified") else 65),
        why_now=str(c.get("fit_reason") or "")[:500] or None, evidence_checked_at=moment, captured_at=moment,
        notice_due_at=moment + NOTICE_WITHIN, retention_due_at=moment + RETENTION)
    common = dict(prospect_id=ident, source_type="web", operation="research", fetched_at=moment,
                  expires_at=moment + EVIDENCE_LIFE, flags=[], adapter_version="out10-v1")
    send.insert(session, "outreach_evidence", bid, **{**common, "operation": "verify"}, source_url=v["source_url"],
                fact_type="email_verification", fact_value=v["email"],
                verification_status=None if review else "valid",
                verification_subject_email_key=None if review else v["email_key"],
                verified_at=None if review else moment)
    facts = {"contact_type": v["contact_type"], "segment": str(c.get("segment") or "")[:80] or "unknown",
             "region": str(c.get("region") or "")[:80] or "unknown"}
    if not review:
        facts.update(role_verified="true" if v.get("role_verified") else "false",
                     companies_house=f"{v.get('number')}|{v.get('company_type')}|active")
    for kind, value in facts.items():
        send.insert(session, "outreach_evidence", bid, **common, source_url=v["source_url"],
                    fact_type=kind, fact_value=value)
    return ident


# -------------------------------------------------------------- enrolment ---

# ------------------------------------------------------------------ the run ---

def _pause_impossible(session, bid: str, brand_id: str, cost, impossible: int, out: dict) -> None:
    """More than any search could cost — a bug or a price change — on either
    settlement path: the full cost is kept and the brand pauses until the owner
    looks. Runs under the settlement's business lock and commits."""
    cfg = _config(_doc(session, bid))
    paused = _brand_config(cfg, brand_id)
    paused["enabled"] = False
    paused["paused_reason"] = f"A search cost {cost}p, more than any search should ({impossible}p)"
    _put_brand(cfg, brand_id, paused)
    _save_config(session, bid, cfg)
    session.commit()
    out["stopped"] = ("Research paused for this brand: a search cost more than any search should. "
                      "Check the prices and the budget, then switch it back on")


def run(session, business, compliance_id, *, search: Optional[Callable] = None, fetch: Optional[Callable] = None,
        mx: Optional[Callable] = None, companies: Optional[Callable] = None,
        moment: Optional[datetime] = None) -> dict:
    """See _run. Whatever fails, a search claim this run holds is given back
    (Codex OUT-19 D review 2)."""
    holder = {"claim": None}
    try:
        return _run(session, business, compliance_id, holder, search=search, fetch=fetch, mx=mx,
                    companies=companies, moment=moment)
    except BaseException:
        session.rollback()
        if holder["claim"]:
            try:
                _lock(session, str(business.id))
                _release_search(session, str(business.id), holder["claim"])
                session.commit()
            except Exception:
                session.rollback()
        raise


def _run(session, business, compliance_id, holder: dict, *, search: Optional[Callable] = None,
         fetch: Optional[Callable] = None, mx: Optional[Callable] = None, companies: Optional[Callable] = None,
         moment: Optional[datetime] = None) -> dict:
    """One research run for one approved audience. Commits its own work.

    Authority is re-read fresh before any spend and again, under the shared
    business lock, before anything is stored. Spend is reserved before each
    search. The day's quota is shared across audiences."""
    moment = moment or now()
    bid = str(business.id)
    out = {"accepted": [], "decision_makers": 0, "gatekeepers": 0, "rejected": [], "attempts": 0,
           "spend_pence": 0, "stopped": None, "enrolled": [], "cards": []}
    if companies is None:
        if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
            out["stopped"] = "Companies House key not configured: no contact can be confirmed as a company"
            return out
        companies = companies_house
    search, fetch, mx = search or web_search, fetch or fetch_page, mx or has_mail_server
    why = _still_allowed(session, bid, compliance_id, moment)
    session.rollback()
    if why:
        out["stopped"] = why
        return out
    lia, rules = _audience(session, bid, compliance_id, moment)
    brand_id = str(lia["brand_id"])
    session.rollback()
    found_new = False
    claim = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Reserve the search's maximum cost first, against the CURRENT budget
        # (re-read every time: lowering it mid-run takes effect at once). The
        # check and the reservation are one step under the business lock, so
        # two runs or an owner's change can never both pass on one balance
        # (Codex OUT-18 review 1).
        _lock(session, bid)
        why = _still_allowed(session, bid, compliance_id, moment)
        if why:
            session.rollback()
            out["stopped"] = why
            break
        # OUT-19 D: is there room to email anyone new today? Checked here,
        # under the same lock as the spend reservation (Codex OUT-19 D review 1).
        room = capacity(session, bid, brand_id, moment, lia["audience_hash"])
        if room["room"] <= 0:
            session.rollback()
            if attempt == 1 and room["found_today"]["decision_maker"] + room["found_today"]["gatekeeper"] < DAILY_TARGET:
                out["stopped"] = _no_room_reason(room)
            break
        claim = _claim_search(session, bid, claim)
        holder["claim"] = claim
        if claim is None:
            session.rollback()
            out["stopped"] = "Another search for this business is running; research carries on in a few minutes"
            break
        if not ai_costs.allowed(session, moment=moment):
            session.rollback()
            out["stopped"] = "Research is paused: the platform's AI spending limit for the month is reached"
            break
        model = research_model()
        try:
            # Enough for every provider the search might fail over to (OUT-19 H);
            # with none configured, the primary model's maximum.
            reserve = ai_router.reserve_pence() if search is web_search else search_reserve_pence()
            impossible = impossible_search_pence()
        except ai_costs.Unpriced:
            session.rollback()
            out["stopped"] = f"Research is paused: no price is set for the research model {model}"
            break
        if not reserve:
            # No provider is configured: nothing can be called, so nothing is
            # reserved or spent (Codex OUT-19 H review 1).
            session.rollback()
            out["stopped"] = "Research is paused: no AI provider is available"
            break
        # OUT-19 B: the brand's AI allowance (a quarter of what it pays) is the
        # hard ceiling, across all its AI spend; the owner's budget below can
        # only lower it.
        from services import outreach_allowance
        if not outreach_allowance.may_research(session, bid, brand_id, moment, reserve):
            out["stopped"] = outreach_allowance.ALLOWANCE_USED
            session.rollback()
            break
        b = _brand_config(_config(_doc(session, bid)), brand_id)
        if not b["enabled"] or _spent(session, bid, moment, brand_id) + reserve > int(b["monthly_cap_pence"]):
            out["stopped"] = "This brand's research budget for the month is reached; research resumes next month"
            session.rollback()
            break
        _spend(session, bid, moment, reserve, brand_id)
        session.commit()
        brief = plan(session, business, compliance_id, moment=moment, attempt=attempt, wanted=room["room"])["brief"]
        out["attempts"] = attempt
        try:
            result = search(brief) or {}
        except Exception as exc:
            # Billable work may have happened: the reservation stays counted,
            # and nothing is retried. An outage never skips an area. Each
            # attempt that reached a provider is recorded at its maximum as an
            # ESTIMATED charge, so the platform limit sees it too (Codex
            # OUT-19 review 1); a search that failed in an unknown way records
            # the reserve; one that found no provider at all records nothing.
            _lock(session, bid)
            attempts = getattr(exc, "calls", None)
            if attempts:
                # Settle against the attempts actually made; release the rest.
                charged = sum(c["pence"] for c in attempts)
                for c in attempts:
                    usage = c.get("usage") or {}
                    ai_costs.record(session, bid, purpose="research", brand_id=brand_id, moment=moment,
                                    pence=c["pence"], estimated=bool(c.get("estimated")), provider=c["provider"],
                                    model=c["model"], input_tokens=int(usage.get("input_tokens") or 0),
                                    output_tokens=int(usage.get("output_tokens") or 0),
                                    tool_calls=int(usage.get("tool_calls") or 0))
            elif isinstance(exc, ai_router.AllProvidersFailed):
                charged = 0          # no provider was reached: nothing was billed
            else:
                charged = reserve    # an unknown failure: keep the whole reserve, as an estimate
                ai_costs.record(session, bid, purpose="research", brand_id=brand_id, moment=moment, pence=reserve,
                                estimated=True, provider="openai", model=model)
            _spend(session, bid, moment, charged - reserve, brand_id)
            out["spend_pence"] += charged
            if charged > impossible:
                _pause_impossible(session, bid, brand_id, charged, impossible, out)   # commits
                break
            session.commit()
            out["stopped"] = "Research was unavailable"
            break
        cost = max(0, int(result.get("cost_pence") or 0))
        # Settle under the business lock, held through any pause and the
        # commit: every meter write takes the business lock first, so the
        # lock order is the same everywhere (Codex OUT-18 review 2).
        _lock(session, bid)
        _spend(session, bid, moment, cost - reserve, brand_id)   # settle the reservation
        # Every attempt the search made (OUT-19 H: a failed-over search has
        # more than one), each against its own provider and model.
        attempts = result.get("calls") or [{"provider": result.get("provider") or "openai",
                                            "model": result.get("model") or model, "pence": cost,
                                            "estimated": bool(result.get("estimated")), "usage": result.get("usage") or {}}]
        for c in attempts:
            usage = c.get("usage") or {}
            ai_costs.record(session, bid, purpose="research", brand_id=brand_id, moment=moment, pence=c["pence"],
                            provider=str(c["provider"]), model=str(c["model"]), estimated=bool(c.get("estimated")),
                            input_tokens=int(usage.get("input_tokens") or 0),
                            output_tokens=int(usage.get("output_tokens") or 0),
                            tool_calls=int(usage.get("tool_calls") or 0))
        out["spend_pence"] += cost
        if cost > impossible:
            _pause_impossible(session, bid, brand_id, cost, impossible, out)   # commits
            break
        if cost > reserve:
            # Option B: an overrun is recorded (above) and the brand stops
            # naturally at its next reservation once its budget is used.
            logger.warning("Research search for business %s cost %sp, over its %sp reserve", bid, cost, reserve)
        session.commit()
        domains, _ = _held(session, bid)
        keys = {r[0] for r in session.execute(text(
            "SELECT email_key FROM outreach_prospects WHERE business_id = :b AND email_key IS NOT NULL"), {"b": bid})}
        held = {"domains": domains, "keys": keys, "seen": set()}
        session.rollback()
        verified, reviews = [], []
        for c in [c for c in (result.get("candidates") or []) if isinstance(c, dict)]:
            v = _verify(session, bid, c, held, fetch, mx, companies)   # no lock held: network
            session.rollback()
            held["seen"].add(v.get("email") or "")
            if v.get("review"):
                reviews.append((c, v))
            if not v["ok"]:
                out["rejected"].append({"company": str(c.get("company") or "")[:200], "reason": v["reason"]})
                continue
            verified.append((c, v))
        # Store under the business lock, re-checking everything that can change.
        _lock(session, bid)
        why = _still_allowed(session, bid, compliance_id, moment)
        if why:
            session.rollback()
            out["stopped"] = why
            break
        if _claim_search(session, bid, claim) != claim:
            session.rollback()
            out["stopped"] = "Another search for this business took over; research carries on in a few minutes"
            break
        counts = _today_counts(session, bid, moment, brand_id)
        # Re-read under the lock: another audience or brand may have filled the
        # inbox meanwhile. Each contact kept takes its campaign place here.
        room = capacity(session, bid, brand_id, moment, lia["audience_hash"])
        left = room["room"]
        stored_domains, stored_keys = _held(session, bid)[0], {r[0] for r in session.execute(text(
            "SELECT email_key FROM outreach_prospects WHERE business_id = :b AND email_key IS NOT NULL"), {"b": bid})}
        # Decision-makers first; gatekeepers only fill, never more than 10.
        verified.sort(key=lambda cv: cv[1]["contact_type"] != "decision_maker")
        for c, v in verified:
            total = counts["decision_maker"] + counts["gatekeeper"]
            if v["email_key"] in stored_keys or v["domain"] in stored_domains:
                out["rejected"].append({"company": v["company"], "reason": "already held"})
                continue
            if _suppressed(session, bid, v["email_key"], v["domain"]):
                out["rejected"].append({"company": v["company"], "reason": "opted out"})
                continue
            if total >= DAILY_TARGET or left <= 0 or (
                    v["contact_type"] == "gatekeeper" and counts["gatekeeper"] >= MAX_GATEKEEPERS):
                out["rejected"].append({"company": v["company"], "reason": "today's quota is full"})
                continue
            ident = _store(session, bid, str(lia["id"]), c, v, moment)
            if not _take_place(session, bid, room, ident, moment):
                # Kept only with a place: a contact that cannot join a campaign
                # is not collected (Codex OUT-19 D review 2).
                _unstore(session, bid, ident)
                out["rejected"].append({"company": v["company"], "reason": "could not join a campaign"})
                continue
            left -= 1
            out["enrolled"].append(ident)
            stored_keys.add(v["email_key"])
            stored_domains.add(v["domain"])
            counts[v["contact_type"]] += 1
            out["accepted"].append(ident)
            out["decision_makers" if v["contact_type"] == "decision_maker" else "gatekeepers"] += 1
            found_new = True
        # Contacts kept only for the owner's review are personal data too: they
        # count toward the brand's daily limits and come after eligible ones.
        for c, v in reviews:
            if v["email_key"] in stored_keys or _suppressed(session, bid, v["email_key"], v["domain"]):
                continue
            kind = v["contact_type"] if v["contact_type"] in counts else "decision_maker"
            if counts["decision_maker"] + counts["gatekeeper"] >= DAILY_TARGET or left <= 0 or (
                    kind == "gatekeeper" and counts["gatekeeper"] >= MAX_GATEKEEPERS):
                out["rejected"].append({"company": v["company"], "reason": "today's quota is full"})
                continue
            _store(session, bid, str(lia["id"]), c, v, moment, review=True)
            left -= 1
            stored_keys.add(v["email_key"])
            counts[kind] += 1
        session.commit()
    if out["enrolled"]:
        out["cards"] = _prepare_cards(session, business, out["enrolled"])
    note = summary(business, out)   # composed before the lock: nothing slow is done holding it
    _lock(session, bid)
    _release_search(session, bid, claim)
    cfg = _config(_doc(session, bid))
    if found_new and out["stopped"] != "Research was unavailable":
        # Advance the area only after a run that found something new (Byron;
        # Codex OUT-10 review 1).
        rotation = cfg["rotation"]
        rotation[str(lia["id"])] = int(rotation.get(str(lia["id"]), 0)) + 1
    cfg["summary"] = note
    cfg["last_summary_at"] = moment.isoformat()
    _save_config(session, bid, cfg)
    session.commit()
    return out


def _prepare_cards(session, business, prospect_ids: list) -> list:
    """Decision E: each newly enrolled contact's first email waits on the home
    page for the owner (or OUT-11's permission). Never sent here."""
    from services import aria_actions, outreach_autopilot
    bid, cards = str(business.id), []
    for pid in prospect_ids:
        rows = send.rows(session, "outreach_enrolments", bid, "AND prospect_id = :p AND state = 'active'", {"p": pid})
        session.rollback()
        open_for = {str((send.loads(a["payload"]) or {}).get("enrolment_id")) for a in send.rows(
            session, "aria_actions", bid, "AND action_type = 'send_outreach' AND status IN ('proposed', 'executing')")}
        session.rollback()
        for e in rows:
            if str(e["id"]) in open_for:
                continue
            # OUT-11: a campaign Aria may send by herself gets no card — a
            # waiting card would block her (she never sends over one).
            held, _ = outreach_autopilot.valid_grant(session, business, str(e["campaign_id"]))
            session.rollback()
            if held:
                continue
            step = next((s for s in send.rows(session, "outreach_sequence_steps", bid,
                                              "AND campaign_id = :c AND sequence_version = :v",
                                              {"c": str(e["campaign_id"]), "v": e["sequence_version"]})
                         if int(s["ordinal"]) == int(e["next_step"])), None)
            session.rollback()
            if step is None:
                continue
            made = aria_actions.propose(session, business, None, "send_outreach",
                                        {"campaign_id": str(e["campaign_id"]), "enrolment_id": str(e["id"]),
                                         "step_id": str(step["id"])})
            if "proposal" in made:
                cards.append(made["proposal"]["id"])
    return cards


def prepare_due_cards(session, business, moment: Optional[datetime] = None) -> list:
    """Each morning: every active enrolment whose next email is due gets its
    card waiting for the owner — follow-ups as well as new contacts (Codex
    OUT-10 review 2). Never sends."""
    moment = moment or now()
    bid = str(business.id)
    due = [str(e["prospect_id"]) for e in send.rows(session, "outreach_enrolments", bid,
                                                    "AND state = 'active' AND takeover_at IS NULL")
           if _parse(e["next_due_at"]) and _parse(e["next_due_at"]) <= moment]
    session.rollback()
    return _prepare_cards(session, business, list(dict.fromkeys(due)))


def summary(business, out: dict) -> str:
    """Aria's one-line report."""
    reasons = {}
    for r in out["rejected"]:
        label = r["reason"].split(" — ")[0].split(" (")[0]
        reasons[label] = reasons.get(label, 0) + 1
    why = ", ".join(f"{n} {label}" for label, n in sorted(reasons.items(), key=lambda x: -x[1])[:4])
    line = (f"I found {len(out['accepted'])} new contacts for {getattr(business, 'name', 'the business')}: "
            f"{out['decision_makers']} decision-makers, {out['gatekeepers']} gatekeepers.")
    if out["rejected"]:
        line += f" {len(out['rejected'])} were rejected ({why})."
    if out.get("stopped"):
        line += f" {out['stopped']}."
    return line


def run_due(session, *, moment: Optional[datetime] = None, runner: Callable = run) -> list:
    """From each hourly pass: on weekdays from 06:00 UK, once per business per
    UK day, every business with outreach started and research switched on."""
    moment = moment or now()
    local = moment.astimezone(LONDON)
    if local.weekday() >= 5 or local.hour < 6:
        return []
    today = local.date().isoformat()
    done = []
    rows = session.execute(text(
        "SELECT s.business_id FROM outreach_settings s WHERE s.pause_all = :f"), {"f": False}).fetchall()
    session.rollback()
    for (bid,) in rows:
        bid = str(bid)
        cfg = _config(_doc(session, bid))
        on = {str(b["id"]) for b in _brands(session, bid) if _brand_config(cfg, b["id"])["enabled"]}
        if not on or cfg.get("last_run") == today:
            session.rollback()
            continue
        business = setup.load_business_row(session, bid)
        if business is None:
            session.rollback()
            continue
        audiences = [r[0] for r in session.execute(text(
            "SELECT id, brand_id FROM outreach_compliance WHERE business_id = :b AND decision = 'approved' "
            "ORDER BY reviewed_at"), {"b": bid}) if str(r[1]) in on]
        _lock(session, bid)   # claim the day under the business lock: two schedulers never both run
        cfg = _config(_doc(session, bid))
        if cfg.get("last_run") == today:
            session.rollback()
            continue
        cfg["last_run"] = today   # claimed before running: a crash never repeats a day's spend
        _save_config(session, bid, cfg)
        session.commit()
        for compliance_id in audiences:
            try:
                runner(session, business, str(compliance_id), moment=moment)
            except Exception:
                session.rollback()
        try:
            prepare_due_cards(session, business, moment)
        except Exception:
            session.rollback()
        done.append(bid)
    return done


# ------------------------------------------------------- default adapters ---

def _public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified)


def _system_resolve(host: str) -> list:
    return [(info[4][0],) for info in socket.getaddrinfo(host, None)]


def fetch_page(url: str, *, resolve: Optional[Callable] = None, transport=None,
               limit: int = 2_000_000) -> Optional[dict]:
    """GET a public web page. The model names the URL, so every hop resolves
    the host ONCE, refuses any non-public address, and connects to exactly
    that checked address (Host header and TLS name kept), so DNS rebinding
    cannot redirect the connection (Codex OUT-10 review 1). The body is read
    to at most `limit` bytes. Returns {"url": final url, "text"} or None."""
    import httpx
    resolve = resolve or _system_resolve
    for _hop in range(4):
        parts = urlparse(url)
        host = parts.hostname
        if parts.scheme not in ("http", "https") or not host:
            return None
        try:
            addresses = [a[0] for a in resolve(host)]
        except Exception:
            return None
        if not addresses or not all(_public_ip(a) for a in addresses):
            return None
        pinned = addresses[0]
        port = parts.port or (443 if parts.scheme == "https" else 80)
        target = parts._replace(netloc=f"[{pinned}]:{port}" if ":" in pinned else f"{pinned}:{port}").geturl()
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False, transport=transport,
                              headers={"User-Agent": "BusinessHero-Research/1.0 (+contact verification)"}) as client:
                with client.stream("GET", target, headers={"Host": host},
                                   extensions={"sni_hostname": host}) as response:
                    if response.is_redirect and response.headers.get("location"):
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code != 200:
                        return None
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) >= limit:
                            break
                    return {"url": url, "text": bytes(body[:limit]).decode(response.encoding or "utf-8", "replace")}
        except Exception:
            return None
    return None


def has_mail_server(domain: str) -> bool:
    import dns.resolver
    try:
        return len(dns.resolver.resolve(domain, "MX", lifetime=5)) > 0
    except Exception:
        return False


def companies_house(query: str) -> Optional[dict]:
    import httpx
    key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if not key:
        return None
    api = "https://api.company-information.service.gov.uk"
    try:
        with httpx.Client(timeout=10.0, auth=(key, "")) as client:
            number = str(query).strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{8}", number):
                hits = client.get(f"{api}/search/companies", params={"q": query, "items_per_page": 5}).json()
                wanted = re.sub(r"\b(limited|ltd|plc|llp)\b\.?", "", str(query).lower()).strip()
                match = next((h for h in hits.get("items", [])
                              if re.sub(r"\b(limited|ltd|plc|llp)\b\.?", "", h.get("title", "").lower()).strip() == wanted),
                             None)
                if not match:
                    return None
                number = match["company_number"]
            profile = client.get(f"{api}/company/{number}").json()
            officers = client.get(f"{api}/company/{number}/officers", params={"items_per_page": 50}).json()
    except Exception:
        return None
    return {"number": number, "name": profile.get("company_name"), "status": profile.get("company_status"),
            "type": profile.get("type"),
            "officers": [o.get("name", "") for o in officers.get("items", []) if not o.get("resigned_on")]}




def web_search(brief: str) -> dict:
    """Research's web search through the AI provider chain, with failover
    (OUT-19 H). No SDK retries anywhere: a retry could be billed twice while
    only one reservation was made (Codex OUT-10 review 2)."""
    return ai_router.web_search(brief)
