"""AI-1 — the model switchboard (docs/AI-1-TICKET.md).

Every AI call names a TASK, never a model. `resolve(task)` answers which
(provider, model) pairs to use, best first:

  1. the choice saved for the task on the admin page (`ai_model_choices`,
     migration 045), when it is valid: each entry's provider has a key and,
     for token-priced tasks, the model has a price in ai_costs (OUT-19's rule:
     an unpriced model is never used); invalid entries are dropped, and a
     choice with none left is ignored (logged);
  2. otherwise the task's DEFAULT: exactly the model its call site used before
     AI-1, including the old Railway setting where there was one — so nothing
     changes until Mike picks (M1).

Choices are read through a short cache (a minute), so a change on the admin
page takes effect without a deploy, and a database problem never stops Aria:
the defaults are used and the problem is logged.

`openai_model(task)` serves call sites that still speak only OpenAI's API (the
first OpenAI entry of the resolved chain, else the default's). AI-1b and 1c
move call sites onto `ai_router` so other providers can serve them too.
"""
import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

PROVIDERS = ("openai", "anthropic", "xai")
KEYS = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "xai": "XAI_API_KEY"}
CACHE_SECONDS = 60


@dataclass(frozen=True)
class Task:
    label: str
    default: tuple                      # ((provider, model), ...), best first
    kind: str = "text"                  # text: priced by tokens; voice/speech/transcribe: by the minute or character
    legacy_env: Optional[str] = None    # the Railway variable that chose the OpenAI model before AI-1
    openai_only: bool = False           # no other provider offers it (realtime voice, speech)
    providers: tuple = field(default=PROVIDERS)
    # Models this task's call site is known to work with, or None for any priced
    # text model (OpenAI chat sites adapt their settings through chat_params).
    # Voice and speech are pinned: a different model may not serve the endpoint,
    # and speech is costed at a fixed per-character rate (Codex AI-1a review 1,
    # findings 3 and 4).
    compatible: Optional[tuple] = None
    # AI-1c (Codex review 1, finding 1): what the task's call site can really
    # use today. A site that still calls OpenAI's API once, with no failover,
    # takes one OpenAI model; the router-based sites (chat, outreach) take any
    # provider and fallbacks. AI-1d moves more sites onto the router.
    max_chain: int = 6
    # The cost-ledger purposes this task's calls are recorded under, which may
    # be shared with other tasks (finding 5); None: not tracked separately.
    ledger: Optional[tuple] = None


def _t(label, *chain, **kw):
    return Task(label, tuple(chain), **kw)


# Defaults are what each call site used on 20 Nov 2026 (tests/test_ai_models.py TODAY).
ONE_OPENAI = {"providers": ("openai",), "max_chain": 1}

TASKS = {
    "chat": _t("Aria chat: everyday questions", ("openai", "gpt-5"), ledger=("chat",)),
    "chat_complex": _t("Aria chat: complex jobs, money and analysis", ("openai", "gpt-5"), ledger=("chat_complex",)),
    "quote_chat": _t("Quote drafting in chat", ("openai", "gpt-4o"), ledger=("quote",), **ONE_OPENAI),
    "quote": _t("Quote estimator", ("openai", "gpt-5.4"), legacy_env="QUOTE_AI_MODEL", ledger=("quote",),
                **ONE_OPENAI),
    "reply_draft": _t("Email reply draft (one)", ("openai", "gpt-4o-mini"), ledger=("draft",), **ONE_OPENAI),
    "reply_drafts": _t("Email reply drafts (three tones)", ("openai", "gpt-5"), ledger=("draft",), **ONE_OPENAI),
    "inbox_classify": _t("Sorting the inbox", ("openai", "gpt-4o-mini"), ledger=("classify",), **ONE_OPENAI),
    "email_briefing": _t("Email briefing", ("openai", "gpt-5"), ledger=("briefing",), **ONE_OPENAI),
    "briefing": _t("CEO briefings", ("openai", "gpt-4o"), ledger=("briefing",), **ONE_OPENAI),
    "meeting": _t("Board meeting", ("openai", "gpt-5"), legacy_env="EXECUTIVE_MEETING_AI_MODEL",
                  ledger=("meeting",), **ONE_OPENAI),
    "support": _t("Help assistant", ("openai", "gpt-4o"), ledger=("chat", "support_draft"), **ONE_OPENAI),
    "call_summary": _t("Call summaries", ("openai", "gpt-4o-mini"), ledger=("call_summary",), **ONE_OPENAI),
    "voice_aria": _t("Aria's voice (realtime)", ("openai", "gpt-realtime-2"), kind="voice",
                     legacy_env="ARIA_REALTIME_MODEL", openai_only=True, compatible=("gpt-realtime-2",), max_chain=1),
    "voice_receptionist": _t("Receptionist (realtime)", ("openai", "gpt-realtime-2"), kind="voice",
                             legacy_env="RECEPTIONIST_REALTIME_MODEL", openai_only=True,
                             compatible=("gpt-realtime-2",), max_chain=1),
    "transcribe": _t("Speech to text", ("openai", "whisper-1"), kind="transcribe", openai_only=True,
                     compatible=("whisper-1",), max_chain=1),
    "speak": _t("Text to speech", ("openai", "tts-1"), kind="speech", openai_only=True, compatible=("tts-1",),
                max_chain=1, ledger=("voice",)),
    "voice_preview": _t("Receptionist voice previews", ("openai", "gpt-4o-mini-tts"), ("openai", "tts-1-hd"),
                        ("openai", "tts-1"), kind="speech", openai_only=True,
                        compatible=("gpt-4o-mini-tts", "tts-1-hd", "tts-1"), max_chain=3, ledger=("voice",)),
    # Outreach's purposes (services/ai_router.py keeps their defaults and env settings).
    "draft": _t("Outreach drafts", ("openai", "gpt-6.1-sol"), ledger=("draft",)),
    "research": _t("Outreach research", ("openai", "gpt-6.1-sol"), ledger=("research",)),
    "classify": _t("Sorting outreach replies", ("openai", "gpt-6-luna"), ledger=("classify",)),
    "wording": _t("Plain-English wording", ("openai", "gpt-6-luna"), ledger=("accountancy_pack",)),
}
ROUTER_PURPOSES = {"draft", "research", "classify", "wording"}

_cache = {"at": None, "choices": {}, "generation": 0}
_refreshing = threading.Lock()        # one background refresh at a time
_loading = threading.Lock()           # one load (background or not) at a time
_state = threading.Lock()             # invalidate() and a load's publication never overlap


def _now() -> float:
    return time.monotonic()


def _engine():
    from db import engine
    return engine


def invalidate() -> None:
    """Forget the cached choices (the admin page calls this after a change).
    A load already under way was reading the old choices: its result is
    dropped, never published (Codex AI-1a review 1, finding 5)."""
    with _state:
        _cache["generation"] += 1
        _cache["at"] = None
        _cache["choices"] = {}


def _parse(raw) -> Optional[list]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(value, list) or not value:
        return None
    out = []
    for entry in value:
        if not (isinstance(entry, dict) and entry.get("provider") in PROVIDERS
                and isinstance(entry.get("model"), str) and entry["model"].strip()):
            return None
        out.append((entry["provider"], entry["model"].strip()))
    return out


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _refresh_in_background() -> None:
    if not _refreshing.acquire(blocking=False):
        return                         # one refresh at a time

    def run():
        try:
            _load()
        finally:
            _refreshing.release()
    threading.Thread(target=run, name="ai-model-choices", daemon=True).start()


def _choices() -> dict:
    """The saved choices, at most a minute old. On the event loop the database
    is never read: the cached choices (or none, so the defaults) are used and a
    refresh runs in a thread (STAB-1: nothing blocks the loop)."""
    if _cache["at"] is not None and _now() - _cache["at"] < CACHE_SECONDS:
        return _cache["choices"]
    if _in_event_loop():
        _refresh_in_background()
        return _cache["choices"]
    return _load()


def _load() -> dict:
    with _loading:
        generation = _cache["generation"]
        loaded = _read()
        with _state:                   # the check and the publication are one step (review 2, finding 5)
            if generation == _cache["generation"]:
                _cache["at"], _cache["choices"] = _now(), loaded
        return loaded


def _read() -> dict:
    loaded = {}
    try:
        from sqlalchemy import text
        with _engine().connect() as conn:
            for task, chain in conn.execute(text("SELECT task, chain FROM ai_model_choices")):
                parsed = _parse(chain)
                if parsed is None:
                    logger.error("[AI] the saved model choice for %s is not valid; using its default", task)
                    continue
                loaded[str(task)] = parsed
    except Exception as exc:          # a missing table (before 045) or a database problem
        logger.warning("[AI] model choices unavailable (%s); using the defaults", type(exc).__name__)
        loaded = {}
    return loaded


def _base_model(model: str) -> str:
    """A fine-tuned id ("ft:gpt-5-mini:org::id") behaves as its base model."""
    m = (model or "").lower()
    return m.split(":")[1] if m.startswith("ft:") and ":" in m[3:] else m


def is_reasoning(model: str) -> bool:
    """gpt-5 and the o-series refuse max_tokens and any non-default
    temperature (BM-1); their -chat variants behave as ordinary chat models."""
    m = _base_model(model)
    return (m.startswith("gpt-5") or (len(m) > 1 and m[0] == "o" and m[1].isdigit())) and "-chat" not in m


def chat_params(model: str, *, max_tokens: Optional[int] = None, temperature: Optional[float] = None) -> dict:
    """The output-limit and temperature settings for one OpenAI Chat
    Completions call, in the form `model` accepts. A reasoning model refuses
    max_tokens and temperature (BM-1): it gets max_completion_tokens, with room
    for its reasoning, and the default temperature."""
    out = {}
    if is_reasoning(model):
        if max_tokens:
            out["max_completion_tokens"] = max(4 * int(max_tokens), 4000)
        return out
    if max_tokens:
        out["max_tokens"] = int(max_tokens)
    if temperature is not None:
        out["temperature"] = temperature
    return out


def chat_request(task_name: str, *, max_tokens: Optional[int] = None, temperature: Optional[float] = None) -> dict:
    """`model` plus its settings for an OpenAI Chat Completions call site."""
    model = openai_model(task_name)
    return {"model": model, **chat_params(model, max_tokens=max_tokens, temperature=temperature)}


def why_unusable(task_name: str, provider: str, model: str) -> Optional[str]:
    """None when the task can use this provider and model now; otherwise why
    not, in words for the admin page (AI-1c)."""
    task = TASKS[task_name]
    if provider not in KEYS:
        return f"{provider} is not a provider Business Hero knows"
    if provider not in task.providers or (task.openai_only and provider != "openai"):
        return f"{provider} can't serve this task (OpenAI only)"
    if task.compatible is not None and model not in task.compatible:
        return f"{model} is not one this task can use (only {', '.join(task.compatible)})"
    if task.kind == "text" and provider == "openai" and is_reasoning(model) and "-pro" in _base_model(model):
        return f"{model} answers only through the Responses API, which this task doesn't use"
    if not os.environ.get(KEYS[provider]):
        return f"{provider} has no key set (add {KEYS[provider]} in Railway)"
    if task.kind != "text":
        return None                   # metered by the minute or character, not ai_costs
    from services import ai_costs
    try:
        ai_costs.require_priced(provider, model)
    except ai_costs.Unpriced:
        return f"{provider}/{model} has no price, so its cost can't be recorded"
    return None


def _usable(task: Task, provider: str, model: str) -> bool:
    name = next(n for n, t in TASKS.items() if t is task)
    return why_unusable(name, provider, model) is None


def default(task_name: str) -> list:
    task = TASKS[task_name]
    chain = list(task.default)
    if task.legacy_env and os.environ.get(task.legacy_env):
        chain[0] = ("openai", os.environ[task.legacy_env].strip())
    return chain


def choice(task_name: str) -> Optional[list]:
    """The saved, valid choice for the task, or None. Never raises."""
    task = TASKS[task_name]
    chosen = _choices().get(task_name)
    if not chosen:
        return None
    usable = [(p, m) for p, m in chosen if _usable(task, p, m)]
    dropped = [f"{p}/{m}" for p, m in chosen if (p, m) not in usable]
    if dropped:
        logger.error("[AI] %s: ignoring %s (no key, no price, or not allowed for this task)",
                     task_name, ", ".join(dropped))
    if len(usable) > task.max_chain:      # saved before the limit: the call site uses only these
        logger.error("[AI] %s: using only the first %d of its saved models", task_name, task.max_chain)
        usable = usable[:task.max_chain]
    return usable or None


def resolve(task_name: str) -> list:
    """(provider, model) pairs to use for the task, best first."""
    if task_name not in TASKS:
        raise KeyError(f"Unknown AI task {task_name!r}")
    return choice(task_name) or default(task_name)


def openai_models(task_name: str) -> list:
    """The OpenAI models for a call site that only speaks OpenAI's API."""
    chosen = [m for p, m in resolve(task_name) if p == "openai"]
    return chosen or [m for p, m in default(task_name) if p == "openai"]


def openai_model(task_name: str) -> str:
    return openai_models(task_name)[0]
