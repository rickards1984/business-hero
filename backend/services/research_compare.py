"""OUT-19: which AI model researches best, on a real brief — side by side.

Mike, 25 Oct 2026: before trusting a fallback (an earlier Grok failed at
research on his own platform), give the same research brief for one of his
brands to each model and put every contact it finds through Business Hero's
own verification (the email on the company's own website, a mail server,
Companies House, a named person). Nothing is stored, enrolled or emailed;
the database is only read. Prints companies, roles and results, never email
addresses. Each search is a real, billed provider call.
"""
import json
import time
from collections import Counter

from services import ai_costs, ai_router
from services import outreach_research as research

DEFAULT_PAIRS = [("openai", "gpt-6.1-sol"), ("xai", "grok-4.7"), ("xai", "grok-4.20-0309-reasoning")]


def parse_pairs(text: str) -> list:
    pairs = []
    for item in (text or "").split(","):
        provider, _, model = item.strip().partition(":")
        if provider and model:
            pairs.append((provider.strip().lower(), model.strip()))
    return pairs


def _searcher(provider: str):
    return ai_router._anthropic_search if provider == "anthropic" else ai_router._openai_compatible_search


def compare(session, business, compliance_id, pairs, *, fetch, mx, companies, searchers=None) -> list:
    """One result per (provider, model): cost, time, and how many of its
    contacts pass verification. Reads only; every transaction is rolled back."""
    bid = str(business.id)
    brief = research.plan(session, business, compliance_id)["brief"]
    domains, _ = research._held(session, bid)
    from sqlalchemy import text
    keys = {r[0] for r in session.execute(text(
        "SELECT email_key FROM outreach_prospects WHERE business_id = :b AND email_key IS NOT NULL"), {"b": bid})}
    session.rollback()
    results = []
    for provider, model in pairs:
        row = {"provider": provider, "model": model}
        search = (searchers or {}).get(provider) or _searcher(provider)
        started = time.monotonic()
        try:
            answer, usage, searches = search(provider, model, brief)
        except ai_router.ProviderError as exc:
            row.update(error=str(exc), seconds=round(time.monotonic() - started, 1))
            results.append(row)
            continue
        row["seconds"] = round(time.monotonic() - started, 1)
        reported = ai_costs.usage_tokens(usage)
        try:
            row["cost_pence"] = round(ai_costs.cost(provider, model, reported[0], reported[1], searches), 1) \
                if reported else None
        except ai_costs.Unpriced:
            row["cost_pence"] = None
        row.update(tokens=reported, searches=searches)
        try:
            candidates = [c for c in json.loads(ai_router.extract_json(answer)).get("candidates", []) if isinstance(c, dict)]
        except (ValueError, AttributeError):
            candidates = []
            row["error"] = "no usable JSON answer"
        held = {"domains": set(domains), "keys": set(keys), "seen": set()}
        tally, reasons, sample = Counter(), Counter(), []
        for c in candidates:
            v = research._verify(session, bid, c, held, fetch, mx, companies)
            session.rollback()
            held["seen"].add(v.get("email") or "")
            if v["ok"]:
                tally["passed"] += 1
                tally["decision_makers" if v.get("contact_type") == "decision_maker" else "gatekeepers"] += 1
            elif v.get("review"):
                tally["review"] += 1
            else:
                reasons[v.get("reason") or "rejected"] += 1
            if len(sample) < 8:
                sample.append({"company": str(c.get("company") or "")[:80], "role": str(c.get("role") or "")[:60],
                               "result": "passed" if v["ok"] else ("review" if v.get("review") else v.get("reason"))})
        row.update(candidates=len(candidates), passed=tally["passed"], decision_makers=tally["decision_makers"],
                   gatekeepers=tally["gatekeepers"], review=tally["review"], rejected=dict(reasons), sample=sample)
        if row.get("cost_pence") and tally["passed"]:
            row["pence_per_verified_contact"] = round(row["cost_pence"] / tally["passed"], 1)
        results.append(row)
    session.rollback()
    return results


def render(results: list) -> str:
    lines = []
    for r in results:
        head = f"{r['provider']}/{r['model']}"
        if r.get("error") and "candidates" not in r:
            lines.append(f"{head}: FAILED — {r['error']} ({r.get('seconds')}s)")
            continue
        cost = "unknown" if r.get("cost_pence") is None else f"{r['cost_pence']}p"
        lines.append(f"{head}: {r['passed']} of {r['candidates']} contacts passed verification "
                     f"({r['decision_makers']} decision-makers, {r['gatekeepers']} gatekeepers, {r['review']} for review) · "
                     f"cost {cost} · {r['searches']} searches · {r['seconds']}s"
                     + (f" · {r['pence_per_verified_contact']}p per verified contact" if r.get("pence_per_verified_contact") else ""))
        if r.get("error"):
            lines.append(f"    note: {r['error']}")
        if r["rejected"]:
            lines.append("    rejected: " + ", ".join(f"{k} ×{v}" for k, v in sorted(r["rejected"].items(), key=lambda kv: -kv[1])))
        for s in r["sample"]:
            lines.append(f"    · {s['company']} — {s['role'] or 'no role'} — {s['result']}")
    return "\n".join(lines)
