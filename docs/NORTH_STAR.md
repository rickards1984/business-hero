# Business Hero — North Star

**Status:** Adopted 28 September 2026
**Owner:** Michael Rickards (product owner, final decision-maker)
**Applies to:** all product, design and engineering work, by every agent and human, from this date.

> **Business Hero is Aria: an AI business partner who knows the whole business and helps the owner run it.**

This is the end goal. Everything we build should either move the product towards it or be a prerequisite it depends on: security, tenant isolation, data correctness or stability. If a piece of work is neither, it needs a stated reason.

---

## 1. Why

Business Hero already does a lot: quoting, invoicing, accounting and Xero sync, email triage, call answering, booking, WhatsApp alerts and board meetings. But using it feels like a set of separate apps, and we sell it as a feature list.

In reality it is one business's data, and Aria can already see across all of it. The board meeting's prep data proves that. So we build the product around her. The departments become things Aria looks after. The owner talks to one colleague who knows everything, and opens a department only when they want to dig in themselves.

The commercial wedge does not change: UK contractors and trades, with MSC as customer zero. The message becomes what Aria does for them: **win the work, run the work, manage the money, prove compliance.**

## 2. The end-state experience

A contractor opens Business Hero between jobs. Aria greets them with a short briefing. Three things need them today:

- a quote the customer has opened twice but not accepted,
- an invoice now 14 days overdue,
- two missed calls from new enquiries.

Each item comes with a proposed action. They approve the invoice chase, then hold the talk button: *"How did we do this month compared with last?"* Aria answers in plain English with the real figures, and each figure can be tapped to show the records behind it. They agree to ring the quote customer tomorrow. Aria adds it to their list and will ask about it next time.

Later, on an invoice page, they type *"why is this one late?"* and Aria already knows which invoice they mean.

Once a month they sit down for a board meeting with the same Aria. She opens by reviewing what they both committed to last time.

## 3. Principles

These are numbered so plans and PRs can reference them (e.g. "serves P2, P6").

**P1 — Aria is the front door.** The home screen is Aria. She is available on every page through a persistent dock that knows what the owner is looking at.

**P2 — Grounded or silent.** Every figure Aria states comes from the business's own data, either through a tool call or from the loaded business snapshot. None comes from the model's head. Every factual claim links to its source record. If data is missing or stale, she says so, reusing the board meeting's `data_quality` pattern.

**P3 — One Aria.** Chat, voice, briefings and board meetings are modes of one persona, never separate characters. That persona is warm, sharp, naturally British and fact-anchored. She writes in plain paragraphs, uses no emoji, and uses UK formats.

**P4 — Aria proposes, the owner decides.** Some actions have effects outside the app, such as sending an email, chasing an invoice, sending a quote or making a booking. These go through an approval card until the owner grants standing permission for that action type. Autonomy is earned one action type at a time, like our own GREEN/AMBER/RED model. **Aria never initiates payments or changes bank or payment details.**

**P5 — Memory is structured and visible.** Aria remembers decisions, commitments, preferences and business facts as records, not just as chat logs. The owner can see, edit and delete what she remembers.

**P6 — Departments, not apps.** Every section keeps its own page, in one consistent visual language. Each page has an Aria summary at the top and "Ask Aria" in context. Working modules are wrapped, not rebuilt.

**P7 — Model-agnostic.** All model calls go through one routing layer. Swapping or upgrading a model means a configuration change plus an eval run, not a rewrite. This is how Business Hero keeps getting smarter as AI does.

**P8 — Trust over cleverness.** Aria is proportionate, honest and never falsely positive. A wrong number costs more than a missing feature.

**P9 — One business, sealed.** Aria can only ever see the current business's data. Every tool is scoped by business and enforced by RLS. No memory or data crosses tenants. Customer data goes only to model providers covered by documented data-processing terms.

## 4. Architecture pillars (target state)

| Pillar | What it is | Builds on |
| --- | --- | --- |
| **Aria Core** | One orchestrator service. It takes a message plus context (business, user, current screen), loads the snapshot and memory, and calls the model with tools. It returns an answer, citations and proposed actions. | Existing Aria chat and persona prompt |
| **Tool layer** | Typed, tenant-scoped read tools for each department: money, invoices, quotes, jobs/calendar, comms, calls, tasks and compliance. Write tools *propose* actions and never execute directly. Tools are the only way Aria touches data. | Existing service functions; board meeting prep aggregators |
| **Business snapshot** | A cached, regularly refreshed "state of the business" that Aria always has loaded. | Board meeting `prep_data`; CEO Briefing |
| **Memory** | Records of facts, decisions, preferences and commitments, each linked to its source conversation, plus the conversation log. | New |
| **Tasks** | One task system covering Aria's tasks and the owner's tasks, told apart by assignee. | Board meeting action items and goals |
| **Actions & permissions** | A queue of proposed actions, approval cards, a permission level per action type (ask / allowed / never), and a full audit trail. | New |
| **Model router** | Provider abstraction, model choice per task, fallback and metering. | Planned multi-provider routing and metering |
| **Voice** | Realtime voice wired to the same Aria Core and tools, not a separate brain. | `realtime_voice.py` (needs GA migration) |
| **Proactive engine** | Scheduled checks that produce "Aria noticed" items for the home feed, the briefing and the WhatsApp daily pulse. | CEO Briefing; daily pulse |
| **Evals** | A seeded test business with known answers, plus grounding tests that check Aria's numbers match the database. Run before any model change. | Existing test harness |

## 5. UX target

- **Home is Aria.** It shows a briefing, a talk/type bar, "needs you" approval cards, department tiles each with a live one-line status, and two task lists: Aria's and yours.
- **Persistent dock** on every page. It is context-aware, text first, with voice once voice is fixed.
- **Department pages share one layout:** Aria summary strip, then data, then actions.
- **Board Meeting is one tap from Aria home** ("hold a board meeting"), not buried in AI Hub.
- **AI Hub dissolves over time.** Its features become Aria's modes or move to the department they belong to, such as receptionist settings under Calls and booking under Calendar.
- **Futuristic means alive, not gimmicky.** That means streaming replies, a presence indicator, a voice waveform and fast transitions. Clarity and speed beat effects.
- **Built for site, not the desk.** Contractors use this on a phone between jobs, often with dirty hands. The app is mobile-first, and voice is a core feature, not an extra.

## 6. Phases

Each phase ships something usable on its own. Security and tenant-isolation work keeps its place in the sequence and is never traded away for North Star features. That work includes 030b Release 2 and RLS batches 4–5.

**Phase 0 — Commit (now).**
- Adopt this doc.
- Update AGENTS.md and the Definition of Done.
- Produce a gap analysis of the current code against this doc.
- Write an RC1 scope proposal for Michael to decide on.

**Phase 1 — Aria-first shell (proposed for RC1, subject to the gap analysis).**
- Aria home screen.
- Text dock.
- Grounded read tools over existing departments, with citations.
- A unified task view built on the existing action items.
- Board Meeting promoted out of AI Hub.
- Aria takes no write actions yet. Existing RC1 blockers remain blockers.

**Phase 2 — Aria remembers and speaks.**
- Voice fixed and wired to Aria Core.
- Structured memory, with a "what Aria remembers" page.
- A proactive "Aria noticed" feed.
- Approval cards for the first write actions: chase an invoice, draft an email reply, follow up a quote.

**Phase 3 — Aria acts.**
- Standing permissions per action type.
- Aria carries out routine actions and reports back.
- Board meetings fully connected to memory and tasks.
- The compliance module wired in as Aria tools.

**Phase 4 — Aria advises.**
- Cash-flow forecasting.
- Scenario questions ("what if I take on another labourer?").
- Pricing and quote-win analysis.

## 7. Positioning

- Lead with Aria, not the feature list. The features are evidence of what she can do.
- Lead with proof: MSC as customer zero and case study.
- Call her an **"AI business partner"**. Avoid "CFO", "accountant" or anything implying regulated financial advice. Keep the board meeting disclaimers.
- Update the marketing site and outreach copy once Phase 1 is real, not before.

## 8. Rules for every piece of work

Answer these in every plan or PR:

1. Which principle, pillar or phase does this serve? If none, which prerequisite does it meet (security, isolation, correctness, stability)?
2. Does it add data Aria can't see? If so, it ships with a tenant-scoped read tool for that data.
3. Does Aria state any new numbers? If so, they come from tools or the snapshot, and a grounding test covers them.
4. Does it add a direct model-provider call outside the router? It shouldn't.

If a request conflicts with this doc, stop and flag it to Michael before building.

## 9. Not doing

- A general-purpose chatbot or ChatGPT wrapper. Aria is about *this* business.
- Self-hosted models before product-market fit.
- Aria moving money, ever.
- Rebuilding working modules just to restyle them.
- Visual effects that slow the app down or confuse the owner.

## 10. Open questions (Michael to decide)

- Is the phone receptionist "Aria" to callers, or a separate voice of the business?
- Can owners rename Aria or change her voice?
- Which tiers get Aria chat, voice and board meetings?
- Which voice provider for a British voice: OpenAI, or a cloned/ElevenLabs voice?
- Which model providers are acceptable for UK customer financial and email data? This is pending legal review.
