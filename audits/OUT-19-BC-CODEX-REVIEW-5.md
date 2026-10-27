Reviewed `254c714` against `b9eeb08` under North Star P8.

- **P1:** No defects found.
- **P2:** Both closed. Removing each fix in memory makes its regression fail: framing yields **128p against a 109p hold**; zero-dispatch retries retain **1,608p instead of zero**.
- **Backlog:** No new findings; review 4’s remaining backlog stands.

No current model-drafter path produces `ActionRefused` after an unrecorded dispatched attempt. `json_chat` notes each failed attempt before reaching `AllProvidersFailed`; `_model_json` converts only that exception. Other errors retain the hold. Settlement failures roll back both ledger writes and hold release.

**Verification:** 32 allowance tests passed using in-memory SQLite, with bytecode/cache writes disabled. `check.sh` was not run because it writes files. No files modified, committed or pushed.

**Verdict: APPROVE.**