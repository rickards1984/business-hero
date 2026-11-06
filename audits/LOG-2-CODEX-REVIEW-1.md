# LOG-2 — Codex review 1 (preserved verbatim)

**Finding — P1:** [backend/providers/xero.py:49](/Users/michaelrickards/dev/bh2-LOG-2/backend/providers/xero.py:49) checks only the exact `accounting.settings.read` scope. Xero also permits GET Accounts with `accounting.settings`. A valid connection holding that broader scope will therefore skip Accounts every sync, potentially withholding payments whose accounts cannot be identified—even after reconnecting with the same broader grant. [Xero scope documentation](https://developer.xero.com/documentation/guides/oauth2/scopes/)

Accept either scope before skipping or diagnosing missing permission, and add a regression test for the broader grant.

Otherwise:
- Parsing supports Xero’s documented JWT scope array. [Token documentation](https://developer.xero.com/documentation/guides/oauth2/token-types/)
- `fetch_chart` catches permission errors before outer auth handlers.
- Skips do not advance cache freshness; new tokens are inspected again.
- Added logs contain no secrets.

All 8 targeted tests passed. Full `check.sh` was not run because it writes files. No files modified.