"""ACC-2: the accountancy pack (docs/ACC-2-TICKET.md). RED: figures handed
to an accountant, and tax points.

One Excel workbook, a first draft for the business's accountant:
- Xero's own P&L, balance sheet (with last year beside this year) and trial balance;
- aged debtors and creditors *at the period end*, rebuilt from Xero's invoices,
  payments and dated credit allocations;
- the period's sales invoices with net, VAT, rounding and gross;
- every ledger line, and a cash summary that says plainly it is not profit;
- the loose ends to tidy first;
- tax points from fixed rules on the business's own figures. The rule's text
  is always what the pack says; AI may add a plain-English line beside it,
  only if that line has no numbers and no claims (Codex ACC-2 review 1).

Without Xero, the P&L is built from Business Hero's ledger (cash basis,
unaudited, with last year beside it) and the balance sheet is left out, with
the reason. Nothing is ever missing silently. Money is Decimal, never float.
Only the base currency is totalled; other currencies are listed, never added.
"""
import asyncio
import calendar
import io
import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

logger = logging.getLogger("accountancy_pack")

UK = ZoneInfo("Europe/London")
ZERO = Decimal("0")
PAGE = 100                       # Xero pages of 100
XERO_CONCURRENCY = 5             # Xero allows 5 calls in flight per organisation
ID_BATCH = 50                    # invoices fetched by id, 50 at a time
WORDING_TIMEOUT_SECONDS = 15     # the pack never waits longer than this for AI wording
WORDING_PURPOSE = "accountancy_pack"     # the cost ledger's purpose
WORDING_ROUTE = "wording"                # ai_router's model table

# UK figures, checked against GOV.UK on the date below. One place, dated.
THRESHOLDS = {
    "checked": "2026-11-02",
    "sources": [
        "https://www.gov.uk/vat-registration/when-to-register",
        "https://www.gov.uk/corporation-tax-rates",
        "https://www.gov.uk/capital-allowances/annual-investment-allowance",
        "https://www.gov.uk/capital-allowances/full-expensing",
        "https://www.gov.uk/simpler-income-tax-simplified-expenses/working-from-home",
        "https://www.gov.uk/government/publications/increase-to-approved-mileage-allowance-payments-amaps-and-"
        "self-employed-simplified-mileage-rates/increasing-mileage-rates",
        "https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim21690",
        "https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim21869",
    ],
    "vat_registration": Decimal("90000"),
    "vat_warning_share": Decimal("0.8"),
    "ct_small_profits": Decimal("50000"),       # 19% at or below
    "ct_main_rate_limit": Decimal("250000"),    # 25% above; marginal relief between
    "ct_band_margin": Decimal("0.1"),
    "aia": Decimal("1000000"),
    "capital_item": Decimal("500"),
    "staff_event_per_head": Decimal("150"),
    "trivial_benefit": Decimal("50"),
    "trivial_director_cap": Decimal("300"),
    # cars and vans, first 10,000 business miles, by the date it applies from
    "mileage_rates": ((date(2011, 4, 6), Decimal("0.45")), (date(2026, 4, 6), Decimal("0.55"))),
    "mileage_first_10000": Decimal("0.55"),     # current
    "mileage_after": Decimal("0.25"),
}

# Category keywords (lower case) for the tax-point facts.
CAPITAL_WORDS = ("equipment", "computer", "tools", "plant", "machinery", "furniture", "fixtures",
                 "motor vehicles", "vehicle purchase", "fixed asset")
PENSION_WORDS = ("pension",)
HOME_WORDS = ("use of home", "home office", "working from home")
MILEAGE_WORDS = ("mileage",)
VEHICLE_WORDS = ("fuel", "motor", "vehicle", "car ")
STAFF_EVENT_WORDS = ("staff entertain", "staff party", "christmas party", "staff event")

TAB_ORDER = ["Summary", "Profit & Loss", "Balance Sheet", "Trial Balance", "Aged Debtors", "Aged Creditors",
             "Invoices", "Transactions", "Cash Summary", "Loose Ends", "Points to Discuss"]


class PeriodError(ValueError):
    """The resolved period is not a valid interval."""


# ------------------------------------------------------------- helpers ---

def _dec(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return ZERO


def _day(value) -> Optional[date]:
    """A Xero date (/Date(…)/ or ISO) or a database date, as a date."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    from providers.xero import _parse_xero_date
    parsed = _parse_xero_date(value) if str(value).startswith("/Date(") else None
    try:
        return date.fromisoformat(str(parsed or value)[:10])
    except ValueError:
        return None


def _moment(value) -> Optional[datetime]:
    """A stored timestamp; a naive one is UTC (Codex review 1), never London."""
    if value is None or value == "":
        return None
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def money(value) -> str:
    v = _dec(value)
    return f"-£{-v:,.2f}" if v < 0 else f"£{v:,.2f}"


def _uk(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _has(category: Optional[str], words) -> bool:
    c = (category or "").lower() + " "
    return any(w in c for w in words)


def _pence(rate: Decimal) -> int:
    return int(rate * 100)


# ------------------------------------------------------------- periods ---

def _year_end(year: int, day: int, month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    if month == 2 and day >= 28:        # Xero's 28/29 Feb means the month end
        return date(year, 2, last)
    return date(year, month, min(day, last))


def default_period(today: date, fy_end_day: Optional[int] = None, fy_end_month: Optional[int] = None) -> tuple:
    """The last *completed* financial year: from Xero's year end when known,
    else the last completed tax year (6 April to 5 April)."""
    if fy_end_day and fy_end_month:
        end = _year_end(today.year, int(fy_end_day), int(fy_end_month))
        if end >= today:
            end = _year_end(today.year - 1, int(fy_end_day), int(fy_end_month))
        start = _year_end(end.year - 1, int(fy_end_day), int(fy_end_month)) + timedelta(days=1)
        return start, end
    end = date(today.year, 4, 5)
    if end >= today:
        end = date(today.year - 1, 4, 5)
    return date(end.year - 1, 4, 6), end


def _year_earlier(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    target_last = calendar.monthrange(d.year - 1, d.month)[1]
    if d.day == last:                   # a month end stays a month end (29 Feb ↔ 28 Feb)
        return date(d.year - 1, d.month, target_last)
    return date(d.year - 1, d.month, min(d.day, target_last))


def prior_period(start: date, end: date) -> tuple:
    return _year_earlier(start), _year_earlier(end)


def mileage_rate(on: date) -> Decimal:
    rate = THRESHOLDS["mileage_rates"][0][1]
    for since, value in THRESHOLDS["mileage_rates"]:
        if on >= since:
            rate = value
    return rate


# --------------------------------------------------------- Xero reports ---

_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _value(cell_value):
    s = str(cell_value).replace(",", "").strip()
    return Decimal(s) if _NUMBER.match(s) else cell_value


def report_rows(report: dict) -> list:
    """A Xero report as rows of {kind, cells}. Only value cells (columns after
    the first, in data and summary rows) become numbers: a label such as an
    account code "200", or a header such as "2026", is never money (A1)."""
    out = []

    def walk(rows):
        for row in rows or []:
            kind = row.get("RowType")
            cells = [c.get("Value", "") for c in row.get("Cells") or []]
            if kind == "Header":
                out.append({"kind": "header", "cells": cells})
            elif kind == "Section":
                if row.get("Title"):
                    out.append({"kind": "title", "cells": [row["Title"]]})
                walk(row.get("Rows"))
            elif kind in ("Row", "SummaryRow"):
                out.append({"kind": "row" if kind == "Row" else "summary",
                            "cells": cells[:1] + [_value(v) for v in cells[1:]]})
    walk(report.get("Rows"))
    return out


def find_value(rows: list, label: str, column: int = 1) -> Optional[Decimal]:
    for row in rows:
        cells = row["cells"]
        if row["kind"] in ("row", "summary") and cells and cells[0] == label and len(cells) > column \
                and isinstance(cells[column], Decimal):
            return cells[column]
    return None


def balance_difference(rows: list) -> Optional[Decimal]:
    """Assets − liabilities − equity at the period end (A6); None if the
    report doesn't carry all three totals."""
    totals = [find_value(rows, label) for label in ("Total Assets", "Total Liabilities", "Total Equity")]
    if any(t is None for t in totals):
        return None
    return totals[0] - totals[1] - totals[2]


# ------------------------------------------------------- invoices, aged ---

LIVE = ("AUTHORISED", "PAID")
BUCKETS = ("current", "d1_30", "d31_60", "d61_90", "d90_plus")


def allocations_by_invoice(records: list) -> dict:
    """Credit notes, prepayments and overpayments: each allocation to an
    invoice, by its own date (not the credit's date)."""
    out: dict = {}
    for rec in records or []:
        if rec.get("Status") in ("VOIDED", "DELETED"):
            continue
        for a in rec.get("Allocations") or []:
            iid = str((a.get("Invoice") or {}).get("InvoiceID") or "")
            if iid:
                out.setdefault(iid, []).append((_day(a.get("Date")), _dec(a.get("Amount"))))
    return out


def _owed_at(inv: dict, as_at: date, allocations: Optional[dict]) -> Decimal:
    less = sum((_dec(p.get("Amount")) for p in inv.get("Payments") or []
                if p.get("Status") != "DELETED" and (_day(p.get("Date")) or date.max) <= as_at), ZERO)
    if allocations is not None:
        less += sum((amt for on, amt in allocations.get(str(inv.get("InvoiceID")), [])
                     if (on or date.max) <= as_at), ZERO)
    else:
        for key in ("CreditNotes", "Prepayments", "Overpayments"):
            less += sum((_dec(x.get("AppliedAmount")) for x in inv.get(key) or []
                         if (_day(x.get("Date")) or date.max) <= as_at), ZERO)
    return _dec(inv.get("Total")) - less


def _bucket(days: int) -> str:
    if days <= 0:
        return "current"
    if days <= 30:
        return "d1_30"
    if days <= 60:
        return "d31_60"
    if days <= 90:
        return "d61_90"
    return "d90_plus"


def _in_base(inv: dict, base: str) -> bool:
    return (inv.get("CurrencyCode") or base) == base


def aged(invoices: list, as_at: date, kind: str, allocations: Optional[dict] = None, *, base: str = "GBP") -> list:
    """Outstanding at `as_at`, by contact (A3): each invoice dated on or before
    it, less payments and allocations dated on or before it. Buckets by due
    date. Only the base currency: others are never added in (review 1)."""
    by: dict = {}
    for inv in invoices:
        if inv.get("Type") != kind or inv.get("Status") not in LIVE or not _in_base(inv, base):
            continue
        issued = _day(inv.get("Date"))
        if issued is None or issued > as_at:
            continue
        owed = _owed_at(inv, as_at, allocations)
        if owed <= 0:
            continue
        due = _day(inv.get("DueDate")) or issued
        name = (inv.get("Contact") or {}).get("Name") or "Unknown contact"
        row = by.setdefault(name, {"contact": name, **{b: ZERO for b in BUCKETS}, "total": ZERO})
        row[_bucket((as_at - due).days)] += owed
        row["total"] += owed
    return [by[k] for k in sorted(by, key=str.lower)]


def period_invoices(invoices: list, start: date, end: date, *, base: str = "GBP") -> list:
    """Sales invoices issued in the period (A4), in the base currency. Xero's
    own figures: net + VAT + rounding = gross, the rounding shown, never hidden."""
    out = []
    for inv in invoices:
        issued = _day(inv.get("Date"))
        if inv.get("Type") != "ACCREC" or inv.get("Status") not in LIVE or not issued or not start <= issued <= end \
                or not _in_base(inv, base):
            continue
        net, vat, gross = _dec(inv.get("SubTotal")), _dec(inv.get("TotalTax")), _dec(inv.get("Total"))
        out.append({"number": inv.get("InvoiceNumber") or "", "contact": (inv.get("Contact") or {}).get("Name") or "",
                    "issued": issued, "due": _day(inv.get("DueDate")), "net": net, "vat": vat,
                    "rounding": gross - net - vat, "gross": gross,
                    "status": (inv.get("Status") or "").capitalize(), "outstanding": _dec(inv.get("AmountDue"))})
    return sorted(out, key=lambda r: (r["issued"], r["number"]))


def foreign(invoices: list, base: str) -> dict:
    """Invoices in other currencies, by currency: listed, never totalled."""
    out: dict = {}
    for inv in invoices:
        if inv.get("Status") in LIVE and not _in_base(inv, base):
            out[inv.get("CurrencyCode")] = out.get(inv.get("CurrencyCode"), 0) + 1
    return out


def invoiced_sales(invoices: list, credits: list, start: date, end: date, *, base: str = "GBP") -> Decimal:
    """Sales invoiced (net of VAT) less sales credit notes, dated in the window:
    the closest figure to taxable turnover the books hold (T1, review 1)."""
    total = ZERO
    for inv in invoices:
        on = _day(inv.get("Date"))
        if inv.get("Type") == "ACCREC" and inv.get("Status") in LIVE and on and start <= on <= end \
                and _in_base(inv, base):
            total += _dec(inv.get("SubTotal"))
    for cn in credits or []:
        on = _day(cn.get("Date"))
        if cn.get("Type") == "ACCRECCREDIT" and cn.get("Status") in LIVE and on and start <= on <= end \
                and (cn.get("CurrencyCode") or base) == base:
            total -= _dec(cn.get("SubTotal"))
    return total


# ---------------------------------------------------------------- ledger ---

def ledger_pnl(lines: list) -> dict:
    """Income and expense by category, exact (A2, A7). Transfers never reach
    the ledger (ACC-1), so none are counted."""
    groups = {"income": {}, "expense": {}}
    for line in lines:
        if line["type"] not in groups:
            continue
        name = line.get("category") or "Uncategorised"
        groups[line["type"]][name] = groups[line["type"]].get(name, ZERO) + abs(_dec(line["amount"]))
    income = sorted(groups["income"].items(), key=lambda kv: kv[0].lower())
    expense = sorted(groups["expense"].items(), key=lambda kv: kv[0].lower())
    ti = sum((v for _, v in income), ZERO)
    te = sum((v for _, v in expense), ZERO)
    return {"income": income, "expense": expense, "total_income": ti, "total_expense": te, "net": ti - te}


def _ledger(session, bid: str, start: date, end: date) -> list:
    rows = session.execute(text("""
        SELECT t.transaction_date, t.description, t.payee_payer, c.name, t.type, t.amount, t.reference,
               t.external_source, t.external_id, t.import_id, t.is_reconciled
        FROM accounting_transactions t
        LEFT JOIN accounting_categories c ON t.category_id = c.id AND c.business_id = t.business_id
        WHERE t.business_id = :b AND t.transaction_date >= :s AND t.transaction_date <= :e
          AND (t.is_archived IS NULL OR t.is_archived = :no)
        ORDER BY t.transaction_date, t.created_at
    """), {"b": bid, "s": start.isoformat(), "e": end.isoformat(), "no": False}).fetchall()
    out = []
    for r in rows:
        if r[7] == "xero":
            source = "Xero payment" if str(r[8] or "").startswith("payment:") else "Xero"
        else:
            source = "Upload" if r[9] else "Manual"
        out.append({"date": _day(r[0]), "description": r[1] or "", "payee": r[2] or "", "category": r[3],
                    "type": r[4], "amount": abs(_dec(r[5])), "reference": r[6] or "", "source": source,
                    "reconciled": bool(r[10])})
    return out


# ------------------------------------------------------------ tax points ---

def facts_from(lines: list, *, org: Optional[dict], profit: Optional[Decimal], turnover_12m: Optional[Decimal],
               period: Optional[tuple] = None) -> dict:
    t = THRESHOLDS
    kind = (org or {}).get("OrganisationEntityType")
    expenses = [ln for ln in lines if ln["type"] == "expense"]

    def total(words):
        return sum((abs(_dec(ln["amount"])) for ln in expenses if _has(ln.get("category"), words)), ZERO)
    return {
        "legal_type": {"COMPANY": "company", "SOLE_TRADER": "sole_trader"}.get(kind),
        "vat_registered": None if org is None else bool(org.get("TaxNumber")),
        "turnover_12m": turnover_12m,
        "capital_items": [(ln["date"], ln.get("description") or "", abs(_dec(ln["amount"]))) for ln in expenses
                          if _has(ln.get("category"), CAPITAL_WORDS) and abs(_dec(ln["amount"])) >= t["capital_item"]],
        "pension": total(PENSION_WORDS),
        "use_of_home": total(HOME_WORDS),
        "mileage": total(MILEAGE_WORDS),
        "vehicle_spend": sum((abs(_dec(ln["amount"])) for ln in expenses if _has(ln.get("category"), VEHICLE_WORDS)
                              and not _has(ln.get("category"), MILEAGE_WORDS)
                              and not _has(ln.get("category"), CAPITAL_WORDS)), ZERO),
        "profit": profit,
        "uncategorised_spend": sum((abs(_dec(ln["amount"])) for ln in expenses if not ln.get("category")), ZERO),
        "staff_entertainment": total(STAFF_EVENT_WORDS),
        "period": period,
    }


def _point(code, title, text_, **figures) -> dict:
    return {"code": code, "title": title, "text": text_, "figures": figures}


def tax_points(f: dict, t: dict = THRESHOLDS) -> list:
    """Fixed rules on the business's own figures. Each point says what
    triggered it, and is for discussion with the accountant, never advice."""
    pts = []
    company, sole = f.get("legal_type") == "company", f.get("legal_type") == "sole_trader"
    ask = " Worth discussing with your accountant."

    threshold = t["vat_registration"]
    turnover = f.get("turnover_12m")
    if f.get("vat_registered") is False and turnover is not None and turnover >= threshold * t["vat_warning_share"]:
        share = int(turnover * 100 / threshold)
        over = turnover >= threshold
        pts.append(_point("T1", "VAT registration threshold",
                          f"Sales invoiced (before VAT, less credit notes) over the 12 months to the period end were "
                          f"{money(turnover)}, {share}% of the {money(threshold)} VAT registration threshold. The test "
                          f"is taxable turnover over any rolling 12 months, so exempt or non-business income may "
                          f"not count, and sales not invoiced in Xero would. "
                          + ("Registration is compulsory once taxable turnover goes over it, so check when it did."
                             if over else "Registration becomes compulsory if taxable turnover goes over it.") + ask,
                          turnover=turnover, threshold=threshold, share=share, months=12))

    items = f.get("capital_items") or []
    if items:
        spent = sum((i[2] for i in items), ZERO)
        relief = ("full expensing (new plant and machinery) or the Annual Investment Allowance" if company
                  else "the Annual Investment Allowance")
        pts.append(_point("T2", "Equipment that may qualify for capital allowances",
                          f"{len(items)} purchase(s) of {money(t['capital_item'])} or more, {money(spent)} in total, "
                          f"are in equipment-type categories. They may qualify for {relief} rather than being treated "
                          f"as ordinary costs; cars are treated differently." + ask,
                          count=len(items), total=spent, minimum=t["capital_item"]))

    if company and (f.get("pension") or ZERO) == ZERO:
        pts.append(_point("T3", "Employer pension contributions",
                          "No employer pension contributions were found in this period. Contributions the company "
                          "makes are normally deductible for corporation tax." + ask))

    if sole and (f.get("use_of_home") or ZERO) == ZERO:
        pts.append(_point("T4", "Working from home",
                          "No use-of-home costs were found. If you work from home, a share of household costs, or "
                          "HMRC's simplified flat rate (£10, £18 or £26 a month depending on hours), may be "
                          "claimable." + ask, low=Decimal("10"), mid=Decimal("18"), high=Decimal("26")))

    vehicle = f.get("vehicle_spend") or ZERO
    if vehicle > ZERO and (f.get("mileage") or ZERO) == ZERO:
        start, end = f.get("period") or (date.today(), date.today())
        first, last = mileage_rate(start), mileage_rate(end)
        if first == last:
            rates = f"The approved mileage rate for this period was {_pence(first)}p a mile"
        else:
            change = next(since for since, value in t["mileage_rates"] if value == last)
            rates = (f"The approved mileage rate was {_pence(first)}p a mile until {_uk(change - timedelta(days=1))} "
                     f"and {_pence(last)}p from {_uk(change)}")
        figures = {"vehicle": vehicle, "rate_pence": _pence(last), "after_10000_pence": _pence(t["mileage_after"])}
        if first != last:
            figures.update(earlier_rate_pence=_pence(first), rate_changed=_uk(change))
        pts.append(_point("T5", "Mileage or actual vehicle costs",
                          f"{money(vehicle)} of vehicle costs and no mileage claims were found. {rates} for the first "
                          f"10,000 business miles, and {_pence(t['mileage_after'])}p after; which method is better "
                          f"depends on your vehicle and records." + ask, **figures))

    profit = f.get("profit")
    if company and profit is not None:
        for edge in (t["ct_small_profits"], t["ct_main_rate_limit"]):
            if abs(profit - edge) <= edge * t["ct_band_margin"]:
                pts.append(_point("T6", "Profit near a corporation tax band",
                                  f"Profit for the period was {money(profit)}, close to the {money(edge)} limit. "
                                  f"Corporation tax is 19% on profits up to {money(t['ct_small_profits'])} and 25% "
                                  f"above {money(t['ct_main_rate_limit'])}, with marginal relief between; the "
                                  f"limits are reduced for short periods and associated companies. The timing of "
                                  f"planned spending can matter." + ask,
                                  profit=profit, limit=edge, small=t["ct_small_profits"],
                                  main=t["ct_main_rate_limit"], low_rate=19, high_rate=25))
                break

    unc = f.get("uncategorised_spend") or ZERO
    if unc > ZERO:
        pts.append(_point("T7", "Uncategorised spending",
                          f"{money(unc)} of spending has no category. Some of it may be allowable expenses; "
                          f"categorise it before the accounts are prepared." + ask, uncategorised=unc))

    staff = f.get("staff_entertainment") or ZERO
    if company and staff > ZERO:
        pts.append(_point("T8", "Staff events and small gifts",
                          f"{money(staff)} was spent on staff events. An annual event open to all staff (or all at "
                          f"one site) can be tax-free for them if annual events together cost no more than "
                          f"{money(t['staff_event_per_head'])} a head. Small gifts up to {money(t['trivial_benefit'])} "
                          f"each can be trivial benefits if they are not cash, not a reward for work and not "
                          f"contractual (directors of close companies are capped at "
                          f"{money(t['trivial_director_cap'])} a year)." + ask,
                          staff=staff, per_head=t["staff_event_per_head"], gift=t["trivial_benefit"],
                          cap=t["trivial_director_cap"]))
    return pts


# ------------------------------------------------------------- AI wording ---

# The AI may add one plain-English line beside each point. It never replaces
# the rule's text, so it can never change a figure or a claim (review 1): the
# line is dropped if it carries any number, amount or claim word.
_NUMBERISH = re.compile(r"[0-9£$€%¼½¾⅓⅔⅛]|\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
                        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
                        r"sixty|seventy|eighty|ninety|hundred|thousand|million|billion|half|quarter|double|"
                        r"twice|triple|percent|dozen|score|couple|several|many|all|every|k)\b", re.IGNORECASE)
_CLAIMS = re.compile(r"\b(guarantee\w*|definitely|certainly|certain|always|never|must|immediately|refund\w*|"
                     r"rebate\w*|you will|you'll|will save|save you|saving you|avoid\w*|evad\w*|loophole\w*|"
                     r"entitled|owed|claim now|risk-free|no risk|deductible|allowable|qualif\w*|eligible|relief|"
                     r"tax[- ]free|exempt|you can claim|claim)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?](\s|$)")


def plain_line_ok(line) -> bool:
    if not isinstance(line, str):
        return False
    s = line.strip()
    return (0 < len(s) <= 400 and not _NUMBERISH.search(s) and not _CLAIMS.search(s)
            and len(_SENTENCE_END.findall(s)) <= 3 and "\n" not in s)


async def word_points(points: list, ask) -> list:
    """One AI call writes an optional plain-English line for each point. The
    rule's text and figures are never changed; a line that fails
    plain_line_ok, or a failed or slow answer, is simply left out (W)."""
    out = [dict(p, plain=None) for p in points]
    if not points or ask is None:
        return out
    try:
        data = await asyncio.wait_for(ask(points), WORDING_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.info("Pack wording unavailable, rule text only: %s", exc)
        return out
    if not isinstance(data, dict):
        return out
    for p in out:
        line = data.get(p["code"])
        if plain_line_ok(line):
            p["plain"] = line.strip()
    return out


WORDING_SYSTEM = (
    "You help a small UK business owner understand points their accountant may raise. For each code, write ONE "
    "plain-English sentence explaining the topic in general terms. Rules: no numbers, amounts, dates or "
    "percentages of any kind (not even in words); no promises, savings or instructions; do not say what the owner "
    "will save, is owed or must do. Answer only with JSON mapping each code to its sentence.")


def make_ask(business_id):
    """The pack's one wording call, through the AI router (failover, pricing)
    with its cost saved to the ledger as accountancy_pack. None (rule text
    only) at the profit guard's limit. The call runs in a worker thread; if it
    outlasts WORDING_TIMEOUT_SECONDS the pack goes on without it."""
    from services import profit_guard
    if not profit_guard.permits(WORDING_PURPOSE):
        return None

    def call(context) -> dict:
        from sqlmodel import Session
        from db import engine
        from services import ai_costs, ai_router
        with ai_costs.collect() as spent:
            try:
                answer = ai_router.json_chat(WORDING_SYSTEM, context, purpose=WORDING_ROUTE, max_tokens=600)
            finally:
                try:
                    with Session(engine) as s:
                        ai_costs.save(s, business_id, spent, purpose=WORDING_PURPOSE)
                        s.commit()
                except Exception:
                    logger.exception("Pack wording cost not recorded")
        return answer

    async def ask(points) -> dict:
        # A daemon thread, not the loop's executor: when the wait times out the
        # pack goes on, and asyncio.run never waits for the call to finish
        # (Codex review 2). The cost is still saved when it does.
        import threading
        context = {p["code"]: p["title"] for p in points}       # titles only: no figures reach the model
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def run():
            try:
                outcome, ok = call(context), True
            except BaseException as exc:            # handed to the waiting pack, never lost
                outcome, ok = exc, False

            def settle():
                if not future.done():
                    future.set_result(outcome) if ok else future.set_exception(outcome)
            try:
                loop.call_soon_threadsafe(settle)
            except RuntimeError:
                pass                                # the pack finished without it
        threading.Thread(target=run, name="pack-wording", daemon=True).start()
        return await future
    return ask


# ------------------------------------------------------------ connection ---

async def connect(session, business_id, *, refresh, decrypt, provider_cls, now: Optional[datetime] = None) -> tuple:
    """(provider, None) for a usable Xero connection; (None, reason) when one
    exists but can't be used; (None, None) when there is none. A token that
    can't be renewed is never used (Codex review 2)."""
    row = session.execute(text("""SELECT id, tenant_id, token_ciphertext, token_expires_at FROM xero_connections
                                  WHERE business_id = :b AND is_active = :yes LIMIT 1"""),
                          {"b": str(business_id), "yes": True}).fetchone()
    if not row:
        return None, None
    try:
        token = decrypt(row[2])
    except Exception as exc:
        return None, f"Xero sign-in couldn't be read ({exc}); reconnect Xero in Settings"
    expires = _moment(row[3])
    if expires is None or (now or datetime.now(timezone.utc)) >= expires - timedelta(minutes=2):
        new_token, _ = await refresh(session, str(row[0]), row[1], str(business_id), logger)
        if not new_token:
            return None, "Xero sign-in expired and couldn't be renewed; reconnect Xero in Settings"
        token = new_token
    return provider_cls(access_token=token, tenant_id=row[1]), None


# ------------------------------------------------------------ loose ends ---

def loose_ends(lines: list, *, pending_duplicates: int, xero: bool, last_sync: Optional[datetime],
               period_end: date, bs_difference: Optional[Decimal], foreign_invoices: Optional[dict] = None) -> list:
    out = []
    unc = [ln for ln in lines if not ln.get("category")]
    if unc:
        out.append(["Uncategorised transactions", len(unc), sum((ln["amount"] for ln in unc), ZERO),
                    "Give each a category on the Accounting page."])
    unrec = [ln for ln in lines if not ln.get("reconciled")]
    if unrec:
        out.append(["Unreconciled transactions", len(unrec), sum((ln["amount"] for ln in unrec), ZERO),
                    "Reconcile them in Xero (or your bank records)."])
    if pending_duplicates:
        out.append(["Possible duplicates waiting for review", pending_duplicates, None,
                    "Review them in Possible duplicates on the Accounting page."])
    if xero:
        last = _moment(last_sync)
        last_day = last.astimezone(UK).date() if last else None
        if last_day is None or last_day <= period_end:
            out.append(["Last complete Xero sync is not after the period end", None, None,
                        (f"Last complete sync {_uk(last_day)}" if last_day else "No complete sync yet")
                        + ": sync from the Accounting page before relying on the transaction tabs."])
    if bs_difference is not None and bs_difference != ZERO:
        out.append(["Balance sheet doesn't balance", None, bs_difference,
                    "Assets less liabilities should equal equity; ask your accountant to check."])
    if foreign_invoices:
        out.append(["Invoices in other currencies left out of the totals", sum(foreign_invoices.values()), None,
                    "Not added to the aged or invoice totals: " + ", ".join(
                        f"{n} in {c}" for c, n in sorted(foreign_invoices.items())) + "."])
    return out


# --------------------------------------------------------------- workbook ---

def _workbook(pack: dict):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    code = pack.get("currency")
    cur = ('#,##0.00;-#,##0.00' if code is None else '£#,##0.00;-£#,##0.00' if code == "GBP"
           else f'"{code} "#,##0.00;-"{code} "#,##0.00')
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", start_color="2B5797")
    title_font, note_font = Font(bold=True, size=14, color="2B5797"), Font(italic=True, color="666666")

    wb = Workbook()
    wb.remove(wb.active)
    for name in TAB_ORDER:
        if name not in pack["tabs"]:
            continue
        spec = pack["tabs"][name]
        ws = wb.create_sheet(name)
        for r, row in enumerate(spec["rows"], 1):
            for c, value in enumerate(row, 1):
                if value is None:
                    continue
                cell = ws.cell(row=r, column=c, value=float(value) if isinstance(value, Decimal) else value)
                if isinstance(value, Decimal):
                    cell.number_format = cur
                elif isinstance(value, date):
                    cell.number_format = "DD/MM/YYYY"
                if r == spec.get("header_at"):
                    cell.font, cell.fill = head_font, head_fill
        if spec.get("title", True) and spec["rows"] and spec.get("header_at") != 1:
            ws.cell(row=1, column=1).font = title_font
        for r in spec.get("notes", ()):
            ws.cell(row=r, column=1).font = note_font
        for col in ws.columns:
            longest = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(longest + 3, 60)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _report_tab(report: dict) -> dict:
    rows = [[report.get("ReportName", "Report")]] + [[t] for t in report.get("ReportTitles") or []] + [[]]
    header_at = None
    for row in report_rows(report):
        if row["kind"] == "header" and header_at is None:
            header_at = len(rows) + 1
        rows.append(row["cells"] if row["kind"] != "title" else [row["cells"][0]])
    return {"rows": rows, "header_at": header_at}


def _ledger_pnl_tab(this: dict, prior: dict, start, end, p_start, p_end) -> dict:
    def section(key):
        names = sorted({k for k, _ in this[key]} | {k for k, _ in prior[key]}, key=str.lower)
        a, b = dict(this[key]), dict(prior[key])
        return [[k, a.get(k, ZERO), b.get(k, ZERO)] for k in names]
    rows = [["Profit & Loss"], [f"{_uk(start)} to {_uk(end)}, with {_uk(p_start)} to {_uk(p_end)} beside it"],
            ["Cash basis, unaudited: built from Business Hero's transactions (no Xero connection)."], [],
            ["", "This period", "Prior period"], ["Income"]] + section("income") + \
           [["Total Income", this["total_income"], prior["total_income"]], [], ["Expenses"]] + section("expense") + \
           [["Total Expenses", this["total_expense"], prior["total_expense"]], [],
            ["Net Profit", this["net"], prior["net"]]]
    return {"rows": rows, "header_at": 5, "notes": (3,)}


# ------------------------------------------------------------------ build ---

async def build(session, business_id, provider=None, *, start: Optional[date] = None, end: Optional[date] = None,
                today: Optional[date] = None, ask=None, business_name: Optional[str] = None,
                now: Optional[datetime] = None, xero_error: Optional[str] = None) -> dict:
    """The pack. `provider` is a Xero provider or None (`xero_error` says why
    a connected Xero couldn't be used). Returns {content, filename, included,
    missing, period}. Raises PeriodError for an invalid resolved period."""
    from services import xero_sync
    bid = str(business_id)
    now = (now or datetime.now(timezone.utc)).astimezone(UK)
    today = today or now.date()
    sem = asyncio.Semaphore(XERO_CONCURRENCY)
    missing: dict = {}

    async def call(fn, *a, **kw):
        async with sem:
            return await xero_sync._xero(fn, *a, **kw)

    org = None
    if provider is not None:
        try:
            org = await call(provider.get_organisation) or {}
        except Exception as exc:
            # without it neither the year end nor the connection can be trusted:
            # the pack is built from Business Hero's own data, and says why (review 2)
            logger.warning("Xero organisation unavailable: %s", exc)
            provider, org = None, None
            xero_error = xero_error or f"Xero didn't answer ({str(exc) or exc.__class__.__name__})"
    base = (org or {}).get("BaseCurrency") or "GBP"
    # A Xero connection that failed leaves the currency unconfirmed: amounts are
    # shown as recorded, with no currency symbol and no tax points (review 3).
    confirmed = xero_error is None
    fy = ((org or {}).get("FinancialYearEndDay"), (org or {}).get("FinancialYearEndMonth"))
    d_start, d_end = default_period(today, *fy)
    start, end = start or d_start, end or d_end
    if start > end:
        raise PeriodError(f"The period starts ({_uk(start)}) after it ends ({_uk(end)}).")
    p_start, p_end = prior_period(start, end)
    year_start = _year_earlier(end) + timedelta(days=1)
    name = business_name or (org or {}).get("Name") or "Business"

    lines = _ledger(session, bid, start, end)
    ledger = ledger_pnl(lines)

    reports: dict = {}
    streams: dict = {}
    if provider is not None:
        def dt(d):
            return f"DateTime({d.year},{d.month},{d.day})"

        async def pages(fn, key, **kw):
            got, page = [], 1
            while page <= xero_sync.MAX_PAGES:
                data = await call(fn, page=page, **kw)
                items = list((data or {}).get(key) or [])
                got.extend(items)
                if len(items) < PAGE:
                    return got
                page += 1
            raise RuntimeError(f"too many {key} for one pack")

        async def guarded(key, coro):
            try:
                return key, await coro, None
            except Exception as exc:
                logger.warning("Pack: %s unavailable: %s", key, exc)
                return key, None, str(exc) or exc.__class__.__name__

        records = getattr(provider, "get_records")
        results = await asyncio.gather(
            guarded("Profit & Loss", call(provider.get_profit_and_loss, from_date=start.isoformat(),
                                          to_date=end.isoformat(), periods=1, timeframe="YEAR")),
            guarded("Balance Sheet", call(provider.get_balance_sheet, date=end.isoformat(), periods=1,
                                          timeframe="YEAR")),
            guarded("Trial Balance", call(provider.get_trial_balance, date=end.isoformat())),
            # aged at the end (review 1): open now, plus every invoice a payment
            # or allocation dated AFTER the end touched (paid since, so owed then)
            guarded("open", pages(provider.get_invoice_list, "Invoices", statuses="AUTHORISED",
                                  where=f"Date<={dt(end)}")),
            guarded("payments_after", pages(records, "Payments", resource="Payments", where=f"Date>{dt(end)}")),
            guarded("credit_notes", pages(records, "CreditNotes", resource="CreditNotes",
                                          where='Status=="AUTHORISED" OR Status=="PAID"')),
            guarded("prepayments", pages(records, "Prepayments", resource="Prepayments")),
            guarded("overpayments", pages(records, "Overpayments", resource="Overpayments")),
            guarded("sales", pages(provider.get_invoice_list, "Invoices", statuses="AUTHORISED,PAID",
                                   where=f'Type=="ACCREC" AND Date>={dt(min(start, year_start))} '
                                         f'AND Date<={dt(end)}')),
        )
        for key, value, error in results:
            if key in TAB_ORDER:
                if error or not (value or {}).get("Reports"):
                    missing[key] = f"Xero report unavailable: {error or 'empty response'}"
                else:
                    reports[key] = value["Reports"][0]
            else:
                streams[key] = (value, error)

        aged_error = next((e for k, (v, e) in streams.items() if k != "sales" and e), None)
        allocations = None
        aged_invoices: dict = {}
        if not aged_error:
            allocations = allocations_by_invoice(streams["credit_notes"][0] + streams["prepayments"][0]
                                                 + streams["overpayments"][0])
            aged_invoices = {str(i.get("InvoiceID")): i for i in streams["open"][0]}
            touched = {str((p.get("Invoice") or {}).get("InvoiceID") or "") for p in streams["payments_after"][0]
                       if p.get("Status") != "DELETED"}
            touched |= {iid for iid, allocs in allocations.items() if any((on or date.max) > end for on, _ in allocs)}
            wanted = sorted(i for i in touched if i and i not in aged_invoices)
            try:
                fetched = await asyncio.gather(*(call(provider.get_invoices_by_ids, wanted[n:n + ID_BATCH])
                                                 for n in range(0, len(wanted), ID_BATCH)))
                for batch in fetched:
                    for inv in batch or []:
                        aged_invoices[str(inv.get("InvoiceID"))] = inv
            except Exception as exc:
                aged_error = str(exc) or exc.__class__.__name__
        if aged_error:
            missing["Aged Debtors"] = missing["Aged Creditors"] = f"Xero invoices unavailable: {aged_error}"
        if streams["sales"][1]:
            missing["Invoices"] = f"Xero invoices unavailable: {streams['sales'][1]}"
    else:
        why = f"Xero connection failed: {xero_error}." if xero_error else "Needs Xero."
        missing["Balance Sheet"] = (f"{why} " if xero_error else "Needs Xero: ") + \
            "a balance sheet can't be built honestly from bank lines alone."
        missing["Trial Balance"] = why
        missing["Aged Debtors"] = missing["Aged Creditors"] = f"{why} Aged balances need Xero invoices and payments."

    tabs: dict = {}
    # ---- Profit & Loss
    pnl_rows = report_rows(reports["Profit & Loss"]) if "Profit & Loss" in reports else None
    if pnl_rows is not None:
        tabs["Profit & Loss"] = _report_tab(reports["Profit & Loss"])
    elif provider is None:
        prior = ledger_pnl(_ledger(session, bid, p_start, p_end))
        tabs["Profit & Loss"] = _ledger_pnl_tab(ledger, prior, start, end, p_start, p_end)
    # ---- Balance sheet, trial balance
    bs_diff = None
    if "Balance Sheet" in reports:
        tabs["Balance Sheet"] = _report_tab(reports["Balance Sheet"])
        bs_diff = balance_difference(report_rows(reports["Balance Sheet"]))
    if "Trial Balance" in reports:
        tabs["Trial Balance"] = _report_tab(reports["Trial Balance"])
    # ---- Aged
    other_currencies: dict = {}
    if provider is not None and "Aged Debtors" not in missing:
        everything = list(aged_invoices.values())
        other_currencies = foreign([i for i in everything if (_day(i.get("Date")) or date.max) <= end], base)
        for tab, kind in (("Aged Debtors", "ACCREC"), ("Aged Creditors", "ACCPAY")):
            data = aged(everything, end, kind, allocations, base=base)
            sums = {b: sum((r[b] for r in data), ZERO) for b in BUCKETS + ("total",)}
            tabs[tab] = {"rows": [[tab], [f"As at {_uk(end)}, in {base}"], [],
                                  ["Contact", "Current", "1–30 days", "31–60 days", "61–90 days", "Over 90 days",
                                   "Total"]]
                         + [[r["contact"]] + [r[b] for b in BUCKETS] + [r["total"]] for r in data]
                         + [["Total"] + [sums[b] for b in BUCKETS] + [sums["total"]]], "header_at": 4}
    # ---- Invoices
    inv_head = ["Invoice", "Customer", "Issued", "Due", "Net", "VAT", "Rounding", "Gross", "Status",
                "Outstanding today"]
    turnover_12m = None
    if provider is not None and "Invoices" not in missing:
        sales = list({str(i.get("InvoiceID")): i for i in streams["sales"][0]}.values())
        for c, n in foreign([i for i in sales if start <= (_day(i.get("Date")) or date.min) <= end], base).items():
            other_currencies[c] = max(other_currencies.get(c, 0), n)
        rows = period_invoices(sales, start, end, base=base)
        tabs["Invoices"] = {"rows": [["Sales invoices issued in the period"], [f"{_uk(start)} to {_uk(end)}, in {base}"],
                                     [], inv_head]
                            + [[r["number"], r["contact"], r["issued"], r["due"], r["net"], r["vat"], r["rounding"],
                                r["gross"], r["status"], r["outstanding"]] for r in rows]
                            + [["Total", None, None, None] + [sum((r[k] for r in rows), ZERO)
                                                              for k in ("net", "vat", "rounding", "gross")]],
                            "header_at": 4}
        if streams["credit_notes"][1] is None:
            turnover_12m = invoiced_sales(sales, streams["credit_notes"][0], year_start, end, base=base)
    elif provider is None:
        got = session.execute(text("""SELECT invoice_number, customer_name, issue_date, due_date, amount, status,
                   currency
            FROM invoices WHERE business_id = :b AND issue_date >= :s AND issue_date <= :e
              AND (archived IS NULL OR archived = :no) ORDER BY issue_date"""),
            {"b": bid, "s": start.isoformat(), "e": end.isoformat(), "no": False}).fetchall()
        for r in got:                                  # other currencies: listed, never shown as pounds (review 3)
            if (r[6] or base) != base:
                other_currencies[r[6]] = other_currencies.get(r[6], 0) + 1
        got = [r for r in got if (r[6] or base) == base]
        tabs["Invoices"] = {"rows": [["Sales invoices issued in the period"],
                                     [f"{_uk(start)} to {_uk(end)}. VAT isn't recorded without Xero: gross only."], [],
                                     inv_head] + [[r[0] or "", r[1] or "", _day(r[2]), _day(r[3]), None, None, None,
                                                   _dec(r[4]), (r[5] or "").capitalize(), None] for r in got],
                            "header_at": 4}
    # ---- Transactions
    tabs["Transactions"] = {"rows": [["Date", "Description", "Payee/Payer", "Category", "Type", "Amount", "Reference",
                                      "Source", "Reconciled"]]
                            + [[ln["date"], ln["description"], ln["payee"], ln["category"] or "Uncategorised",
                                ln["type"].capitalize(), ln["amount"], ln["reference"], ln["source"],
                                "Yes" if ln["reconciled"] else "No"] for ln in lines], "header_at": 1}
    # ---- Cash summary
    cats: dict = {}
    for ln in lines:
        row = cats.setdefault(ln["category"] or "Uncategorised", [ZERO, ZERO])
        row[0 if ln["type"] == "income" else 1] += ln["amount"]
    cin, cout = sum((v[0] for v in cats.values()), ZERO), sum((v[1] for v in cats.values()), ZERO)
    tabs["Cash Summary"] = {"rows": [["Cash Summary"],
                                     ["Cash movements, not profit: money in and out by category, including VAT, "
                                      "capital purchases, loans and drawings. Profit is on the Profit & Loss tab."],
                                     [], ["Category", "Money in", "Money out"]]
                            + [[k, v[0], v[1]] for k, v in sorted(cats.items(), key=lambda kv: kv[0].lower())]
                            + [["Total", cin, cout], ["Net cash movement", cin - cout]], "header_at": 4, "notes": (2,)}
    # ---- Loose ends
    last_sync = None
    if provider is not None:
        row = session.execute(text("SELECT last_sync_at FROM xero_connections WHERE business_id = :b "
                                   "AND is_active = :yes ORDER BY last_sync_at DESC LIMIT 1"),
                              {"b": bid, "yes": True}).fetchone()
        last_sync = _moment(row[0]) if row else None
    pending = len(xero_sync._dups(xero_sync._doc(session, bid)).get("review") or [])
    ends = loose_ends(lines, pending_duplicates=pending, xero=provider is not None, last_sync=last_sync,
                      period_end=end, bs_difference=bs_diff, foreign_invoices=other_currencies)
    tabs["Loose Ends"] = {"rows": [["Item", "Count", "Value", "What to do"]]
                          + (ends or [["Nothing to tidy", None, None, "No loose ends were found."]]), "header_at": 1}
    # ---- Points to discuss
    profit = find_value(pnl_rows, "Net Profit") if pnl_rows is not None else (ledger["net"] if provider is None else None)
    gbp = base == "GBP" and confirmed
    points = await word_points(tax_points(facts_from(lines, org=org, profit=profit, turnover_12m=turnover_12m,
                                                     period=(start, end))), ask) if gbp else []
    tabs["Points to Discuss"] = {"rows": [["Points to discuss with your accountant"],
                                          [f"From this pack's own figures, using UK rules checked {THRESHOLDS['checked']}. "
                                           "These are prompts for a conversation, not tax advice. The 'In plain words' "
                                           "column is AI-written background and may be imprecise: the Explanation and "
                                           "Figures are what count; check anything with your accountant."],
                                          [], ["Ref", "Point", "Explanation", "In plain words (AI-written, may be imprecise)", "Figures"]]
                                 + [[p["code"], p["title"], p["text"], p.get("plain"),
                                     "; ".join(f"{k}: {money(v) if isinstance(v, Decimal) else v}"
                                               for k, v in p["figures"].items())] for p in points]
                                 + ([] if points else [["", "Nothing to raise", "No rule applied to these figures."
                                                         if gbp else (f"Tax points compare figures with UK limits in "
                                                         f"pounds; this organisation reports in {base}, so none are "
                                                         f"raised." if confirmed else "Xero couldn't be used, so the "
                                                         "currency and business type aren't confirmed; no tax points "
                                                         "are raised.")]]),
                                 "header_at": 4, "notes": (2,)}
    # ---- Summary (last: it reports what was built)
    included = [t for t in TAB_ORDER[1:] if t in tabs]
    for t in TAB_ORDER[1:]:
        if t not in tabs and t not in missing:
            missing[t] = "Not available."
    income = find_value(pnl_rows, "Total Income") if pnl_rows is not None else ledger["total_income"]
    legal = {"COMPANY": "Limited company", "SOLE_TRADER": "Sole trader"}.get((org or {}).get("OrganisationEntityType"),
                                                                             "Not known (connect Xero)")
    has_comparatives = "Profit & Loss" in tabs
    summary = [["Accountancy Pack"], [name], [f"Legal type: {legal}"],
               [f"Period: {_uk(start)} to {_uk(end)}"],
               [f"Currency: {base}" if confirmed else
                "Currency: not confirmed (Xero couldn't be used); amounts are shown as recorded"],
               [f"Comparatives: {_uk(p_start)} to {_uk(p_end)}" if has_comparatives
                else "Comparatives: none (no Profit & Loss in this pack)"],
               [f"Generated: {now:%d/%m/%Y %H:%M} (UK time)"],
               ["A first draft prepared by Business Hero for your accountant; not filed accounts."], [],
               ["Headline figures"], ["Income", income], ["Net profit (from the Profit & Loss)", profit], [],
               ["Included"]] + [[t] for t in included] + [[]] + \
              ([["Not included"]] + [[f"{t}: not included. {missing[t]}"] for t in TAB_ORDER[1:] if t in missing]
               if missing else []) + [[], ["Loose ends to tidy", len(ends)], ["Points to discuss", len(points)]]
    tabs["Summary"] = {"rows": summary, "notes": (7, 8)}

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "business"
    return {"content": _workbook({"tabs": tabs, "currency": base if confirmed else None}), "filename": f"accountancy-pack-{slug}-{start}-to-{end}.xlsx",
            "included": included, "missing": {t: missing[t] for t in TAB_ORDER if t in missing},
            "period": (start, end)}
