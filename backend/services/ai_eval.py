"""AI-1c — the evaluation set behind "Test this model" (docs/AI-1-TICKET.md, M5).

A handful of fixed, synthetic cases per kind of task, each with a check that
says pass or fail and why. Real-shaped data, never a customer's. A run calls
one provider and model directly (never the failover chain, and never trips a
provider for everyone), records its cost as platform `eval`, and saves
nothing else.

Sets: Aria's chat (`chat` and `chat_complex`), and since AI-1d the help
assistant (`support`) and the briefings (`briefing`). Other text tasks can be
chosen without a test set.
"""
import json
import re
import time
from types import SimpleNamespace
from typing import Optional

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
        if not isinstance(args, dict):
            return False, f"its {name} arguments were not an object"
        for k, v in (arguments or {}).items():
            if args.get(k) != v:                # missing counts as wrong (Codex AI-1c review 2)
                return False, f"it looked up {name} with {k}={args.get(k)!r}, expected {v!r}"
        if _amounts(reply.content):
            return False, "it stated an amount before looking anything up"
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


TOTAL = 1250.0
OWED = {"harbour": 750.0, "northgate": 500.0}
GROUNDED = {TOTAL, *OWED.values()}
# Sentences end at ; a full stop (not a decimal point) or a new line; within
# one, clauses split at a comma, colon, dash or slash with spaces, "and" or
# "while". "£1,250.00" and "10:30" stay whole.
_SENTENCES = re.compile(r";|\.(?!\d)|\n")
_CLAUSES = re.compile(r",\s|:\s|\s[—–-]\s|\s?/\s?|\band\b|\bwhile\b", re.I)
_TOTAL_WORDS = re.compile(r"\b(total|altogether|in all|overall|combined|between them)\b", re.I)


_NOT_NAMES = re.compile(r"\bbusiness hero\b", re.I)     # the product's name is not the Business plan


def _named(text, names=None) -> list:
    """The names (customers, or plans) mentioned as whole words, in order."""
    names = OWED if names is None else names
    low = _NOT_NAMES.sub(" ", (text or "").lower())
    found = [(m.start(), n) for n in names for m in [re.search(rf"\b{re.escape(n)}\b", low)] if m]
    return [n for _, n in sorted(found)]


def _in_order(text) -> list:
    """Amounts in the order they appear."""
    out = []
    for m in _MONEY.finditer(text or ""):
        try:
            out.append(round(float((m.group(1) or m.group(2)).replace(",", "")), 2))
        except ValueError:
            continue
    return out


def _attribution_error(sentence, owed=None, total=None) -> Optional[str]:
    """Why this sentence gives a name the wrong amount, or None. The total
    counts with one name only beside that name's own amount, or in a sentence
    naming several, and with a word that says it's the total ("£750 of the
    £1,250 total"), never as one name's amount (Codex AI-1d review 1, finding 8)."""
    owed = OWED if owed is None else owed
    total = TOTAL if total is None and owed is OWED else total
    if "respectively" in sentence.lower():
        names = _named(sentence, owed)
        amounts = [a for a in _in_order(sentence) if a != total]
        if names and len(names) == len(amounts):
            for name, amount in zip(names, amounts):
                if owed[name] != amount:
                    return f"it gave {name.title()} the wrong amount (£{amount:,.2f})"
            return None
    shared = len(_named(sentence, owed)) > 1     # "Harbour and Northgate owe £1,250 between them"
    for clause in _CLAUSES.split(sentence):
        named = _named(clause, owed)
        amounts = _amounts(clause)
        if not named or not amounts:
            continue
        if len(named) > 1:
            if amounts - {total}:
                return "it gave two amounts together, so neither can be checked"
            continue
        own = owed[named[0]]
        totalled = total is not None and (own in amounts or shared) and _TOTAL_WORDS.search(clause)
        allowed = {own} | ({total} if totalled else set())
        wrong = amounts - allowed
        if wrong:
            return f"it gave {named[0].title()} the wrong amount (£{sorted(wrong)[0]:,.2f})"
    return None


def _uses_the_result(reply):
    """It states the £1,250 it looked up, no amount that wasn't in the data,
    and no customer with another customer's balance or the total (Codex
    AI-1c reviews 2 and 3)."""
    found = _amounts(reply.content)
    if TOTAL not in found:
        return False, "expected it to state the £1,250 from the invoices it looked up"
    stray = found - GROUNDED
    if stray:
        return False, f"it stated an amount that wasn't in the data (£{sorted(stray)[0]:,.2f})"
    for sentence in _SENTENCES.split(reply.content or ""):
        why = _attribution_error(sentence)
        if why:
            return False, why
    return True, ""


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

# ------------------------------------------- AI-1d: the help assistant ---
# A shortened form of support_api's prompt: the same rules (knowledge base
# only, [ESCALATE] for a person, the category tag) on a two-article base.

PLAN_PRICES = {69.0, 129.0, 269.0}
SUPPORT_SYSTEM = (
    "You are the Business Hero help assistant. Answer only from the knowledge base, in British English, "
    "concisely. If the answer isn't in the knowledge base, say so and offer to pass it to the team; never "
    "make up a policy or price. If the user asks for a person, include [ESCALATE].\n"
    "At the end of EVERY response add a classification tag on a new line in this format:\n"
    "[CATEGORY: how-to] [CONFIDENCE: 0.9]\n"
    "Categories: bug, feature-request, how-to, billing, integration, account, general\n\n"
    "KNOWLEDGE BASE:\n"
    "### Connecting Gmail\nGo to Settings → Email and click Connect Gmail, then approve access in the Google window.\n"
    "### Plans\nStarter is £69, Pro £129 and Business £269 a month, billed monthly.")
PLANS = {"starter": 69.0, "pro": 129.0, "business": 269.0}
_HEDGE = re.compile(r"(isn't|aren't|is not|are not|not) (in|covered|something|part of|listed)|"
                    r"(don't|do not) (know|have)|(can't|cannot|can not|unable to|not able to) (confirm|say|tell|answer)|"
                    r"not sure|no information|check with|confirm (it|this|that) for you", re.I)
_PROMISE = re.compile(r"^\s*yes\b|\bfull refund\b|\bpro-?rata\b|\bpartial refund\b|\bwill be refunded\b|"
                      r"\brefunds? (are|is) (available|given|issued|processed|offered)\b|\byou('ll| will) (get|receive)\b", re.I)
_TAG = re.compile(r"\[CATEGORY:\s*[a-z-]+\]\s*\[CONFIDENCE:\s*[\d.]+\]", re.I)
_HANDOFF = re.compile(r"\b(team|person|human|colleague|escalat\w*|pass (it|this) on)\b", re.I)


def _support(messages_text):
    return [{"role": "system", "content": SUPPORT_SYSTEM}, {"role": "user", "content": messages_text}]


def _tagged(reply):
    return (bool(_TAG.search(reply.content or "")), "it left off the [CATEGORY: …] [CONFIDENCE: …] tag")


def _all(*checks):
    def check(reply):
        for c in checks:
            ok, why = c(reply)
            if not ok:
                return False, why
        return True, ""
    return check


def _says(*words):
    def check(reply):
        low = (reply.content or "").lower()
        missing = [w for w in words if w.lower() not in low]
        return (not missing, f"expected it to mention {', '.join(missing)}")
    return check


def _only_amounts(allowed, *, need=None):
    def check(reply):
        found = _amounts(reply.content)
        if need is not None and need not in found:
            return False, f"expected it to state £{need:,.2f}"
        stray = found - set(allowed)
        return (not stray, f"it stated an amount that isn't in what it was given (£{sorted(stray)[0]:,.2f})"
                if stray else "")
    return check


def _escalates(reply):
    return ("[ESCALATE]" in (reply.content or ""), "expected [ESCALATE] when asked for a person")


def _hands_off(reply):
    """It says it doesn't know, promises nothing, and offers the team: naming
    "the team" while promising a refund is not a handoff (review 1, finding 3)."""
    text = reply.content or ""
    if _PROMISE.search(text):
        return False, "it promised a refund policy the knowledge base doesn't have"
    if not _HEDGE.search(text):
        return False, "expected it to say the answer isn't in its guides"
    return (bool(_HANDOFF.search(text)), "expected it to offer the team, not to guess")


def _plans_right(reply):
    """Each plan named with its own price, never another plan's."""
    for sentence in _SENTENCES.split(reply.content or ""):
        why = _attribution_error(sentence, PLANS)
        if why:
            return False, why
    return True, ""


CASES["support"] = [
    {"name": "Answers from the knowledge base", "messages": _support("How do I connect Gmail?"),
     "check": _all(_says("settings", "email"), _tagged)},
    {"name": "Hands over when asked for a person", "messages": _support("I'd like to talk to a real person please."),
     "check": _escalates},
    {"name": "Never invents a policy", "messages": _support("Do I get a refund if I cancel halfway through a month?"),
     "check": _all(_only_amounts(PLAN_PRICES), _hands_off)},
    {"name": "Quotes the price it was given", "messages": _support("How much is the Pro plan?"),
     "check": _all(_only_amounts(PLAN_PRICES, need=129.0), _plans_right, _tagged)},
]


# ------------------------------------------------- AI-1d: the briefings ---
# Shortened forms of briefing_generator's prompts, on a fixed week.

WEEK = {"period": "week to 21 Nov 2026", "revenue": "£4,200.00", "revenue_last_week": "£3,500.00",
        "overdue_invoices": [{"customer": "Harbour Lettings", "owed": "£750.00", "days_overdue": 12}],
        "calls": 14, "missed_calls": 2, "emails_needing_reply": 3}
WEEK_AMOUNTS = {4200.0, 3500.0, 750.0}
PULSE_SYSTEM = ("You produce a very short daily business pulse for Mike at \"New Body\".\n"
                "RULES:\n- Maximum 800 characters\n- Use British English\n"
                "- Start with \"🌅 Good morning, Mike! Here's your daily pulse:\"\n"
                "- List only the most important 4-5 data points\n- End with \"Anything you'd like me to handle?\"\n"
                "- Only mention things that need attention or are noteworthy")
WEEKLY_SYSTEM = ("You are the AI business intelligence analyst for \"New Body\". You produce a concise, actionable "
                 "weekly CEO briefing for Mike.\nRULES:\n- Use British English\n- Lead with what matters most\n"
                 "- Include specific numbers and percentage changes against last period (↑12% or ↓5%)\n"
                 "- NEVER give financial advice\n- Keep the briefing under 3500 characters\n"
                 "After the briefing write ===JSON=== on its own line, then one JSON object: "
                 '{"observations": [...], "suggestions": [...], "action_options": '
                 '[{"number": 1, "label": "...", "type": "...", "config": {}}]} with 3 to 5 action_options.')


def _pulse_shape(reply):
    text = (reply.content or "").strip()
    if not text.startswith("🌅 Good morning"):
        return False, "expected it to open with the morning greeting"
    return (len(text) <= 800, f"it ran to {len(text)} characters (the limit is 800)")


def _weekly_shape(reply):
    content = reply.content or ""
    if "===JSON===" not in content:
        return False, "it left out the ===JSON=== section the app reads its actions from"
    text, _, rest = content.partition("===JSON===")
    if len(text.strip()) > 3500:
        return False, f"the briefing ran to {len(text.strip())} characters (the limit is 3,500)"
    try:
        from services.ai_text import strip_fences
        data = json.loads(strip_fences(rest))
    except ValueError:
        return False, "its JSON section could not be read"
    if len(text.strip()) < 40:
        return False, "there was no briefing before the ===JSON=== section"
    options = data.get("action_options") if isinstance(data, dict) else None
    if not isinstance(options, list) or not 3 <= len(options) <= 5:
        return False, "expected 3 to 5 action options"
    for option in options:                     # what the WhatsApp reply menu reads (review 1, finding 4)
        if not (isinstance(option, dict) and isinstance(option.get("number"), int)
                and isinstance(option.get("label"), str) and option["label"].strip()):
            return False, "an action option is missing its number or label"
    return True, ""


_UP = re.compile(r"↑|\bup\b|\brise\b|\brose\b|\bincreas|\bgrew\b|\bgrowth\b|\bhigher\b|\bimprov", re.I)
_DOWN = re.compile(r"↓|\bdown\b|\bfell\b|\bfall|\bdrop|\bdecreas|\blower\b|\bdeclin", re.I)
_BEFORE = re.compile(r"(last week|previous week|prior week|week before|\bfrom|against|compared (?:to|with)|\bvs\.?)"
                     r"['’]?s?\s*(?:revenue\s*)?(?:of\s*)?£\s?(\d[\d,]*(?:\.\d+)?)", re.I)


def _weekly_grounded(reply):
    """The right amounts, revenue UP 20%, and last week's figure as last
    week's (review 1, finding 4: "fell 20% to £4,200 from £3,500" passed)."""
    text = (reply.content or "").partition("===JSON===")[0]
    ok, why = _only_amounts(WEEK_AMOUNTS, need=4200.0)(SimpleNamespace(content=text))
    if not ok:
        return ok, why
    change = [s_ for s_ in _SENTENCES.split(text) if "20%" in s_]
    if not change:
        return False, "expected revenue up 20% on last week (£4,200 against £3,500)"
    if any(_DOWN.search(s_) for s_ in change) or not any(_UP.search(s_) for s_ in change):
        return False, "it got the direction of the change wrong: revenue went up"
    for m in _BEFORE.finditer(text):
        if round(float(m.group(2).replace(",", "")), 2) != 3500.0:
            return False, f"it gave last week's revenue as £{float(m.group(2).replace(',', '')):,.2f}, not £3,500"
    return True, ""


def _data_prompt(intro):
    return intro + json.dumps(WEEK, indent=2)


CASES["briefing"] = [
    {"name": "Daily pulse: short, and opens right", "max_tokens": 400, "messages": [
        {"role": "system", "content": PULSE_SYSTEM},
        {"role": "user", "content": _data_prompt("Generate a daily pulse from this data:\n")}],
     "check": _all(_pulse_shape, _only_amounts(WEEK_AMOUNTS))},
    {"name": "Daily pulse: flags the overdue invoice", "max_tokens": 400, "messages": [
        {"role": "system", "content": PULSE_SYSTEM},
        {"role": "user", "content": _data_prompt("Generate a daily pulse from this data:\n")}],
     "check": _all(_says("harbour"), _only_amounts(WEEK_AMOUNTS, need=750.0))},
    {"name": "Weekly: the shape the app reads", "max_tokens": 2000, "messages": [
        {"role": "system", "content": WEEKLY_SYSTEM},
        {"role": "user", "content": _data_prompt("Write this week's briefing from this data:\n")}],
     "check": _weekly_shape},
    {"name": "Weekly: right numbers and change", "max_tokens": 2000, "messages": [
        {"role": "system", "content": WEEKLY_SYSTEM},
        {"role": "user", "content": _data_prompt("Write this week's briefing from this data:\n")}],
     "check": _weekly_grounded},
]

KIND_OF_TASK = {"chat": "chat", "chat_complex": "chat", "support": "support", "briefing": "briefing"}
# Per set: the tools offered (chat only) and the output limit (None: chat's own).
SET_TOOLS = {"chat": TOOLS, "support": None, "briefing": None}
SET_MAX_TOKENS = {"chat": None, "support": 800, "briefing": 2000}   # a case's own "max_tokens" wins: the
# site's real limit, so an answer production would cut off fails here too (review 1, finding 5)


def has_cases(task: str) -> bool:
    return KIND_OF_TASK.get(task) in CASES


def _set(task: str):
    kind = KIND_OF_TASK[task]
    return CASES[kind], SET_TOOLS[kind], SET_MAX_TOKENS[kind]


def _worst(provider, model, messages, tools, max_tokens) -> tuple:
    from services import ai_chat, ai_text
    if max_tokens is None:
        return ai_chat._worst(provider, model, messages, tools)
    return ai_text._worst(provider, model, messages, max_tokens)


def _ask(provider, model, messages, tools, seconds, max_tokens):
    from services import ai_chat
    if max_tokens is None:                  # chat: exactly the call Aria's chat makes
        return ai_chat._ADAPTERS[provider](provider, model, messages, tools, seconds, None)
    return ai_chat._ADAPTERS[provider](provider, model, messages, None, seconds, None, max_tokens=max_tokens)


# Codex AI-1c review 1, findings 2 and 3: a test spends real money, so it is
# admitted like any other non-essential AI (the profit guard), its most
# possible cost must fit a cap, only one runs at a time, at most a few an hour,
# and the whole of it has a deadline.
MAX_RUN_PENCE = 300            # both models, every case, at their most possible cost (Opus v GPT-5: £1.95)
RUNS_PER_HOUR = 10
CALL_SECONDS = 25.0
MIN_CALL_SECONDS = 3.0         # a call that would be cut short before it can answer isn't started
DEADLINE_SECONDS = 150.0       # every call ends by then: each call's timeout is what's left
_running = __import__("threading").Lock()
_window = __import__("threading").Lock()  # the hourly list, read and written as one step
_recent: list = []


def worst_pence(task: str, provider: str, model: str) -> float:
    from services import ai_chat
    cases, tools, max_tokens = _set(task)
    return sum(ai_chat._pence(provider, model, _worst(provider, model, c["messages"], tools,
                                                      c.get("max_tokens", max_tokens)))
               for c in cases)


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
    with _window:
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
    from services import ai_chat, ai_router, profit_guard
    cases, tools, max_tokens = _set(task)
    results, pence = [], 0.0
    for case in cases:
        held = not profit_guard.permits("eval")
        started = time.monotonic()            # after the guard's query, so its time counts (review 3)
        seconds = CALL_SECONDS if deadline is None else min(CALL_SECONDS, deadline - started)
        skip = ("not run: AI spending is now held by the profit guard" if held
                else "not run: the test ran out of time" if seconds < MIN_CALL_SECONDS
                else None)
        if skip:
            results.append({"name": case["name"], "passed": False, "why": skip,
                            "answer": "", "seconds": 0.0, "pence": 0.0})
            continue
        limit = case.get("max_tokens", max_tokens)
        worst = _worst(provider, model, case["messages"], tools, limit)
        try:
            reply, usage = _ask(provider, model, case["messages"], tools, seconds, limit)
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
