# Architecture decision records

**Status: stub — the directory exists, the ADRs are not yet written.**

Significant decisions to date were recorded inside the specs that prompted
them, not as standalone ADRs. That was reasonable while one person held the
context, and it stops being reasonable with multiple agents. Existing
decisions stay where they are; **new ones land here.**

## Decisions already made, and where they live

| Decision | Location |
|---|---|
| Top tier is `business`, not `elite`/`enterprise` | `ENTITLEMENT-SPEC.md` PART A, DECISION 1 |
| Metered overage with a customer-set spend cap | `ENTITLEMENT-SPEC.md` DECISION 2 |
| `paused` removed; `subscription_status` drives access | `ENTITLEMENT-SPEC.md` DECISION 3 |
| Unpaid means read-only, not lockout (VAT retention, GDPR Art. 20) | `ENTITLEMENT-SPEC.md` DECISION 3 |
| Founder accounts pay zero via a real Stripe path | `ENTITLEMENT-SPEC.md` DECISION 4 |
| Tax calculated, never looked up; US sales tax permanently out | `MONEY-ENGINE-BATCH1-SPEC-v2.md` |
| Discount order and per-line tax rounding | `MONEY-ENGINE-BATCH1-SPEC-v2.md` D2, D5 |
| `030b` ships in two releases; the revoke is second | `030B-SPEC.md` |
| `biz_update_if_owner` dropped rather than left unreachable | `030B-SPEC.md` PART E |
| Compliance ships after launch, marketed at launch | `COMPLIANCE-MODULE-BRIEF.md` D1 |
| Compliance is a separately purchasable module, one codebase | `COMPLIANCE-MODULE-BRIEF.md` D4 |
| The product manages evidence and never certifies compliance | `COMPLIANCE-MODULE-BRIEF.md` D7 |

## Format

`NNNN-short-title.md`:

```markdown
# NNNN — Title
**Status:** proposed | accepted | superseded by NNNN
**Date:** YYYY-MM-DD
**Decider:** Mike

## Context     What forced a decision. Evidence, with file:line.
## Decision    What was decided, in the active voice.
## Consequences  What this makes easy, what it makes hard, what it rules out.
## Alternatives  What was rejected and why.
```

Write an ADR when a decision has lasting consequence and a future agent would
otherwise reasonably choose differently. Not for routine implementation
choices.
