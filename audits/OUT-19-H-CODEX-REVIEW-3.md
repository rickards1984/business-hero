# OUT-19 part H — Codex review 3

- Commit reviewed: 71840fa
- Model: gpt-6-astra · session 01a1732b-e0bb-77a0-848d-fb2609530968 · tokens used: 54,329
- Verdict: REQUEST CHANGES (final repair cycle reached: escalated to Mike)

## Prompt

```
You are the independent reviewer for OUT-19 part H, cycle 3 (the final repair cycle; RED: AI spend and availability). Do not commit, push or modify files.
Reviews 1 and 2 with responses are in audits/OUT-19-H-CODEX-REVIEW-1.md and -2.md. Review commit 71840fa (`git show 71840fa`) with the files at HEAD.
Confirm review 2's five findings are resolved without new problems: OpenAI long-context tiers; reported usage preserved on malformed Anthropic content and a missing Responses envelope treated as a provider failure; the impossible-cost pause on both settlement paths (no double counting of spend); the production reply reader (chase_replies.classify_with_model) now using the router's classify chain (check its callers and the automations that use it still behave, and that failures still raise so a reply becomes "unknown"); tier validation and component-wise price_max.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `71840fa`, which is HEAD, against North Star P7 and spend correctness.

1. **P2 — The newly routed reply-classification attempts are not recorded in the cost ledger.**  
   [chase_replies.py:454](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/chase_replies.py:454) calls `json_chat`, but neither `scan` nor its automation callers wrap classification in `ai_costs.collect()` and save the results. `ai_costs.note()` silently discards usage outside collection. I reproduced OpenAI failure followed by xAI success: both attempts had no active collection. These costs therefore remain invisible to ledger totals and spending alarms. Collect and persist every attempt against the business, including failures and invalid answers, with a regression test through the production caller.

Review 2’s five specific repairs are otherwise present: long-context tiers, preserved Anthropic usage and missing-envelope failure, the impossible-cost pause on both settlement paths without double counting, production classification routing, and tier validation/component-wise maxima. Classification failures still raise and become `unknown`; existing chase-pause behaviour remains intact.

**Verification:** 107 tests passed; 40 encountered fixture setup errors because the read-only sandbox has no writable temporary directory. I inspected the relevant blocked tests and ran an in-memory failover reproduction. `check.sh` and live-provider smoke tests were not run. No files were modified, committed or pushed.