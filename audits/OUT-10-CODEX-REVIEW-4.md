**REQUEST-CHANGES — one P1 remains. Escalate to Mike; this is the final repair cycle.**

Reviewed OUT-10 against `ticket/OUT-15-outreach-setup`, including `41011e6..fc091d8`.

**P1 — blocking**

- **A website-designer disclosure still establishes the prospect’s corporate identity.** [outreach_research.py:451](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:451). Reproduced offline: a personal trainer’s website lists their email and a footer saying “Website designed and hosted by Studio 1 Ltd. Company registration number …”. If the model mistakenly names the designer as the prospect’s company, verification creates an **eligible, automatically enrolled contact**. Nothing establishes that the trainer is a corporate subscriber. The page need not explicitly say “sole trader”. Review-3 P1 #1 therefore remains open generally: proximity of registration words, name and number still accepts an explicitly unrelated entity. This requires distinguishing operator disclosures from third-party credits, not cryptographic proof.

**Backlog — non-blocking**

- **Legitimate corporate trading names are rejected.** [outreach_research.py:465](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:465). Reproduced: “Studio 1 Ltd trading as Fitness Club”, with valid registration details, remains review-only because every occurrence of “trading as” is treated as disqualifying.

The quoted-address repair and increased spend reservation address the previous reproductions; I found no further realistic P1 in those paths. Provider billing limits were not independently verified online. No additional P1 was identified in SSRF, tenant isolation, suppression, scheduling or evidence binding.

**Verification**

- Requested targeted tests: **272 passed**.
- `./check.sh`: TypeScript, compilation and Ruff passed; **3,300 passed, 305 skipped**, with only the declared OUT-7 concurrency flake failing. Its isolated rerun passed; excluded from this verdict.
- Both findings reproduced in [offline probes](/tmp/test_out10_review4.py).

No network, commits or pushes. Worktree clean; empty test-generated database removed.