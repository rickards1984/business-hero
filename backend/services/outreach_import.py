"""Offline OUT-5 validation and masked reporting. No persistence or activation."""

import argparse
import calendar
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 100_000
BRANDS = {"MSC": "MSC", "FitFutures": "FitFutures", "UKFI": "FitFutures", "New Body": "New Body"}
STRINGS = set("id business segment company contact_name contact_email subject body status reply_status escalation_status notes created_at".split())
NULLABLE = set("approved_at sent_at gmail_message_id gmail_thread_id reply_checked_at followup_due_at last_followup_at source_account".split())
INTEGERS = {"last_known_message_count", "followup_count"}
DATES = set("created_at approved_at sent_at reply_checked_at followup_due_at last_followup_at".split())
SUPPRESSIONS = {"opt_out", "unsubscribe", "hard_bounce", "objection"}
COUNTERS = "input_rows excluded_business_hero unknown_namespace quarantined_rows new_contacts merged_rows duplicate_rows duplicate_messages collisions suppressions invalid_addresses unresolved_mailbox_thread date_inconsistencies unsupported_history expired_records scheduled_held send_actions current_allowance".split()


class ImportValidationError(ValueError):
    """Public errors contain only fixed messages, never input values."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(value):
    raise ValueError


def read_json(path, error="Invalid export"):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (OSError, ValueError, RecursionError):
        raise ImportValidationError(error) from None


def timestamp(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value):
        raise ValueError
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError
    return result.astimezone(timezone.utc)


def validate_export(payload):
    try:
        if not isinstance(payload, dict) or set(payload) != {"schema_version", "rows"}:
            raise ValueError
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError
        rows = payload["rows"]
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise ValueError
        for row in rows:
            if not isinstance(row, dict) or set(row) != STRINGS | NULLABLE | INTEGERS | {"followup_history"}:
                raise ValueError
            if any(not isinstance(row[k], str) for k in STRINGS) or not row["id"].strip():
                raise ValueError
            if any(row[k] is not None and not isinstance(row[k], str) for k in NULLABLE):
                raise ValueError
            if any(type(row[k]) is not int or row[k] < 0 for k in INTEGERS):
                raise ValueError
            if not isinstance(row["followup_history"], list):
                raise ValueError
            for key in DATES:
                if row[key] is not None:
                    timestamp(row[key])
        canonical(payload)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ImportValidationError("Invalid export") from None
    return rows


def validate_mapping(mapping):
    try:
        if not isinstance(mapping, dict) or set(mapping) != {"version", "namespaces"}:
            raise ValueError
        if not isinstance(mapping["version"], str) or not mapping["version"].strip():
            raise ValueError
        namespaces = mapping["namespaces"]
        if not isinstance(namespaces, dict) or set(namespaces) - (set(BRANDS) | {"Business Hero"}):
            raise ValueError
        tenants = {}
        for name, entry in namespaces.items():
            if not isinstance(entry, dict) or set(entry) != {"tenant_id", "brand", "mailboxes"}:
                raise ValueError
            tenant = str(UUID(entry["tenant_id"]))
            if tenant != entry["tenant_id"]:
                raise ValueError
            if name != "Business Hero" and entry["brand"] != BRANDS[name]:
                raise ValueError
            boxes = entry["mailboxes"]
            if not isinstance(boxes, dict) or any(not isinstance(k, str) or not k.strip() or
                    not isinstance(v, str) or not v.strip() for k, v in boxes.items()):
                raise ValueError
            if name != "Business Hero":
                tenants[name] = tenant
        new_body = {v for k, v in tenants.items() if k != "MSC"}
        if len(new_body) > 1 or tenants.get("MSC") in new_body:
            raise ValueError
        canonical(mapping)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise ImportValidationError("Invalid mapping") from None
    return namespaces


def _email(value):
    value = value.strip().casefold()
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        return None
    local, domain = value.split("@")
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in value:
        return None
    if any(label.startswith("-") or label.endswith("-") or len(label) > 63 for label in domain.split(".")):
        return None
    return value


def dry_run(path, *, mapping, as_of):
    namespaces = validate_mapping(mapping)
    rows = validate_export(read_json(path))
    try:
        if not isinstance(as_of, datetime) or as_of.utcoffset() is None:
            raise ValueError
        as_of = as_of.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ImportValidationError("Invalid export") from None
    counts = dict.fromkeys(COUNTERS, 0)
    counts["input_rows"] = len(rows)
    report = dict(schema_version=1, mapping_version=mapping["version"],
                  manifest_hash=digest({"export": {"schema_version": 1, "rows": rows}, "mapping": mapping}),
                  as_of=as_of.isoformat(), status="paused", passes=["suppression", "history"],
                  input_by_source={}, targets={}, counts=counts, samples=[])
    problems = [set() for _ in rows]
    identities = []
    suppressed = set()
    sources = defaultdict(set)
    id_namespaces = defaultdict(set)
    # Suppression is collected before any historical quarantine or deduplication.
    for i, row in enumerate(rows):
        name = row["business"]
        label = name if name in BRANDS or name == "Business Hero" else "unknown"
        report["input_by_source"][label] = report["input_by_source"].get(label, 0) + 1
        entry = namespaces.get(name) if name in BRANDS else None
        identity = (entry["tenant_id"], _email(row["contact_email"])) if entry else None
        identities.append(identity)
        if name == "Business Hero":
            counts["excluded_business_hero"] += 1
            continue
        if entry is None:
            counts["unknown_namespace"] += 1
            problems[i].add("unknown_namespace")
            continue
        sources[(name, row["id"])].add(digest(row))
        id_namespaces[row["id"]].add(name)
        if identity[1] and (row["reply_status"] in SUPPRESSIONS or
                           "do not contact me again" in row["notes"].casefold()):
            suppressed.add(identity)
    changed = {k for k, values in sources.items() if len(values) > 1}
    crossed = {k for k, values in id_namespaces.items() if len(values) > 1}
    counts["collisions"] = len(changed) + len(crossed)
    counts["suppressions"] = len(suppressed)
    contacts, messages, seen_rows, contact_sources = set(), set(), set(), set()
    for i, row in enumerate(rows):
        identity = identities[i]
        if identity is None or row["business"] == "Business Hero":
            continue
        tenant, email = identity
        entry = namespaces[row["business"]]
        target = report["targets"].setdefault(tenant, dict(rows=0, brands={}, unique_contacts=0,
                            unique_messages=0, suppressed_contacts=0, blocked_rows=0))
        target["rows"] += 1
        brand = entry["brand"]
        target["brands"][brand] = target["brands"].get(brand, 0) + 1
        source = (row["business"], row["id"])
        fingerprint = digest(row)
        if fingerprint in seen_rows:
            counts["duplicate_rows"] += 1
        seen_rows.add(fingerprint)
        if source in changed:
            problems[i].add("source_changed")
        if row["id"] in crossed:
            problems[i].add("cross_namespace_id")
        if email is None:
            problems[i].add("invalid_addresses")
        else:
            if identity not in contacts:
                contacts.add(identity)
                target["unique_contacts"] += 1
                counts["new_contacts"] += 1
                target["suppressed_contacts"] += int(identity in suppressed)
            elif (identity, source) not in contact_sources:
                counts["merged_rows"] += 1
            contact_sources.add((identity, source))
        mailbox = entry["mailboxes"].get(row["source_account"])
        if not mailbox or not row["gmail_thread_id"] or (row["status"] == "sent" and not row["gmail_message_id"]):
            problems[i].add("unresolved_mailbox_thread")
        if mailbox and row["gmail_message_id"]:
            message = (tenant, mailbox, row["gmail_message_id"])
            if message in messages:
                counts["duplicate_messages"] += 1
            else:
                messages.add(message)
                target["unique_messages"] += 1
        dates = {k: timestamp(row[k]) if row[k] is not None else None for k in DATES}
        ordered = [dates[k] for k in ("created_at", "approved_at", "sent_at") if dates[k] is not None]
        if ordered != sorted(ordered) or (dates["last_followup_at"] is not None and
                (dates["sent_at"] is None or dates["last_followup_at"] < dates["sent_at"])):
            problems[i].add("date_inconsistencies")
        if row["followup_history"]:
            problems[i].add("unsupported_history")
        if row["status"] not in {"sent", "send_failed", "template_approved"}:
            problems[i].add("unknown_status")
        if row["reply_status"] not in SUPPRESSIONS | {"none"}:
            problems[i].add("unknown_reply_status")
        if row["escalation_status"] != "none":
            problems[i].add("unknown_escalation_status")
        if row["notes"].strip() and "do not contact me again" not in row["notes"].casefold():
            # Notes have no structured consent semantics; require owner review.
            problems[i].add("notes_review")
        start = dates["sent_at"] or dates["created_at"]
        if start.year < 9999:
            anniversary = start.replace(year=start.year + 1,
                day=min(start.day, calendar.monthrange(start.year + 1, start.month)[1]))
            if row["reply_status"] == "none" and anniversary <= as_of:
                counts["expired_records"] += 1
                problems[i].add("expired_records")
        if dates["followup_due_at"] is not None:
            counts["scheduled_held"] += 1
        if problems[i] or identity in suppressed:
            target["blocked_rows"] += 1
    diagnostic_counters = {"invalid_addresses", "unresolved_mailbox_thread", "date_inconsistencies", "unsupported_history"}
    for i, codes in enumerate(problems):
        counts["quarantined_rows"] += int(bool(codes))
        for code in sorted(codes):
            if code in diagnostic_counters:
                counts[code] += 1
            if len(report["samples"]) < 5:
                report["samples"].append(dict(row_number=i + 1, code=code,
                    masked_email="***@***" if rows[i]["contact_email"] else None))
    report["report_hash"] = digest(report)
    return report


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ImportValidationError("Invalid arguments")


def main(argv=None):
    parser = SafeArgumentParser(description="Print a masked, offline outreach dry-run report.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--as-of", required=True)
    try:
        args = parser.parse_args(argv)
        try:
            as_of = timestamp(args.as_of)
        except (ValueError, OverflowError):
            raise ImportValidationError("Invalid export") from None
        report = dry_run(args.input, mapping=read_json(args.mapping, "Invalid mapping"), as_of=as_of)
        print(canonical(report))
        return 0
    except ImportValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
