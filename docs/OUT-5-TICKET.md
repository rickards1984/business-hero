## TICKET OUT-5 — Stage A: outreach history import dry run

**Outcome** Mike can review the contract for a deterministic, masked, local history-import report before any personal data is imported or outreach is activated.

**Current evidence** `docs/OUT-1-DESIGN.md` §8 defines source fields, namespace mapping, suppression-first processing, masking and quarantine; §11 assigns OUT-5 parser/dry-run before separately authorised execution. Its 19 October decisions approve decisions 1–9, including import review. `docs/OUT-2-CONTRACTS.md` F15 specifies mapping, collisions, paused history and no-op reruns; F19 requires retention without resetting age; F21 gates activation. Its §5 reserves `outreach_import_runs`/`outreach_import_items`. `docs/OUT-4-TICKET.md` explicitly defers import tables/reports to OUT-5. The proposed `backend/services/outreach_import.py` is absent in this checkout. No source export or live mailbox has been inspected.

**Scope** Stage A only: this packet and synthetic failing contract tests. Propose a pure local parser/report function and CLI for later Stage B implementation. No implementation is delivered here.

**Non-goals** Apply/import, DB reads or writes, sessions, models, migration, account discovery, live mailbox verification, scheduler, dispatch, usage charges, API routes, Aria registration, provider/model calls, real outreach files, network, commit and push. No access to `~/.openclaw`. No alteration to existing tests or implementation.

**Dependencies** OUT-2 fixed contracts and OUT-3/OUT-4 baseline. Synthetic offline tests require no deployed schema. Independent Claude review and Mike's approval of the proposed AMBER parser contract precede Stage B. Two separate mandatory gates precede any real personal-data import: (1) apply and its `outreach_import_runs`/`outreach_import_items` migration are a later RED stage, with explicit approval per production action, staging rehearsal, verified RLS/grants/constraints and rollback preserving objections; (2) OUT-13 retention and subject-rights handling must be operational, including erasure and processor/backup arrangements. A dry-run report does not grant either authority. Real export handling also requires Mike's explicitly authorised minimal export and verified mapping. Real sends remain separately authorised under OUT-9 and its prerequisites.

**Affected systems** Backend test contracts and documentation only; future local backend service/CLI, no frontend, database or third-party changes.

**Security & data risk** Stage A GREEN synthetic tests/documentation, explicitly requested. Future parser AMBER; real import/schema/production actions RED. Tenant isolation and correctness prerequisites support North Star P9 and P2/P8. Nothing new is stored or fetched from a service; the future persisted import report must ship a tenant-scoped Aria read tool under OUT-4's deferred catalogue.

**Acceptance criteria**

1. Accept only the versioned UTF-8 JSON contract below, from a caller-supplied local file. Validate the whole envelope and mapping before returning any report. Malformed structural/type/date input fails closed with `ImportValidationError("Invalid export")`, without echoing payloads, logs or partial output. Invalid mapping says `Invalid mapping`. No DB/session, network or output-file access, even during module import.
2. Exact namespace allowlist: MSC → verified MSC tenant; FitFutures and UKFI → verified New Body tenant, brand FitFutures; New Body → same New Body tenant, brand New Body. Different target tenants must remain distinct. Business Hero is unconditionally excluded and counted, even if a caller tries to map it. Unknown/missing/empty namespace is quarantined; no case folding or free-text tenant inference. Preserve source/brand counts when people merge.
3. Pass one validates and stages every recognised opt-out, unsubscribe, hard bounce and objection in memory by target tenant/normalised email; pass two resolves history. Staging means no persistence. Suppression is monotonic across later rows and New Body brands; never crosses to MSC. Date-quarantined history cannot discard a valid suppression. Explicit note “Do not contact me again” suppresses; ambiguous objections block pending review. Unknown reply labels require review, never invented freshness or consent.
4. Normalise email by trimming and case folding; retain plus tags and dots. Invalid or ambiguous addresses quarantine. Merge people only by normalised email within tenant. Message dedup key is target tenant + mapped original mailbox + provider message ID; retain source history associations. Duplicate source key with identical content counts duplicate; changed content under that key is a review collision, never last-write-wins. Same ID across namespaces also reports a collision, without treating it as a global identity.
5. Quarantine inconsistent chronology (creation ≤ approval ≤ send; follow-up cannot precede send), unresolved mailbox/thread, unsupported follow-up history. Syntactically invalid timestamps fail the whole export. Expiry is measured from first contact (sent_at), or creation if never contacted, with a 12-calendar-month unanswered threshold at explicit `as_of`; no reset on import/follow-up. Engaged retention policy remains OUT-13. Old due dates are held; historical sent/draft/failed states never enqueue, retry, approve or consume current allowance. Everything remains paused.
6. Report contains aggregate counts and at most five minimal masked diagnostic samples globally, selected deterministically by input row number/code. Never return names, company, notes, subjects, bodies, full/partial addresses beyond the constant mask, raw source/provider identifiers or per-contact projections. Errors/stdout/stderr/logs follow the same minimisation. Report is not a contact dump.
7. Identical export, mapping and explicit `as_of` give byte-equivalent canonical report and identical report hash, with zero side effects. No wall-clock/run UUID/randomness. Mapping changes affect identity. This proves deterministic dry-run reruns only; transactional apply no-op/resumption, changed hash against an existing journal and rollback are RED-stage tests later.
8. Strict xfail catches only the custom exception raised when `find_spec("services.outreach_import") is None`. Once the module exists, dependency/import/assertion failures are ordinary failures and successful tests are strict XPASS until Stage B removes the marker.

**Required tests** `backend/tests/test_outreach_import_dry_run.py`, synthetic `example.invalid` addresses only: source/brand mapping, adversarial Business Hero mapping, unknown namespace, both suppression orders and all four reasons, suppression surviving date quarantine, tenant isolation, plus/dot preservation, invalid addresses, source collisions/exact duplicates, mapped-mailbox message dedup, chronology, unresolved history, expiry/held dates/no allowance, bounded masking, deterministic hash, malformed export, invalid mapping and empty export. All tests install DB/session/network denial before importing the proposed module. Input files remain unchanged and no output files are created. Stage B extends adversarial parser coverage for resource limits, unknown labels and ambiguous notes before approval; no claim that synthetic tests prove live continuity or RLS.

**Verification** `PYTHONDONTWRITEBYTECODE=1 ./check.sh`; targeted `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest backend/tests/test_outreach_import_dry_run.py -q`; `git diff --check`. No push; `./check.sh full` is required before any future authorised push.

**Likely files** Stage A exactly `docs/OUT-5-TICKET.md` and `backend/tests/test_outreach_import_dry_run.py`. Stage B proposed `backend/services/outreach_import.py` plus these files; no shared main.py or DB models.

**Builder** Codex.

**Reviewer** Claude Code, independent review pending. Mike reviews the behaviour/input assumptions, not code correctness.

**Branch** `ticket/OUT-5-import-dry-run`, isolated worktree `/Users/michaelrickards/dev/bh2-OUT-5`, built on OUT-4. Initial working tree clean.

**Budget band** S (<2h) Stage A; M (half day) proposed Stage B parser. RED execution estimated separately.

**Max repair cycles** 3, then escalate.

**Completion evidence** Pending verification below.

**Status** in review — Stage A only; Stage B and RED stages not authorised by this packet.

### Proposed export and executable seam

This is an **assumed interchange format**, not a claim about Mike's local export. UTF-8 JSON object with exactly `schema_version: 1` and `rows: [...]`; reject duplicate JSON keys, non-finite numbers, wrong types and unknown keys. Each row has exactly the fields in the synthetic `row()` fixture:

- Required strings: `id` (nonempty source ID), `business` (source namespace), `segment`, `company`, `contact_name`, `contact_email`, `subject`, `body`, `status`, `reply_status`, `escalation_status`, `notes`, `created_at`. Empty `business` is an unknown mapping; invalid string email is quarantined.
- Nullable strings: `approved_at`, `sent_at`, `gmail_message_id`, `gmail_thread_id`, `reply_checked_at`, `followup_due_at`, `last_followup_at`, `source_account`.
- Nonnegative integers (not booleans): `last_known_message_count`, `followup_count`.
- `followup_history`: JSON array. Only empty arrays are resolved in this initial contract; nonempty history is quarantined as `unsupported_history` until its actual shape is documented. Never silently drop or guess its events.

All timestamp strings must be valid timezone-aware ISO 8601, normalised to UTC. `source_account` is the one proposed additional provenance field absent from §8's legacy list: an export-side opaque account alias resolved using the supplied mapping. Missing account information remains unresolved; never look up Gmail over the network. Known historical statuses include `sent`, `send_failed`, `template_approved`; `reply_status` supports `none`, `opt_out`, `unsubscribe`, `hard_bounce`, `objection` for these fixtures. Other values require documented semantics/review, not automatic activation.

Mapping is a separate trusted local manifest: `{version, namespaces: {<exact namespace>: {tenant_id, brand, mailboxes: {<source_account>: <mapped mailbox>}}}}`. Require nonempty version and valid tenant UUIDs; MSC differs from New Body, FitFutures/UKFI share New Body. Reject contradictions. Business Hero entries can never override exclusion. UUIDs/mailbox aliases in tests are synthetic; a local parser cannot verify actual ownership. Mike must later approve the exact mapping against verified accounts before apply.

Proposed callable: `dry_run(path, *, mapping, as_of) -> dict`; exception `ImportValidationError`. Proposed local command (not implemented): `PYTHONPATH=backend python -m services.outreach_import --input export.json --mapping mapping.json --as-of 2026-10-20T12:00:00Z`. Reads only the explicit local files, prints one masked JSON report, no HTTP/admin endpoint, session, engine, provider credentials or apply flag. CLI returns nonzero and only a safe error on malformed input. CLI tests follow implementation; Stage A tests exercise the pure file-reading seam.

### Exact report contract

Top-level keys: `schema_version`, `mapping_version`, `manifest_hash`, `report_hash`, `as_of`, `status` (always `paused`), `passes` (always `["suppression", "history"]`), `input_by_source`, `targets`, `counts`, `samples`. Unknown namespace text is bucketed as `unknown` rather than echoed; known source names are fixed allowlisted labels.

`counts` has zero-initialised integer counters: `input_rows`, `excluded_business_hero`, `unknown_namespace`, `quarantined_rows`, `new_contacts`, `merged_rows`, `duplicate_rows`, `duplicate_messages`, `collisions`, `suppressions`, `invalid_addresses`, `unresolved_mailbox_thread`, `date_inconsistencies`, `unsupported_history`, `expired_records`, `scheduled_held`, `send_actions`, `current_allowance`. Last two always zero. Diagnostic categories can overlap; `quarantined_rows` counts each affected input row once. `collisions` counts distinct source-change keys and distinct IDs spanning namespaces; duplicates do not multiply those collision groups.

`targets` keyed only by mapped tenant UUID contains `rows` (mapped input rows), `brands` (allowlisted brand → input count), `unique_contacts`, `unique_messages`, `suppressed_contacts`, `blocked_rows`. Excluded/unknown rows never enter it. Contact/message counters deduplicate valid identities; suppressed identities remain counted but blocked. `new_contacts` is distinct valid identities in this export, **not** a comparison against a live DB. `merged_rows` counts additional distinct source rows sharing a tenant/email. No list of those identities is returned.

Each diagnostic sample has exactly `{row_number, code, masked_email}`, with 1-based row number, safe enum code and constant `***@***` (null when no address exists). No source ID is needed to locate an issue in the owner's local export. Collision codes include `source_changed` and `cross_namespace_id`. Maximum five samples globally, including large exports.

Hash canonicalisation: sorted JSON keys, compact separators, ASCII escapes and UTF-8 bytes; SHA-256 hex. `manifest_hash` covers the parsed export plus complete mapping manifest; `report_hash` covers the entire report except itself, including fixed `as_of`. Never expose individual address/body hashes. File formatting alone need not change identity. Local expiry is a review signal, not evidence that retention/erasure is operational.

### Questions and review action

Mike: confirm whether his local system can provide this versioned JSON or needs an explicit CSV/JSONL conversion contract; confirm exact source namespace spellings, source account provenance, reply/status meanings and nonempty follow-up-history shape using schema documentation or synthetic examples. No real export requested or inspected in this stage. The destination decisions (MSC/New Body, Business Hero excluded) are settled.

Open this packet and the test file to review the assumptions; there is no new app screen to click. `check.sh` with expected failures validates the scaffold and existing suite, not a working importer. Claude's independent review remains pending. Neither green checks nor approving this packet authorises real personal-data import, SQL or sends.

### Mike's decision — 21 October 2026

The Stage A tests are **approved**. The export format is still open: Mike isn't sure what his local system can export. Claude will inspect the local system's *code* (never its prospect data) to find or propose an export that matches the contract above.

### Claude's review of Stage B — 21 October 2026

Codex built `backend/services/outreach_import.py` (the dry run and its CLI), `scripts/export-outreach-history.py` (the converter Mike runs on his Mac) and `backend/tests/test_outreach_export_converter.py`, and removed the strict-xfail marker. **All 73 OUT-5 tests pass**, and `./check.sh full` is green. Codex's log shows no access to `~/.openclaw` or `~/control-tower`; the source shape came from Claude's reading of the engine *code*.

**I read the personal-data paths in full.**

The converter:
- opens the send log with `mode=ro` and `PRAGMA query_only`;
- refuses an output path inside any git repository, checking twice;
- creates the file with `O_EXCL` and mode `0600`, so it never overwrites anything and only Mike's user can read it;
- prints only per-business counts and the output path;
- on any error, prints only "Export failed".

The dry run:
- reads only the two files it's given;
- prints only the canonical masked report;
- on errors, prints only fixed safe messages.

**Mapping template verified:** a mapping with empty `mailboxes` is accepted. Unmapped sending accounts are then counted (`unresolved_mailbox_thread`) rather than guessed, which is right for a first look.

**Still open:** compatibility with Mike's real files is untested by design, because nobody but Mike reads them. His first run is that test. It changes nothing, and anything unexpected is counted as `unmapped` or quarantined.


### Mapping rules (Claude, 21 Oct)

Repair cycle 2 is narrowly authorised by Mike conveying Claude's review. It
serves P2/P8 data correctness and P9 tenant isolation. Scope is the converter,
dry-run service, their two test files and this ticket; no commit, push, network,
real source inspection, persistence or sends. This section supersedes the
initial assumed vocabulary and unsupported-summary treatment above.

- Suppress by target tenant and normalised email before history processing.
  Queue opted_out, reply unsubscribe/opted_out and escalation
  auto_resolved_unsubscribe mean unsubscribe. Reply bounce or escalation
  auto_resolved_bounce means hard_bounce. Reply objection/polite_decline means
  objection. Preserve each reason, including multiple reasons per contact;
  failure statuses alone never suppress. Existing opt_out/hard_bounce and
  explicit do-not-contact note support remains.
- Reply categories: strong_positive/interested → interested;
  needs_judgment/unclear/handled → unknown human reply; ooo/auto_ack →
  out_of_office; bounce → bounce; unsubscribe/opted_out → unsubscribe;
  objection/polite_decline → objection; missing/none/no_reply → no reply.
- Escalation pending_byron/action_needed → owner_review.
  Missing/none/handled and the observed auto_resolved_bounce,
  auto_resolved_unsubscribe, auto_resolved_ooo, auto_resolved_auto_ack have no
  review flag. Unrecognised escalation values are never guessed.
- Queue sent retains accepted history; approved/template_approved retain
  historical drafts requiring fresh approval; send_failed retains failure;
  skipped retains not-contacted history; opted_out suppresses. All stay paused.
- followup_count and last_followup_at form a per-contact summary, not invented
  messages. Successful linked ledger events supply a count (maximum of the
  source count and observed sends, avoiding double counting) and latest date.
  Failed linked events are counted separately in the summary. Exact queue IDs
  take precedence; otherwise link only one queue candidate with the same
  business and normalised recipient. Multiple candidates are collisions.
  No candidate retains an orphan record. Business Hero is excluded by the
  importer; its unlinked ledger records remain separate excluded records.
  Unknown/malformed history remains quarantined.
- A mailbox alias may map to literal unconnected: known tenant ownership,
  counted as mailbox_unconnected and blocked, without treating that mailbox
  as unresolved. Missing mapping remains unresolved_mailbox_thread. Thread
  and message provenance checks still apply independently. Cross-tenant
  alias ownership and mapped mailbox contradictions fail with Invalid mapping;
  local mapping checks cannot establish live account ownership.
- Report counts add suppressions_by_reason (distinct tenant/contact per reason),
  replies_by_category, owner_review, orphan_sends, mailbox_unconnected and
  unsupported_by_field. unsupported_history counts rows with genuinely unknown
  fields/history; field counters contain only fixed field names, never values.
  Existing masked samples, deterministic hashes, exclusion, zero send actions,
  zero allowance and paused status remain.
- Only the three authorised conflicting tests change their unknown-value
  examples to mystery_reply_status_x/mystery_escalation_y, including matching
  expected unmapped labels. Their assertions remain. New tests independently
  verify strong_positive → interested and pending_byron → owner_review.

Acceptance: all observed labels above are recognised, suppressions survive
quarantine and remain tenant-scoped, ambiguous links never select a recipient,
and imports cannot activate sending. Synthetic tests cover these behaviours.
No app UI changes: review the masked JSON counts from a separately authorised
owner-run dry run; there is no new screen to click. Real-file compatibility and
live mailbox ownership are not verified by these offline tests.

Verification: new regression tests first failed (22 failures, 79 passes), then
the initial implementation passed all 101 targeted tests. Final expanded suite
and required check result recorded below.

Final completion evidence: `PYTHONDONTWRITEBYTECODE=1 ./check.sh` exited 0:
4 passed, 0 failed, 1 skipped (no eslint script); pytest 2529 passed,
234 skipped, 220 subtests passed. OUT-5 targeted suite: 117 passed.
Converter ruff and `git diff --check` passed. The verification-created
untracked data.db artifact was removed. Only the five authorised files remain
changed. No commit, push, network or real source directory access occurred.
Status: repair cycle 2 ready for Claude review; no apply/activation authority.
