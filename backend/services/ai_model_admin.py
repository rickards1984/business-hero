"""AI-1c — Mike's admin page for Aria's models (docs/AI-1-TICKET.md, M2).

One row per task: its default, Mike's saved choice (who, when, the one
before), what is actually used now, this month's spend, and every model it
could use, with its price or the reason it can't. Choosing validates each
entry (services.ai_models.why_unusable) and refuses with the reason; every
change keeps the previous chain for Revert. "Test this model" (services.
ai_eval) runs the task's evaluation set on the candidate and on what the task
uses now, side by side, and saves nothing.

Platform admins only (admin_ai_api). Provider keys are never shown: only
whether each is set.
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from services import ai_models
from services.aria_actions import ActionRefused

MAX_CHAIN = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pg(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _pairs(chain) -> list:
    return [{"provider": p, "model": m} for p, m in chain]


def _row(session, task: str):
    row = session.execute(text("SELECT chain, changed_by, changed_at, previous FROM ai_model_choices WHERE task = :t"),
                          {"t": task}).first()
    if row is None:
        return None

    def load(value):
        if value is None:
            return None
        return json.loads(value) if isinstance(value, str) else value
    return {"chain": load(row[0]), "changed_by": str(row[1]) if row[1] else None,
            "changed_at": str(row[2]) if row[2] else None, "previous": load(row[3])}


def _spent_purpose(session, purpose: str, period: str) -> float:
    pattern = "ai\\_pence:" + purpose.replace("_", "\\_") + ":%"
    total = 0.0
    for table in ("usage_meters", "platform_meters"):
        try:
            with session.begin_nested():
                total += float(session.execute(text(
                    f"SELECT COALESCE(SUM(value), 0) FROM {table} WHERE period = :p AND meter LIKE :m ESCAPE '\\'"),
                    {"p": period, "m": pattern}).scalar() or 0)
        except Exception:
            continue                      # a table this database doesn't have
    return total


def _spend(session, task: str, period: str) -> dict:
    """This month's spend for the ledger purposes the task's calls are
    recorded under, and which other tasks share them (Codex AI-1c review 1,
    finding 5: purposes are not task names, and some are shared)."""
    t = ai_models.TASKS[task]
    if not t.ledger:
        return {"spent_pence": None, "recorded_as": [], "shared_with": []}
    shared = sorted({other.label for name, other in ai_models.TASKS.items()
                     if name != task and other.ledger and set(other.ledger) & set(t.ledger)})
    total = sum(_spent_purpose(session, p, period) for p in t.ledger)
    return {"spent_pence": round(total, 2), "recorded_as": list(t.ledger), "shared_with": shared}


def _options(task: str) -> list:
    from services import ai_costs
    t = ai_models.TASKS[task]
    seen, out = set(), []
    candidates = list(ai_costs.known_models()) + [tuple(x) for x in t.default]
    if t.compatible:
        candidates += [("openai", m) for m in t.compatible]
    for provider, model in candidates:
        if (provider, model) in seen:
            continue
        seen.add((provider, model))
        why = ai_models.why_unusable(task, provider, model)
        if t.compatible is not None and model not in t.compatible:
            continue                      # never offered: this task can't use it
        try:
            price = ai_costs.price(provider, model)
            price_in, price_out = price[0], price[1]
        except ai_costs.Unpriced:
            price_in = price_out = None
        on = ai_models.retires_on(provider, model)
        out.append({"provider": provider, "model": model, "usable": why is None, "reason": why,
                    "price_in_pence": price_in, "price_out_pence": price_out,
                    "retires_on": on.isoformat() if on else None})
    return sorted(out, key=lambda o: (not o["usable"], o["provider"], o["model"]))


def overview(session, moment: Optional[datetime] = None) -> dict:
    from services.metering import period_for
    period = period_for(moment or _now())
    from services import ai_eval
    tasks = []
    for name, t in ai_models.TASKS.items():
        row = _row(session, name)
        tasks.append({
            "task": name, "label": t.label, "kind": t.kind, "openai_only": t.openai_only,
            "compatible": list(t.compatible) if t.compatible else None,
            "default": _pairs(ai_models.default(name)),
            "choice": row["chain"] if row else None,
            "previous": row["previous"] if row else None,
            "changed_by": row["changed_by"] if row else None,
            "changed_at": row["changed_at"] if row else None,
            "effective": _pairs(ai_models.resolve(name)),
            "max_chain": t.max_chain,
            # HK-3: anything the job is set to use that OpenAI is retiring.
            "retiring": [{"provider": p, "model": m, "retires_on": ai_models.retires_on(p, m).isoformat()}
                         for p, m in ((e["provider"], e["model"]) for e in (row["chain"] if row else []))
                         if ai_models.retires_on(p, m)],
            **_spend(session, name, period),
            "testable": ai_eval.has_cases(name),
            "options": _options(name),
        })
    session.rollback()
    return {"period": period, "tasks": tasks,
            "providers": {p: bool(os.environ.get(k)) for p, k in ai_models.KEYS.items()}}


def _validate(task: str, chain) -> list:
    if task not in ai_models.TASKS:
        raise ActionRefused(404, f"Unknown task {task}")
    if not isinstance(chain, list) or not chain:
        raise ActionRefused(422, "Choose at least one model")
    limit = ai_models.TASKS[task].max_chain
    if len(chain) > limit:
        raise ActionRefused(422, "This job still calls OpenAI directly, so it uses one model and no fallbacks for now"
                            if limit == 1 else f"Choose at most {limit} models (a first choice and its fallbacks)")
    pairs = []
    for entry in chain:
        if not (isinstance(entry, dict) and isinstance(entry.get("provider"), str) and entry["provider"]
                and isinstance(entry.get("model"), str) and entry["model"].strip()):
            raise ActionRefused(422, "Each entry needs a provider and a model")
        pair = (entry["provider"].strip(), entry["model"].strip())
        if pair in pairs:
            raise ActionRefused(422, f"{pair[0]}/{pair[1]} is listed twice")
        why = ai_models.why_unusable(task, *pair)
        if why:
            raise ActionRefused(422, why)
        pairs.append(pair)
    return pairs


def _write(session, task: str, chain, previous, user_id) -> None:
    cast = "CAST(:c AS jsonb)" if _pg(session) else ":c"
    prev = "CAST(:p AS jsonb)" if _pg(session) else ":p"
    session.execute(text("DELETE FROM ai_model_choices WHERE task = :t"), {"t": task})
    session.execute(text(f"INSERT INTO ai_model_choices (task, chain, changed_by, changed_at, previous) "
                         f"VALUES (:t, {cast}, :u, :at, {prev})"),
                    {"t": task, "c": json.dumps(chain), "u": str(user_id) if user_id else None, "at": _now(),
                     "p": json.dumps(previous) if previous is not None else None})


def _lock(session, task: str) -> None:
    if _pg(session):                      # two admins saving the same task queue, never interleave
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext('ai_model_choices:' || :t))"), {"t": task})


def _done(session) -> None:
    session.commit()
    ai_models.invalidate()                # takes effect at once, not after the minute's cache


def choose(session, task: str, chain, user_id) -> dict:
    pairs = _validate(task, chain)
    _lock(session, task)
    current = _row(session, task)
    _write(session, task, _pairs(pairs), current["chain"] if current else None, user_id)
    _done(session)
    return {"task": task, "choice": _pairs(pairs)}


def revert(session, task: str, user_id) -> dict:
    if task not in ai_models.TASKS:
        raise ActionRefused(404, f"Unknown task {task}")
    _lock(session, task)
    current = _row(session, task)
    if current is None:
        raise ActionRefused(409, "Nothing to revert: this task already uses its default")
    if current["previous"]:
        _write(session, task, current["previous"], current["chain"], user_id)
    else:
        session.execute(text("DELETE FROM ai_model_choices WHERE task = :t"), {"t": task})
    _done(session)
    after = _row(session, task)
    session.rollback()
    return {"task": task, "choice": after["chain"] if after else None}


def reset(session, task: str, user_id) -> dict:
    """Back to the default, kept as a choice so Revert can undo it."""
    if task not in ai_models.TASKS:
        raise ActionRefused(404, f"Unknown task {task}")
    _lock(session, task)
    current = _row(session, task)
    _write(session, task, _pairs(ai_models.default(task)), current["chain"] if current else None, user_id)
    _done(session)
    return {"task": task, "choice": _pairs(ai_models.default(task))}


def test(session, task: str, provider: str, model: str) -> dict:
    """Run the task's evaluation set on the candidate and on the model the
    task uses now. Saves nothing; records its own cost as platform `eval`."""
    from services import ai_eval
    if task not in ai_models.TASKS:
        raise ActionRefused(404, f"Unknown task {task}")
    if not ai_eval.has_cases(task):
        raise ActionRefused(422, "This job has no test set yet, so it can be chosen but not tested")
    why = ai_models.why_unusable(task, provider, model)
    if why:
        raise ActionRefused(422, why)
    session.rollback()
    current = ai_models.resolve(task)[0]
    ai_eval.admit(task, [(provider, model), current])
    try:
        import time
        deadline = time.monotonic() + ai_eval.DEADLINE_SECONDS
        return {"task": task, "candidate": ai_eval.run(task, provider, model, deadline=deadline),
                "current": ai_eval.run(task, *current, deadline=deadline)}
    finally:
        ai_eval.done()
