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

import logging

from services import ai_costs, ai_router, aria_actions
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
               # a real Gmail/Workspace outbound address; SPF must authorise it
               "sender_ip": "209.85.220.41",
               "dkim_help": "In the Google Workspace admin console, open Apps, Google Workspace, "
                            "Gmail, Authenticate email, generate a DKIM key and publish the record it gives you.",
               "dkim_host": "google._domainkey",
               "dkim_steps": ("Sign in to admin.google.com as an administrator.",
                              "Open Apps → Google Workspace → Gmail → Authenticate email.",
                              "Choose your domain and click Generate new record (2048-bit).",
                              "Add the TXT record it shows, named google._domainkey, where your domain's DNS is managed.",
                              "Wait for it to be live (up to an hour), then click Start authentication."),
               "dkim_url": "https://support.google.com/a/answer/174124"},
    "microsoft": {"spf": "spf.protection.outlook.com", "selectors": ("selector1", "selector2"),
                  # a real Exchange Online outbound address (40.107.0.0/16)
                  "sender_ip": "40.107.22.50",
                  "name": "Microsoft 365",
                  "dkim_help": "In Microsoft 365 Defender, open Email authentication settings, DKIM, "
                               "enable signing for your domain and publish the two selector CNAME records.",
                  "dkim_host": "selector1._domainkey and selector2._domainkey",
                  "dkim_steps": ("Sign in to security.microsoft.com as an administrator.",
                                 "Open Email & collaboration → Policies & rules → Threat policies → "
                                 "Email authentication settings → DKIM.",
                                 "Choose your domain; Microsoft shows two CNAME records (selector1 and selector2).",
                                 "Add both CNAME records where your domain's DNS is managed.",
                                 "Once they are live, switch 'Sign messages for this domain with DKIM signatures' on."),
                  "dkim_url": "https://learn.microsoft.com/en-us/defender-office-365/email-authentication-dkim-configure"},
}
# Settings-document keys this ticket owns; the generic settings save keeps them.
PRIVACY_KEY, AUDIENCE_KEY = "outreach_privacy", "outreach_audiences"
PROFILE_KEY = "outreach_brand_profiles"   # OUT-20: what each brand offers, for Aria's drafts
PROFILE_FIELDS = ("offer", "audience", "proof", "tone", "ask", "website")
# OUT-20: who runs a domain's DNS, from its nameservers. Domain Connect marks
# providers that offer one-click record changes (domainconnect.org).
DNS_HOSTS = (
    (("phase8.net", "names.co.uk"), "namesco", "names.co.uk",
     "https://www.names.co.uk/support/articles/changing-your-domains-dns-settings/"),
    (("domaincontrol.com",), "godaddy", "GoDaddy", "https://www.godaddy.com/help/manage-dns-records-680"),
    (("cloudflare.com",), "cloudflare", "Cloudflare",
     "https://developers.cloudflare.com/dns/manage-dns-records/how-to/create-dns-records/"),
    (("ui-dns.",), "ionos", "IONOS", None),
    (("123-reg.co.uk",), "123reg", "123 Reg", None),
    (("registrar-servers.com",), "namecheap", "Namecheap", None),
    (("squarespacedns.com", "googledomains.com"), "squarespace", "Squarespace", None),
    (("wixdns.net",), "wix", "Wix", None),
    (("awsdns",), "route53", "Amazon Route 53", None),
    (("azure-dns.",), "azure", "Microsoft Azure DNS", None),
)
DNS_PAUSE = "Daily check failed:"
SETUP_KEY = "outreach_setup"   # the only pause a DNS pass may lift


logger = logging.getLogger(__name__)


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


def load_business_row(session, bid: str):
    """The business as a plain record, for system jobs with no request."""
    row = session.execute(text(
        "SELECT id, name, plan_tier, feature_flags, subscription_status, is_active, trial_ends_at "
        "FROM businesses WHERE id = :b"), {"b": str(bid)}).mappings().first()
    return SimpleNamespace(**row) if row else None


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
    profile = _profile(data.get("profile")) if "profile" in data else None
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
        if profile is not None:
            _save_profile(session, bid, str(brand["id"]), profile)
        session.commit()
        return {"id": str(brand["id"]), "version": int(brand["version"]) + bool(changes),
                "privacy_url": brand["privacy_url"]}
    ident = str(uuid.uuid4())
    url = privacy_url(ident)
    session.execute(text(
        "INSERT INTO outreach_brands (id, business_id, created_at, updated_at, name, default_mailbox_id, "
        "privacy_url, sender_identity, version) VALUES (:id, :b, :at, :at, :n, :m, :u, :s, 1)"),
        {"id": ident, "b": bid, "at": now(), "n": name, "m": default_box or None, "u": url, "s": sender})
    if profile is not None:
        _save_profile(session, bid, ident, profile)
    session.commit()
    return {"id": ident, "version": 1, "privacy_url": url}


def _profile(value) -> dict:
    value = value if isinstance(value, dict) else {}
    out = {}
    for k in PROFILE_FIELDS:
        v = value.get(k)
        if v is not None and str(v).strip():
            out[k] = _clean(v, k.capitalize(), 1000, one_line=False)
    return out


def _save_profile(session, bid: str, brand_id: str, profile: dict) -> None:
    doc = _settings_doc(session, bid)
    doc.setdefault(PROFILE_KEY, {})[brand_id] = profile
    _save_settings_doc(session, bid, doc)


def update_brand(session, business, user, brand_id, data: dict) -> dict:
    """OUT-20: edit a brand at any time — its name, sender identity and the
    details Aria drafts from. Owner only; this business's brands only."""
    _authority(session, business, user)
    bid = str(business.id)
    brand = send.one(session, "outreach_brands", bid, brand_id, True)
    changes = {}
    if "name" in data:
        name = _clean(data.get("name"), "Brand name", 120)
        clash = send.rows(session, "outreach_brands", bid, "AND name = :n AND id <> :i", {"n": name, "i": str(brand["id"])})
        if clash:
            refuse(409, "Another brand already has that name.")
        if name != brand["name"]:
            changes["name"] = name
    if "sender_identity" in data:
        sender = _clean(data.get("sender_identity"), "Sender identity", 200)
        if sender != brand["sender_identity"]:
            changes["sender_identity"] = sender
    if changes:
        send.update(session, "outreach_brands", bid, brand["id"], **changes,
                    version=int(brand["version"]) + 1, updated_at=now())
    if "profile" in data:
        _save_profile(session, bid, str(brand["id"]), _profile(data.get("profile")))
    session.commit()
    return {"id": str(brand["id"]), "version": int(brand["version"]) + bool(changes)}


def register_mailbox(session, business, user, data: dict) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    account = send.one(session, "email_accounts", bid, data.get("mailbox_id"), True)
    given = data.get("daily_cap")
    cap = int(given or 5)
    send.require(1 <= cap <= 20, "A daily cap is 1–20", 422)
    found = send.rows(session, "outreach_mailboxes", bid, "AND mailbox_id = :m", {"m": str(account["id"])}, True)
    if found:
        if given is not None:   # a recheck without a cap never resets the owner's limit
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
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    # A timeout or broken nameserver raises: SPF then reports a temporary
    # error rather than mistaking an outage for "no record".
    return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


def _tag_list(record: str) -> list:
    """Tag=value pairs in order (DKIM RFC 6376 / DMARC RFC 7489 syntax)."""
    out = []
    for part in record.split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            return []          # malformed: no usable record
        k, v = part.split("=", 1)
        out.append((k.strip(), "".join(v.split())))
    return out


def _usable_dkim(record: str) -> bool:
    """RFC 6376: v (if present, first) is exactly DKIM1; k is rsa or ed25519;
    not in testing mode (t=y); usable for email (s absent, * or email); and p
    decodes to a real key — RSA of at least 1024 bits or 32-byte Ed25519 (an
    empty p= is a revoked key). Codex OUT-15 reviews 1–3."""
    import base64
    import binascii
    tags = _tag_list(record)
    if not tags:
        return False
    names = [k for k, _ in tags]          # tag names are case-sensitive (RFC 6376 3.2)
    if len(set(names)) != len(names):
        return False                                   # duplicate tags are invalid
    t = dict(tags)
    if "v" in t and (names[0] != "v" or t["v"] != "DKIM1"):
        return False
    key_type = t.get("k", "rsa").lower()
    if key_type not in ("rsa", "ed25519"):
        return False
    if "y" in [f.lower() for f in t.get("t", "").split(":")]:
        return False
    if "s" in t and not {x.lower() for x in t["s"].split(":")} & {"*", "email"}:
        return False
    try:
        raw = base64.b64decode(t.get("p", ""), validate=True)
    except (binascii.Error, ValueError):
        return False
    if not raw:
        return False
    if key_type == "ed25519":
        return len(raw) == 32
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        key = load_der_public_key(raw)
    except Exception:
        return False
    return isinstance(key, rsa.RSAPublicKey) and key.key_size >= 1024


# pyspf performs its own lookups through the module-level `spf.DNSLookup`.
# We route those to the resolver for THIS check via a thread-local, and leave
# every other part of pyspf — its void-lookup and lookup-count limits, CNAME
# handling and caching — exactly as written (Codex OUT-15 review 5: overriding
# `query.dns` silently dropped its void-lookup limit).
import threading as _threading

_SPF_LOCAL = _threading.local()


def _install_spf_lookup():
    import spf
    if getattr(spf.DNSLookup, "_business_hero", False):
        return
    original = spf.DNSLookup

    def lookup(name, qtype, tcpfallback=True, timeout=30):
        resolvers = getattr(_SPF_LOCAL, "resolvers", None)
        if resolvers is None:
            return original(name, qtype, tcpfallback, timeout)
        txt, other = resolvers
        name = str(name).rstrip(".")
        try:
            if qtype == "TXT":
                return [((name, "TXT"), (r.encode(),)) for r in txt(name.lower())]
            if qtype == "SPF":
                return []
            return [((name, qtype), v) for v in other(name.lower(), qtype)]
        except Exception as exc:
            raise spf.TempError(f"DNS lookup failed for {name}: {type(exc).__name__}")
    lookup._business_hero = True
    spf.DNSLookup = lookup


def _spf_result(domain: str, sender_ip: str, txt: Callable, other: Callable) -> str:
    """RFC 7208 via pyspf, the established implementation (Mike, 24 Oct
    2026, after Codex's OUT-15 review 4): pyspf's result for a real sending
    address of the provider — "pass", "fail", "permerror", "temperror" (a DNS
    lookup failed: inconclusive, never a verdict on the record)..."""
    import spf
    _install_spf_lookup()
    _SPF_LOCAL.resolvers = (txt, other)
    try:
        return str(spf.query(i=sender_ip, s=f"postmaster@{domain}", h=domain, strict=True, timeout=15).check()[0])
    except Exception:
        return "temperror"
    finally:
        _SPF_LOCAL.resolvers = None


def _spf_authorises(domain: str, sender_ip: str, txt: Callable, other: Callable) -> bool:
    """Only a genuine `pass` passes; every error, limit or failure is a fail."""
    return _spf_result(domain, sender_ip, txt, other) == "pass"


def _usable_dmarc(record: str) -> bool:
    """RFC 7489: the first tag is exactly v=DMARC1, and p is none,
    quarantine or reject."""
    tags = _tag_list(record)
    if not tags or tags[0] != ("v", "DMARC1"):
        return False
    policy = {k.lower(): v for k, v in tags}.get("p", "").lower()
    return policy in ("none", "quarantine", "reject")


def dns_other(name: str, qtype: str) -> list:
    """A, AAAA, MX and PTR lookups for SPF mechanisms, in pyspf's shape."""
    import dns.resolver
    try:
        answer = dns.resolver.resolve(name, qtype, lifetime=5)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    if qtype in ("A", "AAAA"):
        return [r.address for r in answer]
    if qtype == "MX":
        return [(r.preference, r.exchange.to_text(True)) for r in answer]
    if qtype == "PTR":
        return [r.target.to_text(True) for r in answer]
    if qtype == "NS":   # OUT-20: who runs the domain's DNS (Codex OUT-20 review 1)
        return [r.target.to_text(True) for r in answer]
    return []


def _evaluate(account: dict, resolve: Callable, other_records: Optional[Callable] = None) -> dict:
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
    if other_records is None:   # an injected TXT resolver (tests) has no other records
        other_records = dns_other if resolve is dns_txt else (lambda name, qtype: [])
    advice = []
    if _spf_authorises(domain, provider["sender_ip"], resolve, other_records):
        evidence["spf"] = "pass"
    else:
        advice.append(f"SPF: your domain's one SPF record must include include:{provider['spf']} for "
                      f"{provider['name']}. Edit the existing record on {domain} rather than adding a second one.")
    for selector in provider["selectors"]:
        if any(_usable_dkim(t) for t in txt(f"{selector}._domainkey.{domain}")):
            evidence["dkim"] = "pass"
            evidence["selectors"].append(selector)
    if evidence["dkim"] != "pass":
        advice.append("DKIM: " + provider["dkim_help"])
    dmarc = [t for t in txt(f"_dmarc.{domain}") if t.strip().lower().startswith("v=dmarc1")]   # candidates
    if len(dmarc) == 1 and _usable_dmarc(dmarc[0]):   # more than one is invalid
        evidence["dmarc"] = "pass"
    else:
        advice.append(f"DMARC: {domain} needs exactly one valid DMARC record (TXT at _dmarc.{domain}), for example "
                      f"v=DMARC1; p=none; rua=mailto:{address}")
    evidence["domain_control"] = bool(account.get("token_ciphertext"))   # connected by OAuth
    evidence["from_aligned"] = evidence["spf"] == "pass" and evidence["dkim"] == "pass"
    ok = all(evidence[k] == "pass" for k in ("spf", "dkim", "dmarc")) and evidence["domain_control"]
    def txt_or_none(name):
        """None when the lookup failed: a failure never means "no record"."""
        try:
            return [str(t) for t in (resolve(name) or [])]
        except Exception:
            return None
    guide = _guide(domain, address, provider, evidence, txt_or_none, other_records)
    return {"status": "pass" if ok else "fail", "evidence": evidence, "advice": advice, "guide": guide}


def _dns_host(domain: str, txt: Callable, other_records: Callable) -> dict:
    try:
        servers = [str(n).lower().rstrip(".") for n in (other_records(domain, "NS") or [])]
    except Exception:
        servers = []
    supported = any(str(t).strip() for t in (txt(f"_domainconnect.{domain}") or []))
    connect = {"supported": supported, "available": supported and os.environ.get("DOMAIN_CONNECT_ENABLED") == "1"}
    for marks, key, name, url in DNS_HOSTS:
        if any(m in server for server in servers for m in marks):
            return {"key": key, "name": name, "help_url": url, "nameservers": servers, "domain_connect": connect}
    return {"key": "unknown", "name": None, "help_url": None, "nameservers": servers, "domain_connect": connect}


def _guide(domain: str, address: str, provider: dict, evidence: dict, txt: Callable, other_records: Callable) -> dict:
    """OUT-20: a plain fix guide built from the domain's real records — what to
    change, exact values, and a ready-written email for whoever runs the DNS."""
    records = []
    unknown = "We couldn't read your domain's records just now, so we can't yet say exactly what to change. We'll check again shortly."
    if evidence["spf"] != "pass":
        found = txt(domain)
        include = f"include:{provider['spf']}"
        if found is None:
            records.append({"what": "spf", "type": "TXT", "host": "@", "action": "unknown", "current": None,
                            "value": None, "why": unknown})
        else:
            current = [t.strip() for t in found if t.strip().lower().split(" ")[0] == "v=spf1"]
            if len(current) > 1:
                records.append({"what": "spf", "type": "TXT", "host": "@", "action": "merge", "current": current,
                                "value": None, "include": include,
                                "why": "Your domain has more than one SPF record, and receivers ignore them all: "
                                       f"there must be only one. Combine them into a single record that includes {include}."})
            elif current:
                proposed = _spf_with(current[0], include)

                def proposed_txt(n):
                    if n.lower().rstrip(".") == domain:
                        return [proposed]
                    found_n = txt(n)
                    if found_n is None:   # a failed lookup stays a failure: inconclusive, not "no record"
                        raise LookupError(n)
                    return found_n
                # Only offer a value that the SPF evaluator itself would pass for
                # the provider (Codex OUT-20 review 3: a malformed term kept from
                # the old record would still fail). A lookup that failed is
                # inconclusive, never blamed on the record (review 4).
                verdict = _spf_result(domain, provider["sender_ip"], proposed_txt, other_records)
                if verdict == "temperror":
                    records.append({"what": "spf", "type": "TXT", "host": "@", "action": "unknown", "current": current[0],
                                    "value": None, "why": unknown})
                elif verdict == "pass":
                    records.append({"what": "spf", "type": "TXT", "host": "@", "action": "edit", "current": current[0],
                                    "value": proposed,
                                    "why": f"Your SPF record doesn't yet list {provider['name']}, so mail you send through "
                                           "it isn't proven to come from you. Edit the existing record (don't add a second one)."})
                else:
                    records.append({"what": "spf", "type": "TXT", "host": "@", "action": "manual", "current": current[0],
                                    "value": None, "include": include,
                                    "why": f"Even with {include} added, your SPF record wouldn't pass the check (for "
                                           "example an entry written incorrectly, or too many lookups), so we can't safely "
                                           "write the fix for you. It needs correcting by hand: the email to your web person "
                                           "below explains this."})
            else:
                records.append({"what": "spf", "type": "TXT", "host": "@", "action": "add", "current": None,
                                "value": f"v=spf1 {include} ~all",
                                "why": f"Your domain has no SPF record yet. This one says {provider['name']} may send "
                                       "email for you."})
    if evidence["dkim"] != "pass":
        records.append({"what": "dkim", "type": "TXT" if provider["name"] == "Google Workspace" else "CNAME",
                        "host": provider["dkim_host"], "action": "add", "current": None, "value": None,
                        "why": "A signature key proves each email really came from you and wasn't altered.",
                        "steps": list(provider["dkim_steps"]), "help_url": provider["dkim_url"]})
    if evidence["dmarc"] != "pass":
        found = txt(f"_dmarc.{domain}")
        fresh = f"v=DMARC1; p=none; rua=mailto:{address}"
        if found is None:
            records.append({"what": "dmarc", "type": "TXT", "host": "_dmarc", "action": "unknown", "current": None,
                            "value": None, "why": unknown})
        else:
            current = [t.strip() for t in found if t.strip().lower().startswith("v=dmarc1")]
            if not current:
                records.append({"what": "dmarc", "type": "TXT", "host": "_dmarc", "action": "add", "current": None,
                                "value": fresh,
                                "why": "This tells receivers your domain checks its email, and sends you reports."})
            elif len(current) > 1:
                records.append({"what": "dmarc", "type": "TXT", "host": "_dmarc", "action": "merge", "current": current,
                                "value": None,
                                "why": "Your domain has more than one DMARC record, so receivers ignore them: keep just one."})
            else:
                records.append({"what": "dmarc", "type": "TXT", "host": "_dmarc", "action": "edit", "current": current[0],
                                "value": _dmarc_repaired(current[0], fresh),
                                "why": "Your DMARC record isn't written in a way receivers accept. Replace it with this "
                                       "(your existing policy is kept where it was valid)."})
    host = _dns_host(domain, txt, other_records)
    # What to type in the host/name box. names.co.uk asks for it to be left
    # blank for the domain itself (Codex OUT-20 review 4); most others take "@".
    for r in records:
        if r["host"] == "@":
            r["host_label"] = "leave it blank" if host["key"] == "namesco" else "@"
        else:
            r["host_label"] = r["host"]
    return {"domain": domain, "mail_provider": provider["name"], "dns_host": host, "records": records,
            "email_to_helper": _helper_email(domain, host, records)}


def _spf_with(record: str, include: str) -> str:
    """The record with the provider's include as a passing mechanism placed
    first, so nothing (such as an earlier "all") can stop it being reached.
    Any other copy of that include — qualified or not — is removed; every
    other mechanism is kept in order. Whole mechanisms only, never substrings."""
    terms = record.split()
    target = include.lower()
    kept = [t for t in terms[1:] if t.lstrip("+-~?").lower() != target]
    return " ".join([terms[0], include] + kept)


# mailto:local@host.tld with an optional size limit (RFC 7489 §6.2); the host
# must be a real domain name (Codex OUT-20 review 4: "bad/#.com" was kept).
_DMARC_URI = __import__("re").compile(
    r"^mailto:[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(![0-9]+[kmgt]?)?$",
    __import__("re").I)
_DMARC_FO = __import__("re").compile(r"^[01ds](:[01ds])*$", __import__("re").I)
_DMARC_RF = __import__("re").compile(r"^[a-z0-9]+(:[a-z0-9]+)*$", __import__("re").I)
# RFC 7489 §6.4 grammar for the optional tags kept on repair (Codex OUT-20 review 3).
DMARC_TAGS = {
    "sp": lambda v: v.lower() in ("none", "quarantine", "reject"),
    "rua": lambda v: bool(v) and all(_DMARC_URI.match(u) for u in v.split(",")),
    "ruf": lambda v: bool(v) and all(_DMARC_URI.match(u) for u in v.split(",")),
    "adkim": lambda v: v.lower() in ("r", "s"),
    "aspf": lambda v: v.lower() in ("r", "s"),
    "pct": lambda v: v.isdigit() and 0 <= int(v) <= 100,
    "fo": lambda v: bool(_DMARC_FO.match(v)),
    "rf": lambda v: bool(_DMARC_RF.match(v)),
    "ri": lambda v: v.isdigit(),
}


def _dmarc_repaired(record: str, fresh: str) -> str:
    """A valid DMARC record that keeps the owner's policy and every valid
    optional setting (subdomain policy, reports, alignment...) in order; an
    invalid tag is dropped. Without a valid policy, the fresh starter record."""
    tags = []
    for part in record.split(";"):
        key, _, value = part.strip().partition("=")
        if key.strip():
            tags.append((key.strip().lower(), value.strip()))
    policy = next((v.lower() for k, v in tags if k == "p"), "")
    if policy not in ("none", "quarantine", "reject"):
        return fresh
    # Whitespace the grammar allows around ":" and "," is normalised first
    # (Codex OUT-20 review 4: "fo=0 : 1" is valid and was dropped).
    import re as _re
    tags = [(k, _re.sub(r"\s*([:,])\s*", r"\1", v)) for k, v in tags]
    kept = [(k, v) for k, v in tags if k in DMARC_TAGS and DMARC_TAGS[k](v)]
    if not any(k == "rua" for k, _ in kept):
        kept.append(("rua", fresh.split("rua=", 1)[1]))
    return "; ".join(["v=DMARC1", f"p={policy}"] + [f"{k}={v}" for k, v in kept])


def _host_words(r: dict) -> str:
    return "leave the hostname blank" if r.get("host_label") == "leave it blank" else f"host {r['host']}"


def _helper_email(domain: str, host: dict, records: list) -> dict:
    lines = ["Hi,", "",
             f"Could you please add these settings to the DNS for {domain}"
             + (f" (managed at {host['name']})" if host.get("name") else "") + "? They let receiving mail servers check that the "
             "emails we send really come from us, so they're less likely to be treated as spam.", ""]
    for n, r in enumerate(records, 1):
        if r["what"] == "spf" and r["action"] == "edit":
            lines += [f"{n}. Edit the existing TXT record on {domain} ({_host_words(r)}) that starts v=spf1, so it reads:",
                      f"   {r['value']}", f"   (it currently reads: {r['current']})"]
        elif r["what"] == "spf" and r["action"] == "merge":
            lines += [f"{n}. {domain} has more than one TXT record starting v=spf1. Please combine them into one "
                      f"record that also includes {r['include']}."]
        elif r["what"] == "spf" and r["action"] == "manual":
            lines += [f"{n}. The TXT record on {domain} that starts v=spf1 currently reads:", f"   {r['current']}",
                      f"   Even with {r['include']} added it wouldn't pass an SPF check (for example an entry written",
                      f"   incorrectly, or too many DNS lookups). Please correct it so it's valid and includes {r['include']}."]
        elif r["action"] == "unknown":
            lines += [f"{n}. We couldn't read {domain}'s {r['what'].upper()} record when this was written; please check "
                      "it exists and is valid."]
        elif r["what"] == "dmarc" and r["action"] == "merge":
            lines += [f"{n}. {domain} has more than one DMARC record (_dmarc). Please keep just one."]
        elif r["what"] == "dmarc" and r["action"] == "edit":
            lines += [f"{n}. Replace the TXT record named _dmarc.{domain} with:", f"   {r['value']}",
                      f"   (it currently reads: {r['current']})"]
        elif r["what"] == "spf":
            lines += [f"{n}. Add a TXT record on {domain} ({_host_words(r)}) with the value:", f"   {r['value']}"]
        elif r["what"] == "dkim":
            lines += [f"{n}. Add the email signature (DKIM) record named {r['host']}. I'll send you its value from "
                      "our email admin console, or you can generate it there: " + r["help_url"]]
        else:
            lines += [f"{n}. Add a TXT record named {r['host']}.{domain} with the value:", f"   {r['value']}"]
    lines += ["", "Thank you!"]
    return {"subject": f"Email settings for {domain}", "body": "\n".join(lines)}


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
        # Any failed check marks a DNS pause (never over a safety hold), so the
        # daily check re-enables the mailbox once the records are fixed.
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
    after = send.rows(session, "outreach_mailboxes", bid, "AND id = :id", {"id": str(found[0]["id"])})[0]
    session.commit()
    reason = after["pause_reason"]
    return {**result, "enabled": bool(after["enabled"]),
            "hold": reason if reason and not str(reason).startswith(DNS_PAUSE) else None}


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
        "FROM outreach_mailboxes m WHERE m.enabled = :t OR m.pause_reason LIKE :dns"),
        {"t": True, "dns": DNS_PAUSE + "%"}).mappings().all()
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
            dns_paused = bool(current) and str(current[0]["pause_reason"] or "").startswith(DNS_PAUSE)
            if not current or not (current[0]["enabled"] or dns_paused) or (already and already >= checked_before):
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

DRAFT_MAX_TOKENS = 4000


def draft_model() -> str:
    return os.getenv("ARIA_DRAFT_MODEL", "gpt-4o")


def _model_json(instructions: str, context: dict) -> dict:
    """One JSON draft from the first AI provider that can serve it (OUT-19 H:
    failover across providers; every attempt is noted for the cost ledger)."""
    try:
        return ai_router.json_chat(instructions, context, purpose="draft", max_tokens=DRAFT_MAX_TOKENS)
    except ai_router.AllProvidersFailed:
        refuse(503, "Aria can't draft this right now; write it yourself or try again later.")


def _ai_draft(session, business, draft: Callable, context: dict, *, brand_id):
    """Run one Aria draft (OUT-19): refused while the platform's AI spend is
    paused or the model has no price; its cost is recorded and committed as
    soon as the model returns, whether or not the draft is then accepted."""
    if draft in (model_draft_audience, model_draft_notice, model_draft_emails, model_redraft_emails) and \
            not ai_router.chain("draft", include_down=True):
        session.rollback()
        refuse(503, "Aria's drafting is unavailable: no AI provider with a priced model is configured. "
                    "Write this yourself for now.")
    if not ai_costs.allowed(session):
        session.rollback()
        refuse(503, "Aria's drafting is paused for now. Write this yourself, or try again later.")
    # OUT-19 B: the brand's allowance, with a small reserve for drafting. The
    # draft's likely cost is HELD under the business lock before Aria starts,
    # so drafts and research running at once all see it (Codex OUT-19 B+C
    # review 1), and released when its real cost is recorded.
    from services import outreach_allowance
    bid, moment = str(business.id), now()
    # The request is frozen before its hold is worked out, so the bound and the
    # call see the same context (Codex OUT-19 B+C review 3).
    context = json.loads(json.dumps(context, default=str))
    hold = _draft_hold(draft, context) if brand_id is not None else 0
    session.rollback()
    send.lock_business(session, bid) if send.pg(session) else session.execute(
        text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})
    if not outreach_allowance.may_draft(session, bid, brand_id, moment, hold):
        session.rollback()
        refuse(409, outreach_allowance.DRAFT_ALLOWANCE_USED)
    outreach_allowance.hold_draft(session, bid, brand_id, moment, hold)
    session.commit()   # held; no lock is held while Aria drafts
    with ai_costs.collect() as spent:
        failure = None
        try:
            return draft(context)
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                session.rollback()
                if send.pg(session):
                    send.lock_business(session, bid)
                if spent:
                    ai_costs.save(session, bid, spent, purpose="draft", brand_id=brand_id)
                if failure is None:
                    # Settled: the real cost replaces the hold.
                    outreach_allowance.hold_draft(session, bid, brand_id, moment, -hold)
                # A draft that failed keeps its hold beside whatever it did
                # record: an attempt interrupted after dispatch may still have
                # been billed, and only success proves the accounting complete
                # (fail closed; Codex OUT-19 B+C reviews 2 and 3).
                if spent and failure is None:
                    recorded = sum(ai_costs.cost(c["provider"], c["model"], c["input_tokens"], c["output_tokens"],
                                                 c.get("tool_calls", 0)) for c in spent)
                    if recorded > hold:
                        logger.error("An Aria draft for business %s cost %.1fp, over its %sp hold", bid, recorded, hold)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Could not record an Aria draft's AI cost for business %s", business.id)
                if failure is None:
                    raise   # never hand out a draft whose cost wasn't recorded
                # otherwise the draft's own error propagates; its hold stays counted (fail closed)


SYSTEM_PROMPT_MAX_CHARS = 8000   # the longest instructions Aria's drafts send (tested)
# A provider counts a little more than the text itself (roles, message framing):
# this margin, in tokens, covers it, so reported usage stays within the bound.
PROVIDER_OVERHEAD_TOKENS = 1000
MODEL_DRAFTS = None              # set below: the model drafters, whose cost the chain bound covers


def _draft_hold(draft: Callable, context: dict) -> int:
    """What a draft holds against its brand's allowance before Aria starts: for
    the model drafters, the provider chain's worst case for this context, so
    the real cost can never exceed it; for any other drafter, the configured
    hold."""
    from services import outreach_allowance
    if draft in MODEL_DRAFTS:
        chars = SYSTEM_PROMPT_MAX_CHARS + len(json.dumps(context, default=str)) + PROVIDER_OVERHEAD_TOKENS
        return max(1, ai_router.chat_bound_pence(chars, DRAFT_MAX_TOKENS, "draft"))
    return outreach_allowance.draft_hold_pence()


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


EMAIL_CRAFT = (
    "Write like a real person at this brand writing to one specific kind of organisation, not like marketing. "
    "Use the brand details: what is offered, who it is for, proof, tone and the ask. Open with something "
    "relevant to the recipient's world, not about the sender. One clear, low-effort ask. Plain, warm, "
    "specific; no hype, no clichés ('I hope this finds you well', 'just checking in', 'game-changer'), no "
    "exclamation marks, no invented facts, numbers or names. Short subject lines a colleague might write "
    "(no clickbait, no capitals, no emojis). First email under 110 words; each follow-up shorter and adds "
    "something new (a fact, a useful angle or an easy way to say no), never just a reminder. British English. "
    "No signature, footer or unsubscribe line: those are added for you.")


def model_draft_emails(context: dict) -> list:
    out = _model_json(
        "Draft three B2B outreach emails for the campaign given: a first email, a follow-up after 5 working "
        "days and a final one after 7 more. " + EMAIL_CRAFT +
        " Return JSON {\"emails\": [{\"subject\": ..., \"body\": ...}, x3]}.", context)
    return list(out.get("emails") or [])


def model_redraft_emails(context: dict) -> list:
    out = _model_json(
        "Rewrite the three outreach emails in current_emails, following the owner's notes in owner_notes "
        "closely; they know their business and customers best. Keep what already works. " + EMAIL_CRAFT +
        " Return JSON {\"emails\": [{\"subject\": ..., \"body\": ...}, x3]} in the same order.", context)
    return list(out.get("emails") or [])


def draft_audience(session, business, user, data: dict, *, draft: Callable = model_draft_audience) -> dict:
    _authority(session, business, user)
    bid = str(business.id)
    brand = send.one(session, "outreach_brands", bid, data.get("brand_id"))
    rules = {"description": _clean(data.get("description"), "Audience description", 2000, one_line=False),
             "segments": [str(s)[:80] for s in (data.get("segments") or [])][:20],
             "regions": [str(r)[:80] for r in (data.get("regions") or [])][:20]}
    audience_hash = hashlib.sha256(_canonical(rules).encode()).hexdigest()
    drafted = _ai_draft(session, business, draft, {"business": getattr(business, "name", None), "brand": brand["name"], **rules},
                        brand_id=str(brand["id"]))
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
    drafted = _ai_draft(session, business, draft, {"business": getattr(business, "name", None), "brand": brand["name"],
                                                   "sender_identity": brand["sender_identity"]}, brand_id=str(brand["id"]))
    return {"text": drafted}


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


MODEL_DRAFTS = (model_draft_audience, model_draft_notice, model_draft_emails, model_redraft_emails)


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
    profile = (_settings_doc(session, bid).get(PROFILE_KEY) or {}).get(str(brand["id"]), {})
    emails = _ai_draft(session, business, draft, {"business": getattr(business, "name", None), "brand": brand["name"],
                                                  "sender_identity": brand["sender_identity"], "brand_details": profile,
                                                  "audience": rules, "purpose": lia["purpose"], "campaign": name},
                       brand_id=str(brand["id"]))
    _authority(session, business, user)
    ident = send.insert(session, "outreach_campaigns", bid, name=name, brand_id=str(brand["id"]),
                        mailbox_id=str(box["mailbox_id"]), daily_cap=cap, status="draft", version=1,
                        sequence_version=1, timezone="Europe/London", target_rules=rules,
                        target_hash=lia["audience_hash"])
    _insert_steps(session, bid, ident, 1, emails)
    session.commit()
    return {"id": ident, "version": 1}


def redraft_emails(session, business, user, campaign_id, data: dict, *, draft: Callable = model_redraft_emails) -> dict:
    """OUT-20: the owner works with Aria on the wording. Aria rewrites the three
    emails from the owner's notes, the brand details and the audience; nothing
    is saved — the owner reviews, edits, saves and approves as before."""
    _authority(session, business, user)
    bid = str(business.id)
    campaign = send.one(session, "outreach_campaigns", bid, campaign_id)
    brand = send.one(session, "outreach_brands", bid, campaign["brand_id"])
    notes = _clean(data.get("notes"), "Your notes for Aria", 4000, one_line=False)
    current = data.get("current") or []
    send.require(isinstance(current, list) and len(current) == 3, "Send the three current emails", 422)
    current = [{"subject": _clean(e.get("subject"), "Subject", 200), "body": _clean(e.get("body"), "Body", 20000, one_line=False)}
               for e in current]
    doc = _settings_doc(session, bid)
    rules = send.loads(campaign["target_rules"]) if isinstance(campaign["target_rules"], str) else campaign["target_rules"]
    context = {"business": getattr(business, "name", None), "brand": brand["name"],
               "sender_identity": brand["sender_identity"],
               "brand_details": (doc.get(PROFILE_KEY) or {}).get(str(brand["id"]), {}),
               "audience": rules or {}, "campaign": campaign["name"], "current_emails": current, "owner_notes": notes}
    emails = _ai_draft(session, business, draft, context, brand_id=str(brand["id"]))
    send.require(isinstance(emails, list) and len(emails) == 3 and all(isinstance(e, dict) for e in emails),
                 "Aria couldn't produce three emails this time. Try again, or edit them yourself.", 422)
    return {"emails": [{"subject": _clean(e.get("subject"), "Subject", 200),
                        "body": _clean(e.get("body"), "Body", 20000, one_line=False)} for e in emails]}


# --------------------------------------------------------- status, finish ---

REQUIRED = ("brand", "mailboxes", "audience", "privacy", "limits", "campaign")

def _truthy(value) -> bool:
    return value in (True, 1, "1", "true", "t")


def _brand_status(brand, notices, rules, boxes, accounts, healthy_ids, lias, campaigns, approved_steps,
                  profiles=None) -> dict:
    """One brand's setup (OUT-18): its mailbox, its audiences each with its own
    email sequence, its privacy notice. Ready = an approved audience whose
    campaign is approved and sends from this brand's healthy mailbox."""
    bid_ = str(brand["id"])
    profiles = profiles or {}
    mine = [c for c in campaigns if str(c["brand_id"]) == bid_]
    chosen = str(brand["default_mailbox_id"]) if brand["default_mailbox_id"] else None

    def sendable(c) -> bool:
        return bool(approved_steps.get(str(c["id"]))) and str(c["mailbox_id"]) in healthy_ids

    latest = {}
    for lia in lias:
        if str(lia["brand_id"]) == bid_:
            if lia["audience_hash"] not in latest or int(lia["version"]) >= int(latest[lia["audience_hash"]]["version"]):
                latest[lia["audience_hash"]] = lia

    def audience_ok(c) -> bool:
        lia = latest.get(c["target_hash"])
        return bool(lia and lia["decision"] == "approved")

    # Pre-OUT-18 brands chose no inbox: use the one a sendable campaign of a
    # currently approved audience uses, else the newest campaign's (Codex
    # OUT-18 part B reviews 1 and 2).
    fallback = next((c for c in mine if sendable(c) and audience_ok(c)), mine[-1] if mine else None)
    mailbox = chosen or (str(fallback["mailbox_id"]) if fallback else None)
    audiences = []
    for lia in latest.values():
        found = [c for c in mine if c["target_hash"] == lia["audience_hash"]]
        on_inbox = [c for c in found if str(c["mailbox_id"]) == mailbox]

        def ready_(c) -> bool:
            return sendable(c) and str(c["mailbox_id"]) == mailbox

        # A campaign that is ready wins; then the newest on the brand's inbox
        # (waiting for approval); then the newest at all (on another inbox).
        best = next((c for c in found if ready_(c)), None) or (on_inbox[-1] if on_inbox else None) \
            or (found[-1] if found else None)
        audiences.append({
            "id": str(lia["id"]), "description": ((rules.get(str(lia["id"])) or {}).get("description") or ""),
            "approved": lia["decision"] == "approved",
            "campaign": None if not best else {
                "id": str(best["id"]), "name": best["name"], "mailbox_id": str(best["mailbox_id"]),
                "approved": bool(approved_steps.get(str(best["id"]))),
                "other_inbox": str(best["mailbox_id"]) != mailbox,
                "ready": ready_(best)}})
    privacy = bid_ in notices
    mailbox_ok = bool(mailbox and mailbox in healthy_ids)
    ready = privacy and mailbox_ok and any(a["approved"] and a["campaign"] and a["campaign"]["ready"] for a in audiences)
    return {"id": bid_, "name": brand["name"], "sender_identity": brand["sender_identity"],
            "profile": profiles.get(bid_, {}),
            "mailbox_id": mailbox, "mailbox_address": accounts.get(mailbox) if mailbox else None,
            "mailbox_ok": mailbox_ok, "privacy": privacy, "audiences": audiences, "ready": ready}



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
    brands = send.rows(session, "outreach_brands", bid, "ORDER BY created_at, id")
    doc = _settings_doc(session, bid)
    notices = doc.get(PRIVACY_KEY) or {}
    rules = doc.get(AUDIENCE_KEY) or {}
    boxes = {str(r["mailbox_id"]): r for r in send.rows(session, "outreach_mailboxes", bid)}
    accounts = {str(a["id"]): a["email_address"] for a in send.rows(session, "email_accounts", bid)}
    healthy_ids = {k for k, r in boxes.items() if _truthy(r["enabled"]) and r["health_status"] == "pass"}
    lias = send.rows(session, "outreach_compliance", bid, "ORDER BY created_at, id")
    campaigns = send.rows(session, "outreach_campaigns", bid, "ORDER BY created_at, id")
    approved_steps = {}
    for c in campaigns:
        steps_ = send.rows(session, "outreach_sequence_steps", bid, "AND campaign_id = :c AND sequence_version = :v",
                           {"c": str(c["id"]), "v": c["sequence_version"]})
        approved_steps[str(c["id"])] = len(steps_) == 3 and all(x["approved_at"] for x in steps_)
    knowledge = session.execute(text(
        "SELECT count(*) FROM outreach_knowledge WHERE business_id = :b AND status = 'approved'"),
        {"b": bid}).scalar()
    session.rollback()
    profiles = doc.get(PROFILE_KEY) or {}
    per_brand = [_brand_status(b, notices, rules, boxes, accounts, healthy_ids, lias, campaigns, approved_steps,
                               profiles) for b in brands]
    ready_brands = [b for b in per_brand if b["ready"]]
    focus = ready_brands[0] if ready_brands else (per_brand[-1] if per_brand else None)
    # OUT-18: setup is finished when ONE brand is ready; the steps describe the
    # ready brand, or else the brand being set up (the newest).
    has_audience = bool(focus and any(a["approved"] for a in focus["audiences"]))
    # The brand's own mailbox once chosen; before that, any checked mailbox.
    mailboxes_done = focus["mailbox_ok"] if focus and focus["mailbox_id"] else bool(healthy_ids)
    steps = {
        "brand": "done" if brands else "todo",
        "mailboxes": "done" if mailboxes_done else "todo",
        "audience": "done" if has_audience else ("blocked" if not brands else "todo"),
        "privacy": "done" if focus and focus["privacy"] else "todo",
        "knowledge": "done" if knowledge else "todo",
        "limits": "done",
        "campaign": "done" if focus and any(a["campaign"] and a["campaign"]["ready"] for a in focus["audiences"])
                    else ("blocked" if not (healthy_ids and has_audience) else "todo"),
    }
    if ready_brands:
        steps.update({k: "done" for k in REQUIRED})
    todo = [s for s in REQUIRED if steps[s] != "done"]
    return {"steps": steps, "next": todo[0] if todo else None, "complete": bool(ready_brands), "started": started,
            "brands": per_brand}


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
