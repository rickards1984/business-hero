# 039 — STAGING REHEARSAL (platform meters)

**Run by:** Mike, 27 Oct 2026, on staging (`gzcrsrqmygublveuzqyg`), following `audits/039-PROD-RUNBOOK.md`.

## First apply
- **STEP 0:** `current_database` postgres; `platform_meters_before` NULL; `policies` **95**; `columns` **1137**.
- **STEP 1:** Success, no rows returned.
- **STEP 2:**
  - `platform_meters` = platform_meters;
  - `meter_columns` 4;
  - `rls_on` true;
  - `meter_policies` 0;
  - `client_grants` 0;
  - `policies` **95** (unchanged);
  - `columns` **1141** (1137 + 4);
  - `constraints`: `CHECK (((length(meter) >= 1) AND (length(meter) <= 200))) | CHECK ((period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'::text)) | PRIMARY KEY (period, meter) | CHECK ((value >= (0)::numeric))`.

## Rollback
`DROP TABLE IF EXISTS public.platform_meters;` succeeded. **STEP 0** then showed `platform_meters_before` NULL again and `columns` back to 1137.

## Re-apply
STEPS 0–2 were run again, with outputs identical to the first apply (Mike: "nothing different and everything worked as expected").

**Result:** apply, rollback and re-apply are all proven on staging. Production may proceed.
