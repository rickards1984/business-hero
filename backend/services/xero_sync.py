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
        session.execute(text(f"INSERT INTO business_settings (business_id, settings) VALUES (:b, {expr})"), params)


def _dups(doc: dict) -> dict:
    d = dict(doc.get("accounting_duplicates") or {})
    d["hidden"] = dict(d.get("hidden") or {})
    d["review"] = list(d.get("review") or [])
    d["kept"] = list(d.get("kept") or [])
    return d


def source_of(external_source, external_id, import_id) -> str:
    """Where a stored transaction came from (for the list and the pack)."""
    if external_source == SOURCE and external_id:
        return "xero_payment" if str(external_id).startswith(PAYMENT_PREFIX) else "xero"
    if external_source and external_id:
        return str(external_source)
    return "upload" if import_id else "manual"


# ------------------------------------------------------------- fetching ---

async def _all(fetch, key: str, since: Optional[str]) -> tuple:
    """Every record of a list, page by page until a short page. (records, complete)"""
    out = []
    for page in range(1, MAX_PAGES + 1):
        data = await fetch(modified_since=since, page=page)
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


async def cached_accounts(session, bid: str, provider, moment: datetime) -> dict:
    """The chart of accounts, read from Xero at most once a day."""
    doc = _doc(session, bid)
    held = doc.get("xero_accounts") or {}
    at = _parse_moment(held.get("at"))
    if at is not None and moment - at < ACCOUNTS_FRESH and held.get("lookup"):
        return dict(held["lookup"])
    try:
        lookup = accounts_from_trial_balance(await provider.get_trial_balance())
    except Exception as exc:                # a missing chart only costs categories, never rows
        logger.warning("Xero chart of accounts unavailable: %s", exc)
        return dict(held.get("lookup") or {})
    if lookup:
        doc = _doc(session, bid)
        doc["xero_accounts"] = {"at": moment.isoformat(), "lookup": lookup}
        _save(session, bid, doc)
    return lookup


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

def _category(session, bid: str, code: Optional[str], kind: str, lookup: dict, cache: dict) -> Optional[str]:
    info = lookup.get(code or "") or {}
    name = info.get("name")
    if not name or name.strip().isdigit():
        return None
    if name in cache:
        return cache[name]
    found = session.execute(text("SELECT id FROM accounting_categories WHERE business_id = :b AND LOWER(name) = LOWER(:n)"),
                            {"b": bid, "n": name}).first()
    if found:
        cache[name] = str(found[0])
        return cache[name]
    ident = str(uuid.uuid4())
    session.execute(text("INSERT INTO accounting_categories (id, business_id, name, type, color, created_at, updated_at) "
                         "VALUES (:i, :b, :n, :t, '#6B7280', :at, :at)"),
                    {"i": ident, "b": bid, "n": name, "t": info.get("type") or kind,
                     "at": datetime.now(timezone.utc).isoformat()})
    cache[name] = ident
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
    Returns "hidden", "review" or ""."""
    if xero_id in dups["hidden"].values() or any(r.get("xero") == xero_id for r in dups["review"]):
        return ""
    d = date.fromisoformat(row["transaction_date"])
    candidates = [str(r[0]) for r in session.execute(text(
        "SELECT id FROM accounting_transactions WHERE business_id = :b AND import_id IS NOT NULL "
        "AND external_id IS NULL AND is_archived = :no AND type = :t AND amount = :a "
        "AND transaction_date >= :lo AND transaction_date <= :hi ORDER BY transaction_date, id"),
        {"b": bid, "no": False, "t": row["type"], "a": row["amount"],
         "lo": (d - timedelta(days=MATCH_DAYS)).isoformat(), "hi": (d + timedelta(days=MATCH_DAYS)).isoformat()})]
    candidates = [c for c in candidates if c not in dups["kept"]]
    if len(candidates) == 1:
        session.execute(text("UPDATE accounting_transactions SET is_archived = :yes, updated_at = :at "
                             "WHERE business_id = :b AND id = :i"),
                        {"yes": True, "at": moment.isoformat(), "b": bid, "i": candidates[0]})
        dups["hidden"][candidates[0]] = xero_id
        return "hidden"
    if len(candidates) > 1:
        dups["review"].append({"xero": xero_id, "uploads": candidates})
        return "review"
    return ""


# ------------------------------------------------------------------ run ---

async def run(session, business_id, provider, *, moment: datetime, account_lookup: Optional[dict] = None) -> dict:
    """One sync. The caller commits. Fetching happens first, then every row in
    its own savepoint; the marker moves only when nothing was missed."""
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
        out["errors"].append("Xero returned more records than one run reads; the next sync carries on.")
        return out
    wanted = sorted({str((p.get("Invoice") or {}).get("InvoiceID")) for p in payments
                     if p.get("Status") not in GONE and (p.get("Invoice") or {}).get("InvoiceID")})
    invoice_codes = {}
    for start in range(0, len(wanted), INVOICE_BATCH):
        for inv in await provider.get_invoices_by_ids(wanted[start:start + INVOICE_BATCH]) or []:
            invoice_codes[str(inv.get("InvoiceID"))] = _largest_code(inv.get("LineItems"))

    dups = _dups(_doc(session, bid))
    cache: dict = {}
    work = [("bank", t) for t in bank] + [("payment", p) for p in payments]
    for kind, record in work:
        ident = record.get("BankTransactionID") if kind == "bank" else record.get("PaymentID")
        try:
            with session.begin_nested():
                external = str(ident) if kind == "bank" else PAYMENT_PREFIX + str(ident)
                if record.get("Status") in GONE or (kind == "bank" and record.get("Type") in BANK_TRANSFER):
                    out["archived"] += _archive_external(session, bid, external, moment)
                    out["skipped"] += 1
                    continue
                if kind == "bank" and record.get("Type") not in BANK_INCOME + BANK_EXPENSE:
                    logger.warning("Xero bank transaction %s: unknown type %r skipped", ident, record.get("Type"))
                    out["skipped"] += 1
                    continue
                if kind == "payment" and record.get("PaymentType") not in PAY_IN + PAY_OUT:
                    logger.warning("Xero payment %s: unknown type %r skipped", ident, record.get("PaymentType"))
                    out["skipped"] += 1
                    continue
                row = _bank_row(record) if kind == "bank" else _payment_row(record, invoice_codes)
                category = _category(session, bid, row["code"], row["type"], lookup, cache)
                row_id, how = _write(session, bid, row, category, moment)
                out[how] += 1
                outcome = _dedupe(session, bid, row_id, row, dups, moment)
                if outcome == "hidden":
                    out["duplicates_hidden"] += 1
                elif outcome == "review":
                    out["needs_review"] += 1
        except Exception as exc:
            out["errors"].append(f"Xero {kind} {ident}: {exc}")
            logger.warning("Xero %s %s not recorded: %s", kind, ident, exc)

    doc = _doc(session, bid)
    doc["accounting_duplicates"] = dups
    out["complete"] = not out["errors"]
    if out["complete"]:
        doc["xero_sync"] = {"version": VERSION,
                            "cursor": (moment - CURSOR_MARGIN).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}
    _save(session, bid, doc)
    out["errors"] = out["errors"][:5]
    return out


# ---------------------------------------------------------- Mike decides ---

def resolve(session, business_id, upload_id, action: str) -> dict:
    """Mike's call on a possible duplicate: "hide" the upload, or "keep" it
    (restored, and never hidden as a duplicate again). The caller commits."""
    from services.aria_actions import ActionRefused
    if action not in ("hide", "keep"):
        raise ActionRefused(422, "Choose hide or keep.")
    bid, upload_id = str(business_id), str(upload_id)
    found = session.execute(text("SELECT id FROM accounting_transactions WHERE business_id = :b AND id = :i "
                                 "AND import_id IS NOT NULL AND external_id IS NULL"), {"b": bid, "i": upload_id}).first()
    if not found:
        raise ActionRefused(404, "That uploaded transaction wasn't found.")
    doc = _doc(session, bid)
    dups = _dups(doc)
    pair = next((r for r in dups["review"] if upload_id in r.get("uploads", [])), None)
    xero_id = dups["hidden"].get(upload_id) or (pair or {}).get("xero")
    now_ = datetime.now(timezone.utc).isoformat()
    if action == "hide":
        session.execute(text("UPDATE accounting_transactions SET is_archived = :yes, updated_at = :at "
                             "WHERE business_id = :b AND id = :i"), {"yes": True, "at": now_, "b": bid, "i": upload_id})
        if xero_id:
            dups["hidden"][upload_id] = xero_id
        if upload_id in dups["kept"]:
            dups["kept"].remove(upload_id)
    else:
        session.execute(text("UPDATE accounting_transactions SET is_archived = :no, updated_at = :at "
                             "WHERE business_id = :b AND id = :i"), {"no": False, "at": now_, "b": bid, "i": upload_id})
        dups["hidden"].pop(upload_id, None)
        if upload_id not in dups["kept"]:
            dups["kept"].append(upload_id)
    if pair is not None:
        dups["review"] = [r for r in dups["review"] if r is not pair]
    doc["accounting_duplicates"] = dups
    _save(session, bid, doc)
    return {"upload_id": upload_id, "action": action}


def duplicates(session, business_id) -> dict:
    """The review list and the uploads hidden as duplicates, with their rows."""
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
    return {"review": [{"xero": rows.get(r.get("xero")), "uploads": [rows[u] for u in r.get("uploads", []) if u in rows]}
                       for r in dups["review"]],
            "hidden": [{"upload": rows.get(u), "xero": rows.get(x)} for u, x in dups["hidden"].items() if u in rows]}
