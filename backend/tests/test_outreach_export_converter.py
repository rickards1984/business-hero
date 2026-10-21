"""Synthetic local layouts only. Never inspect the operator's source files."""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from test_outreach_import_dry_run import MAPPING, NOW


@pytest.fixture
def converter():
    path = Path(__file__).resolve().parents[2] / "scripts/export-outreach-history.py"
    spec = importlib.util.spec_from_file_location("outreach_export_converter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path):
    home = tmp_path / "synthetic-home"
    for biz in ("msc", "fitfutures", "newbody", "businesshero"):
        directory = home / ".openclaw" / f"workspace-{biz}" / "outreach"
        directory.mkdir(parents=True)
        (directory / "queue.json").write_text(json.dumps([dict(
            id=f"queue-{biz}", contact_email="private-person@example.invalid",
            contact_name="PRIVATE_NAME", company="PRIVATE_COMPANY", subject="PRIVATE_SUBJECT",
            body="PRIVATE_BODY", created_at="2026-10-01T09:00:00Z", status="sent",
            sent_at="2026-10-02T10:00:00Z", gmail_thread_id="thread", reply_status="none",
        )]))
    database = home / "control-tower/server/control-tower.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute('''CREATE TABLE send_ledger (
            id INTEGER, created_at TEXT, business_id TEXT, from_account TEXT,
            to_address TEXT, fingerprint TEXT, queue_entry_id TEXT, status TEXT,
            message_id TEXT, claimed_at TEXT, sent_at TEXT, failed_at TEXT, error TEXT)''')
        connection.execute("INSERT INTO send_ledger VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            1, "2026-10-01T09:00:00Z", "msc", "private-sender@example.invalid",
            "private-person@example.invalid", "fp", "queue-msc", "sent", "message",
            "2026-10-02T09:00:00Z", "2026-10-02T10:00:00Z", None, None))
    return home, database


def queue_path(home, biz="msc"):
    return home / ".openclaw" / f"workspace-{biz}" / "outreach/queue.json"


def test_business_hero_passthrough_and_only_safe_stdout(converter, source, tmp_path, capsys):
    home, _ = source
    output = tmp_path / "export.json"
    assert converter.main(["--home", str(home), "--output", str(output)]) == 0
    payload = json.loads(output.read_text())
    assert payload["schema_version"] == 1
    assert [r["business"] for r in payload["rows"]] == ["MSC", "FitFutures", "New Body", "Business Hero"]
    assert payload["rows"][0]["gmail_message_id"] == "message"
    assert payload["rows"][0]["source_account"].startswith("account-")
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == ["MSC: 1", "FitFutures: 1", "New Body: 1", "Business Hero: 1", str(output)]
    assert "private-person@example.invalid" not in captured.out
    assert "private-sender@example.invalid" not in captured.out
    assert "PRIVATE" not in captured.out
    assert output.stat().st_mode & 0o777 == 0o600
    from services.outreach_import import dry_run
    report = dry_run(output, mapping=MAPPING, as_of=NOW)
    assert report["counts"]["excluded_business_hero"] == 1


def test_read_only_sqlite_and_unchanged_inputs(converter, source, tmp_path, monkeypatch):
    home, database = source
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    connect = sqlite3.connect
    calls = []

    def checked_connect(database_uri, **kwargs):
        assert database_uri.startswith("file:") and database_uri.endswith("?mode=ro") and kwargs["uri"] is True
        connection = connect(database_uri, **kwargs)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden (id INTEGER)")
        calls.append(database_uri)
        return connection

    monkeypatch.setattr(converter.sqlite3, "connect", checked_connect)
    converter.export_history(home, tmp_path / "export.json")
    assert len(calls) == 1
    assert before == {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert database.exists()


@pytest.mark.parametrize("status", ["send_unverified", "dead", "unexpected-private-value"])
def test_unmapped_values_quarantined(converter, source, tmp_path, status):
    home, _ = source
    path = queue_path(home)
    entry = json.loads(path.read_text())[0]
    entry.update(status=status, reply_status="strong_positive", escalation_status="pending_byron")
    path.write_text(json.dumps({"queue": [entry]}))
    output = tmp_path / "export.json"
    converter.export_history(home, output)
    row = json.loads(output.read_text())["rows"][0]
    assert row["status"].startswith("unmapped:")
    assert row["reply_status"] == "unmapped:strong_positive"
    assert row["escalation_status"] == "unmapped:pending_byron"
    from services.outreach_import import dry_run
    report = dry_run(output, mapping=MAPPING, as_of=NOW)
    assert report["counts"]["quarantined_rows"] >= 1
    assert status not in json.dumps(report)


@pytest.mark.parametrize("changes, reason", [({"opted_out": True}, "opt_out"),
    ({"reply_status": "objection"}, "objection"), ({"reply_status": "hard_bounce"}, "hard_bounce")])
def test_suppressions(converter, source, tmp_path, changes, reason):
    home, _ = source
    path = queue_path(home)
    entry = json.loads(path.read_text())[0]
    entry.update(changes)
    path.write_text(json.dumps([entry]))
    output = tmp_path / "export.json"
    converter.export_history(home, output)
    assert json.loads(output.read_text())["rows"][0]["reply_status"] == reason


@pytest.mark.parametrize("git_kind", ["directory", "worktree", "bare", "symlink"])
def test_refuses_repository_output_before_source_access(converter, tmp_path, git_kind):
    repo = tmp_path / "repo"
    repo.mkdir()
    if git_kind == "bare":
        (repo / "HEAD").write_text("ref: refs/heads/main")
        (repo / "objects").mkdir()
        (repo / "refs").mkdir()
    elif git_kind == "worktree":
        (repo / ".git").write_text("gitdir: /synthetic")
    else:
        (repo / ".git").mkdir()
    destination = repo
    if git_kind == "symlink":
        destination = tmp_path / "link"
        destination.symlink_to(repo, target_is_directory=True)
    with pytest.raises(converter.ExportError):
        converter.export_history(tmp_path / "absent", destination / "export.json")
    assert not (repo / "export.json").exists()


@pytest.mark.parametrize("bad", [{}, {"queue": [], "unexpected": True}, [None], "bad", {"queue": {}}])
def test_bad_queue_fails_closed(converter, source, tmp_path, bad, capsys):
    home, _ = source
    queue_path(home).write_text(json.dumps(bad))
    output = tmp_path / "export.json"
    assert converter.main(["--home", str(home), "--output", str(output)]) == 2
    assert not output.exists()
    captured = capsys.readouterr()
    assert not captured.out
    assert captured.err == "Export failed\n"


def test_orphan_and_conflicting_ledger_preserved(converter, source, tmp_path):
    home, database = source
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO send_ledger SELECT 2, created_at, business_id, from_account, to_address, fingerprint, queue_entry_id, 'failed', NULL, claimed_at, NULL, created_at, 'private failure' FROM send_ledger")
        connection.execute("INSERT INTO send_ledger SELECT 3, created_at, 'businesshero', from_account, to_address, fingerprint, 'orphan', status, message_id, claimed_at, sent_at, failed_at, error FROM send_ledger WHERE id=1")
    output = tmp_path / "export.json"
    converter.export_history(home, output)
    rows = json.loads(output.read_text())["rows"]
    assert rows[0]["followup_history"]
    assert rows[-1]["business"] == "Business Hero"
    assert rows[-1]["id"] == "ledger:3"


def test_existing_output_not_overwritten(converter, source, tmp_path):
    home, _ = source
    output = tmp_path / "export.json"
    output.write_text("keep")
    with pytest.raises(converter.ExportError):
        converter.export_history(home, output)
    assert output.read_text() == "keep"


def test_converter_rejects_output_larger_than_parser_limit(converter, source, tmp_path, monkeypatch):
    home, _ = source
    output = tmp_path / "export.json"
    monkeypatch.setattr(converter, "MAX_BYTES", 100)
    with pytest.raises(converter.ExportError):
        converter.export_history(home, output)
    assert not output.exists()


def test_ledger_hard_bounce_stages_suppression(converter, source, tmp_path):
    home, database = source
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE send_ledger SET error='hard_bounce', status='failed'")
    output = tmp_path / "export.json"
    converter.export_history(home, output)
    row = json.loads(output.read_text())["rows"][0]
    assert row["reply_status"] == "hard_bounce"
    assert row["followup_history"]  # Conflicting send state stays quarantined.
    from services.outreach_import import dry_run
    assert dry_run(output, mapping=MAPPING, as_of=NOW)["counts"]["suppressions"] == 1


def test_opt_out_preserves_unknown_reply_evidence(converter, source, tmp_path):
    home, _ = source
    path = queue_path(home)
    entry = json.loads(path.read_text())[0]
    entry.update(opted_out=True, reply_status="strong_positive")
    path.write_text(json.dumps([entry]))
    output = tmp_path / "export.json"
    converter.export_history(home, output)
    row = json.loads(output.read_text())["rows"][0]
    assert row["reply_status"] == "opt_out"
    assert "unmapped:reply_status=strong_positive" in row["notes"]
    from services.outreach_import import dry_run
    report = dry_run(output, mapping=MAPPING, as_of=NOW)
    assert report["counts"]["suppressions"] == 1
    assert "notes_review" in {s["code"] for s in report["samples"]}
