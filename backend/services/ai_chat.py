"""AI-1b — Aria's chat on the switchboard (docs/AI-1-TICKET.md, M3 and M4).

`pick_task` chooses `chat` (everyday) or `chat_complex` (money, analysis,
planning, long conversations, many tool rounds, or "Think harder") by rules,
never by another AI call.

`turn` makes ONE round of the conversation — the model's next message, which
may ask for tools — on the first provider in the task's chain that answers
(services.ai_models.resolve). Aria's tools are written in OpenAI's format;
for Anthropic the conversation and tools are translated to its Messages API
and the reply translated back, so a conversation can move between providers
mid-turn. A provider that fails (outage, rate limit, credit, timeout, a
malformed reply) is skipped for the router's cooldown and the round goes to
the next. `turn` never runs a tool: tools already run stay in `messages` as
their results, so a failover never runs one again.

Every attempt is recorded in the cost ledger for its business and purpose:
the usage the provider reported, or the call's conservative maximum, marked
estimated, when it reported none.
"""
import json
import logging
import os
import re
from types import SimpleNamespace
from typing import Optional

from services import ai_models, ai_router

logger = logging.getLogger(__name__)

PURPOSE = "chat"
OUTPUT_TOKENS = 8192                 # the most one reply may write (Anthropic and xAI need a figure)
LONG_CONVERSATION_TOKENS = 30_000    # M3: about 120,000 characters
COMPLEX_AFTER_TOOL_ROUNDS = 3

# M3: words that mean money, numbers or thinking work. Matched as whole words.
# Not "account" (an app account), "why" or "review" on their own: too many
# everyday questions use them (Codex AI-1b review 1, finding 8).
_COMPLEX = re.compile(r"\b(" + "|".join([
    r"invoices?", r"owed?", r"owing", r"overdue", r"debts?", r"paid", r"payments?", r"cash(?:\s*flow)?",
    r"profits?", r"loss(?:es)?", r"margins?", r"revenue", r"turnover", r"income", r"expenses?", r"costs?",
    r"budgets?", r"forecasts?", r"accounts", r"accounting", r"accountant", r"vat", r"tax(?:es)?",
    r"pric(?:e|es|ing)", r"quotes?", r"quotation", r"estimates?", r"bank", r"balance", r"xero", r"payroll",
    r"money", r"earn(?:ed|ings)?", r"made", r"make\s+(?:this|last|a)\s+(?:month|year|week|profit|loss)",
    r"spen[dt]", r"afford", r"wages?", r"salar(?:y|ies)", r"hire", r"hiring", r"employees?", r"staff costs",
    r"analy[sz]e", r"analysis", r"compare", r"comparison", r"plan", r"planning", r"strategy", r"strategic",
    r"breakdown", r"recommend(?:ation)?s?", r"should\s+(?:i|we)", r"worth\s+it", r"growth", r"grow",
]) + r")\b", re.I)
# A short follow-up ("what about last month?") keeps the topic of the
# question before it.
FOLLOW_UP_CHARS = 60


def _chars(messages) -> int:
    n = 0
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        n += len(content) if isinstance(content, str) else len(json.dumps(content, default=str)) if content else 0
    return n


def pick_task(message: str, *, history, think_harder: bool = False, tool_rounds: int = 0) -> str:
    """M3: `chat_complex` for money, analysis and planning, a long
    conversation, three or more tool rounds, or "Think harder"; else `chat`."""
    if think_harder or tool_rounds >= COMPLEX_AFTER_TOOL_ROUNDS:
        return "chat_complex"
    if (_chars(history) + len(message or "")) / 4 > LONG_CONVERSATION_TOKENS:
        return "chat_complex"
    if _complex(message):
        return "chat_complex"
    if _is_follow_up(message):
        # The topic is set by the last user message that wasn't itself a short
        # follow-up: "profit?" → "what about last month?" → "and before?"
        for m in reversed(history or []):
            if not (isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)):
                continue
            if _complex(m["content"]):
                return "chat_complex"
            if not _is_follow_up(m["content"]):
                break
    return "chat"


# A short message that starts a new job is a change of topic, not a follow-up
# (Codex AI-1b review 2: "Change my account name" after a profit question).
_NEW_TOPIC = re.compile(r"^\s*(?:(?:please|can you|could you|would you|will you|can i|could i|"
                        r"i want to|i'd like to|i need to|help me)\s+)*"
                        r"(change|update|rename|delete|remove|add|set|create|book|cancel|send|show|open|"
                        r"remind|turn|switch|log|sign|reset|edit|move|call|email|text)\b", re.I)


def _is_follow_up(text) -> bool:
    text = (text or "").strip()
    return bool(text) and len(text) <= FOLLOW_UP_CHARS and not _NEW_TOPIC.search(text)


def _complex(text) -> bool:
    return bool(text) and (bool(_COMPLEX.search(text)) or "£" in text)


# ---------------------------------------------- the deeper-thinking budget ---

# Mike, 21 Nov 2026: each business's monthly spend on the stronger model, in
# pence, by plan; after it, the everyday model answers and Aria says so.
# AI_COMPLEX_MONTHLY_PENCE_JSON ({"starter": 500, ...}) overrides it.
COMPLEX_MONTHLY_PENCE = {"starter": 500, "pro": 1200, "business": 3000}
BUDGET_USED = "budget"
PAUSED = "paused"


def complex_budget_pence(plan_tier) -> int:
    table = dict(COMPLEX_MONTHLY_PENCE)
    raw = os.environ.get("AI_COMPLEX_MONTHLY_PENCE_JSON")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and all(isinstance(v, (int, float)) and v >= 0 for v in parsed.values()):
                table.update({str(k): int(v) for k, v in parsed.items()})
            else:
                raise ValueError
        except (TypeError, ValueError):
            logger.error("AI_COMPLEX_MONTHLY_PENCE_JSON is not valid; the built-in budgets are used")
    return table.get(str(plan_tier or "starter").lower(), table["starter"])


def complex_spent_pence(session, business_id, moment=None) -> float:
    from sqlalchemy import text
    from services.metering import period_for
    from datetime import datetime, timezone
    period = period_for(moment or datetime.now(timezone.utc))
    value = session.execute(text(
        "SELECT COALESCE(SUM(value), 0) FROM usage_meters WHERE business_id = :b AND period = :p "
        "AND meter LIKE 'ai\\_pence:chat\\_complex:%' ESCAPE '\\'"), {"b": str(business_id), "p": period}).scalar()
    return float(value or 0)


def complex_refusal(business_id) -> Optional[str]:
    """None when this business may use the stronger model now; else why not:
    BUDGET_USED (its month's budget, Mike's figures) or PAUSED (the platform's
    profit guard, or a problem checking — never treated as allowed)."""
    from services import profit_guard
    if not profit_guard.permits("chat_complex"):
        return PAUSED
    try:
        from sqlalchemy import text
        from sqlmodel import Session
        with Session(profit_guard._engine()) as s:
            plan = s.execute(text("SELECT plan_tier FROM businesses WHERE id = :b"), {"b": str(business_id)}).scalar()
            spent = complex_spent_pence(s, business_id)
            s.rollback()
    except Exception:
        logger.exception("[AI] the deeper-thinking budget could not be checked; the everyday model answers")
        return PAUSED
    return BUDGET_USED if spent >= complex_budget_pence(plan) else None


class BudgetRefused(Exception):
    """The stronger model may not take this attempt: `reason` is BUDGET_USED
    or PAUSED. The chat loop answers with the everyday model instead."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Reservations:
    """Each attempt on the stronger model first RESERVES its most possible
    cost from the business's month (Codex AI-1b review 2, finding 2), so
    concurrent turns can't all pass a check made just under the budget: spend
    recorded + held by attempts in flight + this attempt's maximum must fit.
    In memory, because production runs one process (STAB-1: a test fails if
    the Procfile or railway.json gains workers). A cost that could not be
    recorded stays counted for ITS month only.

    The recorded spend is read UNDER the lock (Codex AI-1b review 3, finding
    1). An attempt records its cost before it settles, so an admission reads
    either the cost not yet recorded and its reservation still held, or the
    cost recorded and the reservation still held (counted twice: on the
    cautious side), never neither."""

    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.inflight: dict = {}
        self.unrecorded: dict = {}          # (business, UK month) → pence (review 3, finding 2)

    @staticmethod
    def _period() -> str:
        from datetime import datetime, timezone
        from services.metering import period_for
        return period_for(datetime.now(timezone.utc))

    def admit(self, business_id, worst_pence: float) -> Optional[str]:
        from services import profit_guard
        if not profit_guard.permits("chat_complex"):
            return PAUSED
        key = str(business_id)
        with self.lock:
            try:
                from sqlalchemy import text
                from sqlmodel import Session
                with Session(profit_guard._engine()) as s:
                    plan = s.execute(text("SELECT plan_tier FROM businesses WHERE id = :b"),
                                     {"b": key}).scalar()
                    spent = complex_spent_pence(s, business_id)
                    s.rollback()
            except Exception:
                logger.exception("[AI] the deeper-thinking budget could not be checked; the everyday model answers")
                return PAUSED
            held = self.inflight.get(key, 0.0) + self.unrecorded.get((key, self._period()), 0.0)
            if spent + held + worst_pence > complex_budget_pence(plan):
                return BUDGET_USED
            self.inflight[key] = self.inflight.get(key, 0.0) + worst_pence
        return None

    def settle(self, business_id, worst_pence: float, *, recorded: bool, pence: float = 0.0) -> None:
        key = str(business_id)
        with self.lock:
            self.inflight[key] = max(0.0, self.inflight.get(key, 0.0) - worst_pence)
            if not recorded:
                slot = (key, self._period())
                self.unrecorded[slot] = self.unrecorded.get(slot, 0.0) + pence


RESERVATIONS = _Reservations()


def _pence(provider, model, tokens) -> float:
    from services import ai_costs, profit_guard
    try:
        return float(ai_costs.cost(provider, model, int(tokens[0]), int(tokens[1])))
    except ai_costs.Unpriced:
        return (tokens[0] * profit_guard.UNPRICED_PENCE[0] + tokens[1] * profit_guard.UNPRICED_PENCE[1]) / 1e6


NOTES = {
    BUDGET_USED: ("(I answered with my everyday model: this month's allowance for deeper thinking is used up. "
                  "It starts again on the 1st.)"),
    PAUSED: "(I answered with my everyday model: deeper thinking is paused for a short while.)",
}


# ---------------------------------------------------------------- cost ---

def _record(business_id, *, purpose, provider, model, input_tokens, output_tokens, estimated) -> bool:
    """One attempt in the ledger, in its own short session (never raises).
    True when it was recorded."""
    try:
        from sqlmodel import Session
        from services import ai_costs, profit_guard
        try:
            pence = ai_costs.cost(provider, model, input_tokens, output_tokens)
        except ai_costs.Unpriced:
            pence = (input_tokens * profit_guard.UNPRICED_PENCE[0] + output_tokens * profit_guard.UNPRICED_PENCE[1]) / 1e6
            estimated = True
        with Session(profit_guard._engine()) as s:
            ai_costs.record(s, None if business_id in (None, profit_guard.PLATFORM) else business_id,
                            purpose=purpose, provider=provider, model=model, input_tokens=int(input_tokens),
                            output_tokens=int(output_tokens), pence=pence, estimated=estimated)
            s.commit()
        return True
    except Exception:
        logger.exception("[AI] could not record a chat attempt's cost (%s/%s)", provider, model)
        return False


# ------------------------------------------------------------- providers ---

class Rejected(ai_router.ProviderError):
    """The provider refused THIS request (400, 404, 413, 422): not an outage.
    It is not billed, never trips the provider for everyone, and the next
    provider may still take the request (Codex AI-1b review 1, finding 3)."""


class Truncated(ai_router.ProviderError):
    """The reply hit its output limit in the middle of a tool call: the call
    is incomplete and must never run (review 1, finding 4)."""


REJECTED_STATUSES = {400, 404, 413, 422}


def _status_of(exc) -> Optional[int]:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


class _Http:
    def post(self, url, *, json=None, headers=None, timeout=None):
        import httpx
        return httpx.post(url, json=json, headers=headers, timeout=timeout)


_http = _Http()


def _tool_calls_out(calls) -> list:
    out = []
    for c in calls or []:
        fn = getattr(c, "function", None)
        out.append({"id": str(getattr(c, "id", "")), "name": str(getattr(fn, "name", "")),
                    "arguments": str(getattr(fn, "arguments", "") or "{}")})
    return out


def _openai_compatible(provider, model, messages, tools, timeout, client_factory):
    """OpenAI (settings per model) or xAI (OpenAI-compatible, takes max_tokens)."""
    if client_factory is None:
        from openai import OpenAI as client_factory
    client = client_factory(api_key=os.environ[ai_models.KEYS[provider]], base_url=ai_router.BASE_URLS.get(provider),
                            timeout=timeout, max_retries=0)
    request = {"model": model, "messages": messages}
    if tools:
        request.update(tools=tools, tool_choice="auto")
    if provider == "openai":
        request.update(ai_models.chat_params(model, max_tokens=OUTPUT_TOKENS))   # an explicit limit (finding 5)
    else:
        request["max_tokens"] = OUTPUT_TOKENS
    from services import profit_guard
    try:
        with profit_guard.accounted():          # recorded here, never also by the SDK hook
            response = client.chat.completions.create(**request)
    except Exception as exc:
        kind = Rejected if _status_of(exc) in REJECTED_STATUSES else ai_router.ProviderError
        raise kind(f"{provider}: {type(exc).__name__}") from exc
    usage = getattr(response, "usage", None)
    try:
        choice = response.choices[0]
        message = choice.message
    except (AttributeError, IndexError, TypeError) as exc:
        raise ai_router.ProviderError(f"{provider}: malformed reply", usage=usage) from exc
    calls = _tool_calls_out(getattr(message, "tool_calls", None))
    truncated = getattr(choice, "finish_reason", None) == "length"
    if truncated and calls:
        raise Truncated(f"{provider}: a tool call was cut off at the output limit", usage=usage)
    return SimpleNamespace(content=getattr(message, "content", None) or "", tool_calls=calls,
                           truncated=truncated), usage


def _arguments(raw) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def to_anthropic(messages: list, tools: Optional[list]) -> dict:
    """OpenAI-format conversation and tools → Anthropic's Messages API body
    (without model and limits). System messages become `system`; an
    assistant's tool calls become tool_use blocks; consecutive tool results
    become one user turn of tool_result blocks."""
    system, out = [], []
    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system.append(str(m["content"]))
            continue
        if role == "tool":
            block = {"type": "tool_result", "tool_use_id": str(m.get("tool_call_id")), "content": str(m.get("content") or "")}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                    and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        if role == "assistant" and not m.get("tool_calls") and not str(m.get("content") or "").strip():
            continue                     # an empty assistant message is invalid there (review 1, finding 6)
        if role == "assistant" and m.get("tool_calls"):
            blocks = [{"type": "text", "text": str(m["content"])}] if m.get("content") else []
            for c in m["tool_calls"]:
                fn = c.get("function") or {}
                blocks.append({"type": "tool_use", "id": str(c.get("id")), "name": str(fn.get("name")),
                               "input": _arguments(fn.get("arguments"))})
            out.append({"role": "assistant", "content": blocks})
            continue
        out.append({"role": "assistant" if role == "assistant" else "user", "content": str(m.get("content") or "")})
    body = {"messages": out}
    if system:
        body["system"] = "\n\n".join(system)
    if tools:
        body["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                          "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                         for t in tools if t.get("type") == "function"]
    return body


def _anthropic(provider, model, messages, tools, timeout, _client_factory):
    body = dict(to_anthropic(messages, tools), model=model, max_tokens=OUTPUT_TOKENS)
    try:
        response = _http.post(ai_router.ANTHROPIC_URL, json=body, timeout=timeout, headers={
            "x-api-key": os.environ[ai_models.KEYS[provider]], "anthropic-version": "2023-06-01",
            "content-type": "application/json"})
    except Exception as exc:
        raise ai_router.ProviderError(f"{provider}: {type(exc).__name__}") from exc
    if response.status_code != 200:
        kind = Rejected if response.status_code in REJECTED_STATUSES else ai_router.ProviderError
        raise kind(f"{provider}: HTTP {response.status_code}")
    reply, usage, _ = ai_router._anthropic_body(provider, response)
    blocks = reply.get("content")
    if not isinstance(blocks, list):
        raise ai_router.ProviderError(f"{provider}: malformed reply", usage=usage)
    text = "".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    calls = [{"id": str(b.get("id")), "name": str(b.get("name")), "arguments": json.dumps(b.get("input") or {})}
             for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    truncated = reply.get("stop_reason") == "max_tokens"
    if truncated and calls:
        raise Truncated(f"{provider}: a tool call was cut off at the output limit", usage=usage)
    return SimpleNamespace(content=text, tool_calls=calls, truncated=truncated), usage


_ADAPTERS = {"openai": _openai_compatible, "xai": _openai_compatible, "anthropic": _anthropic}


def _tokens(usage) -> Optional[tuple]:
    """(input, output) as the provider reported them; None unless BOTH are
    reported, so a missing figure is estimated, never taken as zero (finding 5)."""
    if usage is None:
        return None
    for a, b in (("prompt_tokens", "completion_tokens"), ("input_tokens", "output_tokens")):
        x, y = getattr(usage, a, None), getattr(usage, b, None)
        if isinstance(x, int) and isinstance(y, int):
            return x, y
    return None


def _worst(provider, model, messages, tools) -> tuple:
    """The most a request can be billed: every character of everything sent
    (tool calls included) a token, and the request's own output limit."""
    sent = len(json.dumps(messages, default=str)) + len(json.dumps(tools or []))
    if provider == "openai":
        limit = ai_models.chat_params(model, max_tokens=OUTPUT_TOKENS)
        out = limit.get("max_completion_tokens") or limit.get("max_tokens") or OUTPUT_TOKENS
    else:
        out = OUTPUT_TOKENS
    return max(1, sent), int(out)


def available(task: str) -> bool:
    """Whether any provider in the task's chain has its key (finding 7)."""
    return any(os.environ.get(ai_models.KEYS.get(p, "")) for p, _ in ai_models.resolve(task))


def turn(task: str, *, business_id, messages: list, tools: Optional[list] = None, timeout: float = 120.0,
         openai_client=None, purpose: Optional[str] = None, budget_business=None):
    """One round of the conversation from the first provider that answers.
    Returns content, tool_calls [{id, name, arguments}], truncated, provider
    and model. Recorded under `purpose` (the task, by default), so each
    business's deeper-thinking spend can be read back. With `budget_business`,
    every attempt first reserves its most possible cost from that business's
    deeper-thinking budget, and raises BudgetRefused when it doesn't fit."""
    purpose = purpose or task
    tried = []
    for provider, model in ai_models.resolve(task):
        if ai_router._is_down(provider) or not os.environ.get(ai_models.KEYS.get(provider, "")):
            continue
        worst = _worst(provider, model, messages, tools)
        reserved = 0.0
        if budget_business is not None:
            reserved = _pence(provider, model, worst)
            why = RESERVATIONS.admit(budget_business, reserved)
            if why:
                raise BudgetRefused(why)
        outcome = {"recorded": True, "pence": 0.0}

        def note(**kw):
            outcome["pence"] = _pence(kw["provider"], kw["model"], (kw["input_tokens"], kw["output_tokens"]))
            outcome["recorded"] = _record(business_id, **kw) is not False
        try:
            reply, usage = _ADAPTERS[provider](provider, model, messages, tools, timeout, openai_client)
        except Rejected as exc:
            # Refused before any work: not billed, and not an outage (finding 3).
            if budget_business is not None:
                RESERVATIONS.settle(budget_business, reserved, recorded=True)
            tried.append(f"{provider}/{model}")
            logger.warning("[AI] %s: %s/%s refused the request (%s); trying the next provider",
                           task, provider, model, exc)
            continue
        except ai_router.ProviderError as exc:
            got = _tokens(exc.usage)
            note(purpose=purpose, provider=provider, model=model,
                 input_tokens=(got or worst)[0], output_tokens=(got or worst)[1], estimated=got is None)
            if budget_business is not None:
                RESERVATIONS.settle(budget_business, reserved, **outcome)
            if not isinstance(exc, Truncated):
                ai_router._trip(provider)     # an outage; a cut-off reply is our limit, not theirs
            tried.append(f"{provider}/{model}")
            logger.warning("[AI] %s: %s/%s failed (%s); trying the next provider", task, provider, model, exc)
            continue
        got = _tokens(usage)
        note(purpose=purpose, provider=provider, model=model,
             input_tokens=(got or worst)[0], output_tokens=(got or worst)[1], estimated=got is None)
        if budget_business is not None:
            RESERVATIONS.settle(budget_business, reserved, **outcome)
        reply.provider, reply.model = provider, model
        return reply
    raise ai_router.AllProvidersFailed("No AI provider could answer" + (f" (tried {', '.join(tried)})" if tried else ""))
