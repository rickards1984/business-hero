# Security — STUB

**Status: stub.** Do not read this as a security assessment.

The brief's instruction applies here more than anywhere:
**"Do not describe the platform as secure merely because no vulnerability has
yet been found."**

| Topic | Source |
|---|---|
| Full findings register, 2026-07-04 | `audits/AUDIT-2026-07-04.md` |
| Perimeter hardening — Twilio signatures, rate limits, OpenAI clients | `audits/SESSION-2-CHANGES.md` |
| Grant narrowing and admin write paths | `audits/030B-SPEC.md`, `audits/030a-PROD-RUNBOOK.md` |
| Current risk list, ranked | `docs/CURRENT_STATE.md` §10 |

## Against the brief's checklist

| Item | State |
|---|---|
| Authentication | Supabase JWT, verified remotely per request |
| **MFA** | **absent** |
| Role-based permissions | Owner / member / platform admin only |
| Tenant isolation | Application-layer on backend; RLS state **unknown** |
| **Audit logging** | **absent** |
| Secrets management | Env vars, 48 distinct; `.env*` gitignored; no rotation policy |
| Encryption | Token ciphertext columns for OAuth providers |
| Input validation | Partial — raw dict bodies on parts of the money path |
| Rate limiting | Present (slowapi), in-process, breaks at 2+ replicas |
| Webhook verification | Stripe ✓, Twilio voice ✓, Twilio WhatsApp ✓ |
| Idempotency | Partial — quote conversion and Stripe only |
| **Dependency vulnerabilities** | **not scanned** |
| **Backups / restore testing** | **absent** |
| **Data export / deletion (UK GDPR)** | **absent** |
| Monitoring / error reporting | Railway logs only |
| Production rollback | Migration runbooks only; no application rollback procedure |
| Real-world send safeguards | Twilio kill switch exists |

**To write properly when:** P0-8 answers the RLS question. A security
document written before that would be describing a system nobody has looked
at.
