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
RETRIES = 1                    # each site's OpenAI client retried once; kept, before failing over


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
    kill switch, or ai_router.AllProvidersFailed when nothing answers."""
    from services import profit_guard
    business_id, purpose = _attribution(task, business_id, purpose)
    if purpose not in profit_guard.ESSENTIAL and not profit_guard.permits(purpose):
        raise profit_guard.Paused(f"{purpose} paused: this month's costs have reached the kill threshold of income")
    tried = []
    for provider, model in ai_models.resolve(task):
        if ai_router._is_down(provider) or not os.environ.get(ai_models.KEYS.get(provider, "")):
            continue
        worst = _worst(provider, model, messages, max_tokens)

        def cost(usage, estimated_anyway=False):
            got = ai_chat._tokens(usage)
            tokens = got or worst
            ai_chat._record(business_id, purpose=purpose, provider=provider, model=model,
                            input_tokens=tokens[0], output_tokens=tokens[1],
                            estimated=got is None or estimated_anyway)
        try:
            reply, usage = ai_chat._ADAPTERS[provider](provider, model, messages, None, timeout, None,
                                                       max_tokens=max_tokens, temperature=temperature,
                                                       retries=RETRIES)
        except ai_chat.Rejected as exc:        # refused before any work: not billed, not an outage
            tried.append(f"{provider}/{model}")
            logger.warning("[AI] %s: %s/%s refused the request (%s); trying the next model", task, provider, model, exc)
            continue
        except ai_router.ProviderError as exc:
            cost(exc.usage)
            if not isinstance(exc, ai_chat.Truncated):
                ai_router._trip(provider)
            tried.append(f"{provider}/{model}")
            logger.warning("[AI] %s: %s/%s failed (%s); trying the next model", task, provider, model, exc)
            continue
        cost(usage)
        content = (reply.content or "").strip()
        if not content:                        # billed, but no answer: the next model, not an outage
            tried.append(f"{provider}/{model}")
            logger.warning("[AI] %s: %s/%s gave an empty answer; trying the next model", task, provider, model)
            continue
        return SimpleNamespace(content=content, provider=provider, model=model,
                               truncated=bool(getattr(reply, "truncated", False)))
    raise ai_router.AllProvidersFailed(f"No AI model could answer {task}" + (f" (tried {', '.join(tried)})" if tried else ""))


async def acomplete(task: str, messages: list, **kwargs):
    """`complete` in a worker thread, so a slow model never blocks the event
    loop. The surrounding attribution goes with it (to_thread copies the
    context)."""
    return await asyncio.to_thread(complete, task, messages, **kwargs)


_FENCE = re.compile(r"```[a-zA-Z]*\s*\n?(.*?)\n?\s*```", re.S)


def strip_fences(text: str) -> str:
    """JSON a model wrapped in a ``` block (Claude often does), or the text."""
    text = (text or "").strip()
    match = _FENCE.search(text)
    return match.group(1).strip() if match else text
