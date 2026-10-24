"""OUT-15 — outreach setup: the owner's wizard, mailbox health, and changing
the sending mailbox (docs/OUT-15-TICKET.md).

Every step is owner-only: an active owner, a FRESH read of the business's
entitlement (the admin switch takes effect at once), and the membership
rechecked under lock, in OUT-6's lock order (business settings, outreach
settings, business row, membership). Aria's drafts are saved as drafts;
nothing she writes takes effect until the owner approves it. Nothing here
sends an email.
"""

import hashlib
import html
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Optional

from fastapi import HTTPException
from sqlalchemy import text

from services import aria_actions
from services import outreach_send as send
from services.chase_replies import _address, _parse

ActionRefused = aria_actions.ActionRefused
LIA_REVIEW = timedelta(days=365)          # decision A: editable by the owner
STEP_DELAYS = (0, 5, 7)                    # OUT-6/OUT-8: three steps, working days
FREE_WEBMAIL = {                           # decision B: never an outreach sender
    "gmail.com", "googlemail.com", "outlook.com", "outlook.co.uk", "hotmail.com", "hotmail.co.uk",
    "live.com", "live.co.uk", "msn.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "icloud.com",
    "me.com", "mac.com", "aol.com", "aol.co.uk", "btinternet.com", "sky.com", "virginmedia.com",
    "talktalk.net", "protonmail.com", "proton.me", "gmx.com", "gmx.co.uk", "mail.com",
}
PROVIDERS = {
    "google": {"spf": "_spf.google.com", "selectors": ("google",), "name": "Google Workspace",
               "dkim_help": "In the Google Workspace admin console, open Apps, Google Workspace, "
                            "Gmail, Authenticate email, generate a DKIM key and publish the record it gives you."},
    "microsoft": {"spf": "spf.protection.outlook.com", "selectors": ("selector1", "selector2"),
                  "name": "Microsoft 365",
                  "dkim_help": "In Microsoft 365 Defender, open Email authentication settings, DKIM, "
                               "enable signing for your domain and publish the two selector CNAME records."},
}
# Settings-document keys this ticket owns; the generic settings save keeps them.
PRIVACY_KEY, AUDIENCE_KEY = "outreach_privacy", "outreach_audiences"
DNS_PAUSE = "Daily check failed:"
SETUP_KEY = "outreach_setup"   # the only pause a DNS pass may lift


def now() -> datetime:
    return send.now()


def refuse(status: int, detail: str):
    raise ActionRefused(status, detail)


# ---------------------------------------------------------------- authority ---

def _authority(session, business, user, *, settings_required: bool = True, growth: bool = True):
    """The owner, their business's CURRENT entitlement, under lock."""
    if not user or not aria_actions._is_active_owner(session, business, user):
        session.rollback()
        refuse(403, "Only the business owner can set up outreach.")
    bid = str(business.id)
    session.rollback()
    if not send.pg(session):   # SQLite: take the writer lock before reading
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"),
                        {"b": bid})
    send.one(session, "business_settings", bid, lock=True)
    if settings_required:
        send.require(send.rows(session, "outreach_settings", bid), "Start outreach setup first", 409)
        send.one(session, "outreach_settings", bid, lock=True)
    row = session.execute(text(
        "SELECT plan_tier, feature_flags, subscription_status, is_active, trial_ends_at FROM businesses "
        "WHERE id = :b" + (" FOR UPDATE" if send.pg(session) else "")), {"b": bid}).mappings().first()
    send.require(row, "Business unavailable", 404)
    fresh = SimpleNamespace(**row)
    fresh.feature_flags = send.loads(fresh.feature_flags) or {}
    fresh.trial_ends_at = _parse(fresh.trial_ends_at)
    from auth import assert_feature_access
    try:
        assert_feature_access(fresh, "outreach", retained_history=not growth)
    except HTTPException:
        session.rollback()
        refuse(403, "Outreach isn't switched on for this business.")
    if not aria_actions._is_active_owner(session, business, user, lock=True):
        session.rollback()
        refuse(403, "Only the business owner can set up outreach.")
    return fresh


def _clean(value, field: str, limit: int, *, one_line: bool = True) -> str:
    out = str(value or "").strip()
    if not out or len(out) > limit or (one_line and ("\r" in out or "\n" in out)):
        refuse(422, f"{field} must be 1–{limit} characters" + (" on one line." if one_line else "."))
    return out


def _settings_doc(session, bid: str) -> dict:
    raw = session.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                          {"b": bid}).scalar()
    return dict(send.loads(raw) or {})


def _save_settings_doc(session, bid: str, doc: dict) -> None:
    expr = "CAST(:s AS jsonb)" if send.pg(session) else ":s"
    session.execute(text(f"UPDATE business_settings SET settings = {expr} WHERE business_id = :b"),
                    {"s": json.dumps(doc), "b": bid})


def _canonical(rules: dict) -> str:
    return json.dumps(rules, sort_keys=True, separators=(",", ":"))


def privacy_url(brand_id: str) -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    send.require(base.startswith("https://"), "The public address for privacy notices is not configured")
    return f"{base}/p/outreach-privacy/{brand_id}"


# ------------------------------------------------------------------- steps ---

def begin(session, business, user) -> dict:
    _authority(session, business, user, settings_required=False)
    bid = str(business.id)
    found = send.rows(session, "outreach_settings", bid)
    if found:
        session.rollback()
        return {"settings_id": str(found[0]["id"])}
    ident = send.insert(session, "outreach_settings", bid, pause_all=True, timezone="Europe/London",
                        business_daily_cap=20, owner_cc_default=False, retention_policy_version=1)
    session.commit()
    return {"settings_id": ident}


def save_brand(session, business, user, data: dict) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    name = _clean(data.get("name"), "Brand name", 120)
    sender = _clean(data.get("sender_identity"), "Sender identity", 200)
    default_box = data.get("default_mailbox_id")
    if default_box:
        send.one(session, "email_accounts", bid, default_box)
    found = send.rows(session, "outreach_brands", bid, "AND name = :n", {"n": name}, True)
    if found:
        brand = found[0]
        changes = {}
        if brand["sender_identity"] != sender:
            changes["sender_identity"] = sender
        if default_box and str(brand["default_mailbox_id"] or "") != str(default_box):
            changes["default_mailbox_id"] = str(default_box)
        if changes:
            send.update(session, "outreach_brands", bid, brand["id"], **changes,
                        version=int(brand["version"]) + 1, updated_at=now())
        session.commit()
        return {"id": str(brand["id"]), "version": int(brand["version"]) + bool(changes),
                "privacy_url": brand["privacy_url"]}
    ident = str(uuid.uuid4())
    url = privacy_url(ident)
    session.execute(text(
        "INSERT INTO outreach_brands (id, business_id, created_at, updated_at, name, default_mailbox_id, "
        "privacy_url, sender_identity, version) VALUES (:id, :b, :at, :at, :n, :m, :u, :s, 1)"),
        {"id": ident, "b": bid, "at": now(), "n": name, "m": default_box or None, "u": url, "s": sender})
    session.commit()
    return {"id": ident, "version": 1, "privacy_url": url}


def register_mailbox(session, business, user, data: dict) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    account = send.one(session, "email_accounts", bid, data.get("mailbox_id"), True)
    cap = int(data.get("daily_cap") or 5)
    send.require(1 <= cap <= 20, "A daily cap is 1–20", 422)
    found = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": str(account["id"])}, True)
    if found:
        send.update(session, "outreach_mailboxes", bid, found[0]["id"], daily_cap=cap, updated_at=now())
        row = found[0]
    else:
        send.insert(session, "outreach_mailboxes", bid, mailbox_id=str(account["id"]), enabled=False,
                    daily_cap=cap, warmup_stage=5, sending_days=0, health_status="unknown", health_evidence={})
        row = {"enabled": False, "health_status": "unknown"}
    session.commit()
    return {"mailbox_id": str(account["id"]), "enabled": bool(row["enabled"]), "health": row["health_status"]}


def dns_txt(name: str) -> list:
    """TXT records for `name` (CNAMEs followed). Missing means empty."""
    import dns.resolver
    try:
        answer = dns.resolver.resolve(name, "TXT", lifetime=5)
    except Exception:  # NXDOMAIN, no answer, timeout: treated as no record
        return []
    return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


def _tags(record: str) -> dict:
    out = {}
    for part in record.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = "".join(v.split())
    return out


def _usable_dkim(record: str) -> bool:
    """A published, non-revoked public key that really IS a key: p= decodes
    to an RSA key of at least 1024 bits, or a 32-byte Ed25519 key (an empty
    p= means revoked) — Codex OUT-15 reviews 1 and 2."""
    import base64
    import binascii
    tags = _tags(record)
    if tags.get("v", "dkim1").lower() != "dkim1":
        return False
    try:
        raw = base64.b64decode(tags.get("p", ""), validate=True)
    except (binascii.Error, ValueError):
        return False
    if not raw:
        return False
    if tags.get("k", "rsa").lower() == "ed25519":
        return len(raw) == 32
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        key = load_der_public_key(raw)
    except Exception:
        return False
    return isinstance(key, rsa.RSAPublicKey) and key.key_size >= 1024


def _spf_includes(record: str, provider: str) -> bool:
    """Read SPF in order: the provider's include must come before any `all`,
    and carry a pass qualifier (none or +)."""
    for term in record.split()[1:]:
        t = term.lower()
        if t.lstrip("+-~?") == "all":
            return False
        if t in (f"include:{provider}", f"+include:{provider}"):
            return True
    return False


def _usable_dmarc(record: str) -> bool:
    tags = _tags(record)
    return record.strip().lower().startswith("v=dmarc1") and tags.get("p", "").lower() in ("none", "quarantine", "reject")


def _evaluate(account: dict, resolve: Callable) -> dict:
    """Plain DNS checks for one sending mailbox. Never raises."""
    address = _address(account["email_address"])
    domain = address.split("@")[-1] if "@" in address else ""
    provider = PROVIDERS.get(account["provider"])
    evidence = {"domain": domain, "provider": account["provider"], "spf": "fail", "dkim": "fail",
                "dmarc": "fail", "domain_control": False, "from_aligned": False, "selectors": [],
                "checked_at": now().isoformat()}
    if not domain or domain in FREE_WEBMAIL:
        return {"status": "fail", "evidence": evidence,
                "advice": ["Outreach needs a mailbox on your own business domain (for example "
                           "you@yourcompany.co.uk), not a personal address like " + (domain or "this") + "."]}
    if provider is None:
        return {"status": "fail", "evidence": evidence,
                "advice": ["Only Google Workspace and Microsoft 365 mailboxes can send outreach."]}

    def txt(name):
        try:
            return [str(t) for t in (resolve(name) or [])]
        except Exception:  # a resolver failure is a missing record, never a pass
            return []
    advice = []
    spf = [t for t in txt(domain) if t.strip().lower().split(" ")[0] == "v=spf1"]
    # Exactly one SPF record (two is a permanent error), naming the provider
    # as a whole mechanism — never a substring (Codex OUT-15 review 1).
    if len(spf) == 1 and _spf_includes(spf[0], provider["spf"]):
        evidence["spf"] = "pass"
    else:
        advice.append(f"SPF: your domain's SPF record must include {provider['name']}. Add or edit the TXT "
                      f"record on {domain} to read: v=spf1 include:{provider['spf']} ~all")
    for selector in provider["selectors"]:
        if any(_usable_dkim(t) for t in txt(f"{selector}._domainkey.{domain}")):
            evidence["dkim"] = "pass"
            evidence["selectors"].append(selector)
    if evidence["dkim"] != "pass":
        advice.append("DKIM: " + provider["dkim_help"])
    dmarc = [t for t in txt(f"_dmarc.{domain}") if t.strip().lower().startswith("v=dmarc1")]
    if len(dmarc) == 1 and _usable_dmarc(dmarc[0]):   # more than one is invalid
        evidence["dmarc"] = "pass"
    else:
        advice.append(f"DMARC: add a TXT record named _dmarc.{domain} with the value "
                      f"v=DMARC1; p=none; rua=mailto:{address}")
    evidence["domain_control"] = bool(account.get("token_ciphertext"))   # connected by OAuth
    evidence["from_aligned"] = evidence["spf"] == "pass" and evidence["dkim"] == "pass"
    ok = all(evidence[k] == "pass" for k in ("spf", "dkim", "dmarc")) and evidence["domain_control"]
    return {"status": "pass" if ok else "fail", "evidence": evidence, "advice": advice}


def _apply_health(session, bid: str, row: dict, result: dict, moment: datetime, *, daily: bool) -> None:
    # Only a pause this check itself caused may be lifted by a pass; a
    # retirement, complaint or bounce hold stays (Codex OUT-15 review 1).
    reason = str(row.get("pause_reason") or "")
    held = bool(reason) and not reason.startswith(DNS_PAUSE)
    passed = result["status"] == "pass"
    fields = dict(health_status=result["status"], health_checked_at=moment,
                  health_evidence=json.dumps(result["evidence"]), updated_at=moment)
    if passed and not held:
        fields.update(enabled=True, pause_reason=None)
    elif not passed:
        fields["enabled"] = False
        if daily:
            fields["pause_reason"] = (DNS_PAUSE + " " + " ".join(result["advice"]))[:900] if not held else reason
    expr = "CAST(:health_evidence AS jsonb)" if send.pg(session) else ":health_evidence"
    session.execute(text(
        "UPDATE outreach_mailboxes SET " + ", ".join(
            f"{k} = {expr}" if k == "health_evidence" else f"{k} = :{k}" for k in fields) +
        " WHERE business_id = :b AND id = :id"), {**fields, "b": bid, "id": str(row["id"])})


def check_mailbox_health(session, business, user, mailbox_id, *, resolve: Callable = dns_txt) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    account = send.one(session, "email_accounts", bid, mailbox_id)
    send.require(send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": str(account["id"])}),
                 "Add this mailbox to outreach first", 409)
    session.rollback()   # DNS lookups happen with no lock held
    result = _evaluate(account, resolve)
    _authority(session, business, user)
    found = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": str(account["id"])}, True)
    send.require(found, "Add this mailbox to outreach first", 409)
    _apply_health(session, bid, found[0], result, now(), daily=False)   # the CURRENT row, under lock
    session.commit()
    return result


def daily_health(session, *, resolve: Callable = dns_txt, moment: Optional[datetime] = None) -> dict:
    """Called from every hourly scheduler pass: from 07:00 UK on weekdays,
    recheck the enabled mailboxes not yet checked this UK day. Restarts and
    drifting hours can neither skip nor repeat a day."""
    from zoneinfo import ZoneInfo
    moment = moment or now()
    local = moment.astimezone(ZoneInfo("Europe/London"))
    if local.weekday() >= 5 or local.hour < 7:
        return {"checked": [], "failed": []}
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    return recheck_health(session, resolve=resolve, moment=moment, checked_before=start)


def recheck_health(session, *, resolve: Callable = dns_txt, moment: Optional[datetime] = None,
                   checked_before: Optional[datetime] = None) -> dict:
    """Decision C: the weekday 07:00 UK recheck. OUT-6 sends only after a
    same-day pass; a failing mailbox pauses with the reason shown."""
    moment = moment or now()
    out = {"checked": [], "failed": []}
    rows = session.execute(text(
        "SELECT m.id, m.business_id, m.mailbox_id, m.pause_reason, m.health_checked_at "
        "FROM outreach_mailboxes m WHERE m.enabled = :t"), {"t": True}).mappings().all()
    if checked_before is not None:
        rows = [r for r in rows if not _parse(r["health_checked_at"])
                or _parse(r["health_checked_at"]) < checked_before]
    session.rollback()
    for row in rows:
        bid = str(row["business_id"])
        try:
            account = send.one(session, "email_accounts", bid, row["mailbox_id"])
            session.rollback()   # lookups with no lock held
            result = _evaluate(account, resolve)
            # Re-read under the business lock: an owner's change during the
            # lookups (retire, pause) wins (Codex OUT-15 review 1).
            if not send.pg(session):
                session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"),
                                {"b": bid})
            send.lock_business(session, bid)
            current = send.rows(session, "outreach_mailboxes", bid, "AND id = :id", {"id": str(row["id"])}, True)
            already = checked_before is not None and _parse(current[0]["health_checked_at"] if current else None)
            if not current or not current[0]["enabled"] or (already and already >= checked_before):
                session.rollback()   # retired meanwhile, or another run checked it today
                continue
            _apply_health(session, bid, current[0], result, moment, daily=True)
            session.commit()
        except Exception:  # one business's failure never stops the rest
            session.rollback()
            result = {"status": "fail"}
        out["checked"].append(str(row["mailbox_id"]))
        if result["status"] != "pass":
            out["failed"].append(str(row["mailbox_id"]))
    return out


# ------------------------------------------------- audience and privacy ---

def _model_json(instructions: str, context: dict) -> dict:
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        refuse(503, "Aria can't draft this right now; write it yourself or try again later.")
    client = OpenAI(api_key=key, timeout=60.0, max_retries=1)
    response = client.chat.completions.create(
        model=os.getenv("ARIA_DRAFT_MODEL", "gpt-4o"), response_format={"type": "json_object"},
        messages=[{"role": "system", "content": instructions},
                  {"role": "user", "content": json.dumps(context, default=str)}])
    return json.loads(response.choices[0].message.content or "{}")


def model_draft_audience(context: dict) -> dict:
    return _model_json(
        "You draft a UK GDPR legitimate-interests assessment for business-to-business outreach. "
        "Return JSON with purpose, necessity, balancing_test, safeguards: plain English, specific to "
        "the business and audience given, each under 120 words. Safeguards must include an opt-out in "
        "every email, honouring opt-outs at once, business contact details only, and a privacy notice.",
        context)


def model_draft_notice(context: dict) -> str:
    out = _model_json(
        "Draft a short UK GDPR Article 14 privacy notice for people contacted by business outreach. "
        "Headings: Who we are; What we hold; Where we got it; Why we contact you; Lawful basis "
        "(legitimate interests); How long we keep it; Your rights; How to opt out. Plain English, "
        "under 400 words, no invented facts. Return JSON {\"text\": ...}.", context)
    return str(out.get("text") or "")


def model_draft_emails(context: dict) -> list:
    out = _model_json(
        "Draft three short, specific B2B outreach emails for the campaign given: a first email, a "
        "follow-up after 5 working days and a final one after 7 more. Honest, no hype, no invented "
        "claims, one clear ask, under 120 words each. Do not add a signature or footer. Return JSON "
        "{\"emails\": [{\"subject\": ..., \"body\": ...}, x3]}.", context)
    return list(out.get("emails") or [])


def draft_audience(session, business, user, data: dict, *, draft: Callable = model_draft_audience) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    brand = send.one(session, "outreach_brands", bid, data.get("brand_id"))
    rules = {"description": _clean(data.get("description"), "Audience description", 2000, one_line=False),
             "segments": [str(s)[:80] for s in (data.get("segments") or [])][:20],
             "regions": [str(r)[:80] for r in (data.get("regions") or [])][:20]}
    audience_hash = hashlib.sha256(_canonical(rules).encode()).hexdigest()
    session.rollback()   # no lock is held while Aria drafts
    drafted = draft({"business": getattr(business, "name", None), "brand": brand["name"], **rules})
    fields = {k: _clean(drafted.get(k), k.replace("_", " ").capitalize(), 4000, one_line=False)
              for k in ("purpose", "necessity", "balancing_test", "safeguards")}
    _authority(session, business, user)
    versions = send.rows(session, "outreach_compliance", bid, "AND brand_id = :br AND audience_hash = :h",
                         {"br": str(brand["id"]), "h": audience_hash}, True)
    ident = send.insert(session, "outreach_compliance", bid, brand_id=str(brand["id"]), audience_hash=audience_hash,
                        version=max([int(v["version"]) for v in versions] or [0]) + 1, sources=[],
                        decision="draft", review_due_at=now() + LIA_REVIEW, **fields)
    doc = _settings_doc(session, bid)
    doc.setdefault(AUDIENCE_KEY, {})[ident] = rules
    _save_settings_doc(session, bid, doc)
    session.commit()
    return {"id": ident, "audience_hash": audience_hash, "decision": "draft", **fields}


def approve_audience(session, business, user, compliance_id, edits: dict) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    row = send.one(session, "outreach_compliance", bid, compliance_id, True)
    send.require(row["decision"] == "draft", "This audience has already been decided; draft a new version", 409)
    fields = {k: _clean(edits[k], k.replace("_", " ").capitalize(), 4000, one_line=False)
              for k in ("purpose", "necessity", "balancing_test", "safeguards") if k in edits}
    moment = now()
    due = _parse(edits.get("review_due_at")) if edits.get("review_due_at") else moment + LIA_REVIEW
    send.require(due and due > moment, "The review date must be in the future", 422)
    send.update(session, "outreach_compliance", bid, row["id"], **fields, decision="approved",
                reviewer=str(user), reviewed_at=moment, review_due_at=due, updated_at=moment)
    session.commit()
    return {"id": str(row["id"]), "audience_hash": row["audience_hash"]}


def draft_privacy_notice(session, business, user, brand_id, *, draft: Callable = model_draft_notice) -> dict:
    _authority(session, business, user)
    brand = send.one(session, "outreach_brands", str(business.id), brand_id)
    session.rollback()
    return {"text": draft({"business": getattr(business, "name", None), "brand": brand["name"],
                           "sender_identity": brand["sender_identity"]})}


def approve_privacy_notice(session, business, user, brand_id, data: dict) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    brand = send.one(session, "outreach_brands", bid, brand_id)
    body = _clean(data.get("text"), "Privacy notice", 20000, one_line=False)
    doc = _settings_doc(session, bid)
    notices = doc.setdefault(PRIVACY_KEY, {})
    version = int((notices.get(str(brand["id"])) or {}).get("version") or 0) + 1
    notices[str(brand["id"])] = {"version": version, "text": body, "approved_by": str(user),
                                 "approved_at": now().isoformat()}
    _save_settings_doc(session, bid, doc)
    session.commit()
    return {"version": version, "url": brand["privacy_url"]}


def public_privacy_notice(session, brand_id) -> Optional[str]:
    """Unauthenticated: the approved notice text for one brand, or None."""
    try:
        uuid.UUID(str(brand_id))
    except ValueError:
        return None
    brand = session.execute(text("SELECT business_id FROM outreach_brands WHERE id = :id"),
                            {"id": str(brand_id)}).fetchone()
    if brand is None:
        return None
    notice = (_settings_doc(session, str(brand[0])).get(PRIVACY_KEY) or {}).get(str(brand_id)) or {}
    session.rollback()
    return notice.get("text") or None


def render_public_notice(body: str) -> str:
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in body.split("\n") if p.strip())
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            "content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>"
            "<title>Privacy notice</title><style>body{font-family:system-ui,sans-serif;max-width:40rem;"
            "margin:2rem auto;padding:0 1rem;line-height:1.5;color:#222}</style></head><body>"
            f"{paragraphs}</body></html>")


# ------------------------------------------------------------- campaigns ---

def _registered(session, bid: str, mailbox_id) -> dict:
    account = send.one(session, "email_accounts", bid, mailbox_id, True)
    found = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": str(account["id"])}, True)
    send.require(found, "Add this mailbox to outreach and check it first", 409)
    return {**found[0], "email_address": account["email_address"]}


def _insert_steps(session, bid: str, campaign_id: str, sequence_version: int, emails: list) -> None:
    send.require(isinstance(emails, list) and len(emails) == 3, "Three emails are needed", 422)
    for ordinal, (email, delay) in enumerate(zip(emails, STEP_DELAYS)):
        envelope = json.dumps(dict(schema_version=1,
                                   subject=_clean(email.get("subject"), "Subject", 200),
                                   body=_clean(email.get("body"), "Body", 20000, one_line=False)))
        send.insert(session, "outreach_sequence_steps", bid, campaign_id=campaign_id,
                    sequence_version=sequence_version, ordinal=ordinal, delay_business_days=delay,
                    template_text=envelope, template_hash=hashlib.sha256(envelope.encode()).hexdigest(),
                    allowed_variables=[])


def create_first_campaign(session, business, user, data: dict, *, draft: Callable = model_draft_emails) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    brand = send.one(session, "outreach_brands", bid, data.get("brand_id"))
    box = _registered(session, bid, data.get("mailbox_id"))
    lia = send.one(session, "outreach_compliance", bid, data.get("compliance_id"))
    send.require(lia["decision"] == "approved" and str(lia["brand_id"]) == str(brand["id"]),
                 "Approve who you'll contact for this brand first", 409)
    rules = (_settings_doc(session, bid).get(AUDIENCE_KEY) or {}).get(str(lia["id"]))
    send.require(rules and hashlib.sha256(_canonical(rules).encode()).hexdigest() == lia["audience_hash"],
                 "The approved audience's details are unavailable", 409)
    name = _clean(data.get("name"), "Campaign name", 120)
    cap = int(data.get("daily_cap") or 5)
    send.require(1 <= cap <= 20, "A daily cap is 1–20", 422)
    session.rollback()   # no lock is held while Aria drafts
    emails = draft({"business": getattr(business, "name", None), "brand": brand["name"],
                    "audience": rules, "purpose": lia["purpose"], "campaign": name})
    _authority(session, business, user)
    ident = send.insert(session, "outreach_campaigns", bid, name=name, brand_id=str(brand["id"]),
                        mailbox_id=str(box["mailbox_id"]), daily_cap=cap, status="draft", version=1,
                        sequence_version=1, timezone="Europe/London", target_rules=rules,
                        target_hash=lia["audience_hash"])
    _insert_steps(session, bid, ident, 1, emails)
    session.commit()
    return {"id": ident, "version": 1}


# --------------------------------------------------------- status, finish ---

REQUIRED = ("brand", "mailboxes", "audience", "privacy", "limits", "campaign")


def status(session, business) -> dict:
    bid = str(business.id)
    settings_rows = send.rows(session, "outreach_settings", bid)
    if not settings_rows:
        session.rollback()
        return {"steps": {s: "todo" for s in REQUIRED + ("knowledge",)}, "next": "brand", "complete": False,
                "started": False}
    # Setup finished is its own durable fact; pausing outreach never undoes it
    # (Codex OUT-15 review 2).
    started = bool((_settings_doc(session, bid).get(SETUP_KEY) or {}).get("finished_at"))
    brands = send.rows(session, "outreach_brands", bid)
    notices = _settings_doc(session, bid).get(PRIVACY_KEY) or {}
    healthy = session.execute(text(
        "SELECT count(*) FROM outreach_mailboxes WHERE business_id = :b AND enabled = :t AND health_status = 'pass'"),
        {"b": bid, "t": True}).scalar()
    approved_lia = session.execute(text(
        "SELECT count(*) FROM outreach_compliance WHERE business_id = :b AND decision = 'approved'"),
        {"b": bid}).scalar()
    ready_campaign = False
    for c in send.rows(session, "outreach_campaigns", bid):
        steps = send.rows(session, "outreach_sequence_steps", bid, "AND campaign_id = :c AND sequence_version = :v",
                          {"c": str(c["id"]), "v": c["sequence_version"]})
        if len(steps) == 3 and all(s["approved_at"] for s in steps):
            ready_campaign = True
    knowledge = session.execute(text(
        "SELECT count(*) FROM outreach_knowledge WHERE business_id = :b AND status = 'approved'"),
        {"b": bid}).scalar()
    session.rollback()
    steps = {
        "brand": "done" if brands else "todo",
        "mailboxes": "done" if healthy else "todo",
        "audience": "done" if approved_lia else ("blocked" if not brands else "todo"),
        "privacy": "done" if brands and all(str(b["id"]) in notices for b in brands) else "todo",
        "knowledge": "done" if knowledge else "todo",
        "limits": "done",
        "campaign": "done" if ready_campaign else ("blocked" if not (healthy and approved_lia) else "todo"),
    }
    todo = [s for s in REQUIRED if steps[s] != "done"]
    return {"steps": steps, "next": todo[0] if todo else None, "complete": not todo, "started": started}


def finish(session, business, user) -> dict:
    _authority(session, business, user)
    session.rollback()
    state = status(session, business)
    if not state["complete"]:
        refuse(409, "Finish these steps first: " + ", ".join(s for s in REQUIRED if state["steps"][s] != "done"))
    _authority(session, business, user)
    row = send.one(session, "outreach_settings", str(business.id), lock=True)
    send.update(session, "outreach_settings", str(business.id), row["id"], pause_all=False, updated_at=now())
    doc = _settings_doc(session, str(business.id))
    doc.setdefault(SETUP_KEY, {}).setdefault("finished_at", now().isoformat())
    doc[SETUP_KEY]["finished_by"] = str(user)
    _save_settings_doc(session, str(business.id), doc)
    session.commit()
    return {"started": True}


# ------------------------------------ changing the sending mailbox (Mike) ---

def replace_mailbox(session, business, user, data: dict) -> dict:
    """Move a brand and its unsent campaigns to a new, healthy mailbox in one
    step. Campaigns with threads stay (follow-ups keep their thread) unless
    the old mailbox is retired, which pauses its in-flight prospects. The old
    inbox stays connected so replies are still read."""
    _authority(session, business, user)
    bid = str(business.id)
    old = send.one(session, "email_accounts", bid, data.get("old_mailbox_id"), True)
    new = _registered(session, bid, data.get("new_mailbox_id"))
    reason = _clean(data.get("reason"), "Reason", 300)
    send.require(str(old["id"]) != str(new["mailbox_id"]), "Choose a different mailbox", 422)
    send.require(new["enabled"] and new["health_status"] == "pass" and not new["pause_reason"],
                 "The new mailbox must pass its check first", 409)
    moment, old_id, new_id = now(), str(old["id"]), str(new["mailbox_id"])
    session.execute(text("UPDATE outreach_brands SET default_mailbox_id = :n, updated_at = :at "
                         "WHERE business_id = :b AND default_mailbox_id = :o"),
                    {"n": new_id, "o": old_id, "b": bid, "at": moment})
    out = {"switched": [], "kept_on_old": [], "paused_enrolments": 0, "dismissed_cards": []}
    for c in send.rows(session, "outreach_campaigns", bid, "AND mailbox_id = :m ORDER BY created_at, id",
                       {"m": old_id}, True):
        history = session.execute(text(
            "SELECT 1 FROM outreach_messages WHERE business_id = :b AND campaign_id = :c "
            "AND direction = 'outbound' LIMIT 1"), {"b": bid, "c": str(c["id"])}).first()
        if history:
            out["kept_on_old"].append(str(c["id"]))
            continue
        send.update(session, "outreach_campaigns", bid, c["id"], mailbox_id=new_id,
                    version=int(c["version"]) + 1, updated_at=moment)
        out["switched"].append(str(c["id"]))
    for action in send.rows(session, "aria_actions", bid, "AND action_type = 'send_outreach' AND status = 'proposed'",
                            lock=True):
        if str(send.loads(action["payload"]).get("mailbox_id")) == old_id:
            session.execute(text("UPDATE aria_actions SET status = 'dismissed', error = :e, updated_at = :at "
                                 "WHERE business_id = :b AND id = :id"),
                            {"e": f"Sending mailbox changed: {reason}", "at": moment, "b": bid, "id": str(action["id"])})
            out["dismissed_cards"].append(str(action["id"]))
    if data.get("retire_old"):
        boxes = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": old_id}, True)
        if boxes:
            send.update(session, "outreach_mailboxes", bid, boxes[0]["id"], enabled=False,
                        pause_reason=f"Retired by owner: {reason}"[:1000], updated_at=moment)
        for cid in out["kept_on_old"]:
            paused = session.execute(text(
                "UPDATE outreach_enrolments SET state = 'paused', stop_reason = 'sending mailbox retired', "
                "updated_at = :at WHERE business_id = :b AND campaign_id = :c AND state IN ('pending', 'active')"),
                {"at": moment, "b": bid, "c": cid})
            out["paused_enrolments"] += paused.rowcount or 0
    session.commit()
    return out


def copy_campaign_to_mailbox(session, business, user, campaign_id, data: dict) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    c = send.one(session, "outreach_campaigns", bid, campaign_id)
    box = _registered(session, bid, data.get("mailbox_id"))
    name = _clean(data.get("name") or f"{c['name']} ({box['email_address']})", "Campaign name", 120)
    steps = send.rows(session, "outreach_sequence_steps", bid, "AND campaign_id = :c AND sequence_version = :v "
                      "ORDER BY ordinal", {"c": str(c["id"]), "v": c["sequence_version"]})
    emails = [{"subject": e["subject"], "body": e["body"]} for e in (send.loads(s["template_text"]) for s in steps)]
    ident = send.insert(session, "outreach_campaigns", bid, name=name, brand_id=str(c["brand_id"]),
                        mailbox_id=str(box["mailbox_id"]), daily_cap=int(c["daily_cap"]), status="draft",
                        version=1, sequence_version=1, timezone="Europe/London",
                        target_rules=send.loads(c["target_rules"]) or {}, target_hash=c["target_hash"])
    _insert_steps(session, bid, ident, 1, emails)
    session.commit()
    return {"id": ident, "version": 1}
