## TICKET BH-009 — VAT invoice PDF (RC1 P0-4)

**Outcome**  An owner can download a PDF of any invoice that is a lawful UK
VAT invoice when the business is VAT-registered, and a plain invoice with no
VAT anywhere when it is not.

**Current evidence**  `docs/CURRENT_STATE.md` §6: "Invoice PDF — absent;
`quote_pdf.py` has no sibling. A UK VAT invoice cannot be produced."
`docs/RC1_SCOPE.md` P0-4. `backend/services/` has `quote_pdf.py` only.

**Serves**  RC1 P0-4 (correctness/money prerequisite). North Star: P8.

**Scope — THIS RUN IS STAGE 1: TESTS AND DESIGN ONLY**
Money is RED (AGENTS.md §2): tests are written first and Mike reviews them
before any implementation. In this run:
1. Write `backend/tests/test_invoice_pdf.py`, failing against today's code,
   with every new-behaviour test marked
   `pytest.mark.xfail(strict=True, reason="BH-009: tests first; implementation follows Mike's review")`
   so `./check.sh` stays green.
2. Write `docs/BH-009-DESIGN.md`: where the data comes from (with file:line),
   the endpoint, the module, and every open question.
3. Do NOT write the implementation, do NOT add a migration, do NOT touch
   production.

**What the tests must encode**
- *VAT-registered business* (`businesses.tax_registered` true): the PDF says
  "VAT invoice" (or "Tax invoice") and shows the supplier's name, address and
  **VAT registration number**; a unique invoice number; the invoice/issue
  date; the tax point if it differs; the customer's name and address; per
  line a description, quantity, unit price excluding VAT, VAT rate and
  line amount; total excluding VAT; total VAT; any discount; total payable.
  This is my summary of HMRC VAT Notice 700 §16 — **you cannot reach the
  network, so mark in the design note which requirements you could not
  verify, for Mike to check against the notice.**
- *Not VAT-registered*: no VAT line, no VAT rate, no VAT number, and the
  document is not titled a VAT invoice anywhere. Issuing a VAT invoice when
  not registered is unlawful. A stored 0 rate must never become 20 (see the
  `rate or 20` trap in `backend/tests/test_tax_registration.py`).
- Money to the penny, `Decimal` end to end, the business's currency symbol
  via `services/region.py` — never a hard-coded `£`.
- **Totals come from the money engine** (`services/money.py`) or the stored
  invoice/line values — not an eighth independent total calculation
  (`RC1_SCOPE.md` P2 notes seven already exist). The PDF must not disagree
  with `invoices.subtotal` / `tax_amount` / `amount`; test that it cannot.
- Mixed per-line rates render per line (the columns exist:
  `invoice_line_items.tax_rate`, `tax_amount`, `tax_treatment`).
- **Tenant isolation:** business A cannot fetch business B's invoice PDF —
  404, not 403, and no bytes. Use the two-tenant harness in
  `backend/tests/test_tenant_isolation_backend_path.py`.
- **Entitlement:** gated by the `invoicing` feature; a read-only business
  (unpaid/cancelled) CAN still download it — `auth.READ_ONLY_PERMITTED_FEATURES`
  includes `invoicing` for exactly this (DECISION 3, six-year VAT record duty).
- Invoices imported from CSV/Xero with no line items still produce a valid
  PDF from the header totals, and say they have no itemised lines rather
  than inventing any.

**Known data gap — resolve in the design note, do not migrate**
`invoices` has no customer address column (`audits/live-schema-public.txt`);
`quotes.customer_address` exists. Find whether an invoice converted from a
quote can reach it (`invoices.source_ref`, `related_invoice_id`, the
conversion code). If a full VAT invoice cannot get the customer address
without a schema change, say so plainly — that is a RED migration for Mike
to decide, not something to work around.

**Shared contract with P0-5 (manual invoice creation)** — RC1_SCOPE review
challenge 6: both invoice-producing paths need the same entitlement gate,
read-only behaviour and tax treatment. Design the PDF so P0-5 can reuse it.

**Non-goals**  No email sending, no Xero push, no migration, no frontend in
this run, no change to quote PDFs.

**Likely files**  `backend/services/quote_pdf.py` (the template to mirror),
`backend/services/money.py`, `backend/services/region.py`,
`backend/quoting_api.py:734` (`_get_quote_pdf_data`) and `:790`,
invoice endpoints in `backend/main.py:2857` onward (hot spot: prefer a new
router module; its registration in `main.py` is one line).

**Verification**  `/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_invoice_pdf.py -q`
and `./check.sh` (run from this worktree root; it uses the same venv path
if `.venv` is absent — if it cannot run, say so).

**Builder** Codex  **Reviewer** Claude Code  **Branch** `ticket/BH-009-invoice-pdf`
**Budget band** L  **Max repair cycles** 3
**Status** in review — Stage 1 tests/design written and verified; awaiting Claude Code review and Mike’s money-contract review before implementation


## Completion evidence — Stage 1, Codex, 6 October 2026

Written: `backend/tests/test_invoice_pdf.py` and `docs/BH-009-DESIGN.md`.
Only tests and documentation changed. No implementation, migration, production
access, network access, commit or push. Existing untracked ticket preserved
and updated. Claude Code remains the reviewer; no review verdict is claimed.

Verified: the two harness checks pass and all 20 new-behaviour cases fail for
the intended missing implementation. Running with `--runxfail` yielded exactly
11 `MissingInvoicePDF: Required BH-009 module services.invoice_pdf does not exist`
and 9 `MissingInvoicePDF: Required BH-009 module invoice_pdf_api does not exist`.
For example, the registered-invoice fields test fails because
`services.invoice_pdf` is absent. These are genuine expected failures for the
proposed API contract, not evidence that the deeper assertions have run against
an implementation. The xfail marker accepts only this specific exception;
fixture errors and other exceptions remain ordinary failures.

Unmasked diagnostic command:
`/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_invoice_pdf.py -q --runxfail`

Exact diagnostic summary: `20 failed, 2 passed in 0.36s` (intentional).

The initial text-observer harness failure was fixed by observing ReportLab's
`_formatText`, then the unmarked observer check passed. No application code
was changed to make tests pass.

`./check.sh` initially could not typecheck because this worktree had no frontend
node_modules. Repaired offline with a worktree-local ignored symlink to the
already-installed `/Users/michaelrickards/dev/business-hero-2/frontend/client/node_modules`.
No dependency installation or external file edits. Reran with npm offline and
a temporary cache inside this worktree. Final check result below is green.
Existing `.venv` already points to the user-specified Python environment.

Not verified: lawful HMRC completeness, actual PDF layout or any new UI flow,
Postgres/RLS behaviour, production schema or data. See the design's open
questions, especially customer-address snapshots, dates/tax point, incomplete
imports and supplier registration history. Stage 1 has nothing new to click;
Mike should review the demanded behaviour in the tests/design before Stage 2.
Later manual check: Invoices → select invoice → Download PDF → open and compare
identity, address, dates, lines and totals with the stored record.

### Exact focused pytest output

Command: `/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_invoice_pdf.py -q -rxX`

```text
.xxxxxxxxxxx.xxxxxxxxx                                                   [100%]
=========================== short test summary info ============================
XFAIL backend/tests/test_invoice_pdf.py::test_registered_invoice_has_required_identity_dates_and_line_fields - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_stored_discount_and_header_totals_are_not_recalculated - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_unregistered_omits_all_vat_even_with_stale_settings[stale_rate0] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_unregistered_omits_all_vat_even_with_stale_settings[stale_rate1] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_registered_zero_rate_is_not_replaced_by_twenty - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_mixed_rates_stay_attached_to_their_lines - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_decimal_pennies_survive_without_float_conversion - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_currency_follows_region[UK-GBP-\xa3] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_currency_follows_region[US-USD-$] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_import_without_lines_uses_only_header_totals[csv] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_import_without_lines_uses_only_header_totals[xero] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_download_is_scoped_both_directions[aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa-11111111-1111-4111-8111-111111111111-22222222-2222-4222-8222-222222222222] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_download_is_scoped_both_directions[bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb-22222222-2222-4222-8222-222222222222-11111111-1111-4111-8111-111111111111] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[active-True-True-200] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[unpaid-False-True-200] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[canceled-False-True-200] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[active-True-False-403] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[unpaid-False-False-403] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[canceled-False-False-403] - BH-009: tests first; implementation follows Mike's review
XFAIL backend/tests/test_invoice_pdf.py::test_http_invoicing_entitlement_and_retained_read_access[active-False-True-403] - BH-009: tests first; implementation follows Mike's review
2 passed, 20 xfailed in 0.49s
```

### Exact full backend pytest output

Command: `/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests -q`

```text
..................................................................... [  8%]
........................................................................ [ 18%]
........................................................................................................................................ [ 35%]
...........................................s............................ [ 45%]
.......................................xxxxxxxxxxx.xxxxxxxxx............ [ 54%]
.......................................................... [ 62%]
........................................................................ [ 71%]
................................................................................................ [ 83%]
..................................................................... [ 92%]
.......................ssssssssssssssssssssssssssssssss                  [100%]
=============================== warnings summary ===============================
../business-hero-2/.venv/lib/python3.12/site-packages/starlette/testclient.py:53
  /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

backend/schemas.py:98
  /Users/michaelrickards/dev/bh2-BH-009/backend/schemas.py:98: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class CallCreate(BaseModel):

backend/schemas.py:180
  /Users/michaelrickards/dev/bh2-BH-009/backend/schemas.py:180: PydanticDeprecatedSince20: Support for class-based `config` is deprecated, use ConfigDict instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    class ChatRequest(BaseModel):

backend/tests/test_accounting_tenant_isolation.py::TestWritePathsRefuseAnotherTenantsCategory::test_patch_transaction_allows_its_own
backend/tests/test_accounting_tenant_isolation.py::TestWritePathsRefuseAnotherTenantsCategory::test_patch_transaction_refuses
  /Users/michaelrickards/dev/bh2-BH-009/backend/accounting.py:364: PydanticDeprecatedSince20: The `dict` method is deprecated; use `model_dump` instead. Deprecated in Pydantic V2.0 to be removed in V3.0. See Pydantic V2 Migration Guide at https://errors.pydantic.dev/2.13/migration/
    for field, value in updates.dict(exclude_unset=True).items():

backend/tests/test_entitlement_defaults.py: 9 warnings
backend/tests/test_entitlement_reads.py: 8 warnings
backend/tests/test_onboarding_flags.py: 6 warnings
  /Users/michaelrickards/dev/bh2-BH-009/backend/onboarding_api.py:143: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    return datetime.utcnow().isoformat()

backend/tests/test_me_endpoint.py: 11 warnings
backend/tests/test_readonly_resolver.py: 179 warnings
backend/tests/test_stripe_webhook_correctness.py: 103 warnings
  /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/pydantic/_internal/_fields.py:727: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    return fac()

backend/tests/test_stripe_webhook_correctness.py: 47 warnings
  /Users/michaelrickards/dev/bh2-BH-009/backend/main.py:1149: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    business.last_stripe_event_at = datetime.utcnow()

backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_replayed_checkout_applies_once
backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_checkout_is_recorded_in_the_audit_table
  /Users/michaelrickards/dev/bh2-BH-009/backend/main.py:1040: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    business.last_stripe_event_at = datetime.utcnow()

backend/tests/test_tenant_isolation_backend_path.py: 180 warnings
  /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default datetime adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
    cursor.execute(statement, parameters)

backend/tests/test_tenant_isolation_backend_path.py: 120 warnings
  /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default date adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
    cursor.execute(statement, parameters)

backend/tests/test_tenant_isolation_backend_path.py: 55 warnings
  /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default date converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
    rows = dbapi_cursor.fetchall()

backend/tests/test_tenant_isolation_backend_path.py: 60 warnings
  /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default timestamp converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
    rows = dbapi_cursor.fetchall()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
718 passed, 33 skipped, 20 xfailed, 785 warnings, 220 subtests passed in 6.82s
```

### Exact final check.sh output

Command: `npm_config_cache="$PWD/.bh009-npm-cache" npm_config_offline=true ./check.sh`

```text
------------------------------------------------------------
  FRONTEND
------------------------------------------------------------
  PASS  tsc --noEmit
  SKIP  eslint  (no lint script in package.json)
------------------------------------------------------------
  BACKEND
------------------------------------------------------------
  PASS  python syntax (py_compile)
        All checks passed!
  PASS  ruff
            business.last_stripe_event_at = datetime.utcnow()
        
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_replayed_checkout_applies_once
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_checkout_is_recorded_in_the_audit_table
          /Users/michaelrickards/dev/bh2-BH-009/backend/main.py:1040: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
            business.last_stripe_event_at = datetime.utcnow()
        
        backend/tests/test_tenant_isolation_backend_path.py: 180 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default datetime adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)
        
        backend/tests/test_tenant_isolation_backend_path.py: 120 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default date adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)
        
        backend/tests/test_tenant_isolation_backend_path.py: 55 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default date converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()
        
        backend/tests/test_tenant_isolation_backend_path.py: 60 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default timestamp converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()
        
        -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
        718 passed, 33 skipped, 20 xfailed, 785 warnings, 220 subtests passed in 6.54s
  PASS  pytest
------------------------------------------------------------
  4 passed   0 failed   1 skipped
  Green. Safe to proceed.
------------------------------------------------------------
```

---

## Stage 2 — implementation (approved by Mike, 8 Oct 2026)

Mike approved the Stage 1 tests and every decision in
`docs/BH-009-DESIGN.md` § "Decisions — Mike, 8 October 2026". Build:

1. **Tests first for the decisions.** Add tests for decisions 2–6 and the
   interim missing-fields header (they are new behaviour Mike approved),
   watch them fail, then implement. Do not weaken any Stage 1 test; if one
   must change to match a decision (e.g. decision 4's "Invoice copy" title),
   change only what the decision requires and say so in Completion evidence.
2. `backend/services/invoice_pdf.py` and `backend/invoice_pdf_api.py`, per
   the design. Register the router in `backend/main.py` — one line, beside
   the other `include_router` calls. No other `main.py` change.
3. Remove the strict-xfail markers as each test passes (strict XPASS will
   force it).
4. Frontend: a **Download PDF** button on each invoice in
   `frontend/client/src/components/InvoicesPanel.tsx`, calling the new
   endpoint with the user's auth and saving the file. If the response has
   `X-Invoice-Missing-Fields`, show a visible warning beside the button
   naming what is missing (e.g. "Customer address not recorded — this is
   not a complete VAT invoice"), not a console message.
5. No migration. No email sending. No change to quote PDFs.
6. Run `./check.sh full` from the worktree (the `.venv` and `node_modules`
   symlinks are there) and paste the output into Completion evidence.

Same rules as Stage 1: no network, no production, no git commit or push —
Claude Code reviews every line, commits and pushes.

**Status** in review — Stage 2 implemented; awaiting Claude Code review


## Completion evidence — Stage 2, Codex, 8 October 2026

**Serves:** North Star P8 correctness and P9 tenant isolation; RC1 P0-4.
**Builder:** Codex. **Reviewer:** Claude Code (review pending).

Built `backend/services/invoice_pdf.py`, `backend/invoice_pdf_api.py`, the
region-owned currency-symbol helper in `backend/services/region.py`, and the
row/drawer Download PDF controls in
`frontend/client/src/components/InvoicesPanel.tsx`. Router registration is
exactly one added line in `backend/main.py`, beside quoting_router; inline
module import keeps the requested one-line main.py change. The endpoint is
read-only, feature-gated and tenant-scoped. Decimal values and stored header
amounts remain authoritative; no invoice total recalculation or money-engine
change. Missing-field warnings remain beside the download buttons, outside
the PDF. Decisions and implementation boundaries are recorded in the design.

**Stage 1 test changes:** no fixture or assertion changes. Removed all 20
strict-xfail case markers (10 decorated test functions) and the unused pending
marker definition after all 20 produced strict XPASS with the implementation.
Updated only explanatory module/helper docstrings. Stage 1 passed unchanged,
including imported-header totals; the new decision tests add the Invoice copy
contract without weakening the original import test.

**Tests first:** added 27 parameterized cases for decisions 2–6, the interim
missing-fields rule, and discount display. Before either implementation module
existed, ran the following command with no xfail markers on the new cases:

`/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_invoice_pdf.py -q -k decision`

Every new case failed with MissingInvoicePDF for its required module. This
proves the missing-implementation red step; assertions were then exercised by
the implementation and passed. The red run's exact case summary follows:

```text
FAILED backend/tests/test_invoice_pdf.py::test_decision_invoice_date_precedence[2026-10-08-2026-10-07-2026-10-06T12:30:00+00:00-08/10/2026]
FAILED backend/tests/test_invoice_pdf.py::test_decision_invoice_date_precedence[None-2026-10-07-2026-10-06T12:30:00+00:00-07/10/2026]
FAILED backend/tests/test_invoice_pdf.py::test_decision_invoice_date_precedence[None-None-2026-10-06T12:30:00+00:00-06/10/2026]
FAILED backend/tests/test_invoice_pdf.py::test_decision_tax_point_only_when_stored_and_different[None-False]
FAILED backend/tests/test_invoice_pdf.py::test_decision_tax_point_only_when_stored_and_different[tax_point1-False]
FAILED backend/tests/test_invoice_pdf.py::test_decision_tax_point_only_when_stored_and_different[tax_point2-True]
FAILED backend/tests/test_invoice_pdf.py::test_decision_vat_number_precedence[CANONICAL-TAX-CANONICAL-TAX-LEGACY-TAX]
FAILED backend/tests/test_invoice_pdf.py::test_decision_vat_number_precedence[None-LEGACY-TAX-CANONICAL-TAX]
FAILED backend/tests/test_invoice_pdf.py::test_decision_vat_number_precedence[   -LEGACY-TAX-CANONICAL-TAX]
FAILED backend/tests/test_invoice_pdf.py::test_decision_import_title_and_origin[False-csv-Imported from CSV]
FAILED backend/tests/test_invoice_pdf.py::test_decision_import_title_and_origin[False-xero-Originally issued from Xero]
FAILED backend/tests/test_invoice_pdf.py::test_decision_import_title_and_origin[True-csv-Imported from CSV]
FAILED backend/tests/test_invoice_pdf.py::test_decision_import_title_and_origin[True-xero-Originally issued from Xero]
FAILED backend/tests/test_invoice_pdf.py::test_decision_invoice_currency_overrides_region[UK-USD-$]
FAILED backend/tests/test_invoice_pdf.py::test_decision_invoice_currency_overrides_region[US-GBP-\xa3]
FAILED backend/tests/test_invoice_pdf.py::test_decision_invoice_currency_overrides_region[UK-CAD-CAD ]
FAILED backend/tests/test_invoice_pdf.py::test_decision_registered_foreign_currency_refused[quote]
FAILED backend/tests/test_invoice_pdf.py::test_decision_registered_foreign_currency_refused[csv]
FAILED backend/tests/test_invoice_pdf.py::test_decision_registered_foreign_currency_refused[xero]
FAILED backend/tests/test_invoice_pdf.py::test_decision_unregistered_stored_vat_refused[20.00]
FAILED backend/tests/test_invoice_pdf.py::test_decision_unregistered_stored_vat_refused[-20.00]
FAILED backend/tests/test_invoice_pdf.py::test_decision_missing_address_threshold_and_no_guess[250.00-True-False]
FAILED backend/tests/test_invoice_pdf.py::test_decision_missing_address_threshold_and_no_guess[250.01-True-True]
FAILED backend/tests/test_invoice_pdf.py::test_decision_missing_address_threshold_and_no_guess[249.99-True-False]
FAILED backend/tests/test_invoice_pdf.py::test_decision_missing_address_threshold_and_no_guess[250.01-False-True]
FAILED backend/tests/test_invoice_pdf.py::test_decision_missing_fields_and_complete_header
FAILED backend/tests/test_invoice_pdf.py::test_decision_discount_uses_stored_taxable_not_percentage_input
27 failed, 22 deselected in 0.57s
```

First implementation run: `20 failed, 29 passed, 1 warning in 1.37s`;
all 20 failures were strict XPASS of Stage 1, requiring marker removal.
Then `49 passed, 1 warning in 1.39s` with all approved cases unmarked.

Supplemental tests cover actual import writers' null net/tax fields (two
cases), ambiguous quote links, long-document line retention/pagination and
page-one drawing positions. These were added after implementation; they are
not claimed as part of the 27 red-first decision cases. The long-text test's
initial literal-angle-bracket assertion failed because ReportLab emits escaped
brackets in separate text fragments; fixed that new assertion to join fragments.
No Stage 1 assertion was touched.

**Visual verification:** offline synthetic PDFs and CoreGraphics previews
inspected: standard one-page invoice, first/last pages of a 65-line ten-page
invoice, and a header-only Xero copy missing address/net/tax. PDFKit extracted
text as an independent check. A PDFKit thumbnail artefact initially appeared
to overlap the heading; CoreGraphics and PDF coordinates disprove that.
ReportLab may repeat a column header before a split row on the same page.
Local ignored evidence: `build/bh009-review/` (PDFs, PNGs, extracted text,
red/XPASS logs and full verification output). No dependencies installed.

**Not verified:** browser download/auth refresh/CORS and warning UX end to end;
all PDF pages/readers/fonts/printing; PostgreSQL numeric driver behaviour, RLS,
production schema/data, and legal completeness under HMRC Notice 700. The
in-memory tests prove application query scoping and the real feature resolver,
not JWT verification. The existing preflight changed-file traps inspect the
committed branch diff/staged files, not all unstaged Stage 2 work; an additional
manual scan of Stage 2 files and diff inspection supplement it. Claude remains
the independent reviewer; no review approval is claimed.

**Mike's behavioural click test:** Invoices → Download PDF on a row (or open
its drawer → Download PDF). Open the file and compare identities, dates, lines
and totals to the invoice. For a registered invoice over 250 without an address,
confirm the visible Customer address warning; at 250 it should not flag that
field. Confirm imported records say Invoice copy; check the explanatory
refusals for registered non-GBP and unregistered stored VAT. Downloads should
remain available for unpaid/cancelled subscriptions with invoicing enabled.

No network, production access, migration, email, dependency installation,
commit or push. All authored files and temporary review artefacts are inside
this worktree. Quote PDF and money engine are unchanged.

### Final Stage 2 check.sh full output

Full output pasted below; trailing spaces on blank lines removed for Markdown.
The byte-for-byte log is in `build/bh009-review/check-full.txt`.

Run from this worktree root with existing venv/node_modules symlinks; npm's
cache is worktree-local and offline mode is enabled:

`npm_config_cache="$PWD/build/bh009-review/npm-cache" npm_config_offline=true ./check.sh full`

```text
------------------------------------------------------------
  FRONTEND
------------------------------------------------------------
  PASS  tsc --noEmit
  SKIP  eslint  (no lint script in package.json)
------------------------------------------------------------
  BACKEND
------------------------------------------------------------
  PASS  python syntax (py_compile)
        All checks passed!
  PASS  ruff
            business.last_stripe_event_at = datetime.utcnow()

        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_replayed_checkout_applies_once
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_checkout_is_recorded_in_the_audit_table
          /Users/michaelrickards/dev/bh2-BH-009/backend/main.py:1041: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
            business.last_stripe_event_at = datetime.utcnow()

        backend/tests/test_tenant_isolation_backend_path.py: 180 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default datetime adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)

        backend/tests/test_tenant_isolation_backend_path.py: 120 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default date adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)

        backend/tests/test_tenant_isolation_backend_path.py: 55 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default date converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()

        backend/tests/test_tenant_isolation_backend_path.py: 60 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default timestamp converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()

        -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
        770 passed, 33 skipped, 785 warnings, 220 subtests passed in 6.73s
  PASS  pytest
------------------------------------------------------------
  PREFLIGHT (deploy traps)
------------------------------------------------------------

        TRAP 1 — requirements.txt sync
          PASS  every backend dep is present in root requirements.txt

        TRAP 2 — trailing newline on requirements.txt
          PASS  trailing newline present

        TRAP 3 — repo location
          PASS  repo is outside CloudStorage/Dropbox

        TRAP 4 — create_all() RLS drift warning
          PASS  no models.py changes on this branch
                comparison base: origin/main

        TRAP 5 — secret scan on staged/changed files
          PASS  no secret patterns in changed files

        PREFLIGHT PASSED — safe to push.

  PASS  preflight
------------------------------------------------------------
  5 passed   0 failed   1 skipped
  Green. Safe to proceed.
------------------------------------------------------------
```


## Completion evidence — Stage 2 repair cycle 1, Codex, 9 October 2026

**Status:** in review — all four Claude Code findings repaired; awaiting
Claude Code re-review. Serves North Star P8 and the correctness prerequisite.
User explicitly authorised these repairs. Base HEAD: `9dfafeb` (clean worktree
at start). No network, commit, push, migration or production action performed.

1. External invoices: CSV, Xero, QuickBooks and FreeAgent sources, or a set
   external_source/external_id, render as Invoice copy. Known systems are named;
   CSV says Imported from CSV. An external ID without an identified provider
   says Originally issued externally rather than guessing a system.
2. Discounted registered invoices now show Subtotal / Discount / Total excluding
   VAT / Total VAT / Total payable. The displayed net is stored subtotal minus
   stored discount, accepted only when it exactly equals the sum of stored line
   taxable values. Otherwise it is omitted and `total_excluding_vat` is reported
   in `X-Invoice-Missing-Fields`. Missing subtotal or unavailable taxable lines
   also cannot establish that equality. Issued subtotal, VAT and payable values
   remain unchanged. Unregistered invoices retain Subtotal / optional Discount /
   Total payable, with no VAT rows.
3. Zero discounts, including those derived from itemised lines, no longer print.
4. main.py imports `router as invoice_pdf_router` and registers that name.

Tests added in `backend/tests/test_invoice_pdf.py` (22 parameterised cases):
- `test_repair_external_invoice_copy`: 14 source/metadata cases with and without lines.
- `test_repair_discounted_net_matches_stored_taxable`: asserts exact Decimal
  equality and the complete ordered totals text.
- `test_repair_unverified_net_omitted_and_reported`: mismatch and missing-subtotal
  endpoint cases verify omission, diagnostic header and unchanged issued totals.
- `test_repair_zero_discount_row_omitted`: four explicit/derived-zero cases for
  registered and unregistered businesses.
- `test_repair_router_uses_explicit_import`: AST check of import and registration.

All 22 cases were observed failing against the committed Stage 2 implementation
before any production-code edits. Command:
`/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_invoice_pdf.py -q -k repair`
Result: `22 failed, 54 deselected, 1 warning in 1.35s`.
Failures were assertions for the incorrect title, totals/diagnostic header,
zero-discount row and absent explicit import, not harness errors.

After repairs, the complete invoice suite passed:
`/Users/michaelrickards/dev/business-hero-2/.venv/bin/python -m pytest backend/tests/test_invoice_pdf.py -q`
Result: `76 passed, 1 warning in 1.58s`.

Final verification command (offline npm; .venv points to the specified Python):
`npm_config_cache="$PWD/.bh009-npm-cache" npm_config_offline=true ./check.sh full`
Exit code: 0. TypeScript, py_compile, ruff, pytest and all five deploy traps passed.
Backend result: `792 passed, 33 skipped, 785 warnings, 220 subtests passed in 6.60s`.
Gate result: `5 passed   0 failed   1 skipped` (eslint: no lint script).
`git diff --check` also passed.

Manual behaviour check: Invoices → select a QuickBooks/FreeAgent import → Download
PDF and confirm Invoice copy and the named source; download a discounted native
invoice and confirm the totals order and post-discount net; download a zero-discount
invoice and confirm no Discount row. Automated checks verify rendered text and
HTTP behaviour, not visual layout or third-party sync behaviour. No new visual
or live integration verification is claimed.

### Full check output

```text
------------------------------------------------------------
  FRONTEND
------------------------------------------------------------
  PASS  tsc --noEmit
  SKIP  eslint  (no lint script in package.json)
------------------------------------------------------------
  BACKEND
------------------------------------------------------------
  PASS  python syntax (py_compile)
        All checks passed!
  PASS  ruff
            business.last_stripe_event_at = datetime.utcnow()

        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_replayed_checkout_applies_once
        backend/tests/test_stripe_webhook_correctness.py::TestCheckoutIsDeduplicatedToo::test_a_checkout_is_recorded_in_the_audit_table
          /Users/michaelrickards/dev/bh2-BH-009/backend/main.py:1043: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
            business.last_stripe_event_at = datetime.utcnow()

        backend/tests/test_tenant_isolation_backend_path.py: 180 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default datetime adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)

        backend/tests/test_tenant_isolation_backend_path.py: 120 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/default.py:952: DeprecationWarning: The default date adapter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            cursor.execute(statement, parameters)

        backend/tests/test_tenant_isolation_backend_path.py: 55 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default date converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()

        backend/tests/test_tenant_isolation_backend_path.py: 60 warnings
          /Users/michaelrickards/dev/business-hero-2/.venv/lib/python3.12/site-packages/sqlalchemy/engine/cursor.py:1201: DeprecationWarning: The default timestamp converter is deprecated as of Python 3.12; see the sqlite3 documentation for suggested replacement recipes
            rows = dbapi_cursor.fetchall()

        -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
        792 passed, 33 skipped, 785 warnings, 220 subtests passed in 6.60s
  PASS  pytest
------------------------------------------------------------
  PREFLIGHT (deploy traps)
------------------------------------------------------------

        TRAP 1 — requirements.txt sync
          PASS  every backend dep is present in root requirements.txt

        TRAP 2 — trailing newline on requirements.txt
          PASS  trailing newline present

        TRAP 3 — repo location
          PASS  repo is outside CloudStorage/Dropbox

        TRAP 4 — create_all() RLS drift warning
          PASS  no models.py changes on this branch
                comparison base: origin/main

        TRAP 5 — secret scan on staged/changed files
          PASS  no secret patterns in changed files

        PREFLIGHT PASSED — safe to push.

  PASS  preflight
------------------------------------------------------------
  5 passed   0 failed   1 skipped
  Green. Safe to proceed.
------------------------------------------------------------
```
