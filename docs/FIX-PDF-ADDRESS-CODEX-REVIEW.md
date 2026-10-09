# Fix: invoice PDF uses the invoice's own address — Codex review

| | |
|---|---|
| Reviewed commit | `fix/pdf-uses-invoice-address` first commit |
| Session id | `01a1222b-7928-7100-b976-a95b5a84d8cf` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 27,646` |
| **Verdict** | **ACCEPT-WITH-CHANGES** |

Verbatim:

---

**ACCEPT-WITH-CHANGES** — address fix is correct; broader BH-010 coverage needs tightening.

- [invoice_pdf_api.py:84](backend/invoice_pdf_api.py:84): invoice address wins; blank/missing addresses retain the tenant-scoped, unambiguous quote fallback.
- [invoice_pdf.py:77](backend/services/invoice_pdf.py:77): existing date inconsistency remains: `issue_date` overrides BH-010’s `invoice_date` when both differ. Prefer `invoice_date`, with a conflicting-dates regression test.
- [test_invoice_pdf.py:668](backend/tests/test_invoice_pdf.py:668): “manual” test still uses `source='quote'`. Set `manual` and assert the title. Its missing-address-header assertion is ineffective: the registered £120 fixture permits an absent address. Use an amount above £250.
- All four tests exercise real SQL and ReportLab rendering. The first two catch the address regression; fallback and supply-date tests cover existing behaviour. [Line 688](backend/tests/test_invoice_pdf.py:688) should assert `Tax point: 20/09/2026`, not merely the date.

Supply-date rendering and manual-source title logic are otherwise correct; missing-field reporting consumes the resolved address correctly.

Permitted test run: **80 passed**, one deprecation warning. No edits or network use.
---

### Response — Claude Code

| Point | Action |
|---|---|
| Address fix correct | — |
| Prefer `invoice_date` over `issue_date` | **Not done: it would reverse Mike's recorded BH-009 decision 2** (8 Oct: issue_date, else invoice_date, else created_at), which an approved test encodes; the full check caught the conflict. Harmless for new invoices: BH-010 writes only invoice_date. A test now proves a new invoice shows its own date |
| "Manual" test used a quote source; the address assertion could not fail at £120 | Test now uses `source='manual'`, £600 gross, asserts the "VAT invoice" title; a companion test proves the same invoice WITHOUT an address IS flagged |
| Assert the full "Tax point:" label | Done |

`./check.sh full`: 888 passed.
