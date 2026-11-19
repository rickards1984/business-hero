"""OUT-28a: the email editor's draft logic (frontend/client/src/lib/outreachEmailDraft.ts).

The frontend has no test runner, so this bundles the module with the repo's
own esbuild and runs it under Node. Codex OUT-28 review 1:
  finding 2 — New Body's three "[Your Name]"s must be fixable in ONE save;
  finding 3 — the version saved is the one editing began from, never a newer
              one picked up by a background refresh.
"""
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

SCENARIOS = r"""
import { startDraft, edit, changed, problems, stale, payload } from './src/lib/outreachEmailDraft';
const NB = (ordinal: number) => ({ ordinal, subject: `Subject ${ordinal + 1}`, body: `Hello,\n\nEmail ${ordinal + 1}.\n\nThanks,\n[Your Name]` });
const out: Record<string, unknown> = {};

// finding 2: all three need fixing before one save
let d = startDraft({ version: 7, emails: [NB(2), NB(0), NB(1)] });
out.start_problems = problems(d).map(p => [p.ordinal, p.kind, p.text]);
d = edit(d, 0, { body: 'Hello,\n\nEmail 1.' });
out.after_one = problems(d).map(p => p.ordinal);
out.payload_after_one = payload(d).emails.map(e => e.body.includes('[Your Name]'));
d = edit(d, 1, { body: 'Hello,\n\nEmail 2.' });
d = edit(d, 2, { body: 'Hello,\n\nEmail 3.' });
out.after_all = problems(d).length;
out.changed = [changed(d), changed(d, 0), changed(d, 1), changed(d, 2)];
out.payload = payload(d);

// finding 3: the snapshot's version is what is saved
out.stale_same = stale(d, 7);
out.stale_newer = stale(d, 8);
out.stale_unknown = stale(d, undefined);

// a subject stays one line; curly brackets and blanks are flagged
let e = startDraft({ version: 1, emails: [0, 1, 2].map(o => ({ ordinal: o, subject: 's', body: 'b' })) });
e = edit(e, 0, { subject: 'two\nlines' });
e = edit(e, 1, { body: 'Hi {first name}' });
out.first_name = problems(e).map(p => [p.ordinal, p.kind]);
e = edit(e, 1, { body: 'Set up in minutes :-}' });
e = edit(e, 2, { subject: '   ' });
out.one_line = e.emails[0].subject;
out.flags = problems(e).map(p => [p.ordinal, p.kind]);
out.unchanged = changed(startDraft({ version: 1, emails: [0, 1, 2].map(o => ({ ordinal: o, subject: 's', body: 'b' })) }));
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp("draft")
    # The entry must sit in the client folder so './src/…' resolves. A unique,
    # exclusively created name: never overwrites a real file, and parallel runs
    # never remove each other's (Codex OUT-28 review 2, finding 5).
    fd, name = tempfile.mkstemp(prefix=".draft-scenarios-", suffix=".ts", dir=CLIENT)
    entry = Path(name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(SCENARIOS)
        bundle = work / "bundle.mjs"
        subprocess.run([str(ESBUILD), str(entry), "--bundle", "--platform=node", "--format=esm",
                        f"--outfile={bundle}", "--log-level=error"], check=True, cwd=CLIENT)
        run = subprocess.run([NODE, str(bundle)], check=True, capture_output=True, text=True)
    finally:
        entry.unlink(missing_ok=True)
    return json.loads(run.stdout)


def test_new_bodys_three_placeholders_are_all_flagged(result):
    assert result["start_problems"] == [[0, "placeholder", "[Your Name]"], [1, "placeholder", "[Your Name]"],
                                        [2, "placeholder", "[Your Name]"]]


def test_fixing_one_keeps_the_others_flagged_and_unsaved(result):
    assert result["after_one"] == [1, 2]
    assert result["payload_after_one"] == [False, True, True]


def test_all_three_fixes_build_up_into_one_save(result):
    assert result["after_all"] == 0 and result["changed"] == [True, True, True, True]
    assert [e["ordinal"] for e in result["payload"]["emails"]] == [0, 1, 2]
    assert all("[Your Name]" not in e["body"] for e in result["payload"]["emails"])


def test_the_version_saved_is_the_one_editing_began_from(result):
    assert result["payload"]["version"] == 7
    assert (result["stale_same"], result["stale_newer"], result["stale_unknown"]) == (False, True, False)


def test_subjects_stay_one_line_and_problems_are_named(result):
    assert result["one_line"] == "two lines"
    assert result["first_name"] == [[1, "placeholder"]]      # a fill-in field is a placeholder
    assert result["flags"] == [[1, "curly"], [2, "blank"]]
    assert result["unchanged"] is False
