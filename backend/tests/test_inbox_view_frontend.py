"""ARIA-1a (Codex review 3): the Comms inbox's request ordering
(frontend/client/src/lib/inboxView.ts), run under Node as the other frontend
tests are, plus that EmailsTab uses it on every path."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "frontend" / "client"
ESBUILD = CLIENT / "node_modules" / ".bin" / "esbuild"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(not (ESBUILD.exists() and NODE),
                                reason="needs frontend node_modules and node. A skip is not a pass.")

SCRIPT = r"""
import { latestOnly, sortingMovedOn } from './src/lib/inboxView';
const out: Record<string, unknown> = {};
// finding 1: page opens on an unsorted mailbox, then the first sort finishes
let seen: string | null | undefined = undefined;
const reloads: boolean[] = [];
for (const next of [null, '2026-11-24T10:15:00Z', '2026-11-24T10:15:00Z', '2026-11-24T10:30:00Z']) {
  reloads.push(sortingMovedOn(seen, next));
  seen = next;
}
out.reloads = reloads;
out.first_status_ever = sortingMovedOn(undefined, '2026-11-24T10:15:00Z');
// findings 2 and 3: requests answered out of order
const r = latestOnly();
const all = r.begin();
const today = r.begin();
out.late_all_is_current = r.isCurrent(all);
out.today_is_current = r.isCurrent(today);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp("view")
    fd, name = tempfile.mkstemp(prefix=".inbox-view-", suffix=".ts", dir=CLIENT)
    entry = Path(name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(SCRIPT)
        bundle = work / "bundle.mjs"
        subprocess.run([str(ESBUILD), str(entry), "--bundle", "--platform=node", "--format=esm",
                        f"--outfile={bundle}", "--log-level=error"], check=True, cwd=CLIENT)
        run = subprocess.run([NODE, str(bundle)], check=True, capture_output=True, text=True)
    finally:
        entry.unlink(missing_ok=True)
    return json.loads(run.stdout)


def test_the_first_sort_after_the_page_opens_reloads_the_list(result):
    """null (nothing sorted) → the first sort's time must reload; no change must not."""
    assert result["reloads"] == [False, True, False, True]
    assert result["first_status_ever"] is False            # the page's own first load, not a change


def test_a_late_answer_for_an_earlier_request_is_not_current(result):
    assert result["late_all_is_current"] is False and result["today_is_current"] is True


def test_the_tab_guards_every_path_with_it():
    src = (CLIENT / "src/components/EmailsTab.tsx").read_text()
    loader = src.split("const loadEmails = useCallback")[1].split("}, [categoryFilter, unreadOnly")[0]
    assert loader.count("listRequests.isCurrent(request)") == 3        # success, failure, finally
    status = src.split("const loadSorting = useCallback")[1].split("}, [timeRange")[0]
    assert "statusRequests.isCurrent(request)" in status and "sortingMovedOn(lastSortedRef.current" in status
    assert "await Promise.all([loadEmailsRef.current(), loadSortingRef.current()]);" in src
