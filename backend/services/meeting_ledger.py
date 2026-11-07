"""BM-3 — the business's own transactions for a board meeting.

Two things for Aria, both read-only and both for the meeting's business only:

* `summary` — the last N full months (6 by default, 12 at most), month by
  month: income by payer, spending by supplier and by category, large
  one-off income lines with their references, this month so far, and how
  much of the period the records actually cover (a new business may have
  only a few months). It goes into the meeting brief.
* `search` — individual transactions by words (payer, reference,
  description), amount, direction and dates, at most 50 lines, with totals
  over every match. Aria calls it during the meeting, typed or spoken.

Figures come from accountancy_pack._ledger: the same lines, filters and
signs as the accountancy pack, so a meeting never shows a second version of
the truth (archived and duplicate lines are excluded there; transfers never
reach the ledger).
"""
from __future__ import annotations

import calendar
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

DEFAULT_MONTHS = 6
MAX_MONTHS = 12
TOP_PAYERS = 15
TOP_SUPPLIERS = 20
TOP_CATEGORIES = 20
LARGE_INCOME = Decimal("500")      # a one-off payment worth seeing on its own (e.g. a full course fee)
LARGE_INCOME_LINES = 40
# A payer seen more often than this in the window pays regularly (Ashbourne,
# GoCardless payouts): its receipts are in income_by_payer, not "one-off".
RECURRING_AT = 3
DESCRIPTION_CHARS = 140
# The most one ledger result may be, as JSON, before it is trimmed: lists are
# shortened (and say so), totals and coverage are always kept whole
# (Codex BM-3 review 1, finding 1).
RESULT_CHARS = 24_000
BRIEF_CHARS = 32_000    # the meeting brief's ledger section (about 8,000 tokens at most)
SEARCH_LIMIT = 50
SEARCH_YEARS = 2
NO_PAYER = "(no payer recorded)"
TWELVE_MONTH_ADVISORY = (
    "Twelve months is twice the usual six, so this part of the meeting uses a little more of "
    "its AI allowance. It shows seasonal patterns better."
)


def _short(value) -> str:
    value = (value or "").strip()
    return value if len(value) <= DESCRIPTION_CHARS else value[:DESCRIPTION_CHARS - 1] + "…"


def _years_back(today: date, years: int) -> date:
    """The same day `years` earlier; 29 February becomes 28 February
    (Codex BM-3 review 1, finding 5)."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        return today.replace(year=today.year - years, day=28)


_TRIM_PATHS = (("transactions",), ("large_one_off_income", "lines"), ("expense_by_supplier",),
               ("income_by_payer",), ("expense_by_category",))
FIELD_CHARS = 200


def _clip_strings(value):
    if isinstance(value, str):
        return value if len(value) <= FIELD_CHARS else value[:FIELD_CHARS - 1] + "…"
    if isinstance(value, list):
        return [_clip_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: _clip_strings(v) for k, v in value.items()}
    return value


def _refresh_counts(result: Dict[str, Any]) -> None:
    """After trimming, what is SHOWN is said truthfully; whole-period counts
    and totals are left as they are (Codex BM-3 review 2, finding 2)."""
    one_off = result.get("large_one_off_income")
    if isinstance(one_off, dict) and isinstance(one_off.get("lines"), list):
        one_off["shown"] = len(one_off["lines"])
    if isinstance(result.get("transactions"), list) and "matched" in result:
        result["shown"] = len(result["transactions"])
        result["truncated"] = result["matched"] > result["shown"]


def fit(result: Dict[str, Any], limit: Optional[int] = None) -> Dict[str, Any]:
    """Make the JSON fit `limit`, saying what was left out. Totals, counts and
    coverage are never touched, so a trimmed result is smaller, never wrong.
    Guaranteed (Codex BM-3 review 2, finding 1): the note is counted in the
    budget; long fields are clipped; lists may shrink to nothing."""
    limit = RESULT_CHARS if limit is None else limit

    def size():
        return len(json.dumps(result, default=str))
    _refresh_counts(result)          # BEFORE measuring: its fields count too (Codex BM-3 review 3)
    if size() <= limit:
        return result
    result["trimmed"] = {}
    result["trimmed_note"] = ("Some lists were shortened to fit; totals, counts and coverage are complete. "
                              "Use search_transactions for the detail.")
    for key in list(result):
        if key not in ("trimmed", "trimmed_note"):
            result[key] = _clip_strings(result[key])
    while size() > limit:
        best = None
        for path in _TRIM_PATHS:
            holder = result
            for key in path[:-1]:
                holder = holder.get(key) if isinstance(holder, dict) else None
            items = holder.get(path[-1]) if isinstance(holder, dict) else None
            if isinstance(items, list) and items and (best is None or len(items) > len(best[1])):
                best = (path, items, holder)
        if best is None:
            break
        path, items, holder = best
        keep = len(items) // 2
        name = ".".join(path)
        result["trimmed"][name] = result["trimmed"].get(name, 0) + (len(items) - keep)
        holder[path[-1]] = items[:keep]
        _refresh_counts(result)
    _refresh_counts(result)
    if size() <= limit:
        return result
    # Still too large with every list empty (Codex BM-3 review 4): keep only
    # the headline numbers and say so; and if even that cannot fit, the
    # smallest valid answer. Never JSON over the limit.
    headline = {k: v for k, v in result.items() if isinstance(v, (int, float, bool))}
    headline["error"] = "That result was too large to show. Narrow the search (fewer months, a payer, dates)."
    for candidate in (headline, {"error": headline["error"]}, {"error": "Too large; narrow the search."}, {}):
        if len(json.dumps(candidate, default=str)) <= limit:
            return candidate
    return {}


def _f(value) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01")))


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _window(today: date, months: int) -> tuple:
    """The last `months` FULL months before the month `today` is in."""
    end = today.replace(day=1) - timedelta(days=1)
    start = end.replace(day=1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    return start, end


def _months_between(start: date, end: date) -> List[str]:
    out, cur = [], start.replace(day=1)
    while cur <= end:
        out.append(_month_key(cur))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _lines(session, bid: str, start: date, end: date) -> list:
    from services import accountancy_pack as pack
    return pack._ledger(session, str(bid), start, end)


def _first_record(session, bid: str) -> Optional[date]:
    row = session.execute(text(
        "SELECT MIN(transaction_date) FROM accounting_transactions WHERE business_id = :b "
        "AND (is_archived IS NULL OR is_archived = :no)"), {"b": str(bid), "no": False}).fetchone()
    if not row or row[0] is None:
        return None
    value = row[0]
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _long_date(day: date) -> str:
    return f"{day.day} {calendar.month_name[day.month]} {day.year}"


def _grouped(lines: list, key, months: List[str], top: int, label: str, other: str) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for ln in lines:
        name = key(ln)
        g = groups.setdefault(name.casefold(), {label: name, "total": Decimal(0), "count": 0,
                                                "by_month": defaultdict(Decimal)})
        g["total"] += ln["amount"]
        g["count"] += 1
        g["by_month"][_month_key(ln["date"])] += ln["amount"]
    ranked = sorted(groups.values(), key=lambda g: g["total"], reverse=True)
    kept, rest = ranked[:top], ranked[top:]

    def shape(g):
        return {label: g[label], "total": _f(g["total"]), "count": g["count"],
                "by_month": {m: _f(g["by_month"].get(m, 0)) for m in months if g["by_month"].get(m)}}
    out = [shape(g) for g in kept]
    if rest:
        merged = {label: f"{other} ({len(rest)})", "total": Decimal(0), "count": 0, "by_month": defaultdict(Decimal)}
        for g in rest:
            merged["total"] += g["total"]
            merged["count"] += g["count"]
            for m, v in g["by_month"].items():
                merged["by_month"][m] += v
        row = shape(merged)
        row["payers" if label == "payer" else "names"] = len(rest)
        out.append(row)
    return out


def summary(session, bid: str, today: date, months: int = DEFAULT_MONTHS) -> Dict[str, Any]:
    """The meeting's ledger section. Never raises for an empty business."""
    months = max(1, min(MAX_MONTHS, int(DEFAULT_MONTHS if months is None else months)))
    start, end = _window(today, months)
    first = _first_record(session, bid)
    if first is None:
        return {"available": False, "months": months,
                "reason": "No transactions are recorded in Business Hero yet."}
    lines = _lines(session, bid, start, end)
    month_keys = _months_between(start, end)
    income = [ln for ln in lines if ln["type"] == "income"]
    expense = [ln for ln in lines if ln["type"] == "expense"]

    monthly = []
    for m in month_keys:
        i = sum((ln["amount"] for ln in income if _month_key(ln["date"]) == m), Decimal(0))
        e = sum((ln["amount"] for ln in expense if _month_key(ln["date"]) == m), Decimal(0))
        monthly.append({"month": m, "income": _f(i), "expense": _f(e), "net": _f(i - e)})

    mtd_start = today.replace(day=1)
    mtd = _lines(session, bid, mtd_start, today)
    mtd_i = sum((ln["amount"] for ln in mtd if ln["type"] == "income"), Decimal(0))
    mtd_e = sum((ln["amount"] for ln in mtd if ln["type"] == "expense"), Decimal(0))

    if first > start:
        full_start = first if first.day == 1 else (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        full = len(_months_between(full_start, end)) if full_start <= end else 0
        note = (f"Records start on {_long_date(first)}, so {full} full month{'' if full == 1 else 's'} "
                f"of the {months} asked for {'is' if full == 1 else 'are'} available.")
    else:
        full, note = months, f"Records cover all {months} months."

    # One-off: a large receipt from a payer that does NOT pay regularly (or
    # with no payer). Regular payers' receipts are in income_by_payer, so they
    # cannot crowd a full course payment out (Codex review 1, finding 3).
    seen = defaultdict(int)
    for ln in income:
        seen[(ln.get("payee") or "").strip().casefold()] += 1
    one_off = sorted((ln for ln in income if ln["amount"] >= LARGE_INCOME
                      and (not (ln.get("payee") or "").strip()
                           or seen[(ln.get("payee") or "").strip().casefold()] < RECURRING_AT)),
                     key=lambda ln: ln["date"], reverse=True)
    large = one_off[:LARGE_INCOME_LINES]
    no_payer = [ln for ln in income if not (ln.get("payee") or "").strip()]
    ti = sum((ln["amount"] for ln in income), Decimal(0))
    te = sum((ln["amount"] for ln in expense), Decimal(0))
    out = {
        "available": True,
        "data_source": "Business Hero ledger (the same figures as the accountancy pack)",
        "months": months,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "coverage": {"first_record": first.isoformat(), "full_months": full, "note": note},
        "total_income": _f(ti),
        "total_expense": _f(te),
        "net": _f(ti - te),
        "monthly_totals": monthly,
        "month_to_date": {"from": mtd_start.isoformat(), "through": today.isoformat(),
                          "income": _f(mtd_i), "expense": _f(mtd_e)},
        "income_by_payer": _grouped(income, lambda ln: (ln.get("payee") or "").strip() or NO_PAYER,
                                    month_keys, TOP_PAYERS, "payer", "All other payers"),
        "expense_by_supplier": _grouped(expense, lambda ln: (ln.get("payee") or "").strip() or NO_PAYER,
                                        month_keys, TOP_SUPPLIERS, "payee", "All other suppliers"),
        "expense_by_category": _grouped(expense, lambda ln: ln.get("category") or "Uncategorised",
                                        month_keys, TOP_CATEGORIES, "category", "All other categories"),
        "large_one_off_income": {
            "rule": (f"receipts of £{int(LARGE_INCOME)} or more from payers seen fewer than {RECURRING_AT} "
                     "times in the period, or with no payer; regular payers are in income_by_payer"),
            "count": len(one_off), "shown": len(large),
            "lines": [{"date": ln["date"].isoformat(), "amount": _f(ln["amount"]),
                       "payer": ln.get("payee") or "", "reference": ln.get("reference") or "",
                       "description": _short(ln.get("description"))} for ln in large]},
        "income_without_payer": {"count": len(no_payer),
                                 "total": _f(sum((ln["amount"] for ln in no_payer), Decimal(0)))},
    }
    if months > DEFAULT_MONTHS:
        out["advisory"] = TWELVE_MONTH_ADVISORY
    return out


def _day_arg(value, name: str) -> Optional[date]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"{name} must be a date like 2026-09-30")


def _amount_arg(value, name: str) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a number")


def search(session, bid: str, today: date, *, text: Optional[str] = None, direction: Optional[str] = None,
           min_amount=None, max_amount=None, date_from=None, date_to=None,
           limit: int = SEARCH_LIMIT) -> Dict[str, Any]:
    """Transactions matching every filter given, newest first, at most
    `limit` lines; the totals and count cover every match. At most the last
    SEARCH_YEARS years."""
    earliest = _years_back(today, SEARCH_YEARS)
    start = max(_day_arg(date_from, "date_from") or earliest, earliest)
    end = min(_day_arg(date_to, "date_to") or today, today)
    low, high = _amount_arg(min_amount, "min_amount"), _amount_arg(max_amount, "max_amount")
    kind = (direction or "").strip().lower() or None
    if kind not in (None, "income", "expense"):
        raise ValueError("direction must be income or expense")
    words = [w for w in (text or "").casefold().split() if w]
    matched = []
    for ln in _lines(session, bid, start, end) if start <= end else []:
        if kind and ln["type"] != kind:
            continue
        if low is not None and ln["amount"] < low:
            continue
        if high is not None and ln["amount"] > high:
            continue
        hay = " ".join((ln.get("payee") or "", ln.get("reference") or "", ln.get("description") or "",
                        ln.get("category") or "")).casefold()
        if words and not all(w in hay for w in words):
            continue
        matched.append(ln)
    matched.sort(key=lambda ln: ln["date"], reverse=True)
    limit = max(1, min(SEARCH_LIMIT, int(limit or SEARCH_LIMIT)))
    return {
        "date_from": start.isoformat(), "date_to": end.isoformat(),
        "matched": len(matched), "truncated": len(matched) > limit,
        "total_income": _f(sum((ln["amount"] for ln in matched if ln["type"] == "income"), Decimal(0))),
        "total_expense": _f(sum((ln["amount"] for ln in matched if ln["type"] == "expense"), Decimal(0))),
        "transactions": [{"date": ln["date"].isoformat(), "direction": ln["type"], "amount": _f(ln["amount"]),
                          "payer": ln.get("payee") or "", "reference": ln.get("reference") or "",
                          "description": _short(ln.get("description")), "category": ln.get("category") or "",
                          "source": ln.get("source"), "reconciled": ln.get("reconciled")}
                         for ln in matched[:limit]],
    }


# ---------------------------------------------------------------- tools ---

_SEARCH_PARAMS = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Words to find in the payer, reference, description or "
                                                  "category, e.g. 'gocardless' or 'smith'. All words must match."},
        "direction": {"type": "string", "enum": ["income", "expense"]},
        "min_amount": {"type": "number", "description": "Smallest amount in pounds"},
        "max_amount": {"type": "number", "description": "Largest amount in pounds (equal to min for an exact amount)"},
        "date_from": {"type": "string", "description": "YYYY-MM-DD"},
        "date_to": {"type": "string", "description": "YYYY-MM-DD"},
    },
    "additionalProperties": False,
}
_SUMMARY_PARAMS = {
    "type": "object",
    "properties": {"months": {"type": "integer", "minimum": 1, "maximum": MAX_MONTHS,
                              "description": "Full months to cover, 6 by default, 12 at most"}},
    "additionalProperties": False,
}
_SEARCH_DOC = ("Look at the business's own recorded transactions: individual lines with payer, reference, "
               "description, category and amount. Returns at most 50 lines, newest first, plus the count and "
               "totals of every match.")
_SUMMARY_DOC = ("The business's ledger month by month for a number of full months: income by payer, spending "
                "by supplier and category, large one-off income, and how many months the records cover.")

CHAT_TOOLS = [
    {"type": "function", "function": {"name": "search_transactions", "description": _SEARCH_DOC,
                                      "parameters": _SEARCH_PARAMS}},
    {"type": "function", "function": {"name": "ledger_summary", "description": _SUMMARY_DOC,
                                      "parameters": _SUMMARY_PARAMS}},
]
REALTIME_TOOLS = [
    {"type": "function", "name": "search_transactions", "description": _SEARCH_DOC, "parameters": _SEARCH_PARAMS},
    {"type": "function", "name": "ledger_summary", "description": _SUMMARY_DOC, "parameters": _SUMMARY_PARAMS},
]
TOOL_NAMES = frozenset({"search_transactions", "ledger_summary"})
_SEARCH_KEYS = ("text", "direction", "min_amount", "max_amount", "date_from", "date_to")


def run_tool(name: str, args: Any, session, bid: str, today: date) -> str:
    """Run one meeting tool for THIS business (never one the model names) and
    return JSON. A bad request is an answer the model can read, not a crash."""
    try:
        args = args if isinstance(args, dict) else json.loads(args or "{}")
        if name == "search_transactions":
            result = search(session, bid, today, **{k: args.get(k) for k in _SEARCH_KEYS})
        elif name == "ledger_summary":
            result = summary(session, bid, today, months=args.get("months"))
        else:
            return json.dumps({"error": f"There is no tool called {name!r} in a board meeting."})
    except (ValueError, TypeError) as exc:
        return json.dumps({"error": str(exc)})
    except Exception:
        logger.exception("[MeetingLedger] %s failed for %s", name, bid)
        return json.dumps({"error": "The transactions could not be read just now."})
    return json.dumps(fit(result), default=str)
