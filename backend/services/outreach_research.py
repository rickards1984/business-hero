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
import json
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
from services.chase_replies import _address
from services.metering import period_for

LONDON = ZoneInfo("Europe/London")
KEY = "outreach_research"
DAILY_TARGET, MIN_DECISION_MAKERS, MAX_GATEKEEPERS = 20, 10, 10
MAX_ATTEMPTS = 3
DEFAULT_CAP_PENCE = 2000                 # decision C: £20 a month, editable
RESERVE_PENCE = 10                       # never start a search the budget cannot cover
METER = "outreach_research_pence"
PILOT_ENROLMENTS = 5                     # decision E: OUT-8's pilot limit for now
EXCLUSION_CAP = 400                      # steers the model; code checks guarantee
NOTICE_WITHIN = timedelta(days=30)       # UK GDPR Article 14: within a month
RETENTION = timedelta(days=365)
EVIDENCE_LIFE = timedelta(days=90)
ROLE_LOCALS = {"info", "hello", "contact", "enquiries", "enquiry", "admin", "office", "reception", "sales",
               "team", "mail", "studio", "bookings", "booking", "support", "accounts", "general", "gym"}
SENIOR = ("director", "owner", "founder", "co-founder", "managing", "md", "ceo", "chief", "manager", "head",
          "partner", "principal", "proprietor", "chair", "president", "lead")
CORPORATE_TYPES = {"ltd", "plc", "llp", "private-unlimited", "private-limited-guarant-nsc",
                   "private-limited-guarant-nsc-limited-exemption", "private-limited-shares-section-30-exemption",
                   "old-public-company", "limited-partnership", "royal-charter", "industrial-and-provident-society",
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


def configure(session, business, user, data: dict) -> dict:
    """Owner-only: research on/off and the monthly cap."""
    setup._authority(session, business, user, growth=bool(data.get("enabled", True)))
    bid = str(business.id)
    cfg = _config(_doc(session, bid))
    if "enabled" in data:
        cfg["enabled"] = bool(data["enabled"])
    if "monthly_cap_pence" in data:
        cap = int(data["monthly_cap_pence"])
        send.require(0 <= cap <= 100000, "The monthly research budget is £0–£1,000", 422)
        cfg["monthly_cap_pence"] = cap
    _save_config(session, bid, cfg)
    session.commit()
    return {k: cfg[k] for k in ("enabled", "monthly_cap_pence")}


def save_lessons(session, business, user, notes: list) -> dict:
    """Owner-only: Aria's lessons notes for this business, edited by the owner."""
    setup._authority(session, business, user, growth=False)
    bid = str(business.id)
    cleaned = [str(n).strip()[:300] for n in (notes or []) if str(n).strip()][:30]
    cfg = _config(_doc(session, bid))
    cfg["lessons"] = cleaned
    _save_config(session, bid, cfg)
    session.commit()
    return {"lessons": cleaned}


def status(session, business) -> dict:
    bid = str(business.id)
    cfg = _config(_doc(session, bid))
    spent = _spent(session, bid, now())
    session.rollback()
    return {"enabled": cfg["enabled"], "monthly_cap_pence": cfg["monthly_cap_pence"], "spent_pence": spent,
            "lessons": cfg["lessons"], "last_run": cfg.get("last_run"), "summary": cfg.get("summary")}


# ------------------------------------------------------------ the learning ---

def performance(session, business) -> list:
    """The business's own outcomes by sector, area and contact type, from
    existing tables only — the "training table"."""
    bid = str(business.id)
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


def lessons(session, business) -> list:
    out = []
    for r in performance(session, business):
        where = f"{r['segment']} in {r['region']} ({r['contact_type'].replace('_', ' ')})"
        if r["positive"]:
            out.append(f"Do more of: {where} — {r['positive']} of {r['sent']} replied with interest.")
        elif r["sent"] >= 5 and not r["replied"]:
            out.append(f"Avoid: {where} — {r['sent']} contacted, no replies.")
        elif r["bounced"] >= 2:
            out.append(f"Check addresses for: {where} — {r['bounced']} bounced.")
    notes = _config(_doc(session, str(business.id)))["lessons"]
    session.rollback()
    return out[:10] + [f"Owner note: {n}" for n in notes]


# ---------------------------------------------------------------- the plan ---

def _audience(session, bid: str, compliance_id) -> tuple:
    lia = send.one(session, "outreach_compliance", bid, compliance_id)
    send.require(lia["decision"] == "approved", "Approve this audience first", 409)
    rules = (_doc(session, bid).get(setup.AUDIENCE_KEY) or {}).get(str(lia["id"])) or {}
    return lia, rules


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


def plan(session, business, compliance_id, *, moment: Optional[datetime] = None, attempt: int = 1) -> dict:
    bid = str(business.id)
    lia, rules = _audience(session, bid, compliance_id)
    cfg = _config(_doc(session, bid))
    wheel = _wheel(rules)
    base = wheel[int(cfg["rotation"].get(str(lia["id"]), 0)) % len(wheel)]
    area = base if attempt == 1 else (f"{base} and the surrounding region" if attempt == 2 else "anywhere in the UK")
    domains, companies = _held(session, bid)
    learned = lessons(session, business)
    excluded = sorted(domains)[:EXCLUSION_CAP]
    brief = f"""RESEARCH — find up to {DAILY_TARGET} NEW business contacts for {getattr(business, 'name', 'this business')}.

Who: {rules.get('description', '')}
Sectors: {', '.join(rules.get('segments') or []) or 'as described'}
Area for this search: {area}

QUALITY BAR (mandatory):
- Real organisations only. The contact email MUST be shown on the organisation's own website; give the exact
  page URL where it appears. NEVER guess, construct or invent an email address.
- Prefer NAMED decision-makers: owner, director, founder, managing director, practice/operations manager,
  head of department. At least {MIN_DECISION_MAKERS} should be named decision-makers.
- A role address (info@, hello@, reception@) is acceptable only when the organisation is highly relevant and no
  named decision-maker is findable; mark it contact_type "gatekeeper".
- Limited companies, LLPs and PLCs only (give the Companies House number when you can find it). Skip sole
  traders and partnerships.
- Prefer smaller, independent organisations over national chains.

ALREADY HELD OR CONTACTED — do NOT return these domains:
{chr(10).join(excluded) if excluded else '(none yet)'}

WHAT HAS WORKED FOR THIS BUSINESS:
{chr(10).join(learned) if learned else '(no results yet)'}

Return ONLY a JSON object: {{"candidates": [{{"company", "company_number", "contact_name", "role",
"contact_email", "contact_type" ("decision_maker" or "gatekeeper"), "source_url", "region", "segment",
"fit_reason" (one sentence)}}]}}"""
    session.rollback()
    return {"area": area, "attempt": attempt, "exclusions": excluded, "lessons": learned, "brief": brief,
            "target": DAILY_TARGET, "min_decision_makers": MIN_DECISION_MAKERS}


# ---------------------------------------------------------------- spending ---

def _spent(session, bid: str, moment: datetime) -> int:
    value = session.execute(text("SELECT value FROM usage_meters WHERE business_id = :b AND meter = :m "
                                 "AND period = :p"), {"b": bid, "m": METER, "p": period_for(moment)}).scalar()
    return int(float(value or 0))


def _spend(session, bid: str, moment: datetime, pence: int) -> None:
    if pence <= 0:
        return
    params = {"b": bid, "m": METER, "p": period_for(moment), "v": int(pence), "at": moment}
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
    wanted = _name_tokens(name)
    return bool(wanted) and any(wanted <= _name_tokens(o) or _name_tokens(o) <= wanted for o in officers or [])


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
    if send.rows(session, "outreach_suppressions", bid,
                 "AND ((key_type = 'email' AND key_digest = :e) OR (key_type = 'domain' AND key_digest = :d))",
                 {"e": key, "d": send.suppression_digest(bid, "domain", domain)}):
        return {"ok": False, "reason": "opted out"}
    source = str(c.get("source_url") or "")
    page = fetch(source) if source else None
    if not page or email.lower() not in page.lower():
        return {"ok": False, "reason": "email not on the cited page"}
    if not mx(domain):
        return {"ok": False, "reason": f"no mail server for {domain}"}
    record = companies(c.get("company_number") or company)
    name, role = str(c.get("contact_name") or "").strip()[:120], str(c.get("role") or "").strip()[:120]
    base = {"email": email, "email_key": key, "domain": domain, "company": company, "name": name, "role": role,
            "contact_type": _contact_type(email, name, role), "source_url": source}
    if record and str(record.get("status", "")).lower() not in ("active", ""):
        return {"ok": False, "reason": f"company is not active ({record.get('status')})"}
    if not record or str(record.get("type", "")).lower() not in CORPORATE_TYPES:
        return {"ok": False, "review": True, **base,
                "reason": "not a registered company — sole traders and partnerships need consent (PECR)"}
    return {"ok": True, **base, "number": record.get("number"),
            "role_verified": _officer_match(name, record.get("officers") or []) if name else False,
            "company_type": record.get("type")}


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

def _enrol(session, bid: str, lia: dict, prospect_ids: list, moment: datetime) -> list:
    """Decision E: verified contacts join the active campaign for this
    audience, within the pilot limit. Never sends; never raises a card."""
    from services import outreach_manage
    settings = send.one(session, "outreach_settings", bid)
    if settings["pause_all"]:
        return []
    joined = []
    for c in send.rows(session, "outreach_campaigns", bid,
                       "AND target_hash = :h AND brand_id = :br AND status IN ('ready', 'running') ORDER BY created_at, id",
                       {"h": lia["audience_hash"], "br": str(lia["brand_id"])}, True):
        active = len(send.rows(session, "outreach_enrolments", bid, "AND campaign_id = :c AND state IN ('pending','active')",
                               {"c": str(c["id"])}))
        for pid in prospect_ids:
            if active >= PILOT_ENROLMENTS or pid in joined:
                continue
            p = send.one(session, "outreach_prospects", bid, pid, True)
            try:
                outreach_manage.qualified(session, bid, c, p)
            except send.ActionRefused:
                continue
            send.insert(session, "outreach_enrolments", bid, prospect_id=pid, campaign_id=str(c["id"]),
                        sequence_version=c["sequence_version"], state="active", next_step=0, next_due_at=moment)
            joined.append(pid)
            active += 1
    return joined


# ------------------------------------------------------------------ the run ---

def run(session, business, compliance_id, *, search: Optional[Callable] = None, fetch: Optional[Callable] = None,
        mx: Optional[Callable] = None, companies: Optional[Callable] = None,
        moment: Optional[datetime] = None) -> dict:
    """One research run for one approved audience. Commits its own work."""
    moment = moment or now()
    bid = str(business.id)
    out = {"accepted": [], "decision_makers": 0, "gatekeepers": 0, "rejected": [], "attempts": 0,
           "spend_pence": 0, "stopped": None, "enrolled": []}
    if companies is None:
        if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
            out["stopped"] = "Companies House key not configured: no contact can be confirmed as a company"
            return out
        companies = companies_house
    search, fetch, mx = search or web_search, fetch or fetch_page, mx or has_mail_server
    lia, rules = _audience(session, bid, compliance_id)
    cfg = _config(_doc(session, bid))
    session.rollback()
    domains, _companies = _held(session, bid)
    keys = {r[0] for r in session.execute(text(
        "SELECT email_key FROM outreach_prospects WHERE business_id = :b AND email_key IS NOT NULL"), {"b": bid})}
    held = {"domains": domains, "keys": keys, "seen": set()}
    session.rollback()
    succeeded = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if len(out["accepted"]) >= DAILY_TARGET:
            break
        if _spent(session, bid, moment) + RESERVE_PENCE > int(cfg["monthly_cap_pence"]):
            out["stopped"] = "This month's research budget is reached; research resumes next month"
            break
        brief = plan(session, business, compliance_id, moment=moment, attempt=attempt)["brief"]
        out["attempts"] = attempt
        try:
            result = search(brief) or {}
        except Exception:   # an outage is a failed attempt; it never skips an area
            out["stopped"] = out["stopped"] or "Research was unavailable"
            break
        succeeded = True
        cost = int(result.get("cost_pence") or 0)
        _spend(session, bid, moment, cost)
        out["spend_pence"] += cost
        session.commit()
        candidates = [c for c in (result.get("candidates") or []) if isinstance(c, dict)]
        verified = []
        for c in candidates:
            v = _verify(session, bid, c, held, fetch, mx, companies)
            held["seen"].add(v.get("email") or "")
            if v.get("review"):
                _store(session, bid, str(lia["id"]), c, v, moment, review=True)
                held["keys"].add(v["email_key"])
                held["domains"].add(v["domain"])
            if not v["ok"]:
                out["rejected"].append({"company": str(c.get("company") or "")[:200], "reason": v["reason"]})
                continue
            verified.append((c, v))
        # Decision-makers first; gatekeepers only fill, never more than 10.
        verified.sort(key=lambda cv: cv[1]["contact_type"] != "decision_maker")
        for c, v in verified:
            total = out["decision_makers"] + out["gatekeepers"]
            if total >= DAILY_TARGET or (v["contact_type"] == "gatekeeper" and out["gatekeepers"] >= MAX_GATEKEEPERS):
                out["rejected"].append({"company": v["company"], "reason": "today's quota is full"})
                continue
            ident = _store(session, bid, str(lia["id"]), c, v, moment)
            held["keys"].add(v["email_key"])
            held["domains"].add(v["domain"])
            out["accepted"].append(ident)
            out["decision_makers" if v["contact_type"] == "decision_maker" else "gatekeepers"] += 1
        session.commit()
    if out["accepted"]:
        out["enrolled"] = _enrol(session, bid, lia, out["accepted"], moment)
        session.commit()
    cfg = _config(_doc(session, bid))
    if succeeded:   # advance the wheel only on a run that searched (Byron)
        rotation = cfg["rotation"]
        rotation[str(lia["id"])] = int(rotation.get(str(lia["id"]), 0)) + 1
    cfg["summary"] = summary(business, out)
    cfg["last_summary_at"] = moment.isoformat()
    _save_config(session, bid, cfg)
    session.commit()
    return out


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
        if not cfg["enabled"] or cfg.get("last_run") == today:
            session.rollback()
            continue
        business = setup.load_business_row(session, bid)
        if business is None:
            session.rollback()
            continue
        audiences = [r[0] for r in session.execute(text(
            "SELECT id FROM outreach_compliance WHERE business_id = :b AND decision = 'approved' ORDER BY reviewed_at"),
            {"b": bid})]
        cfg["last_run"] = today   # claimed before running: a crash never repeats a day's spend
        _save_config(session, bid, cfg)
        session.commit()
        for compliance_id in audiences:
            try:
                runner(session, business, str(compliance_id), moment=moment)
            except Exception:
                session.rollback()
        done.append(bid)
    return done


# ------------------------------------------------------- default adapters ---

def _public_host(host: str) -> bool:
    """No fetch may reach Business Hero's own network (the model names URLs)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def fetch_page(url: str) -> Optional[str]:
    import httpx
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or not _public_host(parts.hostname):
        return None
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False,
                          headers={"User-Agent": "BusinessHero-Research/1.0 (+contact verification)"}) as client:
            for _ in range(3):   # follow redirects by hand so each hop is checked too
                response = client.get(url)
                if response.is_redirect and response.headers.get("location"):
                    url = str(response.url.join(response.headers["location"]))
                    nxt = urlparse(url)
                    if nxt.scheme not in ("http", "https") or not nxt.hostname or not _public_host(nxt.hostname):
                        return None
                    continue
                if response.status_code != 200:
                    return None
                return response.text[:2_000_000]
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


# Rough, conservative pence per run, in GBP. Overridable without a deploy.
PRICE_IN_PER_M = float(os.environ.get("ARIA_RESEARCH_PRICE_IN_PENCE_PER_M", "160"))
PRICE_OUT_PER_M = float(os.environ.get("ARIA_RESEARCH_PRICE_OUT_PENCE_PER_M", "640"))
PRICE_PER_SEARCH = float(os.environ.get("ARIA_RESEARCH_PRICE_PER_SEARCH_PENCE", "2"))


def web_search(brief: str) -> dict:
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("no model key configured")
    client = OpenAI(api_key=key, timeout=300.0, max_retries=1)
    response = client.responses.create(model=os.environ.get("ARIA_RESEARCH_MODEL", "gpt-4.1"),
                                       tools=[{"type": "web_search"}], input=brief)
    usage = getattr(response, "usage", None)
    searches = sum(1 for item in (getattr(response, "output", None) or [])
                   if getattr(item, "type", "") == "web_search_call")
    cost = ((getattr(usage, "input_tokens", 0) or 0) * PRICE_IN_PER_M
            + (getattr(usage, "output_tokens", 0) or 0) * PRICE_OUT_PER_M) / 1_000_000 + searches * PRICE_PER_SEARCH
    textout = getattr(response, "output_text", "") or ""
    match = re.search(r"\{.*\}", textout, re.S)
    try:
        candidates = json.loads(match.group(0)).get("candidates", []) if match else []
    except (ValueError, AttributeError):
        candidates = []
    return {"candidates": candidates, "cost_pence": max(1, round(cost))}
