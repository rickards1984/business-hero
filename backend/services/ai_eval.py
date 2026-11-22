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


def _calls(name):
    def check(reply):
        names = [c["name"] for c in reply.tool_calls]
        return (name in names, f"expected it to look up {name}, it {'called ' + ', '.join(names) if names else 'answered without looking'}")
    return check


def _no_invented_price(reply):
    found = re.search(r"£\s?\d", reply.content or "")
    if reply.tool_calls:
        return True, ""
    return (not found, f"it invented a price ({found.group(0)}…)" if found else "")


def _short_hello(reply):
    text = (reply.content or "").strip()
    return (0 < len(text) <= 300 and not reply.tool_calls, "expected a short greeting")


def _uses_the_result(reply):
    return ("1,250" in (reply.content or "") or "1250" in (reply.content or ""),
            "expected it to use the £1,250 from the invoices it looked up")


def _msgs(*turns):
    return [{"role": "system", "content": SYSTEM}, *turns]


CASES = {
    "chat": [
        {"name": "Looks up overdue invoices", "messages": _msgs({"role": "user", "content": "Which invoices are overdue?"}),
         "check": _calls("get_invoices")},
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


def run(task: str, provider: str, model: str) -> dict:
    """Every case on one provider and model. Never raises for a provider
    failure: the case fails with the provider's reason."""
    from services import ai_chat, ai_router
    cases = CASES[KIND_OF_TASK[task]]
    results, pence = [], 0.0
    for case in cases:
        started = time.monotonic()
        worst = ai_chat._worst(provider, model, case["messages"], TOOLS)
        try:
            reply, usage = ai_chat._ADAPTERS[provider](provider, model, case["messages"], TOOLS, 60.0, None)
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
