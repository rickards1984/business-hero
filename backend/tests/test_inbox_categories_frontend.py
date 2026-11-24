"""ARIA-1a: the Comms page's category rule (frontend/client/src/lib/inboxCategories.ts)
is the server's (services/inbox_sorting.py): the same categories, in the same
order, and the same answer for "important" in every case. Bundled with the
repo's own esbuild and run under Node, as test_outreach_email_draft does."""
import itertools
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

CATS = ["money", "new_enquiry", "customer", "complaint", "supplier", "scheduling", "fyi", "junk", None]
PRIOS = [None, 1, 2, 3, 4, 5]
CASES = list(itertools.product(CATS, PRIOS))


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    work = tmp_path_factory.mktemp("cats")
    script = ("import { INBOX_CATEGORIES, isImportant } from './src/lib/inboxCategories';\n"
              f"const cases = {json.dumps(CASES)};\n"
              "console.log(JSON.stringify({keys: INBOX_CATEGORIES.map(c => [c.key, c.label]),"
              " important: cases.map(([c, p]) => isImportant(c, p))}));\n")
    fd, name = tempfile.mkstemp(prefix=".inbox-cats-", suffix=".ts", dir=CLIENT)
    entry = Path(name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(script)
        bundle = work / "bundle.mjs"
        subprocess.run([str(ESBUILD), str(entry), "--bundle", "--platform=node", "--format=esm",
                        f"--outfile={bundle}", "--log-level=error"], check=True, cwd=CLIENT)
        run = subprocess.run([NODE, str(bundle)], check=True, capture_output=True, text=True)
    finally:
        entry.unlink(missing_ok=True)
    return json.loads(run.stdout)


def test_the_page_lists_the_server_s_categories(page):
    from services import inbox_sorting
    assert [tuple(k) for k in page["keys"]] == list(inbox_sorting.CATEGORIES.items())


def test_the_page_and_the_server_agree_on_important_in_every_case(page):
    from services import inbox_sorting
    server = [inbox_sorting.is_important(c, p) for c, p in CASES]
    assert page["important"] == server
