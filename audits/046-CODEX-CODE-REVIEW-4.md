# 046 — Codex CODE review 4 (verbatim)

The staging fix (email link to email_messages (business_id, id)), commit 59253af.

**APPROVE** — commit `59253af`. No P0/P1/P2 findings.

- **Both databases:** the composite FK uses the existing `UNIQUE (business_id, id)`. It does not require `email_messages_pkey` and rejects cross-business email links, serving North Star P9.
- **Null links:** default `MATCH SIMPLE` permits `email_message_id = NULL`; the separate business FK still enforces a valid business.
- **Deletion:** email deletion removes matching example rows, including copied text. `CASCADE` deletes the whole referencing row; including non-null `business_id` causes no conflict and does not delete the business. The independent business cascade removes linked and unlinked examples, including on staging without email-table FKs. These semantics match [PostgreSQL’s documentation](https://www.postgresql.org/docs/17/ddl-constraints.html).
- **Tests:** the 19 cases cover null links, valid links, cross-business rejection, exact constraint errors and both deletion entry points. The new catalog assertion verifies dependence on the composite unique index. It does not itself drop the primary key; the reported manual rehearsal supplies that separate evidence. Business deletion with a linked email is not explicitly exercised, but the SQL introduces no cascade conflict.
- **Runbook:** the failure explanation, transactional rollback, replacement FK and verification expectations are accurate. `C + 10` remains correct. STEP 0’s stop-on-existing-table safeguard matters: `CREATE TABLE IF NOT EXISTS` would not replace an already-installed old FK.

Static, read-only review. I did not independently rerun the reported **396 passing tests**, the manual rehearsal, or `check.sh`; no files or databases were modified. No UI behaviour changes to click-test.
