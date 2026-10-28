Reviewed `fc9c1d9` against `febb427` under **North Star P8**. Worktree unchanged.

**P1 — still open**

- **Reported usage can exceed the hold.** [chat_bound_pence](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/ai_router.py:249) bounds character-based estimates, but `json_chat` records provider-reported tokens without that bound. Using the real model drafter with mocked reported usage of 100,000 input / 4,000 output tokens, a **14p hold settled at 18.848p**. Two overlapping drafts starting at 2,747p produced **2,784p recorded spend against the 2,775p ceiling**. The reservation therefore still does not establish the required guarantee. Reserve a defensible maximum covering reported usage; do not truncate genuine costs to fit the hold.

- **Partially accounted failures still release unknown spend.** [The settlement condition](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_setup.py:844) treats any nonempty `spent` list as complete accounting. A probe where the first provider failed with an accounted estimate and the fallback was interrupted after dispatch recorded **3.370783p and released the entire 14p hold**. The fallback’s possible charge remained unknown. Settlement needs to distinguish complete accounting from partial accounting and preserve protection for unknown attempts.

**P2**

No additional confirmed P2 finding in this diff.

**Bound checks and backlog**

- `price_max` correctly includes higher pricing tiers. `include_down=True` correctly includes cooling providers; with unchanged configuration, the execution chain is a subset of the reserved chain.
- The context is serialized separately for reservation and execution. An injected change between those points produced **36.885648p against a 14p hold**. I found no ordinary concurrent mutation path in the current callers, so this is hardening rather than a separate confirmed production defect. Freeze the request used for both calculations. Configuration changes between reservation and execution likewise lack a shared snapshot.
- Draft/research overlap coverage passes, but protecting research from visible holds cannot compensate for drafts settling above those holds.
- PostgreSQL contention remains unverified. Retain the previous follow-through for part F’s atomic charging and suggested-reply adapter protection.

**Regression verification**

All **28 allowance tests passed** using process-local in-memory SQLite, with bytecode and pytest cache writes disabled.

Restoring `febb427`’s `_ai_draft` **in memory only** caused three regressions to fail:

- Unknown failure retains its hold.
- Model draft cost stays within its hold.
- Overlapping model drafts stay within allowance plus reserve.

Those tests discriminate against the previous implementation, but miss reported usage above the estimate and partial-accounting failures. The reply-sorting test now also asserts recorded cost.

`check.sh`, live providers, PostgreSQL and browser behaviour were not verified. No UI click can prove this concurrency guarantee; it needs deterministic backend regressions.

**Verdict: REQUEST CHANGES.**