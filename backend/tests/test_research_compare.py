"""OUT-19: the side-by-side model comparison reads only, verifies with the real
checks, and reports each model's verified contacts and cost."""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import json
from types import SimpleNamespace

from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, db  # noqa: F401
from test_outreach_research import World, gatekeeper, person, started


def counts(db):
    with db.connect() as c:
        return tuple(c.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                     for t in ("outreach_prospects", "outreach_evidence", "usage_meters", "outreach_enrolments"))


def test_each_model_is_scored_on_verified_contacts_and_nothing_is_stored(db):
    from services import ai_router, research_compare
    biz, brand, lia, campaign = started(db)
    world = World([])
    good = [person(i) for i in range(5)] + [gatekeeper(50)]
    world.not_companies.add("Studio 9 Ltd")

    def answer(found):
        for c in found:
            world.site_company.setdefault(c["source_url"].split("/")[2], c["company"])
        return json.dumps({"candidates": found}), SimpleNamespace(input_tokens=20_000, output_tokens=2_000), 3

    def sol(provider, model, brief):
        return answer(good)

    def grok(provider, model, brief):
        return answer([person(9)])            # not a company: rejected

    def broken(provider, model, brief):
        raise ai_router.ProviderError("down")
    before = counts(db)
    with Session(db) as s:
        out = research_compare.compare(
            s, biz, lia["id"], [("openai", "gpt-6.1-sol"), ("xai", "grok-4.7"), ("anthropic", "claude-sonnet-4-5")],
            fetch=world.fetch, mx=world.mx, companies=world.companies,
            searchers={"openai": sol, "xai": grok, "anthropic": broken})
    assert counts(db) == before, "the comparison never writes"
    sol_row, grok_row, claude_row = out
    assert (sol_row["candidates"], sol_row["passed"], sol_row["decision_makers"], sol_row["gatekeepers"]) == (6, 6, 5, 1)
    assert sol_row["cost_pence"] > 0 and sol_row["pence_per_verified_contact"] > 0
    assert grok_row["passed"] == 0 and grok_row["review"] == 1          # a non-company is held for review, never passed
    assert "down" in claude_row["error"]
    text_out = research_compare.render(out)
    assert "openai/gpt-6.1-sol: 6 of 6" in text_out and "FAILED" in text_out
    assert "@" not in text_out, "no email addresses are printed"


def test_model_lists_are_read_from_the_command_line():
    from services import research_compare
    assert research_compare.parse_pairs("openai:gpt-6.1-sol, xai:grok-4.7,junk") == [("openai", "gpt-6.1-sol"),
                                                                                     ("xai", "grok-4.7")]
