# OUT-23 Part B (Hunter.io) — Codex design review 4 (targeted, verbatim)

Commit reviewed: 4feed86 (design revision 4).

---

No findings. Revision 4 answers review 3’s three findings and implementation notes: disconnect tombstones, authoritative assessment selection, atomic brand-credit settlement, historical ledger handling, and deadline coverage. It introduces no new blocking design issue.

Implementation note: reservation and storage checks must use fresh time. `_audience` rejects approvals after its supplied `moment`, while `_run` currently retains the run’s starting time; reusing that timestamp could hide a mid-run approval.

Read-only review; nothing modified, committed or pushed. Tests not run. Serves correctness, security and tenant isolation.

VERDICT: APPROVE