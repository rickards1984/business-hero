**REQUEST-CHANGES — three P1s remain.**

Reviewed OUT-10’s diff against the locally available `ticket/OUT-15-outreach-setup`, including `a323f85..41011e6`. The review-2 fixes address individual examples, but do not close all three failure mechanisms generally.

**P1 — blocking**

1. **A company number anywhere on the page still establishes corporate identity.** [outreach_research.py:427](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:427). A page explicitly identifying Sam as a sole trader, with “Website built by Studio 1 Ltd (company number …)” in its credits, produces an **eligible, enrolled contact**. The number appearing only in an image filename also passes. Require a disclosure binding the website/mailbox operator to the registered entity; an unrelated number is insufficient. The explicit-active-status repair works.

2. **Email proof still accepts a substring of another valid mailbox.** [outreach_research.py:354](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:354). A page containing only `"sam@studio1.example"@other.example` proves `sam@studio1.example`, producing an **eligible, enrolled contact**. The atext-prefix fixes work, but quoted local parts bypass them. Compare complete parsed mailbox addresses, including quoted forms.

3. **The increased reserve still does not enforce the spend cap.** [outreach_research.py:881](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:881). `search_context_size="low"` is described by the installed SDK as *guidance*, not an input-token ceiling. There remains no enforced input-cost bound. With 1,900p already spent, a mocked provider response reporting 600,000 input tokens, 8,000 output tokens and eight searches settles at **2,017p against the 2,000p cap**. [Line 586](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:586) pauses only after the overspend. This is an offline synthetic-usage reproduction, not an observed provider bill. Reserve a defensible maximum covering all billable work. Disabling retries, retaining uncertain spend and rereading the cap are confirmed repairs.

**Backlog — non-blocking**

- **Compound surnames still overclaim role verification.** [outreach_research.py:330](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:330): `Sam Jones` matches `SMITH-JONES, Sam`. Comparing surname tokens instead of the complete surname can mark a different person’s role verified.

No new SSRF, cross-tenant learning, or general model-controlled action-execution defect was found. Research evidence supplies OUT-6’s expiry, flags and address-binding fields.

Verification: **264 targeted tests passed**. `./check.sh` passed: **3,293 passed, 305 skipped**, TypeScript/compilation/Ruff green. The known OUT-7 flake did not occur. Offline probes remain in [/tmp/test_out10_review3.py](/tmp/test_out10_review3.py).

No network, commits or pushes. Worktree clean; the empty test-generated database was removed.