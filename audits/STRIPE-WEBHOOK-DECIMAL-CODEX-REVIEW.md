**APPROVE** this fix. It serves the North Star prerequisites of correctness and stability.

- **P1:** None introduced by this diff.
- **P2:** None introduced by this diff.
- **Backlog:** The existing freshness check compares Stripe’s event creation time against local processing time. Delayed events or checkout arriving first can suppress a legitimate tier update. This is unrelated to Decimal and should be handled separately. [main.py:1152](/Users/michaelrickards/dev/bh2-stripefix/backend/main.py:1152)

The payload fix is correct: `json.loads(payload)` parses the exact request body passed to signature verification, preserving the signed JSON values—including decimal strings—without SDK conversion. It is semantically identical JSON, **not byte-for-byte archival storage**, because parsing and JSONB discard formatting. [main.py:1240](/Users/michaelrickards/dev/bh2-stripefix/backend/main.py:1240)

The remaining handler paths are unaffected by Decimal values: checkout reads metadata and IDs; BH-006 compares price IDs and resolved tiers; business updates use strings, booleans and timestamps. Feature flags come from existing business data, and `last_stripe_event_at` uses the local clock. Reconciliation serializes selected IDs, statuses, tiers, counts and ISO timestamps—not the subscription dictionaries containing Decimal prices.

**Verification:** All 85 webhook and reconciliation tests passed using installed Stripe **15.6.1**. Reverting only the payload assignment **in memory** made the new real-SDK/HMAC regression test fail with `TypeError: Object of type Decimal is not JSON serializable`.

One non-blocking test improvement: its fake session does not serialize at commit, so the original implementation fails at the final serialization assertion rather than returning production’s 503. A database-backed regression would cover that transaction boundary.

No files were changed. I did not run `check.sh`, whose compilation step writes bytecode. After deployment, confirm the failed event’s next delivery shows **200** in Stripe and the expected subscription state appears in Business Hero.