"""Regression tests for the verification harness itself.

Every case here is a false-success path that Codex demonstrated in foundation
review 001 or its re-review: a command that exited 0, or printed "Green. Safe
to proceed.", while having verified nothing. The harness is the thing that
tells us whether everything else is safe, so a silent hole in it is worse than
a bug in a feature.

These call the real scripts as subprocesses. They are fast because every case
fails (or is refused) early, before any heavy work.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECK = REPO / "check.sh"
PREFLIGHT = REPO / "scripts" / "preflight.sh"
HOOK = REPO / ".githooks" / "pre-push"


# NOTE: no test here may invoke ./check.sh in a mode that runs the suite.
# check.sh runs pytest, pytest runs this file, and the recursion does not
# terminate. Every subprocess case below either fails at argument validation
# (before any work) or calls preflight/the hook directly. The one property
# that would need a full run — that valid modes are still accepted — is
# asserted against check.sh's source instead.


# Every variable .githooks/pre-push, scripts/preflight.sh or check.sh reads to
# change its own behaviour. Keep in step with those files:
#   grep -ohE '\$\{?[A-Z][A-Z0-9_]+' .githooks/pre-push scripts/preflight.sh check.sh
_GATE_CONTROLS = frozenset({"PREPUSH_ALLOW_UNTRACKED", "PREFLIGHT_BASE", "SKIP_RLS_DRIFT"})


def run(cmd, cwd=REPO, env=None, stdin=None):
    """Run a command with every GIT_* variable stripped from the environment.

    This is not tidiness, it is the difference between a test and an incident.
    When `git push` invokes the pre-push hook, git exports GIT_DIR and
    GIT_INDEX_FILE into the hook's environment. The hook runs ./check.sh, which
    runs pytest, which runs this file. GIT_DIR overrides repository discovery
    regardless of cwd — so `git commit` inside a throwaway fixture repo under
    tmp_path committed onto the REAL branch instead, and `git rev-parse
    --show-toplevel` inside the hook under test resolved to the real worktree
    rather than the fixture.

    That happened: it moved a live ticket branch onto a commit containing two
    fixture files. Recovered from reflog, but the branch was briefly wrong.

    Stripping GIT_* makes each fixture repo genuinely independent, and makes
    these tests safe to run from inside a git hook — which is exactly where
    check.sh runs them.

    The gate's own controls are stripped for the same reason (BH-008): a
    variable the caller set to steer THIS push must not steer the hook or
    preflight a test launches. A test that wants one passes it via `env=`.
    """
    e = {
        k: v for k, v in os.environ.items()
        if not k.startswith("GIT_") and k not in _GATE_CONTROLS
    }
    if env:
        e.update(env)
    return subprocess.run(
        cmd, cwd=cwd, env=e, input=stdin, capture_output=True, text=True
    )


# --------------------------------------------------------------- check.sh ---

@pytest.mark.parametrize("mode", ["ful", "FULL", "--full", "fastt", ""])
def test_check_rejects_unrecognised_mode(mode):
    """`./check.sh ful` used to run fast mode and print "Green. Safe to
    proceed." having skipped every deploy trap. A typo must not downgrade the
    gate silently."""
    r = run([str(CHECK), mode])
    assert r.returncode != 0, f"mode {mode!r} was accepted"
    assert "Green. Safe to proceed." not in r.stdout


def test_check_rejects_extra_arguments():
    r = run([str(CHECK), "full", "extra"])
    assert r.returncode != 0
    assert "Green. Safe to proceed." not in r.stdout


def test_check_still_accepts_the_documented_modes():
    """The fail-closed guard must not reject valid modes. Asserted against the
    source rather than by running the gate: invoking ./check.sh in a mode that
    runs the suite would re-enter this file and recurse without terminating."""
    src = CHECK.read_text()
    assert "fast|full)" in src, "the mode allow-list no longer accepts fast/full"
    assert 'MODE="${1-fast}"' in src, "the default mode is no longer fast"
    assert 'MODE="${1:-fast}"' not in src, (
        "the ${1:-fast} form treats an explicitly-passed empty argument as "
        "absent, so `./check.sh \"\"` runs the gate instead of being rejected"
    )


# -------------------------------------------------------------- preflight ---

def test_preflight_rejects_base_equal_to_head():
    """PREFLIGHT_BASE=HEAD produced an empty diff and exited 0 reporting
    "no changed files to scan" — traps 4 and 5 inspected nothing."""
    r = run([str(PREFLIGHT)], env={"PREFLIGHT_BASE": "HEAD"})
    assert r.returncode != 0
    assert "PREFLIGHT PASSED" not in r.stdout


def test_preflight_rejects_unresolvable_base():
    r = run([str(PREFLIGHT)], env={"PREFLIGHT_BASE": "refs/heads/no-such-ref"})
    assert r.returncode != 0
    assert "PREFLIGHT PASSED" not in r.stdout


def test_preflight_rejects_base_with_no_common_ancestry(tmp_path):
    """A ref with no merge base makes `git diff a...b` fail. The empty output
    of a FAILED diff used to read as "nothing changed"."""
    orphan = run(
        ["git", "commit-tree", "-m", "orphan", "HEAD^{tree}"],
    ).stdout.strip()
    if not orphan:
        pytest.skip("could not create an orphan commit")
    r = run([str(PREFLIGHT)], env={"PREFLIGHT_BASE": orphan})
    assert r.returncode != 0, "a base with no merge base was accepted"
    assert "PREFLIGHT PASSED" not in r.stdout


def test_preflight_passes_with_a_real_base():
    """The fail-closed paths must not block the normal case."""
    r = run([str(PREFLIGHT)])
    assert r.returncode == 0, r.stdout[-2000:]
    assert "PREFLIGHT PASSED" in r.stdout


# -------------------------------------------------------------- pre-push ----

def _repo(tmp_path, check_exit=0):
    """A throwaway git repo carrying the real hook and a stub check.sh."""
    d = tmp_path / "r"
    d.mkdir()
    run(["git", "init", "-q", "-b", "main"], cwd=d)
    run(["git", "config", "user.email", "t@t"], cwd=d)
    run(["git", "config", "user.name", "t"], cwd=d)
    (d / "check.sh").write_text(f"#!/usr/bin/env bash\nexit {check_exit}\n")
    (d / "check.sh").chmod(0o755)
    (d / "f.txt").write_text("one\n")
    run(["git", "add", "-A"], cwd=d)
    run(["git", "commit", "-qm", "c1"], cwd=d)
    return d


def _push(d, line):
    return run(["bash", str(HOOK), "origin", "https://example/r"], cwd=d, stdin=line)


def test_hook_allows_a_branch_at_head(tmp_path):
    d = _repo(tmp_path)
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    r = _push(d, f"refs/heads/main {head} refs/heads/main {'0'*40}\n")
    assert r.returncode == 0, r.stderr


def test_hook_allows_an_annotated_tag_pointing_at_head(tmp_path):
    """The tag OBJECT's sha never equals HEAD, so the first version refused
    every annotated tag outright — including a correct one."""
    d = _repo(tmp_path)
    run(["git", "tag", "-a", "v1", "-m", "v1"], cwd=d)
    tag_obj = run(["git", "rev-parse", "v1"], cwd=d).stdout.strip()
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    assert tag_obj != head, "expected an annotated tag object distinct from HEAD"
    r = _push(d, f"refs/tags/v1 {tag_obj} refs/tags/v1 {'0'*40}\n")
    assert r.returncode == 0, r.stderr


def test_hook_refuses_a_revision_that_is_not_head(tmp_path):
    d = _repo(tmp_path)
    first = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    (d / "f.txt").write_text("two\n")
    run(["git", "commit", "-aqm", "c2"], cwd=d)
    r = _push(d, f"refs/heads/main {first} refs/heads/main {'0'*40}\n")
    assert r.returncode != 0
    assert "not your HEAD" in r.stderr


def test_hook_refuses_a_dirty_tracked_tree(tmp_path):
    d = _repo(tmp_path)
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    (d / "f.txt").write_text("dirty\n")
    r = _push(d, f"refs/heads/main {head} refs/heads/main {'0'*40}\n")
    assert r.returncode != 0
    assert "uncommitted tracked changes" in r.stderr


def test_hook_refuses_untracked_files(tmp_path):
    """check.sh may have imported a helper the pushed commit does not carry."""
    d = _repo(tmp_path)
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    (d / "helper.py").write_text("x = 1\n")
    r = _push(d, f"refs/heads/main {head} refs/heads/main {'0'*40}\n")
    assert r.returncode != 0
    assert "untracked files are present" in r.stderr.lower()


def test_hook_untracked_escape_is_explicit(tmp_path):
    d = _repo(tmp_path)
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    (d / "helper.py").write_text("x = 1\n")
    r = run(
        ["bash", str(HOOK), "origin", "https://example/r"],
        cwd=d,
        env={"PREPUSH_ALLOW_UNTRACKED": "1"},
        stdin=f"refs/heads/main {head} refs/heads/main {'0'*40}\n",
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize(
    "var,value",
    [("PREPUSH_ALLOW_UNTRACKED", "1"), ("SKIP_RLS_DRIFT", "1"),
     ("PREFLIGHT_BASE", "refs/heads/no-such-ref")],
)
def test_the_callers_gate_controls_do_not_reach_the_gate_under_test(
    tmp_path, monkeypatch, var, value
):
    """BH-008. The gate's own tests must not inherit the caller's gate controls.

    `run()` copies the caller's environment into every hook and preflight it
    launches. So `PREPUSH_ALLOW_UNTRACKED=1 git push` — the escape the hook
    documents — exported the escape into pytest, which handed it to the hook
    in `test_hook_refuses_untracked_files`. That hook then allowed the
    untracked file, the test failed, the gate went red, and the push was
    refused. The documented escape could never succeed. Found 30 Sep 2026.

    The same leak applies to every variable the hook or preflight reads.
    A test states its controls explicitly through `env=`, or it has none.
    """
    monkeypatch.setenv(var, value)
    r = run(["env"])
    assert f"{var}=" not in r.stdout, f"{var} leaked into the gate under test"


def test_the_untracked_refusal_holds_even_when_the_caller_used_the_escape(
    tmp_path, monkeypatch
):
    """BH-008, end to end: the exact failure. With the escape set in the
    shell that ran pytest, the refusal test must still see a refusal."""
    monkeypatch.setenv("PREPUSH_ALLOW_UNTRACKED", "1")
    d = _repo(tmp_path)
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    (d / "helper.py").write_text("x = 1\n")
    r = _push(d, f"refs/heads/main {head} refs/heads/main {'0'*40}\n")
    assert r.returncode != 0
    assert "untracked files are present" in r.stderr.lower()


def test_an_explicit_env_still_reaches_the_gate(monkeypatch):
    """Stripping must not break the tests that pass a control on purpose."""
    monkeypatch.delenv("PREFLIGHT_BASE", raising=False)
    r = run(["env"], env={"PREFLIGHT_BASE": "HEAD"})
    assert "PREFLIGHT_BASE=HEAD" in r.stdout


def test_the_gate_control_list_matches_what_the_gate_reads():
    """BH-008: a control added to the hook or preflight later must be added to
    `_GATE_CONTROLS` too, or it leaks exactly as PREPUSH_ALLOW_UNTRACKED did.

    An outside control is read with a fallback for when it is unset, so this
    looks for every parameter-expansion form that supplies one — `:-` `-`
    `:=` `=` `:?` `?` `:+` `+` — outside comments. It also refuses sourced
    files, because a control read in a file these scripts `source` would be
    invisible here. Limit (Codex review of BH-008): a control read bare, as
    `$NAME` with no fallback, is not detected. All three scripts run under
    `set -u`, where reading an unset outside variable bare aborts the script,
    so a working control needs a fallback form — which this does detect."""
    import re
    read = set()
    for f in (HOOK, PREFLIGHT, CHECK):
        code = "\n".join(
            line for line in f.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        read |= set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):?[-=?+]", code))
        assert not re.search(r"^\s*(source|\.)\s+\S", code, re.M), (
            f"{f.name} sources another file; extend this guard to read it too"
        )
    assert read == set(_GATE_CONTROLS), (
        f"gate reads {sorted(read)}, _GATE_CONTROLS has {sorted(_GATE_CONTROLS)}"
    )


def test_hook_allows_a_deletion(tmp_path):
    d = _repo(tmp_path)
    r = _push(d, f"(delete) {'0'*40} refs/heads/gone {'0'*40}\n")
    assert r.returncode == 0, r.stderr


def test_hook_refuses_when_the_gate_is_red(tmp_path):
    d = _repo(tmp_path, check_exit=1)
    head = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    r = _push(d, f"refs/heads/main {head} refs/heads/main {'0'*40}\n")
    assert r.returncode != 0
    assert "PUSH REFUSED" in r.stderr


# --------------------------------------------- fixture isolation (incident) --
# Regression for a real incident: run from inside the pre-push hook, these
# tests inherited git's GIT_DIR and committed fixture files onto a live ticket
# branch. The failure is silent, so it needs its own test.

def test_git_env_is_stripped_from_subprocesses():
    r = run(["bash", "-c", "env | grep -c '^GIT_' || true"])
    assert r.stdout.strip() == "0", "GIT_* leaked into a subprocess"


def test_a_fixture_commit_cannot_land_in_the_real_repository(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    run(["git", "init", "-q", "-b", "main"], cwd=d)
    run(["git", "config", "user.email", "t@t"], cwd=d)
    run(["git", "config", "user.name", "t"], cwd=d)
    (d / "only-in-fixture.txt").write_text("x\n")
    run(["git", "add", "-A"], cwd=d)
    run(["git", "commit", "-qm", "fixture-commit-marker"], cwd=d)

    assert "fixture-commit-marker" in run(
        ["git", "log", "--oneline", "-1"], cwd=d
    ).stdout, "the fixture repo did not receive its own commit"

    tip = run(["git", "log", "--oneline", "-5"]).stdout
    assert "fixture-commit-marker" not in tip, (
        "a fixture commit reached the real repository"
    )


# ---------------------------------------------------- preflight TRAP 4 (HK-1) ---

def _trap4_repo(tmp_path):
    """A throwaway repo with the real preflight, passing traps 1–3, and a
    backend whose db.py calls create_all()."""
    d = tmp_path / "t4"
    (d / "scripts").mkdir(parents=True)
    (d / "backend").mkdir()
    (d / "scripts" / "preflight.sh").write_text(PREFLIGHT.read_text())
    (d / "scripts" / "preflight.sh").chmod(0o755)
    (d / "requirements.txt").write_text("fastapi\n")
    (d / "backend" / "requirements.txt").write_text("fastapi\n")
    (d / "backend" / "db.py").write_text("SQLModel.metadata.create_all(engine)\n")
    (d / "backend" / "models.py").write_text("class A: pass\n")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        assert run(cmd, cwd=d).returncode == 0
    return d


def _trap4(d, path, content):
    target = d / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    base = run(["git", "rev-parse", "HEAD"], cwd=d).stdout.strip()
    run(["git", "add", "-A"], cwd=d)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "change"], cwd=d)
    out = run([str(d / "scripts" / "preflight.sh")], cwd=d, env={"PREFLIGHT_BASE": base}).stdout
    return out.split("TRAP 4")[1].split("TRAP 5")[0]


@pytest.mark.parametrize("path,content,flagged", [
    ("backend/tests/test_ai_models.py", "def test_x(): pass\n", False),       # the old false positive
    ("backend/services/outreach_models.py", "X = 1\n", False),
    ("backend/models.py", "class A: pass\nclass B: pass\n", True),
    ("backend/services/thing.py", "class Thing(SQLModel, table=True):\n    id: int\n", True),
])
def test_preflight_trap4_flags_real_model_changes_only(tmp_path, path, content, flagged):
    trap = _trap4(_trap4_repo(tmp_path), path, content)
    assert ("FAIL" in trap) is flagged, trap


def test_preflight_trap4_ignores_table_text_in_tests(tmp_path):
    """A test may contain `table=True` as data; only application code counts."""
    trap = _trap4(_trap4_repo(tmp_path), "backend/tests/test_x.py", 'SRC = "class T(SQLModel, table=True)"\n')
    assert "FAIL" not in trap, trap


@pytest.mark.parametrize("content,flagged", [
    ('from supabase_auth import SUPABASE_SERVICE_ROLE_KEY\nif not SUPABASE_SERVICE_ROLE_KEY: pass\n', False),
    ('SUPABASE_SERVICE_ROLE_KEY = "eyJhbGciOiJIUzI1NiJ9.x.y"\n', True),
    ('SUPABASE_SERVICE_ROLE_KEY: eyJhbGciOiJIUzI1NiJ9.x.y\n', True),
    ('key = "sk-ant-abc123"\n', True),
])
def test_preflight_secret_scan_flags_values_not_setting_names(tmp_path, content, flagged):
    """TRADE-0: reading SUPABASE_SERVICE_ROLE_KEY from the environment is not
    a secret, so a changed file that merely names it must not block a push."""
    d = _trap4_repo(tmp_path)
    _trap4(d, "backend/app/thing.py", content)                  # commits the change
    full = run([str(d / "scripts" / "preflight.sh")], cwd=d,
               env={"PREFLIGHT_BASE": run(["git", "rev-parse", "HEAD~1"], cwd=d).stdout.strip()}).stdout
    trap5 = full.split("TRAP 5")[1]
    assert ("possible secret" in trap5) is flagged, trap5
