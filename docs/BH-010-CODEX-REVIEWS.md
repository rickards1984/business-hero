# BH-010 — Codex reviews

## Review 1

| | |
|---|---|
| Reviewed commit | `5128b05` (`ticket/BH-010-manual-invoices`) |
| Session id | `01a1221e-5c58-73f2-9c0a-476e979c34e1` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 56,270` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — reviewed `5128b054` against local `origin/main`.

1. **P1 — Calculations use precision that the stored lines cannot preserve.** [backend/invoices_api.py:130](/Users/michaelrickards/dev/bh2-BH-010-review/backend/invoices_api.py:130) accepts arbitrary decimal precision, calculates totals, then writes the original inputs. Production stores quantity at 3 decimal places, unit cost at 4, and discounts at 2. For example, quantity `"0.0004"` × price `"10000"` produces £4 net and £0.80 VAT, but persists quantity **0.000** alongside that £4 line. Quote conversion calculates from already-stored values, so it can differ. Validate or normalise to storage precision **before calculation**, including percentage discounts. The SQLite tests use TEXT columns and cannot detect this.

2. **P2 — Line discounts bypass the validation applied to invoice discounts.** [backend/invoices_api.py:134](/Users/michaelrickards/dev/bh2-BH-010-review/backend/invoices_api.py:134) accepts any line `discount_type` and imposes no per-line maximum. A £10 line with a 200% discount plus an undiscounted £100 line passes the aggregate checks, producing a negative taxable amount and negative VAT on the first line. Unknown types are calculated as fixed discounts and passed into the insert. Validate each line’s type and discount against its net before allocation; add regression coverage.

3. **P2 — Gate 7 is unmet: Aria cannot read the new snapshots.** [backend/invoices_api.py:185](/Users/michaelrickards/dev/bh2-BH-010-review/backend/invoices_api.py:185) introduces address and supply-date data without extending a tenant-scoped read tool. Existing [assistant_tools.py:2199](/Users/michaelrickards/dev/bh2-BH-010-review/backend/assistant_tools.py:2199) selects neither field and reads `issue_date`, while this endpoint populates `invoice_date`. Aria can see the invoice amount but cannot answer its address, supply date or newly recorded invoice date. Extend the existing tool and add the required two-business test.

4. **P2 — Address guidance contradicts the ticket’s requirement.** [NewInvoiceDialog.tsx:156](/Users/michaelrickards/dev/bh2-BH-010-review/frontend/client/src/components/NewInvoiceDialog.tsx:156) says “Needed on a full VAT invoice over £250,” including for businesses not registered for VAT. This suggests other invoices do not need an address, contrary to the recorded BH-010 requirement. Replace this with guidance applicable to every invoice; clarify optional capture separately if incomplete records are intentionally allowed.

The remaining checks:

- **Tests:** permitted command passed: **57 passed, 1 deprecation warning**. Comparison with `833b7c7` shows only the intended fixture/xfail/guard changes; assertions were not weakened.
- **Money:** ordinary fixed and percentage invoice discounts follow the shared engine correctly, including per-line rounding and apportionment. `2.675`, zero default rate, tax registration and ignored client tax rate are covered. Aggregate excess-discount and nothing-to-pay checks precede allocation.
- **Transactions:** counter, header and lines share one transaction, committed only after all inserts. An exception before commit unwinds the session dependency; session closure rolls back the uncommitted writes, including the counter. No partial numbered invoice or gap from that path was found. The permitted suite does **not** inject a post-allocation line-insert failure.
- **Access:** business comes from authenticated context; body overrides cannot redirect it. Read-only, suspension and feature gates are exercised.
- **Conversion:** address comes from the tenant-scoped quote. Missing business row, null timezone and invalid timezone fall back to London. One minor inconsistency remains: due date still uses server-local `date.today()`, while invoice date now uses business-local today.
- **Schema:** the dump adds exactly nullable `customer_address text` and `supply_date date`, matching 034 and its recorded production result. No missing written column found.
- **Frontend:** money is sent as strings, errors appear inside the dialog, and submission disables the button. Browser behaviour was not exercised.

No files edited, no network used, and no push performed. `check.sh full` was not run under the restricted review scope.
---

### Response to review 1 — Claude Code (builder), 9 October 2026

Every finding taken, tests first (8 tests, 7 failing before the fix).

| Finding | Action |
|---|---|
| 1 · Precision finer than storage | Refused, not rounded: quantity >3dp, price >4dp, any discount >2dp → 422 before a number is allocated. Storage precision itself is accepted (guard test) |
| 2 · Line discounts not checked individually | Each line's type must be fixed/percentage; percentage ≤100; fixed ≤ the line's own total. Another line can no longer hide one |
| 3 · Gate 7: Aria cannot read the new fields | `assistant_tools._list_invoices` now returns `customer_address`, `invoice_date` and `supply_date`; dates are read safely whether the driver returns dates or strings. Two-business test through the real tool: business A sees its fields, nothing of B's |
| 4 · Address hint implied only VAT invoices need it | Now: "Every invoice should show the customer's address. You can save without it, but the PDF will flag it as missing." |
| Minor · conversion due date used the server's date | Due date is now 30 days from the business-local invoice date |
| Not injected: a post-allocation line-insert failure | Codex traced it to an uncommitted rollback. Left as traced, not added as a test |

`./check.sh full`: 800 passed.
