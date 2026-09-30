# BH-008 — Codex review

| | |
|---|---|
| Reviewed commit | `1272e6eebdef87a53d7be128b2e43b89e5208b9f` (`ticket/BH-008-gate-env-leak`) |
| Tool | Codex CLI 0.153.4, `codex exec --sandbox workspace-write` (to run pytest), prompt on stdin |
| Model | `gpt-6-astra` |
| Session id | `01a0f461-0354-7b81-aaa3-ea2f13f22555` |
| Worktree | `~/dev/bh2-BH-008-review`, detached at the reviewed commit; reviewer made no edits |
| Usage, as reported | `tokens used 30,932` |
| **Verdict** | **ACCEPT** |

Verbatim below; response at the end.

---

**ACCEPT** — no blocking defects in this commit.

Non-blocking observations, most significant first:

- **Drift guard has limited coverage** — `backend/tests/test_harness_gates.py:277`. It detects only `${NAME:-…}` expressions, including those in comments. Future bare `$NAME`, `${NAME-default}`, or sourced-file controls could escape detection. Today it captures all three project-specific controls: I found no additional controls or sourced files in the scripts. Bare `$PREFLIGHT_BASE` uses refer to the already-covered variable.
- **Raw evidence becomes less visible** — `.gitignore:24`. New matching Supabase exports disappear from ordinary status/add operations. The comment’s rename requirement is manual, so evidence could be forgotten. Existing tracked CSVs remain tracked; the dated BH-001 evidence names do not match this pattern.

The diagnosis is correct. The filter at `backend/tests/test_harness_gates.py:63` isolates fixture subprocesses without altering the parent environment. Explicit `env=` still wins. Default refusal tests therefore exercise their intended conditions, while the explicit escape test still exercises the override. The real `check.sh full` and preflight retain the caller’s controls. This removes the reported push blocker without introducing a gate bypass; it does not guarantee an otherwise failing push succeeds.

I found no other subprocess launch paths in the test suite leaking these controls.

**Verification:** using the existing main checkout’s interpreter because this worktree lacks `.venv/bin/python`:

- Normal environment: **26 passed, 1 skipped**.
- `PREPUSH_ALLOW_UNTRACKED=1`: **26 passed, 1 skipped**.

The existing unrelated-ancestry test skipped because it could not create an orphan commit. No full check or actual push was performed. No edits or network access; working tree remains clean.
---

## Response — Claude Code, 30 September 2026

| Observation | Action |
|---|---|
| Drift guard catches only `${NAME:-…}`, including comments | **Taken.** It now matches every fallback form (`:-` `-` `:=` `=` `:?` `?` `:+` `+`), ignores comment lines, and fails if any of the three scripts `source` another file. Bare `$NAME` is still not matched; the docstring explains why that is acceptable: all three scripts run under `set -u`, so an unset control read bare aborts the script, and a working control needs a fallback form |
| Raw Supabase exports become less visible | **Kept, as an accepted trade-off.** The alternative is what happened on 30 Sep: an untracked export blocked every push. Evidence is committed by renaming into the dated `BH-001-prod-*` form, which the pattern does not match; the `.gitignore` comment says so |
| Orphan-commit test skipped in the reviewer's run | Environment-specific to the review worktree; it runs and passes in the main checkout (27 passed) |

Not re-reviewed: the drift-guard widening is a strictly stronger version of the reviewed check.
