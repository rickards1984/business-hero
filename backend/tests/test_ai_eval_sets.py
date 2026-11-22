"""AI-1d — "Test this model" for the help assistant and the briefings, and
the AI-1c review 3 follow-ups on grading and the deadline."""
import json
import time
from types import SimpleNamespace

import pytest


def r(content):
    return SimpleNamespace(content=content, tool_calls=[], truncated=False)


def check(set_name, case_name):
    from services import ai_eval
    return next(c["check"] for c in ai_eval.CASES[set_name] if c["name"] == case_name)


# ------------------------------------------------------------ the sets ---

def test_the_help_assistant_and_briefings_can_be_tested_on_the_admin_page():
    from services import ai_eval
    assert ai_eval.has_cases("support") and ai_eval.has_cases("briefing")
    assert not ai_eval.has_cases("inbox_classify")


GOOD_SUPPORT = {
    "Answers from the knowledge base": "Go to Settings → Email and click Connect Gmail.\n[CATEGORY: how-to] [CONFIDENCE: 0.9]",
    "Hands over when asked for a person": "Of course: I'll pass you to the team. [ESCALATE]\n[CATEGORY: general] [CONFIDENCE: 0.5]",
    "Never invents a policy": "That isn't in my guides, so I'll pass it to the team to confirm.\n[CATEGORY: billing] [CONFIDENCE: 0.3]",
    "Quotes the price it was given": "Pro is £129 a month.\n[CATEGORY: billing] [CONFIDENCE: 0.9]",
}
BAD_SUPPORT = {
    "Answers from the knowledge base": "Go to Settings → Email and click Connect Gmail.",          # no tag
    "Hands over when asked for a person": "I can help with anything you need!",
    "Never invents a policy": "Yes, you get a pro-rata refund of £64.50.",
    "Quotes the price it was given": "Pro is £99 a month.\n[CATEGORY: billing] [CONFIDENCE: 0.9]",
}


@pytest.mark.parametrize("name", GOOD_SUPPORT)
def test_each_support_case_passes_a_good_answer_and_fails_a_bad_one(name):
    assert check("support", name)(r(GOOD_SUPPORT[name]))[0] is True
    ok, why = check("support", name)(r(BAD_SUPPORT[name]))
    assert ok is False and why


WEEKLY = ("📊 Week to 21 Nov\nRevenue £4,200, ↑20% on last week's £3,500. Harbour Lettings owes £750 (12 days).\n"
          "===JSON===\n```json\n" + json.dumps({"observations": [], "suggestions": [], "action_options": [
              {"number": n, "label": f"Action {n}", "type": "x", "config": {}} for n in (1, 2, 3)]}) + "\n```")
PULSE = "🌅 Good morning, Mike! Here's your daily pulse:\n- Harbour Lettings owes £750\n- 2 missed calls\nAnything you'd like me to handle?"


@pytest.mark.parametrize("name,good,bad", [
    ("Daily pulse: short, and opens right", PULSE, "Morning! " + "x" * 900),
    ("Daily pulse: flags the overdue invoice", PULSE, "🌅 Good morning, Mike! All quiet."),
    ("Weekly: the shape the app reads", WEEKLY, WEEKLY.split("===JSON===")[0]),
    ("Weekly: right numbers and change", WEEKLY, WEEKLY.replace("↑20%", "↑35%").replace("£4,200", "£4,700")),
])
def test_each_briefing_case_passes_a_good_answer_and_fails_a_bad_one(name, good, bad):
    assert check("briefing", name)(r(good))[0] is True
    ok, why = check("briefing", name)(r(bad))
    assert ok is False and why


def test_the_weekly_shape_wants_three_to_five_actions():
    data = {"observations": [], "suggestions": [], "action_options": [{"number": 1}]}
    ok, why = check("briefing", "Weekly: the shape the app reads")(r("📊 Week in brief: revenue up 20% to £4,200.\n===JSON===\n" + json.dumps(data)))
    assert ok is False and "3 to 5" in why


def test_a_text_set_is_asked_without_tools_and_with_its_own_limit(monkeypatch):
    from services import ai_chat, ai_eval
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    calls = []

    def fake(provider, model, messages, tools, timeout, factory, **opts):
        calls.append((tools, opts))
        return r(GOOD_SUPPORT["Quotes the price it was given"]), SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": fake, "anthropic": fake, "xai": fake})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    from services import profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    out = ai_eval.run("support", "openai", "gpt-4o")
    assert out["cases"] == 4 and all(t is None and o == {"max_tokens": 800} for t, o in calls)


def test_a_text_set_s_most_possible_cost_uses_its_limit():
    from services import ai_eval
    support = ai_eval.worst_pence("support", "anthropic", "claude-opus-5-5")
    chat = ai_eval.worst_pence("chat", "anthropic", "claude-opus-5-5")
    assert 0 < support < chat                            # 800 output tokens a case, not chat's 8,192


def test_testing_opus_against_the_help_assistant_s_default_fits_the_cap():
    from services import ai_eval
    worst = ai_eval.worst_pence("support", "anthropic", "claude-opus-5-5") + \
        ai_eval.worst_pence("support", "openai", "gpt-4o")
    assert worst <= ai_eval.MAX_RUN_PENCE
    worst = ai_eval.worst_pence("briefing", "anthropic", "claude-opus-5-5") + \
        ai_eval.worst_pence("briefing", "openai", "gpt-4o")
    assert worst <= ai_eval.MAX_RUN_PENCE


# ------------------------------------------- review 3 follow-ups: grading ---

@pytest.mark.parametrize("content,ok", [
    ("Harbour and Northgate owe £750 and £500 respectively; £1,250 total.", True),     # was a false failure
    ("Harbour and Northgate owe £500 and £750 respectively; £1,250 total.", False),
    ("£1,250 total; Harbour £500 / Northgate £750.", False),                            # was a false pass
    ("£1,250 total. Harbour £500 Northgate £750.", False),                              # no separator at all
    ("£1,250 total. Harbour £750 Northgate £500.", False),                              # can't tell whose is whose
    ("£1,250 total; Harbour owes £1,250; Northgate owes £500.", False),                 # was a false pass
    ("You're owed £1,250 — £750 from Harbour Lettings and £500 from Northgate Estates.", True),
    ("£1,250 in total: Harbour Lettings £750 (12 days late), Northgate Estates £500 (5 days).", True),
    ("Harbour Lettings and Northgate Estates owe £1,250 between them.", True),
    ("You're owed £1,250 on INV-101 and INV-104, due since 10:30 on 10 November 2026.", True),
])
def test_balances_are_attributed_to_the_right_customer(content, ok):
    from services import ai_eval
    assert ai_eval._uses_the_result(r(content))[0] is ok, ai_eval._uses_the_result(r(content))


# ------------------------------------------ review 3 follow-ups: deadline ---

def test_the_guard_s_own_time_counts_against_the_deadline(monkeypatch):
    """A slow guard query no longer pushes a call past the deadline."""
    from services import ai_chat, ai_eval, profit_guard
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    timeouts = []

    def fake(provider, model, messages, tools, timeout, factory, **opts):
        timeouts.append(timeout)
        return r("ok"), None
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": fake, "anthropic": fake, "xai": fake})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: time.sleep(0.3) or True)
    monkeypatch.setattr(ai_eval, "MIN_CALL_SECONDS", 0.01)
    deadline = time.monotonic() + 0.5
    ai_eval.run("support", "openai", "gpt-4o", deadline=deadline)
    assert timeouts and timeouts[0] <= 0.2 + 0.05


# ------------------------------------------------ Codex AI-1d review 1 ---

@pytest.mark.parametrize("content,ok", [
    ("Yes, cancellations receive a full refund. The team will process it.", False),            # finding 3
    ("You'll get a pro-rata refund: I'll ask the team.", False),
    ("Refunds aren't covered in my guides, so I'll pass this to the team to confirm.", True),
    ("I'm not sure about that one: I'll pass it on to a colleague.", True),
    ("I don't have that in my guides.", False),                                                 # no handoff
    ("I'm not sure, but you'll get a full refund; the team can confirm.", False),              # hedged, still a promise
    ("Refunds are handled by the team.", False),                                                # no "I don't know"
    ("You'll get a full refund whether you cancel early or late. I'm not sure about fees; ask the team.", False),
])
def test_the_refund_case_wants_an_honest_handoff_and_no_promise(content, ok):
    assert check("support", "Never invents a policy")(r(content + "\n[CATEGORY: billing] [CONFIDENCE: 0.3]"))[0] is ok


@pytest.mark.parametrize("content,ok", [
    ("Pro costs £269 a month; Business costs £129.", False),                                    # finding 3
    ("Pro is £129 a month, and Business is £269.", True),
    ("Business Hero's Pro plan is £129 a month.", True),                       # the product's name, not the plan
    ("The Pro plan is £129 a month: we process payments monthly.", True),      # "process" is not "pro"
    ("Pro is £129 a month. Business is £269 with professional support.", True),  # "professional" is not "pro"
])
def test_the_price_case_wants_each_plan_s_own_price(content, ok):
    assert check("support", "Quotes the price it was given")(r(content + "\n[CATEGORY: billing] [CONFIDENCE: 0.9]"))[0] is ok


def test_weekly_actions_must_be_usable():
    """Finding 4: {"action_options": [1, 2, 3]} passed."""
    body = "📊 Week to 21 Nov: revenue up 20% to £4,200 on last week's £3,500.\n===JSON===\n"
    shape = check("briefing", "Weekly: the shape the app reads")
    assert shape(r(body + json.dumps({"action_options": [1, 2, 3]})))[0] is False
    assert shape(r(body + json.dumps({"action_options": [{"number": n, "label": ""} for n in (1, 2, 3)]})))[0] is False
    assert shape(r(body + json.dumps({"action_options": [{"number": n, "label": f"Do {n}"} for n in (1, 2, 3)]})))[0] is True
    assert shape(r("===JSON===\n" + json.dumps({"action_options": [{"number": n, "label": "x"} for n in (1, 2, 3)]})))[0] is False


@pytest.mark.parametrize("content,ok", [
    ("Revenue fell 20% to £4,200 from £3,500.", False),                                          # finding 4
    ("Revenue £3,500, up 20% on last week's £4,200.", False),                                    # swapped
    ("Revenue rose 20% to £4,200 from £3,500.", True),
    ("Revenue £4,200 (↑20% on last week's £3,500). Harbour Lettings owes £750.", True),
    ("Revenue was £4,200, 20% higher than the £3,500 the week before.", True),
])
def test_the_weekly_change_must_go_the_right_way(content, ok):
    assert check("briefing", "Weekly: right numbers and change")(r(content))[0] is ok


def test_each_briefing_case_uses_the_site_s_own_limit():
    """Finding 5: the pulse is asked for 400 tokens in production, not 2,000."""
    from services import ai_eval
    limits = {c["name"]: c.get("max_tokens") for c in ai_eval.CASES["briefing"]}
    assert limits["Daily pulse: short, and opens right"] == 400 == limits["Daily pulse: flags the overdue invoice"]
    assert limits["Weekly: the shape the app reads"] == 2000
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "services/briefing_generator.py").read_text()
    assert "max_tokens=400, temperature=0.3)" in source and "max_tokens=2000, temperature=0.4)" in source


def test_a_pulse_cut_off_at_its_limit_fails(monkeypatch):
    from services import ai_chat, ai_eval, profit_guard
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    asked = []

    def fake(provider, model, messages, tools, timeout, factory, **opts):
        asked.append(opts["max_tokens"])
        return SimpleNamespace(content="🌅 Good morning, Mike! Here", tool_calls=[], truncated=True), None
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": fake, "anthropic": fake, "xai": fake})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    out = ai_eval.run("briefing", "openai", "gpt-4o")
    assert asked == [400, 400, 2000, 2000] and out["passed"] == 0
    assert all("cut off" in c["why"] for c in out["results"])


@pytest.mark.parametrize("content,ok", [
    ("Harbour owes £1,250 in total. Northgate owes £500.", False),                               # finding 8
    ("Harbour Lettings owes £750 of the £1,250 total; Northgate £500.", True),
    ("Harbour Lettings and Northgate Estates owe £1,250 between them.", True),
])
def test_the_total_is_never_one_customer_s_balance(content, ok):
    from services import ai_eval
    assert ai_eval._uses_the_result(r(content))[0] is ok, ai_eval._uses_the_result(r(content))


# ------------------------------------------------ Codex AI-1d review 2 ---

@pytest.mark.parametrize("content", [
    "I can't confirm whether a full refund is available; I'll ask the team.",                 # finding 2
    "I don’t have that information; I’ll pass this to the team.",                              # curly apostrophes
])
def test_honest_uncertainty_about_refunds_passes(content):
    assert check("support", "Never invents a policy")(r(content + "\n[CATEGORY: billing] [CONFIDENCE: 0.3]"))[0] is True


@pytest.mark.parametrize("content,ok", [
    ("Revenue is up 20% to £4,200 from £3,500, so it did not fall.", True),                    # finding 3
    ("Last week revenue was £3,500, compared with £4,200 this week, up 20%.", True),
    ("Revenue is £3,500 this week, up 20% from the previous £4,200.", False),
    ("Revenue £4,200, up 20% on last week’s £3,500.", True),
])
def test_the_weekly_change_reads_who_each_amount_belongs_to(content, ok):
    assert check("briefing", "Weekly: right numbers and change")(r(content))[0] is ok


@pytest.mark.parametrize("content,ok", [
    ("The Pro plan costs £129 a month for your business.", True),                               # finding 4
    ("Pro is £129; the Business plan is £269.", True),
    ("Pro is £129; the Business plan is £129.", False),
])
def test_an_ordinary_business_is_not_the_business_plan(content, ok):
    assert check("support", "Quotes the price it was given")(r(content + "\n[CATEGORY: billing] [CONFIDENCE: 0.9]"))[0] is ok


@pytest.mark.parametrize("content,ok", [
    ("Harbour owes £1,250 in total and Northgate owes £500.", False),                           # finding 5
    ("Harbour pays £750 while Northgate owes £1,250 in total.", False),                         # not shared: £750 between
    ("Harbour Lettings and Northgate Estates owe £1,250 between them.", True),
    ("Harbour Lettings and Northgate Estates owe £1,250 in total: £750 and £500 respectively.", True),
])
def test_a_shared_total_needs_every_name_before_it(content, ok):
    from services import ai_eval
    assert ai_eval._uses_the_result(r(content))[0] is ok, ai_eval._uses_the_result(r(content))
