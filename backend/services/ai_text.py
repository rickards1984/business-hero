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


def _worst(provider: str, model: str, messages, max_tokens: int) -> tuple:
    """The most this request can be billed: every character sent a token, and
    its own output limit in the form the model takes."""
    sent = max(1, len(json.dumps(messages, default=str)))
    if provider == "openai":
        limit = ai_models.chat_params(model, max_tokens=max_tokens)
        return sent, int(limit.get("max_completion_tokens") or limit.get("max_tokens") or max_tokens)
    return sent, int(max_tokens)


def complete(task: str, messages: list, *, max_tokens: int, temperature: Optional[float] = None,
             timeout: float = 30.0, business_id=_UNSET, purpose: Optional[str] = None):
    """The text of the first of the task's models to answer, stripped, with
    the provider and model that answered. Raises profit_guard.Paused at the
    kill switch, or ai_router.AllProvidersFailed when nothing answers.

    `timeout` is one attempt's limit; no attempt starts or runs past
    TOTAL_ATTEMPT_LIMITS of it from the start (Codex AI-1d review 1, finding
    7: a chain of timeouts each got the full limit, plus the SDK's own retry).
    Only an attempt's costing and one guard query can run past it. Each model
    gets one retry of its own after an outage, made and costed here rather
    than inside the SDK (finding 6), before the provider is switched off."""
    import time
    from services import profit_guard
    business_id, purpose = _attribution(task, business_id, purpose)
    essential = purpose in profit_guard.ESSENTIAL
    deadline = time.monotonic() + timeout * TOTAL_ATTEMPT_LIMITS
    tried = []

    def held() -> bool:
        return not essential and not profit_guard.permits(purpose)

    for provider, model in ai_models.resolve(task):
        if ai_router._is_down(provider) or not os.environ.get(ai_models.KEYS.get(provider, "")):
            continue
        worst = _worst(provider, model, messages, max_tokens)

        def cost(usage):
            got = ai_chat._tokens(usage)
            tokens = got or worst
            ai_chat._record(business_id, purpose=purpose, provider=provider, model=model,
                            input_tokens=tokens[0], output_tokens=tokens[1], estimated=got is None)
        for attempt in range(1 + RETRIES):
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
            try:
                reply, usage = ai_chat._ADAPTERS[provider](provider, model, messages, None, seconds, None,
                                                           max_tokens=max_tokens, temperature=temperature, retries=0)
            except ai_chat.Rejected as exc:    # refused before any work: not billed, not an outage
                tried.append(f"{provider}/{model}")
                logger.warning("[AI] %s: %s/%s refused the request (%s); trying the next model",
                               task, provider, model, exc)
                break
            except ai_router.ProviderError as exc:
                cost(exc.usage)
                tried.append(f"{provider}/{model}")
                if isinstance(exc, ai_chat.Truncated):
                    break                      # our limit, not their outage: no retry, no trip
                if attempt < RETRIES:
                    logger.warning("[AI] %s: %s/%s failed (%s); retrying once", task, provider, model, exc)
                    continue
                ai_router._trip(provider)
                logger.warning("[AI] %s: %s/%s failed (%s); trying the next model", task, provider, model, exc)
                break
            cost(usage)
            content = (reply.content or "").strip()
            if not content:                    # billed, but no answer: the next model, not an outage
                tried.append(f"{provider}/{model}")
                logger.warning("[AI] %s: %s/%s gave an empty answer; trying the next model", task, provider, model)
                break
            return SimpleNamespace(content=content, provider=provider, model=model,
                                   truncated=bool(getattr(reply, "truncated", False)))
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


def strip_fences(text: str) -> str:
    """The JSON in a model's answer, when it wrapped it in a ``` block (Claude
    often does), or the text.

    - Valid JSON is returned as it is, so a fence inside one of its strings is
      never taken for a wrapper (Codex AI-1d review 1, finding 2).
    - Otherwise the first fenced block holding JSON, wherever it sits: after a
      line of prose, before "let me know if you'd like changes", or inline
      (review 2, finding 1).
    - Otherwise what the sites' own stripping accepted before AI-1d, when it
      is JSON: a lone closing fence, stray backticks, a bare "json" label
      (review 3, finding 1).
    - Otherwise, an answer that opens with a fence loses it (a block cut off
      before its closing fence), as the sites' own stripping did.
    """
    text = (text or "").strip()
    if _is_json(text):
        return text
    for block in _ANY_FENCE.finditer(text):
        inner = block.group(1).strip()
        if _is_json(inner):
            return inner
    lenient = _legacy_strip(text)
    if _is_json(lenient):
        return lenient
    if text.startswith("```"):
        inner = text.split("\n", 1)[1] if "\n" in text else text.lstrip("`")
        return inner.rstrip("`").strip()
    return text


def _legacy_strip(text: str) -> str:
    """Everything the sites' own stripping accepted before AI-1d (Codex AI-1d
    review 3): an opening fence line dropped, stray backticks at either end,
    and a bare "json" label, so `[...]\n```` and `json\n[...]` still read."""
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    text = text.strip().strip("`").strip()
    if text[:4].lower() == "json":
        text = text[4:].strip()
    return text
