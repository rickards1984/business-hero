"""PROFIT-2 — the running-costs tracker (docs/PROFIT-2-TICKET.md). RED: the
profit guard's fixed costs.

Mike, 31 Oct 2026: each bill (Railway, Vercel, Supabase, Twilio, domains...)
with its monthly amount. The list carries forward each month; a month can be
corrected to the actual bill. PLATFORM_FIXED_COSTS_PENCE is the fallback
while no list exists.

Stored in platform_meters (no migration): `fixed_cost:<name>` = pence for a
month, and `fixed_costs_set` = 1 once that month has its own list. A month
without one shows the latest earlier month's list WITHOUT writing (the profit
guard reads costs on every AI call); the first edit copies it in.
"""
import os
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from services.aria_actions import ActionRefused

PREFIX, MARK = "fixed_cost:", "fixed_costs_set"
NAME = re.compile(r"^[A-Za-z0-9 .&()/\-]{1,60}$")
MAX_PENCE = 10_000_000
MONTHS_BACK = 24
PERIOD = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def refuse(detail: str):
    raise ActionRefused(422, detail)


def _source(session, period: str) -> Optional[str]:
    """The month whose list applies to `period`: its own, or the latest earlier one.
    Without migration 039's table there is no list (as ai_costs, PROFIT-1)."""
    from services import ai_costs
    if not ai_costs.has_platform_table(session):
        return None
    found = session.execute(text("SELECT max(period) FROM platform_meters WHERE meter = :m AND period <= :p"),
                            {"m": MARK, "p": period}).scalar()
    return str(found) if found else None


def items(session, period: str) -> list:
    source = _source(session, period)
    if source is None:
        return []
    rows = session.execute(text("SELECT meter, value FROM platform_meters WHERE period = :p AND meter LIKE :m"),
                           {"p": source, "m": PREFIX + "%"}).all()
    return sorted(({"name": meter[len(PREFIX):], "pence": int(value or 0)} for meter, value in rows),
                  key=lambda i: i["name"].lower())


def fixed_total(session, period: str) -> tuple:
    """(pence, source) for the month: the list, else the Railway setting."""
    if _source(session, period) is not None:
        return sum(i["pence"] for i in items(session, period)), "list"
    try:
        fixed = int(os.environ.get("PLATFORM_FIXED_COSTS_PENCE", "0") or 0)
    except ValueError:
        fixed = 0
    return max(0, fixed), ("railway setting" if fixed else "none")


def _months_between(earlier: str, later: str) -> int:
    (y1, m1), (y2, m2) = (map(int, earlier.split("-")), map(int, later.split("-")))
    return (y2 - y1) * 12 + (m2 - m1)


def _check_period(period, moment: datetime) -> str:
    from services.metering import period_for
    if not isinstance(period, str) or not PERIOD.match(period):
        refuse("The month must look like 2026-10.")
    current = period_for(moment)
    if period > current:
        refuse("Bills can't be entered for a future month.")
    if _months_between(period, current) > MONTHS_BACK:
        refuse(f"Bills can be corrected up to {MONTHS_BACK} months back.")
    return period


def _check_name(name) -> str:
    name = name.strip() if isinstance(name, str) else ""
    if not NAME.match(name):
        refuse("A bill's name is 1–60 letters, digits, spaces and . - & ( ) /")
    return name


def _materialise(session, period: str, moment: datetime) -> None:
    """Give the month its own list (a copy of what it was showing)."""
    if session.execute(text("SELECT 1 FROM platform_meters WHERE period = :p AND meter = :m"),
                       {"p": period, "m": MARK}).first():
        return
    for item in items(session, period):
        _put(session, period, PREFIX + item["name"], item["pence"], moment)
    _put(session, period, MARK, 1, moment)


def _put(session, period: str, meter: str, value: int, moment: datetime) -> None:
    params = {"p": period, "m": meter, "v": value, "at": moment.isoformat()}
    if not session.execute(text("UPDATE platform_meters SET value = :v, updated_at = :at "
                                "WHERE period = :p AND meter = :m"), params).rowcount:
        session.execute(text("INSERT INTO platform_meters (period, meter, value, updated_at) VALUES (:p, :m, :v, :at)"),
                        params)


def set_item(session, period, name, pence, *, moment: datetime) -> dict:
    period, name = _check_period(period, moment), _check_name(name)
    if isinstance(pence, bool) or not isinstance(pence, int) or not 0 <= pence <= MAX_PENCE:
        refuse("A bill's amount is whole pence, from 0 to £100,000.")
    _materialise(session, period, moment)
    _put(session, period, PREFIX + name, pence, moment)
    return {"period": period, "name": name, "pence": pence}


def remove_item(session, period, name, *, moment: datetime) -> dict:
    period, name = _check_period(period, moment), _check_name(name)
    _materialise(session, period, moment)
    session.execute(text("DELETE FROM platform_meters WHERE period = :p AND meter = :m"),
                    {"p": period, "m": PREFIX + name})
    return {"period": period, "name": name, "removed": True}
