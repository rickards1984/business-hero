#!/usr/bin/env python3
"""OUT-19: compare AI models on a real research brief (services/research_compare.py).

Reads the database, calls each AI provider once, verifies every contact with
Business Hero's own checks, and prints the results. Stores, enrolls and emails
nothing. Run with the production settings (database, AI keys, Companies House):

    railway run .venv/bin/python scripts/compare-research-models.py \
        --business "New Body" --brand FitFutures --spend

Without --spend it only shows which brand, audience and models it would use.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--business", required=True, help="business name (or its start)")
    parser.add_argument("--brand", required=True, help="brand name")
    parser.add_argument("--models", default="", help='e.g. "openai:gpt-6.1-sol,xai:grok-4.7" (default: Sol, Grok 4.7, Grok 4.20)')
    parser.add_argument("--spend", action="store_true", help="actually call the AI providers (a few pence each)")
    args = parser.parse_args()

    from sqlalchemy import text
    from db import get_session_context
    from services import outreach_research as research, outreach_setup, research_compare

    pairs = research_compare.parse_pairs(args.models) or research_compare.DEFAULT_PAIRS
    with get_session_context() as session:
        found = session.execute(text("SELECT id, name FROM businesses WHERE name ILIKE :n ORDER BY name"),
                                {"n": args.business + "%"}).fetchall()
        if len(found) != 1:
            print(f"Expected one business starting '{args.business}', found {len(found)}: {[f[1] for f in found]}")
            return 1
        bid = str(found[0][0])
        business = outreach_setup.load_business_row(session, bid)
        audience = session.execute(text(
            "SELECT c.id FROM outreach_compliance c JOIN outreach_brands b ON b.business_id = c.business_id "
            "AND b.id = c.brand_id WHERE c.business_id = :b AND b.name = :n AND c.decision = 'approved' "
            "ORDER BY c.reviewed_at DESC LIMIT 1"), {"b": bid, "n": args.brand}).scalar()
        session.rollback()
        if not audience:
            print(f"No approved audience for brand '{args.brand}' at {found[0][1]}.")
            return 1
        print(f"Business: {found[0][1]} · brand: {args.brand} · audience {audience}")
        print("Models: " + ", ".join(f"{p}/{m}" for p, m in pairs))
        missing = [p for p, _ in pairs if not os.environ.get({"openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY",
                                                              "anthropic": "ANTHROPIC_API_KEY"}.get(p, ""))]
        if missing:
            print(f"Missing API keys for: {', '.join(sorted(set(missing)))} — those models will fail.")
        if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
            print("COMPANIES_HOUSE_API_KEY is not set: no contact can pass verification.")
            return 1
        if not args.spend:
            print("Dry run. Add --spend to call the providers (each search is billed, typically a few pence).")
            return 0
        results = research_compare.compare(session, business, audience, pairs, fetch=research.fetch_page,
                                           mx=research.has_mail_server, companies=research.companies_house)
    print()
    print(research_compare.render(results))
    print("\nNothing was stored or sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
