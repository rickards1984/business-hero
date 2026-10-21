"""OUT-5 Stage A contract: synthetic local exports only; no importer implemented."""

import copy
import hashlib
import importlib
import importlib.util
import json
import socket
import sqlite3
from datetime import datetime, timezone

import pytest


class MissingOutreachImport(AssertionError):
    """Only this precise missing implementation is an expected failure."""


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
MSC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NEW_BODY = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
MAPPING = {
    "version": "synthetic-v1",
    "namespaces": {
        "MSC": {"tenant_id": MSC, "brand": "MSC", "mailboxes": {"source-m": "mailbox-m"}},
        "FitFutures": {"tenant_id": NEW_BODY, "brand": "FitFutures", "mailboxes": {"source-f": "mailbox-f"}},
        "UKFI": {"tenant_id": NEW_BODY, "brand": "FitFutures", "mailboxes": {"source-f": "mailbox-f"}},
        "New Body": {"tenant_id": NEW_BODY, "brand": "New Body", "mailboxes": {"source-n": "mailbox-n"}},
    },
}


def row(source_id="1", business="MSC", **changes):
    """All personal fields are synthetic; source keys come from OUT-1 §8."""
    result = dict(
        id=source_id, business=business, segment="synthetic-segment",
        company="SYNTHETIC_COMPANY_SECRET", contact_name="SYNTHETIC_NAME_SECRET",
        contact_email="person@example.invalid", subject="SYNTHETIC_SUBJECT_SECRET",
        body="SYNTHETIC_BODY_SECRET", status="sent",
        approved_at="2026-10-01T10:00:00Z", sent_at="2026-10-02T10:00:00Z",
        gmail_message_id=f"message-{source_id}", gmail_thread_id=f"thread-{source_id}",
        reply_status="none", reply_checked_at="2026-10-03T10:00:00Z",
        last_known_message_count=1, followup_count=0, followup_due_at=None,
        followup_history=[], last_followup_at=None, escalation_status="none",
        notes="SYNTHETIC_NOTES_SECRET", created_at="2026-10-01T09:00:00Z",
        source_account={"MSC": "source-m", "New Body": "source-n"}.get(business, "source-f"),
    )
    result.update(changes)
    return result


@pytest.fixture
def importer(monkeypatch):
    """Deny DB/network access before module import, including read-only sessions."""
    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run attempted DB or network access")

    import sqlalchemy
    import sqlalchemy.orm
    import sqlmodel

    for owner, name in [(socket, "socket"), (socket, "create_connection"),
                        (sqlite3, "connect"), (sqlalchemy, "create_engine"),
                        (sqlalchemy.orm.Session, "__init__"),
                        (sqlmodel.Session, "__init__")]:
        monkeypatch.setattr(owner, name, forbidden)
    if importlib.util.find_spec("services.outreach_import") is None:
        raise MissingOutreachImport("backend/services/outreach_import.py does not exist")
    return importlib.import_module("services.outreach_import")


def run(importer, tmp_path, rows, mapping=None):
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps({"schema_version": 1, "rows": rows}), encoding="utf-8")
    before = path.read_bytes()
    result = importer.dry_run(path, mapping=copy.deepcopy(mapping or MAPPING), as_of=NOW)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["synthetic.json"]
    return result


def test_namespace_mapping_exclusion_and_brand_retention(importer, tmp_path):
    report = run(importer, tmp_path, [row(str(i), ns) for i, ns in enumerate(
        ["MSC", "FitFutures", "UKFI", "New Body", "Business Hero"])])
    assert report["counts"]["input_rows"] == 5
    assert report["counts"]["excluded_business_hero"] == 1
    assert report["input_by_source"] == dict.fromkeys(
        ["MSC", "FitFutures", "UKFI", "New Body", "Business Hero"], 1)
    assert set(report["targets"]) == {MSC, NEW_BODY}
    assert report["targets"][MSC]["rows"] == 1
    assert report["targets"][NEW_BODY]["rows"] == 3
    assert report["targets"][NEW_BODY]["brands"] == {"FitFutures": 2, "New Body": 1}
    assert report["targets"][NEW_BODY]["unique_contacts"] == 1
    assert report["counts"]["merged_rows"] == 2


def test_business_hero_cannot_be_remapped(importer, tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["namespaces"]["Business Hero"] = mapping["namespaces"]["MSC"]
    report = run(importer, tmp_path, [row(business="Business Hero")], mapping)
    assert report["targets"] == {}
    assert report["counts"]["excluded_business_hero"] == 1


@pytest.mark.parametrize("namespace", ["Unknown", "", "msc"])
def test_unknown_namespace_quarantined_without_default(importer, tmp_path, namespace):
    report = run(importer, tmp_path, [row(business=namespace)])
    assert report["targets"] == {}
    assert report["counts"]["unknown_namespace"] == 1
    assert report["counts"]["quarantined_rows"] == 1


@pytest.mark.parametrize("reason", ["opt_out", "unsubscribe", "hard_bounce", "objection"])
@pytest.mark.parametrize("reverse", [False, True])
def test_suppression_first_and_never_overridden(importer, tmp_path, reason, reverse):
    rows = [row("1", "FitFutures", reply_status=reason),
            row("2", "New Body", status="template_approved", sent_at=None), row("3")]
    report = run(importer, tmp_path, list(reversed(rows)) if reverse else rows)
    assert report["passes"] == ["suppression", "history"]
    assert report["targets"][NEW_BODY]["suppressed_contacts"] == 1
    assert report["targets"][NEW_BODY]["blocked_rows"] == 2
    assert report["targets"][MSC]["suppressed_contacts"] == 0
    assert report["counts"]["suppressions"] == 1
    assert report["counts"]["send_actions"] == 0


def test_notes_objection_survives_date_quarantine(importer, tmp_path):
    report = run(importer, tmp_path, [row(notes="Do not contact me again",
        sent_at="2026-09-01T00:00:00Z"), row("2")])
    assert report["counts"]["date_inconsistencies"] == 1
    assert report["targets"][MSC]["suppressed_contacts"] == 1
    assert report["targets"][MSC]["blocked_rows"] == 2


def test_email_normalisation_is_tenant_scoped_and_preserves_plus_and_dots(importer, tmp_path):
    emails = [" Person@EXAMPLE.INVALID ", "person@example.invalid",
              "person+tag@example.invalid", "per.son@example.invalid"]
    report = run(importer, tmp_path, [row(str(i), contact_email=e) for i, e in enumerate(emails)]
                 + [row("other", "New Body")])
    assert report["targets"][MSC]["unique_contacts"] == 3
    assert report["targets"][NEW_BODY]["unique_contacts"] == 1
    assert report["counts"]["new_contacts"] == 4
    assert report["counts"]["merged_rows"] == 1


@pytest.mark.parametrize("email", ["not-an-address", "a@example.invalid,b@example.invalid", ""])
def test_invalid_addresses_quarantined(importer, tmp_path, email):
    report = run(importer, tmp_path, [row(contact_email=email)])
    assert report["counts"]["invalid_addresses"] == 1
    assert report["counts"]["quarantined_rows"] == 1


def test_identity_duplicates_and_changed_content_report_collisions(importer, tmp_path):
    report = run(importer, tmp_path, [row(), row(), row(body="changed synthetic body"),
                                    row(business="New Body")])
    assert report["counts"]["duplicate_rows"] == 1
    assert report["counts"]["collisions"] == 2
    assert {s["code"] for s in report["samples"]} >= {"source_changed", "cross_namespace_id"}
    assert report["counts"]["send_actions"] == 0


@pytest.mark.parametrize("changes, counter", [
    ({"sent_at": "2026-09-30T10:00:00Z"}, "date_inconsistencies"),
    ({"last_followup_at": "2026-10-01T10:00:00Z"}, "date_inconsistencies"),
    ({"source_account": "unmapped"}, "unresolved_mailbox_thread"),
    ({"gmail_thread_id": None}, "unresolved_mailbox_thread"),
    ({"followup_history": [{"unverified": "shape"}]}, "unsupported_history"),
])
def test_inconsistent_or_unresolved_history_is_quarantined(importer, tmp_path, changes, counter):
    report = run(importer, tmp_path, [row(**changes)])
    assert report["counts"][counter] == 1
    assert report["counts"]["quarantined_rows"] == 1


def test_expired_and_overdue_history_never_activates_or_consumes_usage(importer, tmp_path):
    report = run(importer, tmp_path, [row(created_at="2024-01-01T00:00:00Z",
        approved_at="2024-01-02T00:00:00Z", sent_at="2024-01-03T00:00:00Z",
        followup_due_at="2024-01-10T00:00:00Z")])
    assert report["counts"]["expired_records"] == 1
    assert report["counts"]["scheduled_held"] == 1
    assert report["counts"]["send_actions"] == report["counts"]["current_allowance"] == 0
    assert report["status"] == "paused"


def test_report_is_bounded_masked_and_has_no_contact_dump(importer, tmp_path, capsys, caplog):
    rows = [row(str(i), contact_email=f"synthetic-person-{i}@example.invalid",
                sent_at="2026-09-01T00:00:00Z") for i in range(30)]
    report = run(importer, tmp_path, rows)
    assert set(report) == {"schema_version", "mapping_version", "manifest_hash", "report_hash",
                          "as_of", "status", "passes", "input_by_source", "targets", "counts", "samples"}
    assert 0 < len(report["samples"]) <= 5
    for sample in report["samples"]:
        assert set(sample) == {"row_number", "code", "masked_email"}
        assert sample["masked_email"] == "***@***"
    output = json.dumps(report) + capsys.readouterr().out + capsys.readouterr().err + caplog.text
    for item in rows:
        for key in ("contact_email", "body", "subject", "notes", "company", "contact_name"):
            assert item[key] not in output


def test_rerun_is_identical_and_hash_covers_canonical_report(importer, tmp_path):
    rows = [row(), row("2", "New Body", reply_status="objection")]
    first = run(importer, tmp_path, rows)
    assert first == run(importer, tmp_path, rows)
    payload = {k: v for k, v in first.items() if k != "report_hash"}
    assert first["report_hash"] == hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    changed = copy.deepcopy(MAPPING)
    changed["version"] = "synthetic-v2"
    assert run(importer, tmp_path, rows, changed)["report_hash"] != first["report_hash"]


@pytest.mark.parametrize("payload", ["not json", "[]", '{"schema_version":2,"rows":[]}',
    '{"schema_version":1,"rows":[{}]}', '{"schema_version":1,"rows":"bad"}',
    '{"schema_version":1,"schema_version":1,"rows":[]}',
    json.dumps({"schema_version": 1, "rows": [row(followup_count=-1)]}),
    json.dumps({"schema_version": 1, "rows": [row(created_at="yesterday")]}),
    json.dumps({"schema_version": 1, "rows": [row(contact_email=123)]}),
])
def test_malformed_input_fails_closed_without_echo(importer, tmp_path, payload, capsys, caplog):
    path = tmp_path / "synthetic.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(importer.ImportValidationError) as exc:
        importer.dry_run(path, mapping=copy.deepcopy(MAPPING), as_of=NOW)
    assert str(exc.value) == "Invalid export"
    captured = capsys.readouterr()
    assert not captured.out and not captured.err and not caplog.text
    assert path.read_text(encoding="utf-8") == payload


def test_empty_export_and_no_database_session_or_network(importer, tmp_path):
    report = run(importer, tmp_path, [])
    assert report["counts"]["input_rows"] == 0
    assert report["targets"] == {} and report["samples"] == []
    assert report["status"] == "paused"


def test_message_dedup_uses_mapped_mailbox_and_tenant(importer, tmp_path):
    rows = [row("1"), row("2", gmail_message_id="message-1", gmail_thread_id="thread-1"),
            row("3", "New Body", gmail_message_id="message-1", gmail_thread_id="thread-1"),
            row("4", "FitFutures", gmail_message_id="message-1", gmail_thread_id="thread-1")]
    report = run(importer, tmp_path, rows)
    assert report["counts"]["duplicate_messages"] == 1
    assert report["targets"][MSC]["unique_messages"] == 1
    assert report["targets"][NEW_BODY]["unique_messages"] == 2


def test_bad_mapping_fails_closed(importer, tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["namespaces"]["FitFutures"]["tenant_id"] = MSC
    with pytest.raises(importer.ImportValidationError, match="^Invalid mapping$"):
        run(importer, tmp_path, [row("1", "FitFutures")], mapping)


@pytest.mark.parametrize("changes, code", [
    ({"status": "unmapped:secret"}, "unknown_status"),
    ({"reply_status": "mystery_reply_status_x"}, "unknown_reply_status"),
    ({"escalation_status": "mystery_escalation_y"}, "unknown_escalation_status"),
    ({"notes": "Please stop, perhaps later"}, "notes_review"),
])
def test_unknown_labels_and_ambiguous_notes_block(importer, tmp_path, changes, code):
    report = run(importer, tmp_path, [row(**changes)])
    assert report["counts"]["quarantined_rows"] == 1
    assert report["targets"][MSC]["blocked_rows"] == 1
    assert code in {s["code"] for s in report["samples"]}
    assert report["counts"]["suppressions"] == 0


@pytest.mark.parametrize("changes", [
    {"created_at": "2026-10-01T09:00:00"}, {"followup_count": True},
    {"approved_at": 1}, {"extra": "secret"}, {"followup_history": {}},
])
def test_additional_bad_row_types_fail_closed(importer, tmp_path, changes):
    with pytest.raises(importer.ImportValidationError, match="^Invalid export$"):
        run(importer, tmp_path, [row(**changes)])


def test_resource_limits_and_nonfinite_json(importer, tmp_path, monkeypatch):
    path = tmp_path / "synthetic.json"
    path.write_text('{"schema_version":1,"rows":[],"extra":NaN}')
    with pytest.raises(importer.ImportValidationError, match="^Invalid export$"):
        importer.dry_run(path, mapping=MAPPING, as_of=NOW)
    monkeypatch.setattr(importer, "MAX_BYTES", 10)
    with pytest.raises(importer.ImportValidationError, match="^Invalid export$"):
        importer.dry_run(path, mapping=MAPPING, as_of=NOW)
    monkeypatch.setattr(importer, "MAX_BYTES", 100000)
    monkeypatch.setattr(importer, "MAX_ROWS", 1)
    with pytest.raises(importer.ImportValidationError, match="^Invalid export$"):
        run(importer, tmp_path, [row(), row("2")])


def test_cli_only_masked_report_and_safe_errors(importer, tmp_path, capsys):
    path = tmp_path / "export.json"
    path.write_text(json.dumps({"schema_version": 1, "rows": [row()]}))
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps(MAPPING))
    args = ["--input", str(path), "--mapping", str(mapping), "--as-of", NOW.isoformat()]
    assert importer.main(args) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == importer.dry_run(path, mapping=MAPPING, as_of=NOW)
    for secret in ("SYNTHETIC", "person@example.invalid", "message-1", "thread-1"):
        assert secret not in captured.out
    path.write_text("private-invalid-payload")
    assert importer.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "Invalid export\n"
    assert importer.main(["--private-secret"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "Invalid arguments\n"


def test_twelve_calendar_month_expiry_and_unanswered_only(importer, tmp_path):
    rows = [row("1", notes="", created_at="2024-02-29T12:00:00Z", approved_at=None,
                sent_at="2024-02-29T12:00:00Z"),
            row("2", reply_status="unmapped:strong_positive", created_at="2024-01-01T00:00:00Z")]
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps({"schema_version": 1, "rows": rows}))
    at_boundary = datetime(2025, 2, 28, 12, tzinfo=timezone.utc)
    report = importer.dry_run(path, mapping=MAPPING, as_of=at_boundary)
    assert report["counts"]["expired_records"] == 1
    before = at_boundary.replace(hour=11)
    assert importer.dry_run(path, mapping=MAPPING, as_of=before)["counts"]["expired_records"] == 0


@pytest.mark.parametrize("reply, category", [
    ("strong_positive", "interested"), ("interested", "interested"),
    ("needs_judgment", "unknown"), ("unclear", "unknown"), ("handled", "unknown"),
    ("ooo", "out_of_office"), ("auto_ack", "out_of_office"),
    ("bounce", "bounce"), ("unsubscribe", "unsubscribe"), ("opted_out", "unsubscribe"),
    ("objection", "objection"), ("polite_decline", "objection"),
])
def test_observed_reply_categories(importer, tmp_path, reply, category):
    report = run(importer, tmp_path, [row(reply_status=reply, notes="", escalation_status="pending_byron")])
    assert report["counts"]["replies_by_category"][category] == 1
    assert report["counts"]["owner_review"] == 1
    assert report["counts"]["unsupported_history"] == 0


@pytest.mark.parametrize("changes, reason", [
    ({"status": "opted_out"}, "unsubscribe"),
    ({"reply_status": "bounce"}, "hard_bounce"),
    ({"escalation_status": "auto_resolved_bounce"}, "hard_bounce"),
    ({"reply_status": "polite_decline"}, "objection"),
    ({"escalation_status": "auto_resolved_unsubscribe"}, "unsubscribe"),
])
def test_observed_suppression_reasons(importer, tmp_path, changes, reason):
    report = run(importer, tmp_path, [row(notes="", **changes)])
    assert report["counts"]["suppressions_by_reason"][reason] == 1
    assert report["counts"]["suppressions"] == 1


def test_unconnected_mailbox_and_followup_summary(importer, tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["namespaces"]["MSC"]["mailboxes"]["source-m"] = "unconnected"
    report = run(importer, tmp_path, [row(notes="", followup_count=2,
        last_followup_at="2026-10-03T10:00:00Z")], mapping)
    assert report["counts"]["mailbox_unconnected"] == 1
    assert report["counts"]["unresolved_mailbox_thread"] == 0
    assert report["counts"]["quarantined_rows"] == 0
    assert report["counts"]["unsupported_history"] == 0
    assert report["counts"]["send_actions"] == 0


def test_mailbox_alias_cannot_cross_tenants(importer, tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["namespaces"]["New Body"]["mailboxes"]["source-m"] = "unconnected"
    with pytest.raises(importer.ImportValidationError, match="^Invalid mapping$"):
        run(importer, tmp_path, [row()], mapping)


def test_unknown_fields_counted_without_values(importer, tmp_path):
    report = run(importer, tmp_path, [row(notes="", reply_status="private_unknown",
        escalation_status="private_other")])
    assert report["counts"]["unsupported_history"] == 1
    assert report["counts"]["unsupported_by_field"] == {"reply_status": 1, "escalation_status": 1}
    assert "private_" not in json.dumps(report)


@pytest.mark.parametrize("status", ["sent", "approved", "template_approved", "skipped", "send_failed", "opted_out"])
def test_observed_queue_states_remain_paused(importer, tmp_path, status):
    report = run(importer, tmp_path, [row(status=status, notes="")])
    assert report["counts"]["unsupported_history"] == 0
    assert report["counts"]["send_actions"] == report["counts"]["current_allowance"] == 0
    assert report["status"] == "paused"
    assert report["counts"]["suppressions"] == int(status == "opted_out")


def test_source_account_mapped_only_under_other_tenant_is_error(importer, tmp_path):
    with pytest.raises(importer.ImportValidationError, match="^Invalid mapping$"):
        run(importer, tmp_path, [row(source_account="source-n")])


@pytest.mark.parametrize("escalation", ["none", "handled", "auto_resolved_bounce",
    "auto_resolved_unsubscribe", "auto_resolved_ooo", "auto_resolved_auto_ack", "action_needed"])
def test_observed_escalations_supported(importer, tmp_path, escalation):
    report = run(importer, tmp_path, [row(escalation_status=escalation, notes="")])
    assert report["counts"]["unsupported_history"] == 0
    assert report["counts"]["owner_review"] == int(escalation == "action_needed")
