# TIER 1 — Core Quoting Fixes (7 July 2026)

Session: `fix-core-quoting-features` branch. Fixes the three launch-critical failures
found in the first-time-customer walkthrough: AI quote generation, quote PDF
generation, and the quote→invoice path. Fixes 1, 2, and 3a are complete on this
branch; 3b (manual invoice creation) is **deferred** — full plan at the bottom.

Deploy notes: no new env vars. One new package in root `/requirements.txt`
(`reportlab>=4.0`). Deploy backend (Railway) and frontend (Vercel) together —
fix 2 spans both.

---

## Fix 1 — Quote PDF generation (was: 503/error, dead "Preview PDF" button)

**Broken:** `POST /v1/quotes/{id}/generate-pdf` failed on every call in production.

**Root cause:** `reportlab` was listed in `backend/requirements.txt:23` but missing
from root `/requirements.txt` — and Railway (Nixpacks, repo root) installs only the
root file. Every PDF request died at `backend/services/quote_pdf.py:28`
(`from reportlab.lib.pagesizes import A4`, imported at call time) with
`ModuleNotFoundError`. The endpoint code itself was correct.

**Changed:** `requirements.txt:20` — added `reportlab>=4.0` (same constraint as
backend's file). No code changes.

### ⚠ The two-requirements-files drift trap (third strike)

Root `/requirements.txt` is what production installs; `backend/requirements.txt`
is what developers read. Packages added only to backend's file crash production:

1. `slowapi` — missing from root, crashed the 5 July deploy (commit 97f7d9f).
2. `reportlab` — missing from root, broke all PDF generation (this fix).

**Both files are confirmed in sync as of this session** — a full comparison
(package names in backend's file vs root's) found zero remaining gaps, and a scan
of every third-party import in backend code confirmed root covers them all.
**Rule going forward: any new dependency goes in BOTH files, and root
`/requirements.txt` is the one that counts. Before pushing a fix that adds a
package: `grep <package> requirements.txt`.**

---

## Fix 2 — AI quote generation (was: silent reset, console `502: AI service error: 400`)

**Broken:** `POST /v1/quotes/ai/generate` always failed; the UI showed "Analysing…"
then reset with no visible error.

**Root cause:** the OpenAI request payload in `backend/quoting_api.py` sent
`temperature: 0.3` and `max_tokens: 4096`. GPT-5-family models (including the
default `QUOTE_AI_MODEL=gpt-5.4`, a valid current model) reject both with a 400 —
`temperature` supports only the default value, and `max_tokens` was renamed
`max_completion_tokens`. The endpoint translated that 400 into a 502 for the
client (`quoting_api.py:1083-1085`). The upstream error body was already being
logged (`logger.error("OpenAI API error: …")`) — check Railway logs around any
past failure to see the exact rejection. Note the four *working* `gpt-5` calls
elsewhere in the codebase (`assistant_chat.py`, `app/email/service.py`) send
neither parameter — only the quoting endpoint did.

**Changed:**
- `backend/quoting_api.py:1067-1078` — removed `temperature`, replaced
  `max_tokens` with `max_completion_tokens: 4096`. The new payload is accepted by
  both GPT-5-family and GPT-4o-family models, so it is safe for any
  `QUOTE_AI_MODEL` value.
- `frontend/client/src/pages/QuotesPage.tsx:112-124` — new `apiErrorDetail()`
  helper: extracts the backend's human-readable `detail` from thrown
  `"<status>: <json>"` errors.
- `frontend/client/src/pages/QuotesPage.tsx` (`handleGenerateAI` catch block) —
  error snackbar now shows e.g. "Quote generation failed: AI service error: 400.
  Please try again." instead of the raw `502: {"detail":…}` string.

**Still worth checking (couldn't be done from this machine):** the value of
`QUOTE_AI_MODEL` in Railway → Variables. If unset, the `gpt-5.4` default applies
and is correct. If set to an old experiment, unset it.

---

## Fix 3a — Quote→invoice path (was: no "Convert to Invoice" anywhere; silent failures)

**Broken:** the walkthrough found no way to turn a quote into an invoice.

**Root cause:** the backend endpoint has existed all along
(`POST /v1/quotes/{id}/convert-to-invoice`, `backend/quoting_api.py:512-571`) and
accepts quotes in `draft`, `sent`, or `accepted` status (line 529) — but the UI
only rendered the button for `accepted` quotes, a status nothing in the normal
flow had reached yet. Compounding it, the button's handler (`handleStatusAction`)
had a bare `catch {}` and no success feedback: clicking any status action showed
the user nothing, ever.

**Changed (all `frontend/client/src/pages/QuotesPage.tsx`):**
- Lines 1120, 1130, 1135 — "Convert to Invoice" button now renders for `draft`,
  `sent`, and `accepted` quotes (matching the backend's allowed statuses).
- Lines 389-415 — `handleStatusAction` rewritten: success snackbar for every
  action (conversion reports the new invoice number: "Invoice INV-0001 created —
  see Finance → Invoices"), and failures show the backend's reason via
  `apiErrorDetail` instead of vanishing.

**No backend changes** — the endpoint was already correct.

---

## Silent-failure spots addressed vs noted

The walkthrough's recurring theme: core actions failing with zero user feedback.

| Spot | State |
|---|---|
| AI generate error snackbar (`QuotesPage.tsx`) | Fixed — human-readable message (fix 2) |
| Status actions incl. convert (`handleStatusAction`) | Fixed — success + error snackbars (fix 3a) |
| PDF preview/download | Already alerted on failure; root cause was backend (fix 1) |
| `handleSaveQuote`, `handleDeleteQuote`, send email/WhatsApp | Already alert on failure — untouched |
| `openDetail` / `openEdit` bare `catch {}` | **Not fixed** (out of scope) — noted for a UI-polish session |
| `handleSaveSettings` bare `catch {}` | **Not fixed** (out of scope) — noted |

---

## Manual test checklist (after deploy)

Use the walkthrough job: **"supply and fit 3 internal fire doors incl.
ironmongery and making good"**.

1. **AI generation:** Quotes → New Quote → AI mode → paste the job → Generate.
   - Expect: ~10-30s "Analysing…", then populated line items grouped by trade
     (Carpentry / Materials / …) and a green success snackbar.
   - Error path (optional): set `QUOTE_AI_MODEL=nonsense` in Railway → expect a
     visible red snackbar, not a silent reset. Unset afterwards.
2. **PDF:** save the quote → open it → "Preview PDF".
   - Expect: PDF opens in a new tab (allow pop-ups), branded, itemised, with VAT
     and total. "Download PDF" saves `QTE-XXXX.pdf`.
   - If it fails: check the Railway build log installed `reportlab`.
3. **Convert to invoice:** open the same quote (status `draft`) —
   - Expect: "Convert to Invoice" button is now visible. Click it.
   - Expect: green snackbar "Invoice INV-XXXX created — see Finance → Invoices";
     quote status becomes `invoiced`; the invoice appears in Finance → Invoices
     with the right customer/amount/due date (+30 days).
4. **Feedback regression check:** mark a `sent` quote accepted/declined — expect
   a confirmation snackbar each time (previously: nothing).

---

## Deferred: 3b — manual invoice creation (missing end to end)

**The gap:** there is no `POST /v1/invoices` (backend has only list, CSV import,
status patch, archive, chase, Xero sync — see `backend/main.py:2416` onwards) and
Finance → Invoices offers only "Upload CSV" (`InvoicesPanel.tsx:681`). Confirmed
missing end to end, not just UI.

**Staged plan (diagnosis done, zero code written — next session implements):**

1. **Schema** — add to `backend/schemas.py` (after `class Invoice`, ~line 265):
   `InvoiceCreateRequest`: `customer_name: str`, `amount: float`,
   `due_date: date`, optional `customer_email`, `issue_date`,
   `invoice_number` (auto-generated when blank), `currency` (default GBP),
   `status` (default `unpaid`). Add it to `main.py`'s `from schemas import (…)`.
2. **Hoist helper** — move `invoice_to_response` (currently nested inside
   `list_invoices` at `backend/main.py:2490`) to module level, body unchanged,
   so the new endpoint can reuse it instead of duplicating ~20 lines of mapping.
3. **Endpoint** — `POST /v1/invoices` (response_model `InvoiceSchema`, 201),
   placed after `list_invoices`. Details that matter:
   - Auth via `Depends(get_current_user_business)` + `Depends(get_session)`,
     same as CSV import.
   - Validate: non-empty `customer_name`, `amount > 0` (400), status normalised
     to `paid|unpaid|overdue|cancelled` (else `unpaid`) — mirrors CSV import.
   - Custom `invoice_number`: 409 if it already exists for the business
     (unique constraint `uq_invoice_business_number`, `models.py:224`).
   - Auto-number when blank: start from `INV-{count+1:04d}` but **loop past
     collisions** — CSV/Xero imports may already occupy INV-style numbers
     (`convert_to_invoice` at `quoting_api.py:536-540` has this latent bug; do
     not copy it blindly).
   - Create via the SQLModel `Invoice` (`models.py:220`): `source="manual"`,
     `amount=Decimal(str(amount))`, `amount_due=amount` when unpaid.
     `Decimal`, `select`, `func` are already imported in `main.py`.
4. **UI** — `frontend/client/src/components/InvoicesPanel.tsx`:
   - "New Invoice" button (import `Add as AddIcon`) next to "Upload CSV"
     (toolbar around line 666), opening a Dialog (all MUI components needed are
     already imported): customer name*, email, amount* (£ adornment),
     due date* (prefill today+30d, `type="date"`), optional invoice number
     ("auto-generated if blank").
   - Submit → `apiRequest('POST', '/v1/invoices', …)` → on success:
     `setSuccessMessage("Invoice INV-XXXX created")` (existing Snackbar,
     line ~1161), close dialog, `fetchInvoices()`.
   - **Errors must render INSIDE the dialog** (local error state + `<Alert>`) —
     the panel's page-level error Alert (line ~479) sits behind the modal.
   - Update the empty-state copy ("Upload a CSV file to import invoices",
     ~line 696) to also mention creating one manually.
5. **Checks** — `python3 -m py_compile backend/main.py backend/schemas.py`;
   `cd frontend && ./node_modules/.bin/tsc --noEmit -p tsconfig.json` and confirm
   no NEW errors (43 pre-existing errors in unrelated files are expected — Vite
   builds don't run tsc, so they never block deploys).

---

*Diagnosed and fixed with Claude Code (Fable 5), 7 July 2026. Human commits and
deploys manually.*
