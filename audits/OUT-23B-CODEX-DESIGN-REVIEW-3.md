# OUT-23 Part B (Hunter.io) — Codex design review 3 (verbatim)

Commit reviewed: 5fb2756 (design revision 3).

---

Read-only review completed on `ticket/OUT-23-hunter`. Nothing modified, committed or pushed; tests not run. This review serves correctness, security and tenant isolation.

1. **P1 — R3.1: Disconnect still fails to invalidate an initial connection attempt.**  
   **Scenario:** No account row exists. Connect reads `seen = 0` and awaits `/account`. Disconnect’s prescribed update affects zero rows. Connect subsequently inserts successfully, reconnecting after the owner disconnected.  
   **Fix:** Disconnect must create a disconnected tombstone with a nonzero generation when the row is absent, under the business lock. Test this initial-connect race separately from disconnect/reconnect with an existing row.

2. **P1 — R3.8: “Current” still does not select the latest approved assessment.**  
   **Scenario:** Version 1 includes Hunter; version 2 is approved without it. [`_audience`](/Users/michaelrickards/dev/bh2-HUNTER/backend/services/outreach_research.py:280) checks approval dates, not supersession, and `run_due` selects all approved versions. Version 1 therefore remains usable for Hunter acquisition, contrary to R3.8’s promised test.  
   **Fix:** Define the authoritative approved version per business, brand and audience hash, and enforce it during acquisition, reservation and storage. Update scheduled selection accordingly. Preserve the explicitly chosen historical `prospect.lia_id` rule for first sends.

3. **P2 — R3.2/R3.3: Settlement does not update the field that controls the brand cap.**  
   **Scenario:** A search reserves one brand credit and returns a valid zero-cost header. The specified settlement updates `used_native` and `pool_actual`, but leaves `brand_credits = 1`. Since the cap sums `brand_credits` across every state, free calls exhaust it and usage is overstated. Hunter explicitly documents zero-cost responses in its [API reference](https://hunter.io/api-documentation/v2). “Charge the larger amount” also lacks a conversion rule when units differ.  
   **Fix:** Specify atomic settlement of `brand_credits` alongside native usage, with explicit conversion into brand-credit units before comparing amounts. Preserve reserved charges for missing/malformed headers and swept rows. Test zero-cost settlement, fractional settlement, mismatched units and duplicate settlement.

Review 2 findings **4–7 and 9 are answered sufficiently for implementation**: the lock order, total enrichment deadline, verifier acceptance, immutable provenance and blocked-dispatch gate fit the inspected code.

Implementation notes: explicitly distinguish historical-ledger settlement/sweeping from writes to the current connection generation; ensure deadline enforcement covers DNS and streaming reads, not merely per-operation HTTP timeouts.

VERDICT: CHANGES REQUESTED