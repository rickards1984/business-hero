"""AI-1d — one plain text request on any provider (docs/AI-1-TICKET.md).

The briefings, the help assistant, email (briefing, sorting, reply drafts) and
call summaries each built their own OpenAI client. They now ask for their
task here: the models chosen for it on the admin page, in order, failing
over when one is down (services/ai_chat's adapters, the same ones Aria's chat
uses). Nothing else about the sites changes: their prompts, their parsing
and their plain fallbacks stay, and they fall back on any error from here
exactly as they did on an OpenAI error.

Costs: each attempt is recorded under the business and purpose the site
already names with `profit_guard.attributed(...)` (or an explicit
`business_id`/`purpose`), so the ledger and the admin page's spend read the
same as before. A failure the provider billed is charged at its real usage,
or at most what that request could have cost.

The kill switch: a non-essential purpose is refused before any call once the
profit guard holds AI spending, as the SDK hook refused these sites before
(profit_guard.Paused, which they already fall back on).
"""
import asyncio
import json
import logging
import os
import re
from types import SimpleNamespace
from typing import Optional

from services import ai_chat, ai_models, ai_router

logger = logging.getLogger(__name__)

_UNSET = object()
RETRIES = 1                    # each site's OpenAI client retried once: kept, here, and costed
TOTAL_ATTEMPT_LIMITS = 2       # the whole call: as long as the old one attempt and its SDK retry
MIN_ATTEMPT_SECONDS = 3.0      # an attempt that would be cut short before it can answer isn't started


def _attribution(task: str, business_id, purpose):
    """The business and purpose to cost this under: what the caller said,
    else what the surrounding `profit_guard.attributed` block says, else the
    platform and the task's first ledger purpose."""
    from services import profit_guard
    current = profit_guard._attribution.get()
    if purpose is None:
        ledger = ai_models.TASKS[task].ledger
        purpose = current[1] if current else (ledger[0] if ledger else task)
    if business_id is _UNSET:
        business_id = current[0] if current else None
    if business_id == profit_guard.PLATFORM:
        business_id = None
    return business_id, purpose


def _worst(provider: str, model: str, messages, max_tokens: int, tools=None, settings=None) -> tuple:
    """The most this request can be billed: every character sent a token, and
    its own output limit in the form the model takes."""
    sent = max(1, len(json.dumps(messages, default=str)) + len(json.dumps(tools or [])))
    if provider == "openai":
        limit = settings if settings is not None else ai_models.chat_params(model, max_tokens=max_tokens)
        return sent, int(limit.get("max_completion_tokens") or limit.get("max_tokens") or max_tokens)
    return sent, int(max_tokens)


def _reported_tokens(usage) -> int:
    """What the provider says the call used, for a site's own token budget
    (the board meeting's caps): its total, else input plus output, else 0."""
    total = getattr(usage, "total_tokens", None)
    if isinstance(total, int):
        return total
    got = ai_chat._tokens(usage)
    return sum(got) if got else 0


def complete(task: str, messages: list, *, max_tokens: int, temperature: Optional[float] = None,
             timeout: float = 30.0, business_id=_UNSET, purpose: Optional[str] = None,
             tools: Optional[list] = None, json_object: bool = False, openai_settings=None,
             refused_hook=None, client_factory=None, chain: Optional[list] = None):
    """The first of the task's models to answer: its text (stripped), any
    tool calls ([{id, name, arguments}]), whether it was cut off, the provider
    and model, and the tokens it reported. Raises profit_guard.Paused at the
    kill switch, or ai_router.AllProvidersFailed when nothing answers.

    `timeout` is one attempt's limit; no attempt starts or runs past
    TOTAL_ATTEMPT_LIMITS of it from the start (Codex AI-1d review 1, finding
    7: a chain of timeouts each got the full limit, plus the SDK's own retry).
    Each model gets one retry of its own after an outage, made and costed here
    rather than inside the SDK (finding 6), before the provider is switched off.

    AI-1d part 2, for the board meeting:
    - `tools`: offered to the model; an answer that is only tool calls counts.
    - `json_object`: OpenAI's and xAI's JSON mode; Claude is asked in its system prompt.
    - `openai_settings(model, tools_offered) -> dict`: the site's own limit,
      temperature and reasoning settings for an OpenAI model, in place of
      `chat_params`.
    - `refused_hook(provider, model, error) -> bool`: True when the site has
      changed what it will send for that model (BM-5's reasoning with
      tools), so it is asked again at once, unbilled, once.
    - `chain`: the models to use instead of the task's choice (a test override).
    """
    import time
    from services import profit_guard
    business_id, purpose = _attribution(task, business_id, purpose)
    essential = purpose in profit_guard.ESSENTIAL
    deadline = time.monotonic() + timeout * TOTAL_ATTEMPT_LIMITS
    tried = []

    def held() -> bool:
        return not essential and not profit_guard.permits(purpose)

    for provider, model in (chain if chain is not None else ai_models.resolve(task)):
        if ai_router._is_down(provider) or not os.environ.get(ai_models.KEYS.get(provider, "")):
            continue
        asked_again = False
        attempt = 0
        while attempt <= RETRIES:
            settings = openai_settings(model, bool(tools)) if (openai_settings and provider == "openai") else None
            worst = _worst(provider, model, messages, max_tokens, tools, settings)

            def cost(usage, worst=worst):
                got = ai_chat._tokens(usage)
                tokens = got or worst
                ai_chat._record(business_id, purpose=purpose, provider=provider, model=model,
                                input_tokens=tokens[0], output_tokens=tokens[1], estimated=got is None)
            out_of_time = ai_router.AllProvidersFailed(f"No AI model could answer {task} in time"
                                                       + (f" (tried {', '.join(tried)})" if tried else ""))
            if deadline - time.monotonic() < MIN_ATTEMPT_SECONDS:
                raise out_of_time              # before the guard's own query (review 2, finding 6)
            # Before every attempt: a failure just costed may have closed the
            # kill switch (finding 1), and the SDK hook can't see these calls.
            if held():
                raise profit_guard.Paused(f"{purpose} paused: this month's costs have reached the kill threshold "
                                          "of income")
            seconds = min(timeout, deadline - time.monotonic())     # after the guard: its time counts
            if seconds < MIN_ATTEMPT_SECONDS:
                raise out_of_time
            options = {"max_tokens": max_tokens, "temperature": temperature, "retries": 0}
            if json_object:
                options["json_object"] = True
            if settings is not None:
                options["settings"] = settings
            try:
                reply, usage = ai_chat._ADAPTERS[provider](provider, model, messages, tools, seconds,
                                                           client_factory, **options)
            except ai_router.ProviderError as exc:
                cause = exc.__cause__ or exc
                if refused_hook and not asked_again and refused_hook(provider, model, cause):
                    asked_again = True         # refused before any work: not billed, not an attempt
                    logger.warning("[AI] %s: %s/%s refused those settings; asking again", task, provider, model)
                    continue
                if isinstance(exc, ai_chat.Rejected):   # refused before any work: not billed, not an outage
                    tried.append(f"{provider}/{model}")
                    logger.warning("[AI] %s: %s/%s refused the request (%s); trying the next model",
                                   task, provider, model, exc)
                    break
                cost(exc.usage)
                tried.append(f"{provider}/{model}")
                if isinstance(exc, ai_chat.Truncated):
                    break                      # our limit, not their outage: no retry, no trip
                if attempt < RETRIES:
                    logger.warning("[AI] %s: %s/%s failed (%s); retrying once", task, provider, model, exc)
                    attempt += 1
                    continue
                ai_router._trip(provider)
                logger.warning("[AI] %s: %s/%s failed (%s); trying the next model", task, provider, model, exc)
                break
            cost(usage)
            content = (reply.content or "").strip()
            calls = list(getattr(reply, "tool_calls", None) or [])
            if not content and not calls:      # billed, but no answer: the next model, not an outage
                tried.append(f"{provider}/{model}")
                logger.warning("[AI] %s: %s/%s gave an empty answer%s; trying the next model", task, provider, model,
                               " (cut off at its output limit: finish_reason=length)"
                               if getattr(reply, "truncated", False) else "")
                break
            return SimpleNamespace(content=content, tool_calls=calls, provider=provider, model=model,
                                   truncated=bool(getattr(reply, "truncated", False)),
                                   tokens=_reported_tokens(usage))
    raise ai_router.AllProvidersFailed(f"No AI model could answer {task}" + (f" (tried {', '.join(tried)})" if tried else ""))


async def acomplete(task: str, messages: list, **kwargs):
    """`complete` in a worker thread, so a slow model never blocks the event
    loop. The surrounding attribution goes with it (to_thread copies the
    context)."""
    return await asyncio.to_thread(complete, task, messages, **kwargs)


_ANY_FENCE = re.compile(r"```[a-zA-Z]*[ \t]*\n?(.*?)\n?[ \t]*```", re.S)


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def _email_strip(text: str) -> str:
    """app/email/service.py's stripping before AI-1d, verbatim in effect."""
    content = (text or "").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _aria_strip(text: str) -> str:
    """assistant_tools.py's stripping before AI-1d, verbatim in effect."""
    content = (text or "").strip().strip("`").strip()
    if content.startswith("json"):
        content = content[4:].strip()
    return content


def strip_fences(text: str) -> str:
    """The JSON in a model's answer, when it wrapped it (Claude often does), or
    the text. In this order:

    1. Valid JSON as it is, so a fence inside one of its strings is never
       taken for a wrapper (Codex AI-1d review 1, finding 2).
    2. Each site's own stripping before AI-1d, exactly as it was, when the
       result is JSON: so every answer a site parsed before still parses to
       the same thing (reviews 3 and 4).
    3. New: the first fenced block holding JSON, wherever it sits: after a
       line of prose, before "let me know if you'd like changes", or inline
       (review 2, finding 1).
    4. Otherwise an answer that opens with a fence loses it, as before.
    """
    text = (text or "").strip()
    if _is_json(text):
        return text
    for legacy in (_email_strip(text), _aria_strip(text)):
        if _is_json(legacy):
            return legacy
    for block in _ANY_FENCE.finditer(text):
        inner = block.group(1).strip()
        if _is_json(inner):
            return inner
    return _email_strip(text) if text.startswith("```") else text
