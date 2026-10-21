#!/usr/bin/env python3
"""Owner-run, offline OUT-5 converter; source data never appears in diagnostics.

Usage: python3 scripts/export-outreach-history.py --output /outside/git/export.json
Profile only: python3 scripts/export-outreach-history.py --profile
Optional --home is intended for synthetic fixtures or an explicit local backup.
All four queues and the ledger must exist; malformed input aborts the export.
The output is sensitive, created exclusively with mode 0600, and never overwritten.

Mailbox provenance comes only from send_ledger.from_account. Its opaque alias is
'account-' + SHA256(exact UTF-8 account value). The owner must verify these aliases
in a separate mapping manifest. sent_via is not evidence of account ownership.
Unknown labels retain their value prefixed with 'unmapped:'. Unresolved ledger
associations and undocumented follow-ups remain unsupported history for review.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.outreach_import import (  # noqa: E402
    MAX_BYTES, MAX_ROWS, ImportValidationError, SafeArgumentParser, read_json, validate_export,
)

BUSINESSES = {"msc": "MSC", "fitfutures": "FitFutures", "newbody": "New Body", "businesshero": "Business Hero"}
COLUMNS = "id created_at business_id from_account to_address fingerprint queue_entry_id status message_id claimed_at sent_at failed_at error".split()
PROFILE_ENUMS = "status reply_status escalation_status sent_via opted_out legacy_inbox organisation_type segment".split()
PROFILE_KEYS = PROFILE_ENUMS + "followup_count last_followup_at reply_message_id gmail_thread_id gmail_message_id sent_at created_at approved_at".split()


class ExportError(ValueError):
    """Fixed, non-personal diagnostic."""


def _outside_repository(path):
    # Check both lexical and resolved ancestors, including linked worktrees and bare repos.
    for candidate in (path.absolute(), path.resolve()):
        for parent in (candidate, *candidate.parents):
            if os.path.lexists(parent / ".git") or ((parent / "HEAD").is_file() and
                    (parent / "objects").is_dir() and (parent / "refs").is_dir()):
                raise ExportError("Export failed")


def _text(value, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise ExportError("Export failed")
    return value


def _identifier(value):
    if type(value) not in (str, int) or not str(value).strip():
        raise ExportError("Export failed")
    return str(value)


def _label(value, mapping, default="none"):
    value = _text(value, default)
    return mapping.get(value, "unmapped:" + value)


def _alias(value):
    value = _text(value)
    return "account-" + hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _queue_row(entry, business, ledger):
    status = _label(entry.get("status"), {"sent": "sent", "send_failed": "send_failed",
                       "approved": "template_approved", "template_approved": "template_approved"}, "unmapped:missing")
    replies = {key: key for key in ("none", "opt_out", "unsubscribe", "objection", "hard_bounce")}
    reply = _label(entry.get("reply_status"), replies, "unmapped:missing")
    notes = []
    if reply.startswith("unmapped:"):
        notes.append("unmapped:reply_status=" + reply.removeprefix("unmapped:"))
    for value in (entry.get("status"), entry.get("reply_status"), entry.get("escalation_status"), entry.get("last_error")):
        if isinstance(value, str) and value in {"opt_out", "unsubscribe", "objection", "hard_bounce"}:
            reply = value
    for event in ledger:
        if event.get("error"):
            notes.append(_text(event["error"]))
            if event["error"] in {"opt_out", "unsubscribe", "objection", "hard_bounce"}:
                reply = event["error"]
    opted_out = entry.get("opted_out", False)
    if opted_out is True:
        reply = "opt_out"
    elif opted_out is not False and opted_out is not None:
        notes.append("unmapped:opted_out")
    for field in ("reply_content", "latest_reply_snippet", "warm_reply_text", "last_error"):
        if entry.get(field):
            notes.append(_text(entry[field]))
    count = entry.get("followup_count", 0)
    if type(count) is not int or count < 0:
        raise ExportError("Export failed")
    history = []
    if count or entry.get("last_followup_at") or entry.get("warm_reply_sent_at"):
        history.append({"unmapped": "followup_history_unavailable"})
    # Only one unambiguous, recipient-matching ledger record can fill provenance.
    usable = len(ledger) == 1
    email = _text(entry.get("contact_email"))
    if usable:
        event = ledger[0]
        usable = _text(event["to_address"]).strip().casefold() == email.strip().casefold()
        for queue_key, log_key in (("gmail_message_id", "message_id"), ("sent_at", "sent_at")):
            if entry.get(queue_key) and event[log_key] and entry[queue_key] != event[log_key]:
                usable = False
        if event["status"] not in {"sent", "failed", "claimed"}:
            usable = False
        if (status == "sent") != (event["status"] == "sent"):
            usable = False
    if ledger and not usable:
        history.append({"unmapped": "ledger_association", "events": ledger})
    event = ledger[0] if usable else {}
    sent = _text(entry.get("sent_at"), None)
    message = _text(entry.get("gmail_message_id"), None)
    if event.get("status") == "sent":
        sent = sent or _text(event.get("sent_at"), None)
        message = message or _text(event.get("message_id"), None)
    return dict(
        id=_identifier(entry.get("id")), business=business,
        segment=_text(entry.get("segment")), company=_text(entry.get("company") or entry.get("company_name")),
        contact_name=_text(entry.get("contact_name")), contact_email=email,
        subject=_text(entry.get("subject")), body=_text(entry.get("body")), status=status,
        reply_status=reply, escalation_status=_label(entry.get("escalation_status"), {"none": "none"}),
        notes="\n".join(notes), created_at=_text(entry.get("created_at")),
        approved_at=_text(entry.get("approved_at"), None), sent_at=sent,
        gmail_message_id=message, gmail_thread_id=_text(entry.get("gmail_thread_id"), None),
        reply_checked_at=_text(entry.get("reply_checked_at"), None), followup_due_at=None,
        last_followup_at=_text(entry.get("last_followup_at"), None),
        source_account=_alias(event.get("from_account")), last_known_message_count=int(bool(message)),
        followup_count=count, followup_history=history,
    )


def _ledger_row(event):
    entry = dict(id="ledger:" + _identifier(event["id"]),
                 contact_email=event["to_address"], created_at=event["created_at"],
                 status={"sent": "sent", "failed": "send_failed"}.get(event["status"], "unmapped:" + _text(event["status"])),
                 last_error=event["error"],
                 sent_at=event["sent_at"], gmail_message_id=event["message_id"])
    business = BUSINESSES.get(event["business_id"], "unmapped:" + _text(event["business_id"]))
    row = _queue_row(entry, business, [])
    row["source_account"] = _alias(event["from_account"])
    row["followup_history"] = [{"unmapped": "ledger_without_queue", "event": event}]
    return row


def export_history(home, output):
    """Read only the supplied source layout; return counts after exclusive output creation."""
    output = Path(output).expanduser()
    _outside_repository(output)
    if os.path.lexists(output) or not output.parent.is_dir():
        raise ExportError("Export failed")
    home = Path(home).expanduser()
    try:
        queues = {}
        for biz in BUSINESSES:
            payload = read_json(home / ".openclaw" / f"workspace-{biz}" / "outreach/queue.json")
            if isinstance(payload, dict) and set(payload) == {"queue"}:
                payload = payload["queue"]
            if not isinstance(payload, list) or len(payload) > MAX_ROWS or any(not isinstance(e, dict) for e in payload):
                raise ExportError("Export failed")
            queues[biz] = payload
        database = (home / "control-tower/server/control-tower.db").resolve()
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            cursor = connection.execute("SELECT " + ", ".join(COLUMNS) + " FROM send_ledger ORDER BY id")
            ledger = [dict(record) for record in cursor.fetchmany(MAX_ROWS + 1)]
        if len(ledger) > MAX_ROWS:
            raise ExportError("Export failed")
        groups = {}
        for i, event in enumerate(ledger):
            if event["queue_entry_id"] is not None:
                key = (_text(event["business_id"]), _identifier(event["queue_entry_id"]))
                groups.setdefault(key, []).append((i, event))
        rows, used = [], set()
        for biz, queue in queues.items():
            for entry in queue:
                linked = groups.get((biz, _identifier(entry.get("id"))), [])
                used.update(i for i, _ in linked)
                rows.append(_queue_row(entry, BUSINESSES[biz], [event for _, event in linked]))
        rows.extend(_ledger_row(event) for i, event in enumerate(ledger) if i not in used)
        payload = {"schema_version": 1, "rows": rows}
        validate_export(payload)
        encoded = json.dumps(payload, ensure_ascii=True, indent=2, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_BYTES:
            raise ExportError("Export failed")
        # Recheck immediately before creation; O_EXCL refuses existing files/symlinks.
        _outside_repository(output)
        with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(encoded)
        counts = dict.fromkeys(BUSINESSES.values(), 0)
        for row in rows:
            label = row["business"] if row["business"] in counts else "unknown"
            counts[label] = counts.get(label, 0) + 1
        return counts
    except (OSError, sqlite3.Error, ImportValidationError, ValueError, TypeError, RecursionError):
        raise ExportError("Export failed") from None


def _non_empty(value):
    return value is not None and value not in ("", [], {}) and not (isinstance(value, str) and not value.strip())


def _profile_value(value, boolean=False):
    if boolean:
        return "true" if value is True else "false" if value is False else "missing"
    if not _non_empty(value):
        return "missing"
    # Inspect the entire value before truncation; never stringify containers.
    if type(value) not in (str, int, float, bool):
        return "<redacted>"
    value = str(value)
    if "@" in value or re.search(r"\d{7,}", value):
        return "<redacted>"
    return value[:40]


def profile_history(home):
    """Owner-run aggregate report. Never emit queue identities or free-text fields.

    Enum fields are the explicitly permitted source values, capped after masking.
    Only ledger from_account is permitted to expose an email address.
    Non-boolean values in boolean fields are counted as missing.
    """
    home = Path(home).expanduser()
    try:
        businesses = {}
        for biz, label in BUSINESSES.items():
            rows = read_json(home / ".openclaw" / f"workspace-{biz}" / "outreach/queue.json")
            if isinstance(rows, dict) and set(rows) == {"queue"}:
                rows = rows["queue"]
            if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(row, dict) for row in rows):
                raise ExportError("Export failed")
            businesses[label] = {
                "rows": len(rows),
                "values": {key: dict(Counter(
                    _profile_value(row.get(key), key in {"opted_out", "legacy_inbox"})
                    for row in rows).most_common(50)) for key in PROFILE_ENUMS},
                "non_empty": {key: sum(_non_empty(row.get(key)) for row in rows) for key in PROFILE_KEYS},
            }
        database = (home / "control-tower/server/control-tower.db").resolve()
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only = ON")
            rows = connection.execute("SELECT business_id, status, from_account FROM send_ledger").fetchmany(MAX_ROWS + 1)
        if len(rows) > MAX_ROWS:
            raise ExportError("Export failed")
        statuses, accounts = Counter(), {}
        for business, status, account in rows:
            # Unknown business identifiers must not become an arbitrary output channel.
            business = business if business in BUSINESSES else "unknown"
            statuses[_profile_value(status)] += 1
            if account is not None and not isinstance(account, str):
                raise ExportError("Export failed")
            accounts.setdefault(business, Counter())[account or "missing"] += 1
        return {"businesses": businesses, "send_ledger": {
            "status": dict(statuses.most_common(50)), "from_account": accounts}}
    except (OSError, sqlite3.Error, ImportValidationError, ValueError, TypeError, RecursionError):
        raise ExportError("Export failed") from None


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output")
    mode.add_argument("--profile", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home())
    try:
        args = parser.parse_args(argv)
        if args.profile:
            print(json.dumps(profile_history(args.home), ensure_ascii=True, indent=2))
            return 0
        counts = export_history(args.home, args.output)
        for business, count in counts.items():
            print(f"{business}: {count}")
        print(str(Path(args.output).expanduser()))
        return 0
    except (ExportError, ImportValidationError, OSError, ValueError):
        print("Export failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
