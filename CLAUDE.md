# CLAUDE.md — Claude-specific guidance

**Read `AGENTS.md` first. It is the working agreement for every agent and it
governs.** This file adds only what is specific to Claude Code, and
deliberately does not repeat AGENTS.md. If the two ever disagree, AGENTS.md
wins — tell Mike, so the contradiction gets fixed rather than carried.

| You need | Read |
|---|---|
| The rules — verification loop, autonomy tiers, do-not-regress, task packet, workflow | `AGENTS.md` |
| What actually works today | `docs/CURRENT_STATE.md` |
| What is in the release | `docs/RC1_SCOPE.md` |
| When a ticket may merge | `docs/DEFINITION_OF_DONE.md` |
| Why a thing is the way it is | `audits/` |

---

## Model selection

Cost and quality both move with this, so it is worth a deliberate choice.

| Work | Model |
|---|---|
| RED tier — money, migrations, security, entitlement, auth | **Opus** |
| Writing tests for RED work | **Opus** |
| Implementation once the tests exist | **Sonnet** |
| Mechanical work — UI fixes, boilerplate, refactors, copy | **Sonnet** |

The principle from `audits/SETUP-HARNESS.md`: with `check.sh` in place, a
cheaper model iterating against a real test signal beats an expensive model
guessing once. Reserve Opus for work where a wrong answer is expensive and
the feedback loop cannot catch it.

---

## Working in this repository

**Bash over dedicated tools where it fits.** Reading with `sed -n`, searching
with `grep`, and batching independent calls into one message is materially
cheaper here than one tool call per file. The repository is large — 41k lines
of Python, 34k of TypeScript — so targeted reads beat whole-file ones.

**Run long checks in the background and wait once.** Do not poll with
`sleep`. `./check.sh full` takes seconds; a Playwright suite will not.

**Do not re-derive what the audits already establish.** `audits/` holds three
weeks of evidence: five migration runbooks, four specs, a full findings log
and a live schema dump. Re-deriving a conclusion that is already written down
costs tokens and risks reaching a different answer from the same facts. Read
the document, cite it, move on.

**Verify before recommending.** Memory and documents describe the repository
as it was. If you are about to recommend a file, function or flag, confirm it
still exists. Two specific traps in this codebase:

- Migration files are not evidence of live state.
- A status claim in a document is not evidence of code. `CLAUDE.md` itself
  carried "PART D done" for months while the entitlement spec's PART D —
  server-side enforcement — remained one endpoint out of seven. Both readings
  were honest; only one was checked.

---

## Verification commands

```bash
./check.sh              # fast — during work
./check.sh full         # before any push; adds the deploy traps
.venv/bin/python -m pytest backend/tests/test_NAME.py -v   # one suite
```

Use `.venv/bin/python`. System `python3` is 3.9 and cannot import a backend
that targets 3.11 — a `ModuleNotFoundError: fastapi` from `python3` means the
wrong interpreter, not a missing dependency.

---

## Current position

Branch `foundation/rc1-baseline`. The engineering foundation is being
established; **no large implementation stream begins until Codex has
independently reviewed it and Mike has accepted the RC1 boundary.**

Live state, verified status of every module, and the ten open risks are in
`docs/CURRENT_STATE.md`. It supersedes the running "Current task" section
this file used to carry — one place, kept honest, rather than two that drift.

**One open RED item in production:** 033 STEP 21, removing the stopgap
`receptionist: true` from MSC and New Body. Gated on STEP 20d passing against
the deployed backend (`9826f61`). Details in
`audits/033-PROD-RUNBOOK.md` and `docs/CURRENT_STATE.md` §8.
