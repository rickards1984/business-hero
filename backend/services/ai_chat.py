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
_COMPLEX = re.compile(r"\b(" + "|".join([
    r"invoices?", r"owed?", r"owing", r"overdue", r"debts?", r"paid", r"payments?", r"cash(?:\s*flow)?",
    r"profits?", r"loss(?:es)?", r"margins?", r"revenue", r"turnover", r"income", r"expenses?", r"costs?",
    r"budgets?", r"forecasts?", r"accounts?", r"accounting", r"vat", r"tax(?:es)?", r"pric(?:e|es|ing)",
    r"quotes?", r"quotation", r"estimates?", r"bank", r"balance", r"xero", r"payroll", r"£",
    r"analy[sz]e", r"analysis", r"compare", r"comparison", r"plan", r"planning", r"strategy", r"review",
    r"breakdown", r"why", r"recommend", r"should i",
]) + r")\b", re.I)


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
    return "chat_complex" if _COMPLEX.search(message or "") or "£" in (message or "") else "chat"


# ---------------------------------------------------------------- cost ---

def _record(business_id, *, purpose, provider, model, input_tokens, output_tokens, estimated) -> None:
    """One attempt in the ledger, in its own short session (never raises)."""
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
    except Exception:
        logger.exception("[AI] could not record a chat attempt's cost (%s/%s)", provider, model)


# ------------------------------------------------------------- providers ---

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
        request.update(ai_models.chat_params(model))
    else:
        request["max_tokens"] = OUTPUT_TOKENS
    from services import profit_guard
    try:
        with profit_guard.accounted():          # recorded here, never also by the SDK hook
            response = client.chat.completions.create(**request)
    except Exception as exc:
        raise ai_router.ProviderError(f"{provider}: {type(exc).__name__}") from exc
    usage = getattr(response, "usage", None)
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError) as exc:
        raise ai_router.ProviderError(f"{provider}: malformed reply", usage=usage) from exc
    return SimpleNamespace(content=getattr(message, "content", None) or "",
                           tool_calls=_tool_calls_out(getattr(message, "tool_calls", None))), usage


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
        raise ai_router.ProviderError(f"{provider}: HTTP {response.status_code}")
    reply, usage, _ = ai_router._anthropic_body(provider, response)
    blocks = reply.get("content")
    if not isinstance(blocks, list):
        raise ai_router.ProviderError(f"{provider}: malformed reply", usage=usage)
    text = "".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    calls = [{"id": str(b.get("id")), "name": str(b.get("name")), "arguments": json.dumps(b.get("input") or {})}
             for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    return SimpleNamespace(content=text, tool_calls=calls), usage


_ADAPTERS = {"openai": _openai_compatible, "xai": _openai_compatible, "anthropic": _anthropic}


def _tokens(usage) -> Optional[tuple]:
    if usage is None:
        return None
    pairs = (("prompt_tokens", "completion_tokens"), ("input_tokens", "output_tokens"))
    for a, b in pairs:
        x, y = getattr(usage, a, None), getattr(usage, b, None)
        if isinstance(x, int) and isinstance(y, int):
            return x, y
        if isinstance(x, int) and y is None:
            return x, 0
    return None


def turn(task: str, *, business_id, messages: list, tools: Optional[list] = None, timeout: float = 120.0,
         openai_client=None, purpose: str = PURPOSE):
    """One round of the conversation from the first provider that answers.
    Returns content, tool_calls [{id, name, arguments}], provider and model."""
    worst = (max(1, _chars(messages) + len(json.dumps(tools or []))), OUTPUT_TOKENS)
    tried = []
    for provider, model in ai_models.resolve(task):
        if ai_router._is_down(provider) or not os.environ.get(ai_models.KEYS.get(provider, "")):
            continue
        try:
            reply, usage = _ADAPTERS[provider](provider, model, messages, tools, timeout, openai_client)
        except ai_router.ProviderError as exc:
            got = _tokens(exc.usage)
            _record(business_id, purpose=purpose, provider=provider, model=model,
                    input_tokens=(got or worst)[0], output_tokens=(got or worst)[1], estimated=got is None)
            ai_router._trip(provider)
            tried.append(f"{provider}/{model}")
            logger.warning("[AI] %s: %s/%s failed (%s); trying the next provider", task, provider, model, exc)
            continue
        got = _tokens(usage)
        _record(business_id, purpose=purpose, provider=provider, model=model,
                input_tokens=(got or worst)[0], output_tokens=(got or worst)[1], estimated=got is None)
        reply.provider, reply.model = provider, model
        return reply
    raise ai_router.AllProvidersFailed("No AI provider could answer" + (f" (tried {', '.join(tried)})" if tried else ""))
