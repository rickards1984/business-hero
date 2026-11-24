"""AI-1a — one model switchboard (docs/AI-1-TICKET.md).

Every AI call names a TASK; services.ai_models answers which provider and
model. On day one every task resolves to exactly the model it used before
(M1: "no change until Mike picks"); a choice saved in ai_model_choices
(migration 045) overrides it within a minute, without a deploy; a choice that
isn't priced or whose provider has no key is ignored, never half-used.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[1]

# Exactly what each call site used before AI-1a (checked in code, 20 Nov 2026).
TODAY = {
    "chat": [("openai", "gpt-5")],                    # assistant_chat.process_chat_message
    "quote_chat": [("openai", "gpt-6.1-sol")],        # assistant_chat quote drafting (ARIA-1a: Mike's choice)
    "quote": [("openai", "gpt-5.4")],                 # quoting_api (QUOTE_AI_MODEL)
    "reply_draft": [("openai", "gpt-6-luna"), ("openai", "gpt-4o-mini")],   # app/email/service (one draft)
    "reply_drafts": [("openai", "gpt-5")],            # app/email/service + assistant_tools (3 tones)
    "inbox_classify": [("openai", "gpt-6-luna"), ("openai", "gpt-4o-mini")],   # analyze_email_batch
    "email_briefing": [("openai", "gpt-5")],          # app/email/service briefing
    "briefing": [("openai", "gpt-5"), ("anthropic", "claude-sonnet-5-5")],   # services/briefing_generator
    "meeting": [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")],     # executive_meeting_orchestrator
    "support": [("openai", "gpt-5"), ("anthropic", "claude-sonnet-5-5")],    # support_api
    "call_summary": [("openai", "gpt-6-luna"), ("openai", "gpt-4o-mini")],   # openai_utils
    "voice_aria": [("openai", "gpt-realtime-2")],     # realtime_voice
    "voice_receptionist": [("openai", "gpt-realtime-2")],
    "transcribe": [("openai", "whisper-1")],
    "speak": [("openai", "tts-1")],                   # main.py /v1/tts
    "voice_preview": [("openai", "gpt-4o-mini-tts"), ("openai", "tts-1-hd"), ("openai", "tts-1")],
}
LEGACY_ENV = {"quote": "QUOTE_AI_MODEL", "meeting": "EXECUTIVE_MEETING_AI_MODEL",
              "voice_aria": "ARIA_REALTIME_MODEL", "voice_receptionist": "RECEPTIONIST_REALTIME_MODEL"}


@pytest.fixture
def m(monkeypatch, tmp_path):
    """The module against an empty choices table, keys set for every provider."""
    from services import ai_models
    engine = create_engine("sqlite:///" + str(tmp_path / "choices.sqlite"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE ai_model_choices (task TEXT PRIMARY KEY, chain TEXT, changed_by TEXT, "
                       "changed_at TEXT, previous TEXT)"))
    monkeypatch.setattr(ai_models, "_engine", lambda: engine)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    for name in LEGACY_ENV.values():
        monkeypatch.delenv(name, raising=False)
    clock = SimpleNamespace(t=1000.0)
    monkeypatch.setattr(ai_models, "_now", lambda: clock.t)
    ai_models.invalidate()
    yield SimpleNamespace(mod=ai_models, engine=engine, clock=clock)
    ai_models.invalidate()


def choose(m, task, chain):
    with m.engine.begin() as c:
        c.execute(text("DELETE FROM ai_model_choices WHERE task = :t"), {"t": task})
        c.execute(text("INSERT INTO ai_model_choices (task, chain, changed_by, changed_at) VALUES (:t, :c, 'mike', 'now')"),
                  {"t": task, "c": json.dumps([{"provider": p, "model": mo} for p, mo in chain])})


# ------------------------------------------------------- day one: no change ---

def test_every_task_is_known(m):
    assert set(m.mod.TASKS) >= set(TODAY)


@pytest.mark.parametrize("task", sorted(TODAY))
def test_with_no_choice_every_task_uses_todays_model(m, task):
    assert m.mod.resolve(task) == TODAY[task]
    assert m.mod.openai_model(task) == next(mo for p, mo in TODAY[task] if p == "openai")


@pytest.mark.parametrize("task,env", sorted(LEGACY_ENV.items()))
def test_the_old_railway_setting_still_chooses_the_openai_model(m, monkeypatch, task, env):
    monkeypatch.setenv(env, "gpt-legacy-x")
    m.mod.invalidate()
    assert m.mod.openai_model(task) == "gpt-legacy-x"


def test_an_unknown_task_is_refused(m):
    with pytest.raises(KeyError):
        m.mod.resolve("no_such_task")


def test_the_speech_fallbacks_are_kept_in_order(m):
    assert m.mod.openai_models("voice_preview") == ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"]


# ------------------------------------------------------------- choices ---

def test_a_saved_choice_is_used(m):
    choose(m, "chat_complex", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    m.mod.invalidate()
    assert m.mod.resolve("chat_complex") == [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")]


def test_a_choice_takes_effect_within_a_minute_without_a_deploy(m):
    assert m.mod.resolve("briefing") == TODAY["briefing"]
    choose(m, "briefing", [("openai", "gpt-5")])
    m.clock.t += 30
    assert m.mod.resolve("briefing") == TODAY["briefing"]      # cached for up to a minute
    m.clock.t += 31
    assert m.mod.resolve("briefing") == [("openai", "gpt-5")]


def test_an_unpriced_choice_is_ignored_and_todays_model_used(m, caplog):
    choose(m, "briefing", [("openai", "gpt-made-up")])
    m.mod.invalidate()
    assert m.mod.resolve("briefing") == TODAY["briefing"]
    assert "gpt-made-up" in caplog.text


def test_a_choice_whose_provider_has_no_key_is_skipped(m, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    choose(m, "chat_complex", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    m.mod.invalidate()
    assert m.mod.resolve("chat_complex") == [("openai", "gpt-5")]


def test_a_choice_with_no_usable_entry_falls_back_to_today(m, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    choose(m, "briefing", [("anthropic", "claude-opus-5-5")])
    m.mod.invalidate()
    assert m.mod.resolve("briefing") == TODAY["briefing"]


@pytest.mark.parametrize("raw", ["not json", "{}", "[]", '[{"provider": "nope", "model": "x"}]',
                                 '[{"provider": "openai"}]', '[{"provider": "openai", "model": 5}]'])
def test_a_malformed_choice_is_ignored(m, raw):
    with m.engine.begin() as c:
        c.execute(text("INSERT INTO ai_model_choices (task, chain) VALUES ('briefing', :c)"), {"c": raw})
    m.mod.invalidate()
    assert m.mod.resolve("briefing") == TODAY["briefing"]


def test_a_database_problem_never_stops_aria(m, monkeypatch):
    def broken():
        raise RuntimeError("database down")
    monkeypatch.setattr(m.mod, "_engine", broken)
    m.mod.invalidate()
    assert m.mod.resolve("chat") == [("openai", "gpt-5")]


def test_an_openai_call_site_uses_the_first_openai_choice(m):
    """Until a call site can speak to other providers (AI-1b/1c), it uses the
    first OpenAI model in the chosen chain."""
    choose(m, "briefing", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    m.mod.invalidate()
    assert m.mod.openai_model("briefing") == "gpt-5"


def test_an_openai_call_site_with_no_openai_choice_keeps_todays_model(m):
    choose(m, "briefing", [("anthropic", "claude-opus-5-5")])
    m.mod.invalidate()
    assert m.mod.openai_model("briefing") == "gpt-5"


@pytest.mark.parametrize("task,model", [("voice_aria", "gpt-5"), ("voice_aria", "gpt-realtime-3"),
                                        ("transcribe", "gpt-5"), ("speak", "tts-1-hd")])
def test_voice_and_speech_accept_only_models_their_code_is_known_to_serve(m, task, model):
    """Codex AI-1a review 1, finding 4: a realtime endpoint can't serve gpt-5,
    and speech is costed per character at tts-1's rate, so a dearer voice
    model would be under-recorded. Pinned until each is checked."""
    choose(m, task, [("openai", model)])
    m.mod.invalidate()
    assert m.mod.resolve(task) == TODAY[task]


def test_a_voice_preview_choice_within_its_known_models_is_used(m):
    choose(m, "voice_preview", [("openai", "tts-1-hd"), ("openai", "tts-1")])
    m.mod.invalidate()
    assert m.mod.openai_models("voice_preview") == ["tts-1-hd", "tts-1"]


def test_voice_stays_with_openai(m):
    choose(m, "voice_aria", [("anthropic", "claude-opus-5-5")])
    m.mod.invalidate()
    assert m.mod.resolve("voice_aria") == [("openai", "gpt-realtime-2")]


# ------------------------------------------------------ outreach's router ---

def test_the_outreach_router_reads_a_saved_choice(m):
    from services import ai_router
    choose(m, "research", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-6.1-sol")])
    m.mod.invalidate()
    assert ai_router.chain("research")[:2] == [("anthropic", "claude-opus-5-5"), ("openai", "gpt-6.1-sol")]


def test_the_outreach_router_is_unchanged_without_a_choice(m):
    from services import ai_router
    assert ai_router.chain("research") == [("openai", "gpt-6.1-sol"), ("xai", "grok-4.7"),
                                           ("anthropic", "claude-sonnet-4-5")]


# --------------------------------------------------------------- prices ---

@pytest.mark.parametrize("provider,model,expected", [
    ("openai", "gpt-5", (98, 787)),                 # $1.25 / $10 per million (OpenAI), £1 = $1.27
    ("anthropic", "claude-opus-5-5", (315, 1575)),  # $4 / $20 (Anthropic pricing page, 20 Nov 2026)
    ("anthropic", "claude-sonnet-5-5", (157, 787)), # $2 / $10
])
def test_the_new_models_are_priced(provider, model, expected):
    from services import ai_costs
    assert ai_costs.price(provider, model)[:2] == expected


def test_aria_s_chat_is_costed_at_gpt_5_s_real_price():
    """Before AI-1a gpt-5 had no price and every chat was recorded at the
    'unknown model' rate (1600p/6400p per million), about 16x too high."""
    from services import ai_costs
    assert ai_costs.cost("openai", "gpt-5", 1_000_000, 0) == pytest.approx(98)


# ---------------------------------------------- no model named elsewhere ---
# Syntax-aware (Codex AI-1a review 1, finding 6): spacing, line breaks and a
# constant passed in all count; comments and strings that are not arguments
# do not.

import ast

ALLOWED = {"services/ai_models.py", "services/ai_router.py", "services/ai_costs.py", "services/profit_guard.py"}
MODEL_SETTING = re.compile(r"MODEL$")
# A constant that looks like an AI model id, wherever it is assigned
# (Codex AI-1a review 2, finding 6: annotated and function-local constants).
MODEL_ID = re.compile(r"^(ft:)?(gpt|chatgpt|o\d|claude|grok|whisper|tts|text-embedding|dall-e|gemini)", re.I)


def named_models(source: str) -> list:
    """Line numbers where code names an AI model instead of a task."""
    tree = ast.parse(source)
    consts = set()
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        value = getattr(n, "value", None)
        if (targets and isinstance(value, ast.Constant) and isinstance(value.value, str)
                and MODEL_ID.match(value.value)):
            consts |= {t.id for t in targets if isinstance(t, ast.Name)}
    hits = []

    def literal(node):
        return (isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value[:1].isalpha()) or \
               (isinstance(node, ast.Name) and node.id in consts)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "model" and literal(node.value):
            hits.append(node.value.lineno)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "model" and literal(v):
                    hits.append(v.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("getenv", "get") and len(node.args) >= 2
              and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
              and MODEL_SETTING.search(node.args[0].value) and literal(node.args[1])):
            hits.append(node.lineno)
    return sorted(hits)


@pytest.mark.parametrize("source,count", [
    ('client.create(model="gpt-5")', 1),
    ('client.create(model = "gpt-5")', 1),
    ('client.create(\n    messages=m,\n    model=\n        "gpt-5",\n)', 1),
    ('M = "gpt-5"\nclient.create(model=M)', 1),
    ('payload = {"model": "gpt-4o"}', 1),
    ('X = os.getenv("QUOTE_AI_MODEL", "gpt-5.4")', 1),
    ('X = os.environ.get("ARIA_DRAFT_MODEL", "gpt-4o")', 1),
    ('# client.create(model="example")', 0),                      # a comment
    ('note = \'call it with model="x"\'', 0),                     # text, not an argument
    ('client.create(model=ai_models.openai_model("chat"))', 0),
    ('client.create(**ai_models.chat_request("support", max_tokens=1))', 0),
    ('plan = "single"\nbilling(model=plan_kind)', 0),
    ('M: str = "gpt-5"\nclient.create(model=M)', 1),                       # annotated (review 2)
    ('def f():\n    M = "gpt-5"\n    client.create(model=M)', 1),          # function-local (review 2)
    ('model = "single"\nbilling(model=model)', 0),                         # not a model id
    ('M = "ft:gpt-4o-mini:org::id"\nclient.create(model=M)', 1),          # fine-tuned (review 3)
])
def test_the_guard_reads_code_not_text(source, count):
    assert len(named_models(source)) == count


def test_no_ai_call_names_a_model_outside_the_switchboard():
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", ".venv/")) or rel in ALLOWED or "/site-packages/" in rel:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        for n in named_models(source):
            offenders.append(f"{rel}:{n}: {source.splitlines()[n - 1].strip()[:100]}")
    assert not offenders, "name a task via services.ai_models instead:\n" + "\n".join(offenders)


# ------------------------------------------------- never blocks the loop ---

def test_on_the_event_loop_the_database_is_never_read(m, monkeypatch):
    """STAB-1: a slow database must not hold up the server. On the loop the
    cached choices are used and the refresh happens in a thread."""
    import asyncio
    import threading
    import time
    choose(m, "briefing", [("openai", "gpt-5")])
    real = m.mod._engine
    started, release = threading.Event(), threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return real()
    monkeypatch.setattr(m.mod, "_engine", slow)

    async def on_loop():
        t0 = time.monotonic()
        out = m.mod.resolve("briefing")
        return out, time.monotonic() - t0
    out, took = asyncio.run(on_loop())
    assert out == TODAY["briefing"] and took < 0.1               # defaults at once, no wait
    assert started.wait(2)                                         # the refresh started in a thread
    release.set()
    for _ in range(50):
        if m.mod._cache["choices"].get("briefing"):
            break
        time.sleep(0.02)
    assert m.mod.resolve("briefing") == [("openai", "gpt-5")]     # and landed


def test_off_the_loop_a_stale_cache_is_refreshed_at_once(m):
    choose(m, "briefing", [("openai", "gpt-5")])
    m.mod.invalidate()
    assert m.mod.resolve("briefing") == [("openai", "gpt-5")]


# --------------------------------------- settings follow the chosen model ---

@pytest.mark.parametrize("model,expected", [
    ("gpt-4o", {"max_tokens": 800, "temperature": 0.3}),
    ("gpt-4o-mini", {"max_tokens": 800, "temperature": 0.3}),
    ("gpt-5", {"max_completion_tokens": 4000}),                 # BM-1: no temperature, no max_tokens
    ("gpt-5.4", {"max_completion_tokens": 4000}),
    ("o4-mini", {"max_completion_tokens": 4000}),
    ("gpt-5-chat-latest", {"max_tokens": 800, "temperature": 0.3}),
])
def test_chat_settings_follow_the_model(model, expected):
    """Codex AI-1a review 1, finding 3: choosing gpt-5 for a task whose code
    sent temperature and max_tokens would have broken it. The settings now
    follow the model; this also mends the email briefing and the three-tone
    reply drafts, which already ran on gpt-5 with settings it refuses."""
    from services import ai_models
    assert ai_models.chat_params(model, max_tokens=800, temperature=0.3) == expected


def test_a_large_limit_keeps_room_for_reasoning():
    from services import ai_models
    assert ai_models.chat_params("gpt-5", max_tokens=1500) == {"max_completion_tokens": 6000}


def test_a_chat_request_names_its_model_once(m):
    choose(m, "support", [("openai", "gpt-5")])
    m.mod.invalidate()
    assert m.mod.chat_request("support", max_tokens=800, temperature=0.3) == {
        "model": "gpt-5", "max_completion_tokens": 4000}


def test_a_responses_only_model_is_never_chosen_for_a_chat_site(m, monkeypatch):
    monkeypatch.setenv("AI_PRICES_JSON", '{"openai/gpt-5-pro": [1000, 8000, 1]}')
    choose(m, "support", [("openai", "gpt-5-pro")])
    m.mod.invalidate()
    assert m.mod.resolve("support") == TODAY["support"]


# ------------------------------------------- a stale load is never published ---

def test_a_load_that_began_before_a_change_is_dropped(m, monkeypatch):
    """Codex AI-1a review 1, finding 5: a refresh read the old choice, paused,
    then published it after invalidate(), so the change was hidden a minute."""
    import threading
    choose(m, "briefing", [("openai", "gpt-4o-mini")])
    real_read = m.mod._read
    reading, resume = threading.Event(), threading.Event()

    def slow_read():
        out = real_read()
        reading.set()
        resume.wait(5)
        return out
    monkeypatch.setattr(m.mod, "_read", slow_read)
    worker = threading.Thread(target=m.mod._load)
    worker.start()
    assert reading.wait(2)
    choose(m, "briefing", [("openai", "gpt-4.1")])          # Mike changes it meanwhile
    m.mod.invalidate()
    resume.set()
    worker.join(5)
    monkeypatch.setattr(m.mod, "_read", real_read)
    assert m.mod.resolve("briefing") == [("openai", "gpt-4.1")]


def test_an_older_read_never_overwrites_a_newer_one(m, monkeypatch):
    """Two loads in the same generation (a change made by another server, so
    no invalidate here): the one that read later must be the one that stays."""
    import threading
    import time
    choose(m, "briefing", [("openai", "gpt-4o-mini")])
    real_read = m.mod._read
    first = {"done": False}
    reading, resume = threading.Event(), threading.Event()

    def read():
        out = real_read()
        if not first["done"]:
            first["done"] = True
            reading.set()
            resume.wait(5)               # the old read stalls
        return out
    monkeypatch.setattr(m.mod, "_read", read)
    old = threading.Thread(target=m.mod._load)
    old.start()
    assert reading.wait(2)
    choose(m, "briefing", [("openai", "gpt-4.1")])           # changed elsewhere
    newer = threading.Thread(target=m.mod._load)
    newer.start()
    time.sleep(0.2)
    resume.set()
    old.join(5)
    newer.join(5)
    assert m.mod._cache["choices"]["briefing"] == [("openai", "gpt-4.1")]



def test_an_invalidate_during_publication_is_never_undone(m, monkeypatch):
    """Codex AI-1a review 2, finding 5: a loader past its generation check,
    then paused, published old choices after invalidate()."""
    import threading
    import time
    choose(m, "briefing", [("openai", "gpt-4o-mini")])
    real_now = m.mod._now
    fired = {"done": False}
    worker = {}

    def now_during_publish():
        if not fired["done"]:
            fired["done"] = True
            worker["t"] = threading.Thread(target=m.mod.invalidate)
            worker["t"].start()
            time.sleep(0.2)              # let invalidate() run, if it can
        return real_now()
    monkeypatch.setattr(m.mod, "_now", now_during_publish)
    m.mod._load()
    worker["t"].join(5)
    monkeypatch.setattr(m.mod, "_now", real_now)
    assert m.mod._cache["at"] is None and m.mod._cache["choices"] == {}   # the invalidate stands


@pytest.mark.parametrize("model,rate", [("tts-1", 1.2), ("tts-1-hd", 2.4), ("gpt-4o-mini-tts", 2.4),
                                        ("tts-9-ultra", 2.4)])
def test_speech_is_costed_at_its_own_model_s_rate(monkeypatch, model, rate):
    """Codex AI-1a review 2, finding 4: every speech model was recorded at
    tts-1's rate, so a dearer preview voice was under-recorded."""
    from services import ai_costs, profit_guard
    seen = {}

    class S:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def commit(self): pass
    monkeypatch.setattr("sqlmodel.Session", S)
    monkeypatch.setattr(profit_guard, "_engine", lambda: None)
    monkeypatch.setattr(ai_costs, "record", lambda s, bid, **kw: seen.update(kw))
    profit_guard._record_speech(None, {"model": model, "input": "x" * 1000})
    assert seen["pence"] == pytest.approx(rate) and seen["model"] == model
