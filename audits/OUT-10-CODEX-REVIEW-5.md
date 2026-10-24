**APPROVE — no P1 findings.**

Reviewed OUT-10’s changes against `ticket/OUT-15-outreach-setup`, including `fc091d8..64f4b44`. No realistic remaining path to contacting an ineligible person was identified.

**P1 list:** None.

**Backlog — reproduced false rejections:**

- [outreach_research.py:457](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:457): A genuine company’s registration disclosure followed by “Website designed by Pixel Forge Ltd” is rejected because the credit appears within the same text window.
- [outreach_research.py:467](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:467): Trading-name matching reads only the cited page and recognises lowercase “trading as”. Genuine branded domains are rejected when the disclosure appears only on the homepage, uses “Trading As”, or uses “t/a”.
- [outreach_research.py:445](/Users/michaelrickards/dev/bh2-OUT-10-review/backend/services/outreach_research.py:445): Ordinary copy such as “We work in partnership with local schools” rejects an otherwise valid limited-company disclosure.

Verification: **282 targeted tests passed**. `./check.sh` passed: **3,311 passed, 305 skipped**, TypeScript, compilation and Ruff green. The known OUT-7 flake did not occur. Six additional offline probes confirmed the backlog cases and a valid control.

No network, commits or pushes. Worktree clean; only the empty test-generated database was removed. Live provider behaviour and billing limits were not independently verified.