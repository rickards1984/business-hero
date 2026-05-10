"""
Per-domain data loaders for the Executive Board Meeting prep service.

Each loader exposes a `gather()` function that takes:
  - business_id (str)
  - period (dict from executive_meeting_scheduling.compute_period_boundaries)
  - session (sqlmodel.Session — read-only single session shared across loaders)

…and returns a structured dict matching its slot in the PrepData schema.

A loader MUST NOT raise. On failure it returns its standard shape with
`available=false` and an `errors` list, so the orchestrator can continue.
"""

from . import (
    calendar as calendar_loader,
    calls as calls_loader,
    emails as emails_loader,
    financial as financial_loader,
    goals_actions as goals_actions_loader,
    invoices as invoices_loader,
    last_meeting as last_meeting_loader,
    quotes as quotes_loader,
    tasks as tasks_loader,
)

__all__ = [
    "calendar_loader",
    "calls_loader",
    "emails_loader",
    "financial_loader",
    "goals_actions_loader",
    "invoices_loader",
    "last_meeting_loader",
    "quotes_loader",
    "tasks_loader",
]
