"""AI-1c — the evaluation set behind "Test this model" (docs/AI-1-TICKET.md, M5).

A handful of fixed, synthetic cases per kind of task, each with a check that
says pass or fail and why. Real-shaped data, never a customer's. A run calls
one provider and model directly (never the failover chain, and never trips a
provider for everyone), records its cost as platform `eval`, and saves
nothing else.

Today: Aria's chat (`chat` and `chat_complex`), the tasks whose model Mike is
most likely to change first. Other text tasks get cases when they move onto
the router (AI-1d).
"""
import json
import re
import time

SYSTEM = ("You are Aria, the AI assistant for a small UK trades business. Use the tools to look things up. "
          "Never invent prices, amounts or dates: if you don't have them, say so and ask. Keep answers short.")

TOOLS = [
    {"type": "function", "function": {
        "name": "get_invoices", "description": "List the business's invoices, optionally by status",
        "parameters": {"type": "object", "properties": {"status": {"type": "string",
                                                                    "enum": ["overdue", "unpaid", "paid", "all"]}}}}},
    {"type": "function", "function": {
        "name": "get_calendar_events", "description": "List calendar events between two dates",
        "parameters": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}}}}},
]


# Money in an answer: £1,250 / £1250.00 / 4500 GBP / 4,500 pounds / 4500 quid.
_MONEY = re.compile(r"£\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:gbp|pounds?|quid)\b", re.I)


def _amounts(text) -> set:
    out = set()
    for m in _MONEY.finditer(text or ""):
        raw = (m.group(1) or m.group(2)).replace(",", "")
        try:
            out.add(round(float(raw), 2))
        except ValueError:
            continue
    return out


def _calls(name, arguments=None):
    """It looked `name` up, with valid arguments (and these, if given), and did
    nothing else; Codex AI-1c review 1, finding 4."""
    def check(reply):
        names = [c["name"] for c in reply.tool_calls]
        if name not in names:
            return False, f"expected it to look up {name}, it {'called ' + ', '.join(names) if names else 'answered without looking'}"
        call = next(c for c in reply.tool_calls if c["name"] == name)
        try:
            args = json.loads(call["arguments"] or "{}")
        except (TypeError, ValueError):
            return False, f"its {name} arguments were not valid JSON"
        for k, v in (arguments or {}).items():
            if args.get(k, v) != v:
                return False, f"it looked up {name} with {k}={args.get(k)!r}, expected {v!r}"
        return True, ""
    return check


def _no_invented_price(reply):
    """An answer, in words, with no amount of money in it: there is no price
    to quote, whatever else it does."""
    if not (reply.content or "").strip():
        return False, "it gave no answer"
    found = _amounts(reply.content)
    return (not found, f"it invented a price (£{sorted(found)[0]:,.2f})" if found else "")


def _short_hello(reply):
    text = (reply.content or "").strip()
    return (0 < len(text) <= 300 and not reply.tool_calls, "expected a short greeting")


GROUNDED = {1250.0, 750.0, 500.0}


def _uses_the_result(reply):
    """It states the £1,250 it looked up and no amount that wasn't in the data."""
    found = _amounts(reply.content)
    if 1250.0 not in found:
        return False, "expected it to state the £1,250 from the invoices it looked up"
    stray = found - GROUNDED
    return (not stray, f"it stated an amount that wasn't in the data (£{sorted(stray)[0]:,.2f})" if stray else "")


def _msgs(*turns):
    return [{"role": "system", "content": SYSTEM}, *turns]


CASES = {
    "chat": [
        {"name": "Looks up overdue invoices", "messages": _msgs({"role": "user", "content": "Which invoices are overdue?"}),
         "check": _calls("get_invoices", {"status": "overdue"})},
        {"name": "Looks up the calendar", "messages": _msgs({"role": "user", "content": "What's on my calendar tomorrow?"}),
         "check": _calls("get_calendar_events")},
        {"name": "Never invents a price", "messages": _msgs(
            {"role": "user", "content": "How much should I charge for a bathroom refit?"}),
         "check": _no_invented_price},
        {"name": "Keeps it short", "messages": _msgs({"role": "user", "content": "Say hello in one short sentence."}),
         "check": _short_hello},
        {"name": "Uses what it looked up", "messages": _msgs(
            {"role": "user", "content": "How much am I owed on overdue invoices?"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_eval_1", "type": "function",
                 "function": {"name": "get_invoices", "arguments": json.dumps({"status": "overdue"})}}]},
            {"role": "tool", "tool_call_id": "call_eval_1", "content": json.dumps(
                {"invoices": [{"number": "INV-101", "customer": "Harbour Lettings", "owed": "£750.00", "days_overdue": 12},
                              {"number": "INV-104", "customer": "Northgate Estates", "owed": "£500.00", "days_overdue": 5}],
                 "total_owed": "£1,250.00"})}),
         "check": _uses_the_result},
    ],
}
KIND_OF_TASK = {"chat": "chat", "chat_complex": "chat"}


def has_cases(task: str) -> bool:
    return KIND_OF_TASK.get(task) in CASES


# Codex AI-1c review 1, findings 2 and 3: a test spends real money, so it is
# admitted like any other non-essential AI (the profit guard), its most
# possible cost must fit a cap, only one runs at a time, at most a few an hour,
# and the whole of it has a deadline.
MAX_RUN_PENCE = 300            # both models, every case, at their most possible cost (Opus v GPT-5: £1.95)
RUNS_PER_HOUR = 10
CALL_SECONDS = 25.0
DEADLINE_SECONDS = 150.0
_running = __import__("threading").Lock()
_recent: list = []


def worst_pence(task: str, provider: str, model: str) -> float:
    from services import ai_chat
    return sum(ai_chat._pence(provider, model, ai_chat._worst(provider, model, c["messages"], TOOLS))
               for c in CASES[KIND_OF_TASK[task]])


def admit(task: str, pairs) -> None:
    """Raise ActionRefused when a test may not run now; else hold the one slot
    (release with `done()`)."""
    from services import profit_guard
    from services.aria_actions import ActionRefused
    if not profit_guard.permits("eval"):
        raise ActionRefused(409, "Testing is paused while AI spending is held by the profit guard")
    worst = sum(worst_pence(task, p, m) for p, m in pairs)
    if worst > MAX_RUN_PENCE:
        raise ActionRefused(422, f"This test could cost up to £{worst / 100:.2f}, over the £{MAX_RUN_PENCE / 100:.2f} "
                                 "limit for one test")
    now = time.monotonic()
    _recent[:] = [t for t in _recent if now - t < 3600]
    if len(_recent) >= RUNS_PER_HOUR:
        raise ActionRefused(429, f"At most {RUNS_PER_HOUR} tests an hour: try again shortly")
    if not _running.acquire(blocking=False):
        raise ActionRefused(409, "A test is already running: wait for it to finish")
    _recent.append(now)


def done() -> None:
    try:
        _running.release()
    except RuntimeError:
        pass


def run(task: str, provider: str, model: str, *, deadline: float = None) -> dict:
    """Every case on one provider and model. Never raises for a provider
    failure: the case fails with the provider's reason. Cases not started
    before `deadline` (time.monotonic()) are reported as not run."""
    from services import ai_chat, ai_router
    cases = CASES[KIND_OF_TASK[task]]
    results, pence = [], 0.0
    for case in cases:
        started = time.monotonic()
        if deadline is not None and started >= deadline:
            results.append({"name": case["name"], "passed": False, "why": "not run: the test ran out of time",
                            "answer": "", "seconds": 0.0, "pence": 0.0})
            continue
        worst = ai_chat._worst(provider, model, case["messages"], TOOLS)
        try:
            reply, usage = ai_chat._ADAPTERS[provider](provider, model, case["messages"], TOOLS, CALL_SECONDS, None)
            if getattr(reply, "truncated", False):
                raise ai_router.ProviderError("the answer was cut off", usage=usage)
            tokens, estimated = ai_chat._tokens(usage), False
            ok, why = case["check"](reply)
            answer = (reply.content or "")[:400] or ", ".join(f"looks up {c['name']}" for c in reply.tool_calls)
        except ai_router.ProviderError as exc:
            tokens, estimated = ai_chat._tokens(exc.usage), True
            ok, why, answer = False, f"the provider failed: {exc}", ""
            if isinstance(exc, ai_chat.Rejected):
                tokens = (0, 0)           # refused before any work: not billed
        if tokens is None:                # no usage reported: its most possible cost, marked estimated
            tokens, estimated = worst, True
        cost = ai_chat._pence(provider, model, tokens) if tokens != (0, 0) else 0.0
        if tokens != (0, 0):
            ai_chat._record(None, purpose="eval", provider=provider, model=model, input_tokens=tokens[0],
                            output_tokens=tokens[1], estimated=estimated)
        pence += cost
        results.append({"name": case["name"], "passed": bool(ok), "why": "" if ok else why, "answer": answer,
                        "seconds": round(time.monotonic() - started, 2), "pence": round(cost, 3)})
    return {"model": f"{provider}/{model}", "cases": len(results), "passed": sum(r["passed"] for r in results),
            "pence": round(pence, 3), "results": results}
