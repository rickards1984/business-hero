"""ACC-1 — the Xero sync brings in everything, once (docs/ACC-1-TICKET.md). RED:
the ledger every report and the accountancy pack read.

Mike, 1 Nov 2026: bank transactions AND payments (lines reconciled by matching
an invoice or bill) are brought in, with no page cap. Transfers between his
own accounts are never income or expense. A run that missed anything never
moves the marker. One bad row never loses the rest. A Xero copy of an
uploaded transaction hides the upload (Xero wins) unless the match is
ambiguous, when Mike decides. After the first full run, each sync fetches only
what changed (speed is a requirement).

State in the business settings document (no migration):
  xero_sync             {"version": 2, "cursor": "YYYY-MM-DDTHH:MM:SS"}  (UTC)
  xero_accounts         {"at": iso, "lookup": {code: {"name", "type"}}}  (a day)
  accounting_duplicates {"hidden": {upload_id: xero_row_id},
                         "review": [{"xero": row_id, "uploads": [ids]}],
                         "kept": [upload_id, ...]}
"""
import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger("xero_sync")

VERSION = 2
PAGE = 100
MAX_PAGES = 500                         # 50,000 records: hitting it stops the run, never silently
CURSOR_MARGIN = timedelta(minutes=5)
MATCH_DAYS = 3
INVOICE_BATCH = 50
SOURCE = "xero"
PAYMENT_PREFIX = "payment:"
ACCOUNTS_FRESH = timedelta(days=1)

BANK_INCOME = ("RECEIVE", "RECEIVE-OVERPAYMENT", "RECEIVE-PREPAYMENT")
BANK_EXPENSE = ("SPEND", "SPEND-OVERPAYMENT", "SPEND-PREPAYMENT")
BANK_TRANSFER = ("SPEND-TRANSFER", "RECEIVE-TRANSFER")
PAY_IN = ("ACCRECPAYMENT", "APCREDITPAYMENT", "APOVERPAYMENTPAYMENT", "APPREPAYMENTPAYMENT")
PAY_OUT = ("ACCPAYPAYMENT", "ARCREDITPAYMENT", "AROVERPAYMENTPAYMENT", "ARPREPAYMENTPAYMENT")
GONE = ("DELETED", "VOIDED")


# ------------------------------------------------------------------ state ---

def _doc(session, bid: str) -> dict:
    from services import outreach_setup as setup
    return setup._settings_doc(session, bid)


def _save(session, bid: str, doc: dict) -> None:
    """Update the settings row, creating it if the business has none (else the
    cursor would never be kept and every sync would be a full one)."""
    import json
    from services import outreach_send as send
    expr = "CAST(:s AS jsonb)" if send.pg(session) else ":s"
    params = {"s": json.dumps(doc), "b": bid}
    if not session.execute(text(f"UPDATE business_settings SET settings = {expr} WHERE business_id = :b"),
                           params).rowcount:
        # The live table requires id, created_at and updated_at, with no defaults (Codex review 1).
        stamp = datetime.now(timezone.utc).replace(tzinfo=None)
        session.execute(text(f"INSERT INTO business_settings (id, business_id, settings, created_at, updated_at) "
                             f"VALUES (:i, :b, {expr}, :at, :at)"), {**params, "i": str(uuid.uuid4()), "at": stamp})


def _lock(session, bid: str) -> None:
    """One settings writer at a time per business (Codex reviews 1, 2): the
    settings row, created first if missing, then locked for the rest of the
    caller's transaction. Settings are always locked FIRST (before invoice or
    transaction rows), the order outreach and billing use too."""
    from sqlalchemy.exc import IntegrityError
    if session.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b"), {"b": bid}).first() is None:
        # Insert only, never update (Codex review 3: an UPDATE here could blank a
        # row another writer created and committed in between).
        expr = "CAST(:s AS jsonb)" if _is_pg(session) else ":s"
        stamp = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            with session.begin_nested():
                session.execute(text(f"INSERT INTO business_settings (id, business_id, settings, created_at, updated_at) "
                                     f"SELECT :i, :b, {expr}, :at, :at WHERE NOT EXISTS "
                                     f"(SELECT 1 FROM business_settings WHERE business_id = :b)"),
                                {"i": str(uuid.uuid4()), "b": bid, "s": "{}", "at": stamp})
        except IntegrityError:
            pass                            # created at the same moment by another writer
    if _is_pg(session):
        session.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b FOR UPDATE"), {"b": bid})
    else:
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"),
                        {"b": bid})


def _is_pg(session) -> bool:
    from services import outreach_send as send
    try:
        return send.pg(session)
    except Exception:                       # a session without a bind (test stand-ins): the portable form
        return False


def _update_doc(session, bid: str, change) -> dict:
    """Lock, read, change, save: the only way this module writes settings."""
    _lock(session, bid)
    doc = _doc(session, bid)
    change(doc)
    _save(session, bid, doc)
    return doc

def _dups(doc: dict) -> dict:
    """hidden {upload: xero row}; review [{"xero", "uploads"}]; kept_pairs
    [[upload, xero row]]: Mike kept that upload as NOT a copy of that Xero row
    (only that pair: the upload can still match another Xero row)."""
    d = dict(doc.get("accounting_duplicates") or {})
    d["hidden"] = dict(d.get("hidden") or {})
    d["review"] = [dict(r, uploads=list(r.get("uploads") or [])) for r in (d.get("review") or [])]
    d["kept_pairs"] = [list(p) for p in (d.get("kept_pairs") or [])]
    d.pop("kept", None)
    return d


def source_of(external_source, external_id, import_id) -> str:
    """Where a stored transaction came from (for the list and the pack)."""
    if external_source == SOURCE and external_id:
        return "xero_payment" if str(external_id).startswith(PAYMENT_PREFIX) else "xero"
    if external_source and external_id:
        return str(external_source)
    return "upload" if import_id else "manual"


# ------------------------------------------------------------- fetching ---

# Xero allows 60 calls a minute per organisation. The first full sync makes
# more than that in a burst (pages of bank transactions and payments, then
# invoices 50 at a time), and a refusal used to sink the whole run, so every
# retry re-read everything and was refused again (ACC-1b). Wait out the minute
# and carry on; a limit that outlasts a few minutes (the daily one) stops it.
RATE_WAIT_SECONDS = 61
RATE_TRIES = 5
_pause = asyncio.sleep


def rate_limited(exc: BaseException) -> bool:
    """Xero's 429, in either form (some provider calls raise httpx's own error)."""
    from providers.xero import XeroRateLimitError
    return isinstance(exc, XeroRateLimitError) or \
        getattr(getattr(exc, "response", None), "status_code", None) == 429


async def _xero(call, *args, **kwargs):
    """One Xero call, waiting out the per-minute rate limit. A limit still in
    force after RATE_TRIES re-raises, and callers that otherwise tolerate a
    failed call let it through: the run stops before writing (Codex ACC-1b)."""
    for attempt in range(1, RATE_TRIES + 1):
        try:
            return await call(*args, **kwargs)
        except Exception as exc:
            if not rate_limited(exc) or attempt == RATE_TRIES:
                raise
            logger.info("Xero rate limit: waiting %ss (attempt %d of %d)", RATE_WAIT_SECONDS, attempt, RATE_TRIES)
            await _pause(RATE_WAIT_SECONDS)


async def _all(fetch, key: str, since: Optional[str]) -> tuple:
    """Every record of a list, page by page until a short page. (records, complete)"""
    out = []
    for page in range(1, MAX_PAGES + 1):
        data = await _xero(fetch, modified_since=since, page=page)
        items = list((data or {}).get(key) or [])
        out.extend(items)
        if len(items) < PAGE:
            return out, True
    logger.error("Xero %s: %d pages and still more; stopping this run incomplete", key, MAX_PAGES)
    return out, False


def accounts_from_trial_balance(tb_data) -> dict:
    """{account code: {"name", "type"}} from Xero's Trial Balance report."""
    import re
    lookup = {}
    for report in (tb_data or {}).get("Reports", []) or []:
        for row in report.get("Rows", []) or []:
            if row.get("RowType") != "Section":
                continue
            income = (row.get("Title", "") or "").lower() in ("revenue", "income", "other income", "other revenue")
            for sub in row.get("Rows", []) or []:
                cells = sub.get("Cells", []) or []
                if len(cells) < 2:
                    continue
                name = cells[0].get("Value", "") or ""
                attrs = cells[0].get("Attributes", []) or []
                ident = attrs[0].get("Value", "") if attrs else ""
                if not (ident and name):
                    continue
                kind = "income" if income else "expense"
                found = re.search(r"\((\d+)\)\s*$", name)
                if found:
                    lookup[found.group(1)] = {"name": re.sub(r"\s*\(\d+\)\s*$", "", name).strip(), "type": kind}
                lookup[ident] = {"name": name, "type": kind}
    return lookup


async def fetch_chart(provider) -> dict:
    """The chart and the account types, from Xero (network only, no lock).
    ok: both were read, so the result may be called fresh."""
    out = {"lookup": None, "bank": None, "other": None, "ok": False}
    try:
        out["lookup"] = accounts_from_trial_balance(await _xero(provider.get_trial_balance))
    except Exception as exc:                # a missing chart only costs categories, never rows
        if rate_limited(exc):
            raise
        logger.warning("Xero chart of accounts unavailable: %s", exc)
    try:
        accounts = await _xero(provider.get_accounts) or []
        # Xero: credit cards and PayPal are Type BANK (BankAccountType CREDITCARD / PAYPAL): they count.
        out["bank"] = sorted(str(a.get("AccountID")) for a in accounts if a.get("Type") == "BANK" and a.get("AccountID"))
        out["other"] = sorted(str(a.get("AccountID")) for a in accounts if a.get("Type") != "BANK" and a.get("AccountID"))
    except Exception as exc:
        if rate_limited(exc):
            raise
        logger.warning("Xero accounts unavailable: %s", exc)
    out["ok"] = out["lookup"] is not None and out["bank"] is not None
    return out


def store_chart(session, bid: str, fetched: dict, moment: datetime) -> dict:
    """Keep what was read; mark it fresh only if all of it was (Codex review 2)."""
    def change(doc):
        held = dict(doc.get("xero_accounts") or {})
        for key in ("lookup", "bank", "other"):
            if fetched.get(key) is not None:
                held[key] = fetched[key]
        if fetched.get("ok"):
            held["at"] = moment.isoformat()
        doc["xero_accounts"] = held
    return dict(_update_doc(session, bid, change).get("xero_accounts") or {})


async def cached_chart(session, bid: str, provider, moment: datetime, *, force: bool = False) -> dict:
    """{"lookup", "bank", "other"}, read from Xero at most once a day (or now,
    when forced). The caller commits soon after: the write locks settings."""
    held = dict(_doc(session, bid).get("xero_accounts") or {})
    at = _parse_moment(held.get("at"))
    if (not force and at is not None and moment - at < ACCOUNTS_FRESH and held.get("lookup") is not None
            and held.get("bank") is not None and held.get("other") is not None):
        return {"lookup": dict(held["lookup"]), "bank": list(held["bank"]), "other": list(held["other"])}
    held = store_chart(session, bid, await fetch_chart(provider), moment)
    return {"lookup": dict(held.get("lookup") or {}), "bank": held.get("bank"), "other": held.get("other")}


async def cached_accounts(session, bid: str, provider, moment: datetime) -> dict:
    """The chart of accounts alone (see cached_chart)."""
    return (await cached_chart(session, bid, provider, moment))["lookup"]


def _parse_moment(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# -------------------------------------------------------------- mapping ---

def _date(value) -> str:
    from providers.xero import _parse_xero_date
    parsed = _parse_xero_date(value)
    if not parsed:
        raise ValueError(f"unreadable date {value!r}")
    return str(parsed)[:10]


def _largest_code(lines) -> Optional[str]:
    lines = [li for li in (lines or []) if li.get("AccountCode")]
    if not lines:
        return None
    return max(lines, key=lambda li: abs(float(li.get("LineAmount", 0) or 0))).get("AccountCode")


def _bank_row(txn: dict) -> dict:
    kind = txn.get("Type", "")
    income = kind in BANK_INCOME
    lines = txn.get("LineItems") or []
    contact = (txn.get("Contact") or {}).get("Name", "") or ""
    description = ((lines[0].get("Description") if lines else "") or contact or f"Xero {kind.lower()}").strip()
    total = abs(float(txn.get("Total", 0) or 0))
    return {"external_id": str(txn["BankTransactionID"]), "transaction_date": _date(txn.get("Date")),
            "description": description, "amount": round(total if income else -total, 2),
            "type": "income" if income else "expense", "reference": txn.get("Reference"),
            "payee_payer": contact or None, "code": _largest_code(lines)}


def _payment_row(p: dict, invoice_codes: dict) -> dict:
    kind = p.get("PaymentType", "")
    income = kind in PAY_IN
    invoice = p.get("Invoice") or {}
    number = invoice.get("InvoiceNumber") or ""
    contact = (invoice.get("Contact") or {}).get("Name", "") or ""
    what = "invoice" if kind in ("ACCRECPAYMENT", "ARCREDITPAYMENT", "AROVERPAYMENTPAYMENT", "ARPREPAYMENTPAYMENT") \
        else "bill"
    amount = p.get("BankAmount") if p.get("BankAmount") is not None else p.get("Amount", 0)
    total = abs(float(amount or 0))
    return {"external_id": PAYMENT_PREFIX + str(p["PaymentID"]), "transaction_date": _date(p.get("Date")),
            "description": " — ".join(x for x in (contact, f"{what} {number}".strip()) if x) or "Xero payment",
            "amount": round(total if income else -total, 2), "type": "income" if income else "expense",
            "reference": number or p.get("Reference"), "payee_payer": contact or None,
            "code": invoice_codes.get(str(invoice.get("InvoiceID") or ""))}


# -------------------------------------------------------------- writing ---

def _category(session, bid: str, code: Optional[str], kind: str, lookup: dict, cache: dict,
              pending: Optional[dict] = None) -> Optional[str]:
    """The category id for an account; created if needed. New ids go to
    `pending`, published to `cache` only once the row's savepoint succeeds
    (Codex review 1: a rolled-back category must never be reused)."""
    pending = cache if pending is None else pending
    info = lookup.get(code or "") or {}
    name = info.get("name")
    if not name or name.strip().isdigit():
        return None
    if name in cache:
        return cache[name]
    if name in pending:
        return pending[name]
    found = session.execute(text("SELECT id FROM accounting_categories WHERE business_id = :b AND LOWER(name) = LOWER(:n)"),
                            {"b": bid, "n": name}).first()
    if found:
        pending[name] = str(found[0])
        return pending[name]
    ident = str(uuid.uuid4())
    session.execute(text("INSERT INTO accounting_categories (id, business_id, name, type, color, created_at, updated_at) "
                         "VALUES (:i, :b, :n, :t, '#6B7280', :at, :at)"),
                    {"i": ident, "b": bid, "n": name, "t": info.get("type") or kind,
                     "at": datetime.now(timezone.utc).isoformat()})
    pending[name] = ident
    return ident


def _write(session, bid: str, row: dict, category_id: Optional[str], moment: datetime) -> tuple:
    """Insert or update one Xero row (restoring it if it had been archived).
    (row id, "new" | "updated")"""
    params = {"b": bid, "src": SOURCE, "e": row["external_id"], "d": row["transaction_date"],
              "desc": (row["description"] or "Xero transaction")[:2000], "a": row["amount"], "t": row["type"],
              "r": (row.get("reference") or None) and str(row["reference"])[:100],
              "p": (row.get("payee_payer") or None) and str(row["payee_payer"])[:255],
              "c": category_id, "at": moment.isoformat()}
    found = session.execute(text("SELECT id FROM accounting_transactions WHERE business_id = :b "
                                 "AND external_source = :src AND external_id = :e"), params).first()
    if found:
        params["id"] = str(found[0])
        session.execute(text("UPDATE accounting_transactions SET transaction_date = :d, description = :desc, "
                             "amount = :a, type = :t, reference = :r, payee_payer = :p, "
                             "category_id = COALESCE(:c, category_id), is_archived = :no, updated_at = :at "
                             "WHERE business_id = :b AND id = :id"), {**params, "no": False})
        return params["id"], "updated"
    params["id"] = str(uuid.uuid4())
    session.execute(text("INSERT INTO accounting_transactions (id, business_id, transaction_date, description, amount, "
                         "type, reference, payee_payer, category_id, external_id, external_source, is_archived, "
                         "created_at, updated_at) VALUES (:id, :b, :d, :desc, :a, :t, :r, :p, :c, :e, :src, :no, "
                         ":at, :at)"), {**params, "no": False})
    return params["id"], "new"


def _archive_external(session, bid: str, external_id: str, moment: datetime) -> int:
    return session.execute(text("UPDATE accounting_transactions SET is_archived = :yes, updated_at = :at "
                                "WHERE business_id = :b AND external_source = :src AND external_id = :e "
                                "AND is_archived = :no"),
                           {"yes": True, "no": False, "at": moment.isoformat(), "b": bid, "src": SOURCE,
                            "e": external_id}).rowcount or 0


def _dedupe(session, bid: str, xero_id: str, row: dict, dups: dict, moment: datetime) -> str:
    """Hide the one upload this Xero row duplicates; list an ambiguous match.
    One-to-one: an upload is hidden against one Xero row at most, and a pair
    Mike kept is never matched again. Returns "hidden", "review" or ""."""
    if xero_id in dups["hidden"].values() or any(r.get("xero") == xero_id for r in dups["review"]):
        return ""
    d = date.fromisoformat(row["transaction_date"])
    candidates = [str(r[0]) for r in session.execute(text(
        "SELECT id FROM accounting_transactions WHERE business_id = :b AND import_id IS NOT NULL "
        "AND external_id IS NULL AND is_archived = :no AND type = :t AND amount = :a "
        "AND transaction_date >= :lo AND transaction_date <= :hi ORDER BY transaction_date, id"),
        {"b": bid, "no": False, "t": row["type"], "a": row["amount"],
         "lo": (d - timedelta(days=MATCH_DAYS)).isoformat(), "hi": (d + timedelta(days=MATCH_DAYS)).isoformat()})]
    candidates = [c for c in candidates if [c, xero_id] not in dups["kept_pairs"]]
    if len(candidates) == 1:
        _hide(session, bid, candidates[0], xero_id, dups, moment)
        return "hidden"
    if len(candidates) > 1:
        dups["review"].append({"xero": xero_id, "uploads": candidates})
        return "review"
    return ""


def _hide(session, bid: str, upload_id: str, xero_id: Optional[str], dups: dict, moment: datetime) -> None:
    session.execute(text("UPDATE accounting_transactions SET is_archived = :yes, updated_at = :at "
                         "WHERE business_id = :b AND id = :i"),
                    {"yes": True, "at": moment.isoformat(), "b": bid, "i": upload_id})
    if xero_id:
        dups["hidden"][upload_id] = xero_id
    # one-to-one: that Xero row is matched, and this upload is spoken for
    dups["review"] = [dict(r, uploads=[u for u in r["uploads"] if u != upload_id]) for r in dups["review"]
                      if r.get("xero") != xero_id]
    dups["review"] = [r for r in dups["review"] if r["uploads"]]


# ------------------------------------------------------------------ run ---

async def run(session, business_id, provider, *, moment: datetime, account_lookup: Optional[dict] = None,
              bank_accounts: Optional[list] = None, other_accounts: Optional[list] = None) -> dict:
    """One sync. The caller commits. Fetching happens first, with no lock;
    then, under the business's lock, every row in its own savepoint. The
    marker moves only when nothing was missed.

    Cash basis, bank movements only (Codex review 1): a payment counts only
    when it was made from or into a BANK account. A payment into a clearing
    account (card processors) is not cash yet; the bank receipt that settles
    the clearing account is, so nothing is counted twice."""
    bid = str(business_id)
    doc = _doc(session, bid)
    state = dict(doc.get("xero_sync") or {})
    full = state.get("version") != VERSION
    since = None if full else state.get("cursor")
    lookup = account_lookup or {}
    out = {"full": full, "new": 0, "updated": 0, "archived": 0, "skipped": 0, "duplicates_hidden": 0,
           "needs_review": 0, "errors": [], "complete": False}

    bank, bank_done = await _all(provider.get_bank_transactions, "BankTransactions", since)
    payments, pay_done = await _all(provider.get_payments, "Payments", since)
    if not (bank_done and pay_done):
        out["errors"].append(f"Xero has more than {MAX_PAGES * PAGE:,} changed records for one sync, so it "
                             "can't finish. Please contact support.")
        return out
    banks, others = set(bank_accounts or []), set(other_accounts or [])
    fresh_chart = None
    accounts_of = {str((p.get("Account") or {}).get("AccountID")) for p in payments if p.get("Status") not in GONE}
    if accounts_of - banks - others:
        # An account the cached list doesn't know (a bank added today?): read the
        # accounts again now, before deciding (Codex review 2), never assume.
        fresh_chart = await fetch_chart(provider)
        if fresh_chart.get("bank") is not None:
            banks, others = set(fresh_chart["bank"]), set(fresh_chart["other"] or [])
    unknown = accounts_of - banks - others
    if unknown:
        held_back = [p for p in payments if str((p.get("Account") or {}).get("AccountID")) in unknown]
        payments = [p for p in payments if p not in held_back]
        out["errors"].append(f"{len(held_back)} Xero payment(s) went to an account Business Hero couldn't identify; "
                             "they weren't recorded and will be tried again on the next sync.")
    wanted = sorted({str((p.get("Invoice") or {}).get("InvoiceID")) for p in payments
                     if p.get("Status") not in GONE and (p.get("Invoice") or {}).get("InvoiceID")
                     and str((p.get("Account") or {}).get("AccountID")) in banks})
    invoice_codes = {}
    for start in range(0, len(wanted), INVOICE_BATCH):
        for inv in await _xero(provider.get_invoices_by_ids, wanted[start:start + INVOICE_BATCH]) or []:
            invoice_codes[str(inv.get("InvoiceID"))] = _largest_code(inv.get("LineItems"))

    _lock(session, bid)                       # from here, one writer per business
    if fresh_chart is not None:
        store_chart(session, bid, fresh_chart, moment)
    dups = _dups(_doc(session, bid))
    cache: dict = {}
    work = [("bank", t) for t in bank] + [("payment", p) for p in payments]
    for kind, record in work:
        ident = record.get("BankTransactionID") if kind == "bank" else record.get("PaymentID")
        tally: dict = {}
        pending_cache: dict = {}
        snapshot = {"hidden": dict(dups["hidden"]), "review": [dict(r, uploads=list(r["uploads"])) for r in dups["review"]],
                    "kept_pairs": [list(p) for p in dups["kept_pairs"]]}
        try:
            with session.begin_nested():
                tally = _one(session, bid, kind, record, ident, banks, invoice_codes, lookup, cache, pending_cache,
                             dups, moment)
        except Exception as exc:
            # the savepoint rolled back: so do this row's cache entries, tallies and duplicate changes
            dups.clear()
            dups.update(snapshot)
            out["errors"].append(f"Xero {kind} {ident}: {exc}")
            logger.warning("Xero %s %s not recorded: %s", kind, ident, exc)
            continue
        cache.update(pending_cache)
        for key, value in tally.items():
            out[key] += value

    doc = _doc(session, bid)
    doc["accounting_duplicates"] = dups
    out["complete"] = not out["errors"]
    if out["complete"]:
        doc["xero_sync"] = {"version": VERSION,
                            "cursor": (moment - CURSOR_MARGIN).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}
    _save(session, bid, doc)
    out["errors"] = out["errors"][:5]
    return out


def _one(session, bid, kind, record, ident, banks, invoice_codes, lookup, cache, pending_cache, dups, moment) -> dict:
    """One Xero record, inside its savepoint. Returns what it did."""
    external = str(ident) if kind == "bank" else PAYMENT_PREFIX + str(ident)
    if record.get("Status") in GONE or (kind == "bank" and record.get("Type") in BANK_TRANSFER):
        return {"archived": _archive_external(session, bid, external, moment), "skipped": 1}
    if kind == "bank" and record.get("Type") not in BANK_INCOME + BANK_EXPENSE:
        logger.warning("Xero bank transaction %s: unknown type %r skipped", ident, record.get("Type"))
        return {"skipped": 1}
    if kind == "payment" and record.get("PaymentType") not in PAY_IN + PAY_OUT:
        logger.warning("Xero payment %s: unknown type %r skipped", ident, record.get("PaymentType"))
        return {"skipped": 1}
    if kind == "payment" and str((record.get("Account") or {}).get("AccountID")) not in banks:
        # not into or out of a bank account (a clearing account): not cash yet;
        # any row stored for it earlier is archived
        return {"archived": _archive_external(session, bid, external, moment), "skipped": 1}
    row = _bank_row(record) if kind == "bank" else _payment_row(record, invoice_codes)
    category = _category(session, bid, row["code"], row["type"], lookup, cache, pending_cache)
    row_id, how = _write(session, bid, row, category, moment)
    tally = {how: 1}
    outcome = _dedupe(session, bid, row_id, row, dups, moment)
    if outcome == "hidden":
        tally["duplicates_hidden"] = 1
    elif outcome == "review":
        tally["needs_review"] = 1
    return tally


# ---------------------------------------------------------- Mike decides ---

def resolve(session, business_id, upload_id, action: str, xero_id: Optional[str] = None) -> dict:
    """Mike's call on one pair: "hide" the upload as a copy of that Xero row,
    or "keep" it (restored; never matched against that Xero row again; any
    other candidates for the same Xero row stay for review). The caller commits."""
    from services.aria_actions import ActionRefused
    if action not in ("hide", "keep"):
        raise ActionRefused(422, "Choose hide or keep.")
    bid, upload_id = str(business_id), str(upload_id)
    _lock(session, bid)
    found = session.execute(text("SELECT id FROM accounting_transactions WHERE business_id = :b AND id = :i "
                                 "AND import_id IS NOT NULL AND external_id IS NULL"), {"b": bid, "i": upload_id}).first()
    if not found:
        raise ActionRefused(404, "That uploaded transaction wasn't found.")
    doc = _doc(session, bid)
    dups = _dups(doc)
    groups = [r for r in dups["review"] if upload_id in r["uploads"]]
    if xero_id is None:
        xero_id = dups["hidden"].get(upload_id) or (groups[0]["xero"] if len(groups) == 1 else None)
    if xero_id is None:
        raise ActionRefused(409, "Say which Xero transaction this upload is being compared with.")
    xero_id = str(xero_id)
    counterpart = session.execute(text("SELECT is_archived FROM accounting_transactions WHERE business_id = :b "
                                       "AND id = :i AND external_source = :src AND external_id IS NOT NULL"),
                                  {"b": bid, "i": xero_id, "src": SOURCE}).first()
    if counterpart is None:
        raise ActionRefused(404, "That Xero transaction wasn't found.")
    if action == "hide" and counterpart[0]:
        # Codex review 3: voided or deleted in Xero since the screen loaded.
        raise ActionRefused(409, "That Xero transaction has been voided or deleted since. Please refresh.")
    pending = any(r["xero"] == xero_id and upload_id in r["uploads"] for r in dups["review"])
    hidden_here = dups["hidden"].get(upload_id) == xero_id
    # Codex review 2: a decision from a stale screen (another tab decided first) is refused.
    if action == "hide":
        if not pending:
            raise ActionRefused(409, "This pair was already decided. Please refresh.")
        if xero_id in dups["hidden"].values():
            raise ActionRefused(409, "That Xero transaction already has its uploaded copy hidden. Please refresh.")
    elif not (pending or hidden_here):
        raise ActionRefused(409, "This pair was already decided. Please refresh.")
    now_ = datetime.now(timezone.utc)
    if action == "hide":
        _hide(session, bid, upload_id, xero_id, dups, now_)
        dups["kept_pairs"] = [p for p in dups["kept_pairs"] if p != [upload_id, xero_id]]
    else:
        session.execute(text("UPDATE accounting_transactions SET is_archived = :no, updated_at = :at "
                             "WHERE business_id = :b AND id = :i"),
                        {"no": False, "at": now_.isoformat(), "b": bid, "i": upload_id})
        if dups["hidden"].get(upload_id) == xero_id:
            dups["hidden"].pop(upload_id)
        if xero_id and [upload_id, xero_id] not in dups["kept_pairs"]:
            dups["kept_pairs"].append([upload_id, xero_id])
        # only this pair is settled: other candidates for the same Xero row stay
        dups["review"] = [dict(r, uploads=[u for u in r["uploads"] if not (u == upload_id and r["xero"] == xero_id)])
                          for r in dups["review"]]
        dups["review"] = [r for r in dups["review"] if r["uploads"]]
    doc["accounting_duplicates"] = dups
    _save(session, bid, doc)
    return {"upload_id": upload_id, "xero_id": xero_id, "action": action}


def duplicates(session, business_id) -> dict:
    """The review list and the uploads hidden as duplicates, with their rows.
    A candidate that is no longer a visible upload is left out."""
    bid = str(business_id)
    dups = _dups(_doc(session, bid))
    ids = set(dups["hidden"]) | set(dups["hidden"].values())
    for r in dups["review"]:
        ids.add(r.get("xero"))
        ids.update(r.get("uploads", []))
    rows = {}
    for ident in [i for i in ids if i]:
        found = session.execute(text("SELECT id, transaction_date, description, amount, type, is_archived "
                                     "FROM accounting_transactions WHERE business_id = :b AND id = :i"),
                                {"b": bid, "i": ident}).mappings().first()
        if found:
            rows[ident] = {"id": str(found["id"]), "date": str(found["transaction_date"])[:10],
                           "description": found["description"], "amount": float(found["amount"]),
                           "type": found["type"], "archived": bool(found["is_archived"])}
    review = []
    for r in dups["review"]:
        uploads = [rows[u] for u in r.get("uploads", []) if u in rows and not rows[u]["archived"]]
        if uploads and r.get("xero") in rows and not rows[r["xero"]]["archived"]:
            review.append({"xero": rows[r["xero"]], "uploads": uploads})
    return {"review": review,
            "hidden": [{"upload": rows.get(u), "xero": rows.get(x)} for u, x in dups["hidden"].items() if u in rows]}


# ------------------------------------------------- invoices (the page's sync) ---

INVOICE_STATUSES = "AUTHORISED,SUBMITTED,PAID,VOIDED,DELETED"


async def fetch_invoices(session, business_id, provider) -> tuple:
    """Invoices changed since the last complete invoice sync, in ONE paged
    stream (open, paid, voided and deleted together). The first run after
    ACC-1 is full. (invoices, complete)"""
    bid = str(business_id)
    state = dict(_doc(session, bid).get("xero_invoice_sync") or {})
    since = state.get("cursor") if state.get("version") == VERSION else None

    async def page_of(modified_since=None, page=1):
        return await provider.get_invoices(modified_since=modified_since, status=INVOICE_STATUSES, page=page)
    return await _all(page_of, "Invoices", since)


def invoices_done(session, business_id, started: datetime) -> None:
    """Move the invoice cursor: only after a complete invoice sync."""
    cursor = (started - CURSOR_MARGIN).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _update_doc(session, str(business_id),
                lambda doc: doc.__setitem__("xero_invoice_sync", {"version": VERSION, "cursor": cursor}))


async def lookup_emails(session, business_id, provider, contact_ids) -> tuple:
    """Emails for contacts not yet known, asked of Xero (network only, no
    lock). (found, failed). A failed lookup is left out of `found`, and the
    caller holds its cursor, so the invoice is fetched and the contact asked
    again next sync (Codex reviews 2, 3). A confirmed empty answer is kept as ""."""
    known = dict(_doc(session, str(business_id)).get("xero_contact_emails") or {})
    found, failed = {}, 0
    for cid in sorted({c for c in contact_ids if c and c not in known}):
        try:
            found[cid] = await _xero(provider.get_contact_email_checked, cid) or ""
        except Exception as exc:
            if rate_limited(exc):
                raise                       # never one 4-minute wait per remaining contact
            failed += 1
            logger.warning("Xero contact %s: email lookup failed (%s); asked again next sync", cid, exc)
    return found, failed


def remember_emails(session, business_id, found: dict) -> dict:
    """Keep looked-up emails (locks settings). Returns every known email."""
    def change(doc):
        known = dict(doc.get("xero_contact_emails") or {})
        known.update(found)
        doc["xero_contact_emails"] = known
    return dict(_update_doc(session, str(business_id), change).get("xero_contact_emails") or {})


async def contact_email(session, business_id, provider, contact_id: str) -> Optional[str]:
    """One contact's email, asked of Xero once ever (a failure is retried)."""
    found, _failed = await lookup_emails(session, business_id, provider, [contact_id])
    known = remember_emails(session, business_id, found) if found else \
        dict(_doc(session, str(business_id)).get("xero_contact_emails") or {})
    return known.get(contact_id) or None
