# BH-002 — deployment, verification and rollback

For Mike. **Nothing here has been run.** No agent has connected to production
or staging, and no customer record has been read to demonstrate the leak.

| | |
|---|---|
| Branch | `ticket/BH-002-accounting-category-isolation` |
| Commit | `b768580` (parent `c72d4fc` on `foundation/rc1-baseline`) |
| Changes | `backend/accounting.py` (+50/−4), one new test file |
| Schema change | **None.** No migration, no DDL, no data change |
| Railway config | **None** |
| Deploy trigger | Merge to `main` → Railway redeploys the backend |

## What it changes

**Six** category joins are now scoped to the transaction's own business, and
three write paths validate a caller-supplied `category_id` before storing it.
Three modules: `backend/accounting.py` (four joins, three writes),
`backend/main.py` (the accountant-pack Excel export) and
`backend/assistant_tools.py` (the assistant's spending analysis).

The last two were found by Codex's review, not by the original repair, which
searched only `accounting.py`. Both leaked a foreign category **name** — one
into a workbook sent to an accountant, one into AI-generated insight text.

**Behaviour change visible to a customer:** a transaction that references a
category belonging to *another* business now displays as **uncategorised**
instead of showing that other business's category name. That is the fix
working. For any legitimately-categorised transaction — the overwhelming
majority — nothing changes.

## Before deploying: find out whether any such rows exist

Read-only. Safe during traffic. Supabase SQL editor, **confirm the project
selector reads `oxblcmwhuwtobdhsfgyi`** first.

```sql
-- Transactions whose category belongs to a different business.
SELECT count(*)                              AS affected_rows,
       count(DISTINCT t.business_id)         AS businesses_affected,
       count(DISTINCT t.category_id)         AS foreign_categories_referenced
  FROM accounting_transactions t
  JOIN accounting_categories  c ON c.id = t.category_id
 WHERE c.business_id <> t.business_id;
```

**Interpretation.**

- **0** — no data was ever affected. The defect was reachable but never
  exercised. Deploy as a straightforward hardening change.
- **> 0** — cross-tenant references exist in live data. Still deploy: after
  this change those rows stop rendering another tenant's category name. Then
  decide separately whether to null out the offending `category_id` values —
  that is a **write**, so it is its own RED runbook, not part of this deploy.
  Note the row counts before deciding.

If you want the detail for a follow-up, this is the read-only breakdown —
it returns ids and category names, so treat the output as customer data:

```sql
SELECT t.business_id AS owning_business, t.id AS transaction_id,
       c.business_id AS category_owner, c.name AS category_name
  FROM accounting_transactions t
  JOIN accounting_categories  c ON c.id = t.category_id
 WHERE c.business_id <> t.business_id
 ORDER BY t.business_id
 LIMIT 200;
```

## Deploying

1. Codex's review of `b768580` is attached to the handoff. Do not merge on a
   REQUEST-CHANGES verdict.
2. Run the count query above and record the number.
3. Merge `ticket/BH-002-accounting-category-isolation` into `main`. **Merge is
   the deploy** (`AGENTS.md` §4) — Railway redeploys the backend, Vercel is
   unaffected because no frontend file changed.
4. Watch the Railway deploy to healthy. There is no migration, so there is no
   window where schema and code disagree.

## Verifying after deploy

Do this in the app, as yourself, on a business you own:

1. **Accounting → transactions list loads**, and categorised transactions
   still show their category name and colour. *This is the important check:*
   the risk of this change is over-scoping the join and blanking legitimate
   categories.
2. **Assign a category** to a transaction and confirm it saves and displays.
3. **Bulk-assign** a category to two or more transactions.
4. **Edit a transaction's category** (the PATCH path) and confirm it saves.
5. **Accounting summary and AI insights** still render category breakdowns
   with names, not blanks.

6. **Export the accountant pack** for a date range with categorised
   transactions and confirm the Category column is populated.
7. **Ask the assistant a spending question** ("what did I spend most on")
   and confirm the category breakdown still names categories.

If steps 1–7 behave normally the change is good: they cover the six joins and
three write paths that were touched.

A negative check needs two businesses and is a test-environment job, not a
production one — it belongs with BH-003, not here.

## Rolling back

No schema change, so rollback is purely code and carries no data risk.

```
git revert b768580        # on main, then push
```

Railway redeploys the previous backend. Nothing else to undo: no migration to
reverse, no config to restore, no data written by this change.

Reverting restores the leak. If you revert because a legitimate category
stopped displaying, that is a **scoping bug in the join**, and the better fix
is forward — the join condition is three lines in four places.

## Known gaps this deploy does NOT close

Codex's review raised four items beyond the leak itself. None is a reason to
withhold the deploy — the code is strictly safer than what is live — but none
is fixed here, and all need their own ticket:

1. **Malformed or empty `category_id` returns 500, not 404.** The ownership
   check casts to uuid; a malformed value raises a database error that is not
   translated. Pre-existing on all three write paths.
2. **`None` handling is inconsistent** across create / PATCH / bulk-update
   (writes NULL / ignores the field / normalises to NULL). A PATCH with an
   explicit null still cannot clear an existing foreign reference.
3. **AI insights can report "all transactions categorized"** while the list
   shows a contaminated row as uncategorised: the count uses raw
   `category_id IS NULL`, the joins now exclude foreign references. Cosmetic,
   but it is a contradiction a customer can see.
4. **No database constraint backs the application check.** A composite foreign
   key on `(category_id, business_id)` would make this class of bug
   impossible. That is a schema change, so a separate RED ticket.

## What remains unverified

- Whether any production row actually carries a foreign `category_id`. The
  count query answers it; it has not been run.
- Whether a database-level constraint (a composite foreign key on
  `(category_id, business_id)`) should back the application check. That is the
  durable fix and it is a schema change, so it is a separate RED ticket.
- The fix is proven by synthetic tests only. No production or staging database
  was touched.
