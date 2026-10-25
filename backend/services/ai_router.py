"""OUT-19 part H — AI provider routing and failover.

Mike, 25 Oct 2026: outreach must keep working if one AI provider goes down,
runs out of credit or fails unexpectedly, by switching to another nearly as
capable — set by configuration, never by a code change.

  AI_PROVIDER_ORDER   e.g. "openai,xai,anthropic" (the default)
  AI_MODELS_JSON      {"draft": {"openai": "gpt-4o", ...}, "research": {...}}
  AI_FAILOVER_COOLDOWN_SECONDS   how long a failed provider is skipped (300)
  OPENAI_API_KEY / XAI_API_KEY / ANTHROPIC_API_KEY

A provider is used only when its key is set and its model has a price in
ai_costs (an unpriced model is never used). A provider error — outage, rate
limit, exhausted credit, timeout — hands over to the next in order, and the
failed provider is skipped for the cooldown. An answer that is not valid JSON
is the model's answer, not an outage: it is not retried elsewhere, so no
second provider is charged for it. Every attempt is noted for the cost
ledger; a failed one at its conservative maximum, marked estimated.

Grok is reached through the OpenAI library pointed at xAI's compatible API;
Claude through Anthropic's Messages API directly (no extra library).
"""
import json
import logging
import os
import re
import time
from types import SimpleNamespace

from services import ai_costs

logger = logging.getLogger(__name__)

DEFAULT_ORDER = ["openai", "xai", "anthropic"]
KEYS = {"openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
BASE_URLS = {"xai": "https://api.x.ai/v1"}
DEFAULT_MODELS = {
    "draft": {"openai": "gpt-4o", "xai": "grok-4", "anthropic": "claude-sonnet-4-5"},
    "research": {"openai": "gpt-4.1", "xai": "grok-4", "anthropic": "claude-sonnet-4-5"},
}
# The most input a single call can be billed for: each model's context window.
CONTEXT_TOKENS = {"openai/gpt-4.1": 1_047_576, "openai/gpt-4o": 128_000, "openai/gpt-4o-mini": 128_000,
                  "xai/grok-4": 256_000, "anthropic/claude-sonnet-4-5": 200_000}
SEARCH_MAX_OUTPUT_TOKENS, SEARCH_MAX_TOOL_CALLS = 8000, 8
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
RETRYABLE_SEARCH_ERRORS = {"too_many_requests", "unavailable"}

_down: dict = {}


class ProviderError(Exception):
    """The provider failed (outage, rate limit, credit, timeout, a malformed
    reply): fail over. `usage`/`searches` carry what the provider reported, if
    anything, so a billed failure is charged at its real cost."""

    def __init__(self, message: str, *, usage=None, searches: int = 0):
        super().__init__(message)
        self.usage, self.searches = usage, searches


class AllProvidersFailed(Exception):
    """No configured provider could serve the call."""


def _now() -> float:
    return time.monotonic()


def cooldown() -> float:
    try:
        return max(0.0, float(os.environ.get("AI_FAILOVER_COOLDOWN_SECONDS", "300")))
    except ValueError:
        return 300.0


def reset_breakers() -> None:
    _down.clear()


def _trip(provider: str) -> None:
    _down[provider] = _now() + cooldown()


def _is_down(provider: str) -> bool:
    until = _down.get(provider)
    if until is None:
        return False
    if _now() >= until:
        _down.pop(provider, None)
        return False
    return True


def order() -> list:
    raw = os.environ.get("AI_PROVIDER_ORDER")
    if not raw:
        return list(DEFAULT_ORDER)
    seen = []
    for p in (x.strip().lower() for x in raw.split(",")):
        if p in KEYS and p not in seen:
            seen.append(p)
    return seen or list(DEFAULT_ORDER)


def models(purpose: str) -> dict:
    table = {p: dict(m) for p, m in DEFAULT_MODELS.items()}.get(purpose, {})
    raw = os.environ.get("AI_MODELS_JSON")
    if raw:
        try:
            parsed = json.loads(raw)
            chosen = parsed.get(purpose, {}) if isinstance(parsed, dict) else None
            if not isinstance(chosen, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in chosen.items()):
                raise ValueError
            table.update(chosen)
        except (ValueError, TypeError, AttributeError):
            logger.error("AI_MODELS_JSON is not valid; all of it is ignored and the built-in models are used")
            table = dict(DEFAULT_MODELS.get(purpose, {}))
    # The settings from before failover still choose OpenAI's model.
    legacy = {"draft": "ARIA_DRAFT_MODEL", "research": "ARIA_RESEARCH_MODEL"}.get(purpose)
    if legacy and os.environ.get(legacy):
        table["openai"] = os.environ[legacy]
    return table


def _priced(provider: str, model: str) -> bool:
    try:
        ai_costs.require_priced(provider, model)
        return True
    except ai_costs.Unpriced:
        return False


def chain(purpose: str, *, include_down: bool = False) -> list:
    """(provider, model) pairs to try, in order: keyed, priced, not cooling down."""
    chosen = models(purpose)
    out = []
    for p in order():
        model = chosen.get(p)
        if model and os.environ.get(KEYS[p]) and _priced(p, model) and (include_down or not _is_down(p)):
            out.append((p, model))
    return out


def extract_json(text: str) -> str:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("The model did not return JSON")
    return match.group(0)


# ---------------------------------------------------------------- chat ---

def _openai_compatible_chat(provider, model, system, user, max_tokens):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ[KEYS[provider]], base_url=BASE_URLS.get(provider), timeout=60.0, max_retries=0)
    try:
        response = client.chat.completions.create(model=model, response_format={"type": "json_object"},
                                                  max_tokens=max_tokens,
                                                  messages=[{"role": "system", "content": system},
                                                            {"role": "user", "content": user}])
    except Exception as exc:
        raise ProviderError(f"{provider}: {type(exc).__name__}") from exc
    usage = getattr(response, "usage", None)
    try:
        text = response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        raise ProviderError(f"{provider}: malformed reply", usage=usage) from exc   # billed, but no answer
    return text, usage


def _anthropic_chat(provider, model, system, user, max_tokens):
    import httpx
    try:
        response = httpx.post(ANTHROPIC_URL, timeout=60.0, headers={
            "x-api-key": os.environ[KEYS[provider]], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system + "\nReply with one JSON object only.",
                  "messages": [{"role": "user", "content": user}]})
    except Exception as exc:
        raise ProviderError(f"{provider}: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ProviderError(f"{provider}: HTTP {response.status_code}")
    try:
        body = response.json()
        usage = _anthropic_usage(body)
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    except (ValueError, AttributeError, TypeError) as exc:
        raise ProviderError(f"{provider}: malformed reply") from exc
    return text, usage


def _anthropic_usage(body: dict):
    usage = body.get("usage") or {}
    return SimpleNamespace(input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))


def json_chat(system: str, context: dict, *, purpose: str, max_tokens: int) -> dict:
    """One JSON answer from the first provider that can serve it."""
    user = json.dumps(context, default=str)
    worst = (len(system) + len(user), max_tokens)   # every character a token, the full output
    tried = []
    for provider, model in chain(purpose):
        call = _anthropic_chat if provider == "anthropic" else _openai_compatible_chat
        try:
            text, usage = call(provider, model, system, user, max_tokens)
        except ProviderError as exc:
            # A failure the provider reported usage for is charged at that; one
            # without, at its conservative maximum, marked estimated.
            ai_costs.note(provider, model, exc.usage, fallback=worst, estimated=exc.usage is None)
            _trip(provider)
            tried.append(f"{provider}/{model}")
            logger.warning("AI failover: %s/%s failed (%s); trying the next provider", provider, model, exc)
            continue
        ai_costs.note(provider, model, usage, fallback=worst)
        return json.loads(extract_json(text))
    raise AllProvidersFailed("No AI provider could serve this" + (f" (tried {', '.join(tried)})" if tried else ""))


# ------------------------------------------------------------ research ---

def max_search_pence(provider: str, model: str) -> int:
    """One search's true maximum cost on this provider: its whole context
    window in, the bounded output out, the bounded tool calls."""
    p_in, p_out, p_tool = ai_costs.price(provider, model)
    context = CONTEXT_TOKENS.get(f"{provider}/{model}", 2_000_000)   # unknown window: assume very large
    return int(-(-((context * p_in + SEARCH_MAX_OUTPUT_TOKENS * p_out) / 1_000_000 + SEARCH_MAX_TOOL_CALLS * p_tool) // 1))


def reserve_pence() -> int:
    """Enough for every provider a search might try: each failed attempt is
    charged its own maximum, so the reservation covers the whole chain."""
    # Every keyed, priced provider, INCLUDING ones cooling down: a cooldown can
    # end mid-search and that provider may then be tried (Codex OUT-19 H review 1).
    pairs = chain("research", include_down=True)
    return sum(max_search_pence(p, m) for p, m in pairs)


def _openai_compatible_search(provider, model, brief):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ[KEYS[provider]], base_url=BASE_URLS.get(provider), timeout=300.0, max_retries=0)
    try:
        response = client.responses.create(model=model, tools=[{"type": "web_search", "search_context_size": "low"}],
                                           input=brief, max_output_tokens=SEARCH_MAX_OUTPUT_TOKENS,
                                           max_tool_calls=SEARCH_MAX_TOOL_CALLS)
    except Exception as exc:
        raise ProviderError(f"{provider}: {type(exc).__name__}") from exc
    usage = getattr(response, "usage", None)
    try:
        searches = sum(1 for item in (getattr(response, "output", None) or [])
                       if getattr(item, "type", "") == "web_search_call")
        text = getattr(response, "output_text", "") or ""
    except (AttributeError, TypeError) as exc:
        raise ProviderError(f"{provider}: malformed reply", usage=usage) from exc
    return text, usage, searches


def _anthropic_search(provider, model, brief):
    import httpx
    try:
        response = httpx.post(ANTHROPIC_URL, timeout=300.0, headers={
            "x-api-key": os.environ[KEYS[provider]], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": SEARCH_MAX_OUTPUT_TOKENS, "messages": [{"role": "user", "content": brief}],
                  "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": SEARCH_MAX_TOOL_CALLS}]})
    except Exception as exc:
        raise ProviderError(f"{provider}: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise ProviderError(f"{provider}: HTTP {response.status_code}")
    try:
        body = response.json()
        usage = _anthropic_usage(body)
        searches = int(((body.get("usage") or {}).get("server_tool_use") or {}).get("web_search_requests") or 0)
        blocks = body.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        # Anthropic reports search outages INSIDE a 200 reply (Codex OUT-19 H
        # review 1): a rate limit or unavailable search is a provider failure;
        # running out of allowed searches is not.
        tool_errors = {(b.get("content") or {}).get("error_code") for b in blocks
                       if b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), dict)
                       and b["content"].get("type") == "web_search_tool_result_error"}
    except (ValueError, AttributeError, TypeError) as exc:
        raise ProviderError(f"{provider}: malformed reply") from exc
    if tool_errors & RETRYABLE_SEARCH_ERRORS:
        raise ProviderError(f"{provider}: web search {', '.join(sorted(tool_errors))}", usage=usage, searches=searches)
    return text, usage, searches


def web_search(brief: str) -> dict:
    """Research's web search through the provider chain. Returns the candidates,
    every attempt's cost (`calls`) and their total (`cost_pence`)."""
    calls = []
    for provider, model in chain("research"):
        search = _anthropic_search if provider == "anthropic" else _openai_compatible_search
        try:
            text, usage, searches = search(provider, model, brief)
        except ProviderError as exc:
            reported = ai_costs.usage_tokens(exc.usage)
            if reported is None:
                calls.append({"provider": provider, "model": model, "pence": max_search_pence(provider, model),
                              "estimated": True, "usage": {}})
            else:
                pence = int(-(-ai_costs.cost(provider, model, reported[0], reported[1], exc.searches) // 1))
                calls.append({"provider": provider, "model": model, "pence": max(1, pence), "estimated": False,
                              "usage": {"input_tokens": reported[0], "output_tokens": reported[1],
                                        "tool_calls": exc.searches}})
            _trip(provider)
            logger.warning("AI failover: research on %s/%s failed (%s); trying the next provider", provider, model, exc)
            continue
        reported = ai_costs.usage_tokens(usage)
        if reported is None:
            pence, estimated, tokens = max_search_pence(provider, model), True, (0, 0)
        else:
            tokens, estimated = reported, False
            pence = int(-(-ai_costs.cost(provider, model, tokens[0], tokens[1], searches) // 1))
        calls.append({"provider": provider, "model": model, "pence": max(1, pence), "estimated": estimated,
                      "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1], "tool_calls": searches}})
        try:
            candidates = json.loads(extract_json(text)).get("candidates", [])
        except (ValueError, AttributeError):
            candidates = []
        return {"candidates": candidates, "calls": calls, "cost_pence": sum(c["pence"] for c in calls),
                "provider": provider, "model": model}
    if calls:
        # Every provider failed after being tried: the attempts may be billed.
        raise _AllFailedWithCost(calls)
    raise AllProvidersFailed("No AI provider is available for research")


class _AllFailedWithCost(AllProvidersFailed):
    def __init__(self, calls):
        super().__init__("Every AI provider failed this search")
        self.calls = calls
