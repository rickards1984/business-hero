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
    """
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
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
