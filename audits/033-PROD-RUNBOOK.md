# 033 — PROD RUNBOOK

**Migration:** `backend/migrations/033_entitlement.sql`
**Target:** Business Hero prod — Supabase project **`oxblcmwhuwtobdhsfgyi`**
**Rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`), 25 Aug 2026.
Sections 1–5 applied → rolled back → re-applied → run twice more for
idempotency. Sections 6–7 rehearsed twice: once against reconstructed
fixtures, then again against **six fixtures seeded row for row from the
exact prod values**. Record: `audits/033-STAGING-REHEARSAL.md`.

---

## Before you start

Read the step, paste the SQL, compare against **EXPECT**, continue only if
it matches. Three rules:

1. **One step at a time.** Never paste two steps at once.

   **And one QUERY at a time.** This bit twice on the night of 29 Aug
   2026, so it is a rule, not advice:

   - **The Supabase SQL editor renders only the LAST statement's result
     grid.** Paste three verification queries together and you see the
     third. The first two run, but you never see them — so a step reports
     "passed" on evidence you did not look at. Where a step lists several
     queries, they are numbered and separated; run each on its own.
   - **A failed statement poisons the rest of its transaction.**
     Everything after it returns `current transaction is aborted,
     commands ignored until end of transaction block`. So every wrapped
     `BEGIN … ROLLBACK` block that EXPECTS an error must be run alone —
     pasted together, the later ones return an abort message that looks
     like the error you wanted and tests nothing.
   - The flip side is useful: **getting a result grid back at all proves
     the statement before it did not raise.**
2. **EXPECT must match.** If it does not, go to that step's **STOP IF**.
   Do not improvise and do not fix it yourself at 1am.
3. **On a mismatch, stop and report it.** Paste the output to Claude Code
   and say "prod 033 step N mismatch". Every section has a `ROLLBACK <n>`
   block in the migration file, and every one of them was executed on
   staging, not merely written.

**Confirm the project selector reads `oxblcmwhuwtobdhsfgyi` before every
paste.** The staging project is `gzcrsrqmygublveuzqyg`. Two projects exist
on this account and getting this wrong is the worst outcome available.

**STEPS 0–5 ARE READ-ONLY. Nothing changes until STEP 6.**

**This runbook has two halves and they are not interchangeable:**

- **PART ONE (STEPS 0–18) — sections 1 to 6.** Safe. Schema, grants, and
  two lossless data transforms. Nobody's access changes.
- **PART TWO (STEPS 19–24) — section 7.** Destructive. It removes
  `feature_flags` keys. It is gated on a code deploy, and STEP 20 is that
  gate. **You may stop after PART ONE and do PART TWO another night.**
  You may not do PART TWO without PART ONE.

**Elapsed time:** about 45 minutes for PART ONE, 15 for PART TWO.
**Downtime:** none expected. STEP 13 rewrites a grant on `businesses`;
it takes a brief lock on a 6-row table.

### What prod is expected to hold going in

> **⚠ THIS TABLE IS FROM 25 AUG 2026 AND PROD HAS SINCE DRIFTED.** A
> `Business Hero` business exists carrying `calendar: true` **and**
> `calendar_booking: false` — a shape none of the original fixtures had,
> and the one that forced R1's merge rule to be rewritten (see STEP 17).
> Treat the table below as the shape to expect, **not** as the EXPECT
> values. **STEP 5's output is the authority.** Every row count in PART
> ONE is written as "derive it from STEP 5" for that reason.

From the live values supplied 25 Aug 2026, which the staging fixtures were
built from:

| Business | plan_tier | feature_flags | brand_color column |
|---|---|---|---|
| Multi Skilled Contractors LTD | `pro` | 11 keys, incl. `brand_color: "#3B82F6"` | `#3B82F6` |
| New Body Health & Fitness | `pro` | 7 keys, incl. `brand_color: "#475569"` | `#3B82F6` |
| Test 1–4 | `starter` | `{"receptionist": false}` | `#3B82F6` |

**Expected end state after PART TWO:** every business at `{}` **except**
those carrying a genuine exception — on current prod that is Business
Hero, which ends at `{"calendar_booking": false}`. MSC's colour unchanged
at `#3B82F6`, New Body's column updated to `#475569`.

---

# PART ONE — SECTIONS 1 TO 6

---

## STEP 0 — Prod before-snapshot (READ-ONLY)

This is what a rollback is diffed against. **Do not skip it.**

```sql
SELECT 'COLUMN' AS kind,
       table_name || ' | ' || column_name AS obj,
       data_type || ' null=' || is_nullable
         || ' def=' || coalesce(column_default, '-') AS detail
  FROM information_schema.columns
 WHERE table_schema='public'
   AND table_name IN ('businesses','plan_definitions','usage_meters')
UNION ALL
SELECT 'CONSTRAINT', conrelid::regclass::text || ' | ' || conname,
       pg_get_constraintdef(oid) || ' valid=' || convalidated::text
  FROM pg_constraint
 WHERE connamespace='public'::regnamespace
   AND conrelid::regclass::text IN
       ('businesses','plan_definitions','usage_meters')
UNION ALL
SELECT 'INDEX', tablename || ' | ' || indexname, indexdef
  FROM pg_indexes
 WHERE schemaname='public'
   AND tablename IN ('businesses','plan_definitions','usage_meters')
UNION ALL
SELECT 'POLICY', tablename || ' | ' || policyname || ' | ' || cmd,
       coalesce(qual,'~') || ' ||WC|| ' || coalesce(with_check,'~')
  FROM pg_policies
 WHERE schemaname='public'
   AND tablename IN ('businesses','plan_definitions','usage_meters')
UNION ALL
SELECT 'RELACL', 'businesses', unnest(relacl)::text
  FROM pg_class WHERE oid='public.businesses'::regclass
UNION ALL
SELECT 'COLACL', 'businesses | ' || attname, attacl::text
  FROM pg_attribute
 WHERE attrelid='public.businesses'::regclass AND attnum>0
   AND NOT attisdropped AND attacl IS NOT NULL
UNION ALL
SELECT 'DATA-BIZ', name || ' | ' || plan_tier,
       'colour=' || coalesce(brand_color,'-')
         || ' flags=' || feature_flags::text
  FROM public.businesses
UNION ALL
SELECT 'DATA-PLAN', 'plan_definitions | ' || id,
       name || ' | ' || coalesce(monthly_price_gbp::text,'-')
         || ' | ' || features::text
  FROM public.plan_definitions
ORDER BY 1, 2, 3;
```

**DO THIS:** click Export → CSV. Save it as `033-prod-before.csv`.

**EXPECT:** a `DATA-BIZ` row for **every** business (6 as of 25 Aug 2026;
prod has since gained at least Business Hero, so expect more) and a
`DATA-PLAN` row for each plan. No `usage_meters` rows of any kind — that
table does not exist yet.

**STOP IF:** you get zero rows, fewer than 6 `DATA-BIZ` rows, or any
`COLUMN` row naming `usage_meters`. Either you are in the wrong project or
part of 033 has already been applied. Go to STEP 1 and settle it.

---

## STEP 1 — Confirm you are on the right database

```sql
SELECT current_database(),
       (SELECT count(*) FROM public.businesses)        AS businesses,
       (SELECT count(*) FROM public.plan_definitions)  AS plans,
       (SELECT count(*) FROM public.invoices)          AS invoices,
       (SELECT to_regclass('public.usage_meters')::text) AS usage_meters,
       (SELECT to_regclass('public.zz_033_flags_backup')::text) AS backup_tbl;
```

**EXPECT:** `businesses` ≥ 6, `plans = 3`, `invoices` ≥ 5,
`usage_meters = NULL`, `backup_tbl = NULL`. **Write the business count
down** — STEP 15 checks the backup against it.

**STOP IF:**
- `businesses = 3` **or** `plans = 0` — **you are on staging.** Close the
  tab, reopen prod, start again. (Checked live 29 Aug 2026: staging holds
  3 businesses and 0 plan_definitions. Do **not** use the invoice count to
  tell them apart — staging has 5 invoices too. `usage_meters` already
  exists on staging as well, from the rehearsal; on prod it must be NULL.)
- `usage_meters` is not NULL — SECTION 3 has already run. Do not re-run
  PART ONE blind; report it.
- `backup_tbl` is not NULL — **SECTION 6 has already run at least once.**
  Stop. The backup table is the only route back and re-running SECTION 6
  will not overwrite it (that is deliberate), but you need to know what
  state you are resuming from before touching anything.

---

## STEP 2 — Pre-flight 1: no business holds a tier that is about to become illegal

```sql
SELECT id, name, plan_tier FROM public.businesses
 WHERE plan_tier NOT IN ('starter','pro','business','beta');
```

**EXPECT:** `0 rows`. (As of 25 Aug: two `pro`, four `starter`, plus
whatever has been created since.)

**STOP IF:** any row comes back. STEP 6's `ALTER TABLE` will fail rather
than corrupt anything, but a business sitting on `elite` or `paused` needs
a **decided** destination tier and that decision is not in this file.
Report the rows and stop.

---

## STEP 3 — Pre-flight 2: what shape is `plan_definitions` in?

**Three queries. RUN THEM ONE AT A TIME** — pasted together you will see
only 2c's result and will not have looked at 2a, which is the one STEP 8
compares against.

```sql
-- 2a: the rows SECTION 2 acts on
SELECT id, name, monthly_price_gbp, sort_order, is_active, features::text
  FROM public.plan_definitions
 WHERE id IN ('enterprise','business');

-- 2b: does prod have a unique id at all?
SELECT conname AS obj, pg_get_constraintdef(oid) AS def
  FROM pg_constraint WHERE conrelid='public.plan_definitions'::regclass
UNION ALL
SELECT indexname, indexdef FROM pg_indexes
 WHERE schemaname='public' AND tablename='plan_definitions';

-- 2c: duplicate ids already present?
SELECT id, count(*) FROM public.plan_definitions
 GROUP BY id HAVING count(*) > 1;
```

**EXPECT:**
- **2a:** exactly one row, `id = 'enterprise'`. **Save this output** —
  STEP 8 compares against it field by field.
- **2b:** either a PRIMARY KEY / UNIQUE on `(id)`, or zero rows. Both are
  survivable. Write down which.
- **2c:** `0 rows`.

**STOP IF:**
- **2a returns a `business` row.** `supabase/migrations/025` has run on
  prod after all. SECTION 2 becomes a no-op and SECTION 1 reduces to
  removing `paused` — the file is safe either way, but this changes
  whether prod's top tier already has features distinct from `pro`.
  Report it before continuing.
- **2a returns zero rows.** Neither id exists. Something has already
  rewritten this table. Stop.
- **2c returns any row.** Duplicate ids, with no unique index to have
  stopped them. `onboarding_api.py:187` does
  `SELECT * FROM plan_definitions WHERE id = :plan_id` expecting one row.
  Stop and resolve the duplicate first.

---

## STEP 4 — Pre-flight 3: the exact column inventory of `businesses`

**This step guards STEP 13, and it is the one most likely to bite.**
SECTION 5 revokes the table-level UPDATE on `businesses` and re-grants an
**explicit list of 26 columns**. Any column that exists on prod but is
missing from that list silently stops being writable from the browser.

```sql
SELECT count(*) AS n_columns,
       string_agg(column_name, ', ' ORDER BY column_name) AS cols
  FROM information_schema.columns
 WHERE table_schema='public' AND table_name='businesses';
```

**EXPECT:** `n_columns = 26`, and the list must be exactly:

```
api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled,
created_at, current_period_end, feature_flags, id, is_active,
last_stripe_event_at, limits, logo_url, name, onboarded_by,
onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier,
region, stripe_customer_id, stripe_subscription_id, subscription_status,
tax_number, tax_registered, timezone, trial_ends_at
```

Then confirm the grant is still table-level, which is what SECTION 5
assumes it is converting:

```sql
SELECT unnest(relacl)::text FROM pg_class
 WHERE oid='public.businesses'::regclass;
SELECT count(*) AS column_level_acls FROM pg_attribute
 WHERE attrelid='public.businesses'::regclass AND attnum>0
   AND NOT attisdropped AND attacl IS NOT NULL;
```

**EXPECT:** an `authenticated=arwdDxtm/postgres` entry, and
`column_level_acls = 0`.

**STOP IF:**
- **`n_columns` is not 26, or the list differs.** Do not run STEP 13. A
  column present on prod but absent from SECTION 5's `GRANT UPDATE` list
  loses browser write access, and the symptom is a customer's save
  failing weeks later. Report the difference; the list needs updating in
  the migration file first.
- **`column_level_acls` is not 0**, or `authenticated` already reads
  `ardDxtm` (no `w`). SECTION 5 has already run, or 030b's grant
  narrowing has landed since this was written. Stop.

---

## STEP 5 — Pre-flight 4: the flag data SECTION 6 will transform

**Five queries. RUN THEM ONE AT A TIME** — pasted together you will see
only 6e's result. 6d is the one you must save, and 6c is the branding
decision; neither would appear.

```sql
-- 6a: every key involved in a rename must hold a BOOLEAN, or the merge
--     cast fails mid-statement.
SELECT b.name, k.key, jsonb_typeof(b.feature_flags -> k.key) AS typ
  FROM public.businesses b,
       LATERAL jsonb_object_keys(b.feature_flags) AS k(key)
 WHERE k.key IN ('accounting_enabled','accounting',
                 'calendar_booking_enabled','calendar','calendar_booking',
                 'quoting_enabled','quoting',
                 'whatsapp_enabled','whatsapp',
                 'voice','aria_voice')
   AND jsonb_typeof(b.feature_flags -> k.key) <> 'boolean';

-- 6b: every brand_color value must be a valid 6-digit hex string,
--     because the key is DELETED after the copy.
SELECT b.name, b.feature_flags -> 'brand_color' AS flag_value
  FROM public.businesses b
 WHERE b.feature_flags ? 'brand_color'
   AND (jsonb_typeof(b.feature_flags -> 'brand_color') <> 'string'
        OR b.feature_flags ->> 'brand_color' !~ '^#[0-9A-Fa-f]{6}$');

-- 6c: the flag/column disagreement, made visible. This is R2's decision.
SELECT name, brand_color AS column_now,
       feature_flags ->> 'brand_color' AS flag_now,
       (brand_color IS DISTINCT FROM feature_flags ->> 'brand_color')
         AS will_change
  FROM public.businesses
 WHERE feature_flags ? 'brand_color'
 ORDER BY name;

-- 6d: the full before picture. SAVE THIS OUTPUT.
SELECT name, plan_tier, brand_color, jsonb_pretty(feature_flags)
  FROM public.businesses ORDER BY name;

-- 6e: MANDATORY, AND THE ONE TO ACTUALLY READ. Every rename whose
--     outcome is not self-evident.
WITH pairs(src, dst) AS (
  VALUES ('accounting_enabled','accounting'),
         ('calendar_booking_enabled','calendar_booking'),
         ('calendar','calendar_booking'),
         ('quoting_enabled','quoting'),
         ('whatsapp_enabled','whatsapp'),
         ('voice','aria_voice')
),
canonical(plan_tier, feature, enabled) AS (
  VALUES ('starter','quoting',true),('starter','accounting',true),
         ('starter','whatsapp',false),('starter','calendar_booking',false),
         ('starter','aria_voice',false),
         ('pro','quoting',true),('pro','accounting',true),
         ('pro','whatsapp',true),('pro','calendar_booking',true),
         ('pro','aria_voice',true),
         ('business','quoting',true),('business','accounting',true),
         ('business','whatsapp',true),('business','calendar_booking',true),
         ('business','aria_voice',true),
         ('beta','quoting',true),('beta','accounting',true),
         ('beta','whatsapp',true),('beta','calendar_booking',true),
         ('beta','aria_voice',true)
),
agg AS (
  SELECT b.id, b.name, b.plan_tier, p.dst,
         bool_or(coalesce((b.feature_flags ->> p.src)::boolean, false)) AS src_val,
         string_agg(p.src || '=' || (b.feature_flags ->> p.src), ', '
                    ORDER BY p.src) AS sources,
         (b.feature_flags ? p.dst) AS target_present,
         CASE WHEN b.feature_flags ? p.dst
              THEN (b.feature_flags ->> p.dst)::boolean END AS target_val
    FROM public.businesses b
    JOIN pairs p ON b.feature_flags ? p.src
   GROUP BY b.id, p.dst
)
SELECT a.name, a.plan_tier, a.dst AS canonical_key, a.sources,
       a.target_val, a.src_val, c.enabled AS plan_default,
       CASE
         WHEN a.target_present AND a.target_val IS DISTINCT FROM a.src_val
           THEN 'CONFLICT — target wins, source discarded'
         WHEN NOT a.target_present AND a.src_val IS DISTINCT FROM c.enabled
           THEN 'RESOLUTION CHANGES — ' || c.enabled::text
                || ' -> ' || a.src_val::text
       END AS effect
  FROM agg a
  LEFT JOIN canonical c ON c.plan_tier = a.plan_tier AND c.feature = a.dst
 WHERE (a.target_present AND a.target_val IS DISTINCT FROM a.src_val)
    OR (NOT a.target_present AND a.src_val IS DISTINCT FROM c.enabled)
 ORDER BY a.name, a.dst;
```

**EXPECT:**
- **6a:** `0 rows`.
- **6b:** `0 rows`.
- **6c:** two rows. New Body `column_now=#3B82F6`, `flag_now=#475569`,
  `will_change=true`. MSC both `#3B82F6`, `will_change=false`.
- **6d:** one row per business. **Save this.** It is what STEP 22 and the
  rollbacks are judged against, and it is where every EXPECT count in
  STEPS 15–18 comes from. Count the businesses; count how many carry at
  least one of `accounting_enabled`, `calendar_booking_enabled`,
  `calendar`, `quoting_enabled`, `whatsapp_enabled`, `voice`; count how
  many carry `brand_color`. Write those three numbers down.
- **6e:** **at least one row — Business Hero, `calendar_booking`,
  `CONFLICT — target wins, source discarded`.** Rows here are not a
  failure. Zero rows would mean every rename is a no-op on resolved
  access; any row means read it.

**STOP IF:**
- **6a returns a row.** A rename key holds a string or a number. The merge
  in STEP 17 would fail mid-statement. Resolve that key by hand first.
- **6b returns a row.** That value is **destroyed** rather than moved —
  6.1's guard leaves it in `feature_flags`, and it would then be the one
  key that never migrates. Decide what it should be first.
- **6c shows a disagreement you did not expect,** or MSC's
  `will_change=true`. R2 says the flag wins unconditionally and overwrites
  the column. Confirm you are happy with each overwrite before continuing;
  after STEP 16 the old column value is only in the backup table.
- **6d shows flags you have never seen before.** Read them. R3 protects
  unknown keys from deletion, but an unknown key you cannot explain is
  worth understanding before you start moving things around.
- **6e shows a `CONFLICT` row whose `target_val` is not the value you
  want kept.** R1 keeps the **target** — the canonical key, the one the
  admin panel writes and the deployed code reads — and discards the
  legacy source. For Business Hero that means `calendar_booking: false`
  survives and `calendar: true` is dropped, which is correct: the denial
  was made deliberately in the wizard and `calendar` never gated
  anything. If any row disagrees with that reading, **stop** — the fix is
  to correct the flag first, not to change the migration.
- **6e shows a `RESOLUTION CHANGES` row you did not expect.** That
  business's access genuinely changes when the rename lands. It is not a
  bug — it is the rename doing its job — but it is a customer's access
  and it should be a decision. Read every one before continuing.

---

## STEP 6 — Section 1: the `plan_tier` CHECK

`business` becomes storable. `elite` and `paused` stop being storable.

```sql
ALTER TABLE public.businesses
  DROP CONSTRAINT IF EXISTS businesses_plan_tier_check;

ALTER TABLE public.businesses
  ADD CONSTRAINT businesses_plan_tier_check
  CHECK (plan_tier IN ('starter','pro','business','beta'));
```

Then:

```sql
SELECT conname, pg_get_constraintdef(oid) AS def,
       (SELECT count(*) FROM public.businesses
         WHERE plan_tier NOT IN ('starter','pro','business','beta')) AS violating
  FROM pg_constraint
 WHERE conrelid='public.businesses'::regclass
   AND conname='businesses_plan_tier_check';
```

**EXPECT:** exactly one row. `def` reads
`CHECK ((plan_tier = ANY (ARRAY['starter'::text, 'pro'::text, 'business'::text, 'beta'::text])))`
with **no `elite` and no `paused`**, and `violating = 0`.

**STOP IF:** `elite` or `paused` still appears — the DROP did not match
the real constraint name. Find the actual name with
`SELECT conname FROM pg_constraint WHERE conrelid='public.businesses'::regclass;`
and report it. Do **not** invent a second constraint.

---

## STEP 7 — Section 1: prove the constraint bites

Both blocks are wrapped in `BEGIN … ROLLBACK` and cannot commit. Run them
one at a time.

```sql
-- 1c: this must FAIL.
BEGIN;
  UPDATE public.businesses SET plan_tier='paused'
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1);
ROLLBACK;
```

**EXPECT:** `ERROR: new row for relation "businesses" violates check
constraint "businesses_plan_tier_check"`. **The error is the pass.** Then
run the `ROLLBACK;` if the editor has not already aborted the transaction.

```sql
-- 1d: this must SUCCEED, then be discarded.
BEGIN;
  UPDATE public.businesses SET plan_tier='business'
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1)
   RETURNING id, name, plan_tier;
ROLLBACK;
```

**EXPECT:** one row, `plan_tier = business`. Then `ROLLBACK`.

> **This used to be an UPDATE followed by a separate SELECT, and it gave a
> false alarm on prod, 29 Aug 2026.** Both statements ended
> `WHERE id = (SELECT id FROM public.businesses LIMIT 1)` with no
> `ORDER BY`. Those are two independent evaluations, and an UPDATE writes
> a new tuple version at the end of the heap — so the second scan returned
> a *different* business, still on `starter`, and the check appeared to
> fail when it had passed. Reproduced on staging: with 3 rows both scans
> hit the same row and it "passed"; with 9 rows they diverged and it
> reported `starter`. `RETURNING` removes the second scan entirely and
> reports the row that was actually written. **Do not simplify this back
> to a separate SELECT.**

**STOP IF:** 1c **succeeds** (the constraint is not enforcing) or 1d
**fails** (the top tier is still unstorable, which was the live bug this
section exists to fix). Run `ROLLBACK 1` from the migration file.

**Make sure you actually ran the `ROLLBACK;`.** An open transaction here
holds a lock on `businesses` for the rest of the night.

---

## STEP 8 — Section 2: `plan_definitions` 'enterprise' → 'business'

```sql
UPDATE public.plan_definitions
   SET id = 'business',
       name = CASE WHEN name = 'Enterprise' THEN 'Business' ELSE name END,
       updated_at = now()
 WHERE id = 'enterprise'
   AND NOT EXISTS (SELECT 1 FROM public.plan_definitions WHERE id = 'business');
```

**EXPECT:** `UPDATE 1`.

Then:

```sql
SELECT (SELECT count(*) FROM public.plan_definitions WHERE id='enterprise') AS enterprise_rows,
       (SELECT count(*) FROM public.plan_definitions WHERE id='business')   AS business_rows,
       (SELECT count(*) FROM public.plan_definitions)                       AS total_rows,
       (SELECT count(*) FROM public.plan_definitions
         WHERE id NOT IN ('starter','pro','business','beta'))               AS non_canonical;

SELECT id, name, monthly_price_gbp, sort_order, is_active,
       features::text, limits::text
  FROM public.plan_definitions WHERE id='business';
```

**EXPECT:** `enterprise_rows = 0`, `business_rows = 1`, `total_rows = 3`
(unchanged from STEP 1), `non_canonical = 0`. The second query returns the
STEP 3 row with `id='business'`, `name='Business'`, and **every other
field byte-identical to what 2a showed.**

**STOP IF:**
- `UPDATE 0` — either the guard fired (a `business` row already existed;
  STEP 3 should have caught that) or there was no `enterprise` row.
- `total_rows` changed. A rename must not create or destroy a plan.
- `business_rows` is 2. There is no unique index to have stopped it. Run
  `ROLLBACK 2` immediately.
- `features` or `monthly_price_gbp` differs from 2a. This statement
  touches `id`, `name` and `updated_at` and nothing else; a change
  anywhere else means something else wrote to the table at the same time.
- `name` reads something other than `Business` — that is bespoke copy the
  equality guard deliberately preserved. **Report it, do not edit it
  here.** It is not a failure.

---

## STEP 9 — Section 3: create `usage_meters`

**Paste this whole block in one go.** The table comes into existence
already writable by the public `anon` key — `pg_default_acl` grants
`arwdDxtm` to `anon`, `authenticated` and `service_role` on every new
table in `public`. The REVOKEs are not undoing a grant of ours; they are
removing privileges Postgres attached at `CREATE TABLE`. **Do not walk
away in the middle of this block.**

```sql
CREATE TABLE IF NOT EXISTS public.usage_meters (
  id          uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid           NOT NULL
                             REFERENCES public.businesses(id) ON DELETE CASCADE,
  meter       text           NOT NULL,
  period      text           NOT NULL,
  value       numeric(14,4)  NOT NULL DEFAULT 0,
  created_at  timestamptz    NOT NULL DEFAULT now(),
  updated_at  timestamptz    NOT NULL DEFAULT now()
);

ALTER TABLE public.usage_meters
  DROP CONSTRAINT IF EXISTS usage_meters_period_chk;
ALTER TABLE public.usage_meters
  ADD CONSTRAINT usage_meters_period_chk
  CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$');

ALTER TABLE public.usage_meters
  DROP CONSTRAINT IF EXISTS usage_meters_meter_nonempty_chk;
ALTER TABLE public.usage_meters
  ADD CONSTRAINT usage_meters_meter_nonempty_chk
  CHECK (length(btrim(meter)) > 0);

ALTER TABLE public.usage_meters
  DROP CONSTRAINT IF EXISTS usage_meters_value_nonneg_chk;
ALTER TABLE public.usage_meters
  ADD CONSTRAINT usage_meters_value_nonneg_chk
  CHECK (value >= 0);

CREATE UNIQUE INDEX IF NOT EXISTS usage_meters_biz_meter_period_uq
  ON public.usage_meters USING btree (business_id, meter, period);

CREATE INDEX IF NOT EXISTS idx_usage_meters_biz_period
  ON public.usage_meters USING btree (business_id, period);

ALTER TABLE public.usage_meters ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS usage_meters_member_read ON public.usage_meters;
CREATE POLICY usage_meters_member_read
  ON public.usage_meters
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), usage_meters.business_id)
         OR public.is_platform_admin(auth.uid()));

REVOKE ALL ON public.usage_meters FROM anon;
REVOKE ALL ON public.usage_meters FROM authenticated;
GRANT SELECT ON public.usage_meters TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.usage_meters TO service_role;
```

**EXPECT:** `Success. No rows returned.`

**STOP IF:** it errors on `is_business_member` or `is_platform_admin` —
those helper functions must already exist on prod. Run
`SELECT proname FROM pg_proc WHERE proname IN ('is_business_member','is_platform_admin');`
If either is missing, `ROLLBACK 3` (`DROP TABLE public.usage_meters;`) and
stop — a table with no working policy and no grants is not dangerous, but
it is not finished either.

---

## STEP 10 — Section 3: verify the table is shut

```sql
SELECT 'columns' AS check, count(*)::text AS value
  FROM information_schema.columns
 WHERE table_schema='public' AND table_name='usage_meters'
UNION ALL SELECT 'value type',
       (SELECT numeric_precision || ',' || numeric_scale
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='usage_meters'
           AND column_name='value')
UNION ALL SELECT 'rls enabled',
       (SELECT relrowsecurity::text FROM pg_class
         WHERE oid='public.usage_meters'::regclass)
UNION ALL SELECT 'policies',
       (SELECT count(*)::text FROM pg_policies
         WHERE schemaname='public' AND tablename='usage_meters')
UNION ALL SELECT 'anon privileges',
       (SELECT count(*)::text FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='usage_meters'
           AND grantee='anon')
UNION ALL SELECT 'authenticated privileges',
       (SELECT string_agg(privilege_type, ',' ORDER BY privilege_type)
          FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='usage_meters'
           AND grantee='authenticated')
UNION ALL SELECT 'indexes',
       (SELECT count(*)::text FROM pg_indexes
         WHERE schemaname='public' AND tablename='usage_meters')
UNION ALL SELECT 'rows',
       (SELECT count(*)::text FROM public.usage_meters)
ORDER BY 1;
```

**EXPECT:**

| check | value |
|---|---|
| anon privileges | `0` |
| authenticated privileges | `SELECT` |
| columns | `7` |
| indexes | `3` |
| policies | `1` |
| rls enabled | `true` |
| rows | `0` |
| value type | `14,4` |

**STOP IF:** `anon privileges` is anything but **0**. That is the public
key in the browser bundle holding write access to the billing meter — any
customer could zero their own usage counter. Re-run the REVOKE block from
STEP 9 immediately and re-check before doing anything else.

Then prove the constraints bite. **Run these three separately** — the
first error would abort a shared transaction and make the other two look
like passes without testing anything. Each must FAIL:

```sql
BEGIN;
  INSERT INTO public.usage_meters (business_id, meter, period, value)
  SELECT id, 'probe', '2026-13', 1 FROM public.businesses LIMIT 1;
ROLLBACK;

BEGIN;
  INSERT INTO public.usage_meters (business_id, meter, period, value)
  SELECT id, '   ', '2026-08', 1 FROM public.businesses LIMIT 1;
ROLLBACK;

BEGIN;
  INSERT INTO public.usage_meters (business_id, meter, period, value)
  SELECT id, 'probe', '2026-08', -1 FROM public.businesses LIMIT 1;
ROLLBACK;
```

**EXPECT:** three errors naming `usage_meters_period_chk`,
`usage_meters_meter_nonempty_chk`, `usage_meters_value_nonneg_chk`.
**The errors are the pass.**

**STOP IF:** any of the three **succeeds**. The constraint is not there.
Re-run its `ALTER TABLE` pair from STEP 9.

---

## STEP 11 — Section 4: the two DECISION 2 columns

```sql
ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS metered_usage_enabled boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS monthly_spend_cap_gbp numeric(10,2);

ALTER TABLE public.businesses
  DROP CONSTRAINT IF EXISTS businesses_spend_cap_chk;

ALTER TABLE public.businesses
  ADD CONSTRAINT businesses_spend_cap_chk
  CHECK (
    (metered_usage_enabled = false)
    OR (monthly_spend_cap_gbp IS NOT NULL AND monthly_spend_cap_gbp > 0)
  ) NOT VALID;

ALTER TABLE public.businesses
  VALIDATE CONSTRAINT businesses_spend_cap_chk;
```

Then verify. This was three separate queries and the editor showed only
the third — it is now ONE statement returning ONE grid, so nothing can be
silently dropped:

```sql
SELECT 'businesses total' AS check,
       (SELECT count(*)::text FROM public.businesses) AS value
UNION ALL SELECT 'metered (must be 0)',
       (SELECT count(*) FILTER (WHERE metered_usage_enabled)::text FROM public.businesses)
UNION ALL SELECT 'capped (must be 0)',
       (SELECT count(*) FILTER (WHERE monthly_spend_cap_gbp IS NOT NULL)::text FROM public.businesses)
UNION ALL SELECT 'metered_usage_enabled column',
       (SELECT data_type || ' null=' || is_nullable
               || ' def=' || coalesce(column_default,'(none)')
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='businesses'
           AND column_name='metered_usage_enabled')
UNION ALL SELECT 'monthly_spend_cap_gbp column',
       (SELECT data_type || ' ' || numeric_precision || ',' || numeric_scale
               || ' null=' || is_nullable
               || ' def=' || coalesce(column_default,'(none)')
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='businesses'
           AND column_name='monthly_spend_cap_gbp')
UNION ALL SELECT 'spend cap constraint',
       (SELECT conname || '  convalidated=' || convalidated::text
          FROM pg_constraint WHERE conrelid='public.businesses'::regclass
           AND conname='businesses_spend_cap_chk')
ORDER BY 1;
```

**EXPECT:**

| check | value |
|---|---|
| businesses total | your STEP 1 count |
| capped (must be 0) | `0` |
| metered (must be 0) | **`0`** |
| metered_usage_enabled column | `boolean null=NO def=false` |
| monthly_spend_cap_gbp column | `numeric 10,2 null=YES def=(none)` |
| spend cap constraint | `businesses_spend_cap_chk  convalidated=true` |

**every existing business must be opted out.** Metered overage is opt-in;
defaulting it on would bill people who never agreed to be billed.

`def=(none)` is correct and deliberate. An explicit `DEFAULT NULL` was
NOT written: it is a no-op that records the string `NULL::numeric` in the
catalog, and a VERIFY that has to explain why its own expected value looks
like a mistake is a VERIFY nobody reads.

**STOP IF:** `metered` is not 0 (someone is about to be billed for
overage they did not choose), or `convalidated = false` (a `NOT VALID`
constraint is not enforced against existing rows and must not be left
that way — re-run the `VALIDATE CONSTRAINT` statement). Otherwise run
`ROLLBACK 4`.

---

## STEP 12 — Section 4: prove the paired CHECK bites

This constraint is the point of the section: it makes "metering on with no
cap" — the unbounded bill — unrepresentable.

**RUN THESE FOUR BLOCKS ONE AT A TIME.** Three of them are meant to raise
`CheckViolation`, and a failed statement aborts the rest of its
transaction — pasted together, the later blocks return `current
transaction is aborted` instead of being tested, which reads like the
error you wanted. All four are wrapped and cannot commit.

```sql
-- 4d: metering ON with no cap. Must FAIL.
BEGIN;
  UPDATE public.businesses SET metered_usage_enabled = true
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1);
ROLLBACK;

-- 4e: metering ON with a cap. Must SUCCEED.
BEGIN;
  UPDATE public.businesses
     SET metered_usage_enabled = true, monthly_spend_cap_gbp = 100.00
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1)
   RETURNING name, metered_usage_enabled, monthly_spend_cap_gbp;
ROLLBACK;

-- 4f: a zero cap. Must FAIL.
BEGIN;
  UPDATE public.businesses
     SET metered_usage_enabled = true, monthly_spend_cap_gbp = 0
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1);
ROLLBACK;

-- 4g: cap NULLed while metering is ON. Must FAIL.
-- BOTH statements must name the SAME row. Without ORDER BY the second
-- UPDATE can land on a different business — one whose metering is still
-- off, where a NULL cap is perfectly legal. That is a FALSE PASS: the
-- block reports no error and you conclude the constraint bites when it
-- was never tested. Same root cause as 1d, but silent instead of loud.
BEGIN;
  UPDATE public.businesses
     SET metered_usage_enabled = true, monthly_spend_cap_gbp = 100.00
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1);
  UPDATE public.businesses SET monthly_spend_cap_gbp = NULL
   WHERE id = (SELECT id FROM public.businesses ORDER BY id LIMIT 1);
ROLLBACK;
```

**EXPECT:** 4d, 4f and 4g each error with
`violates check constraint "businesses_spend_cap_chk"`. 4e returns one
row showing `true` and `100.00`. **Three errors and one row is the pass.**

Remember that in Postgres a failed statement poisons the rest of the
transaction — every following statement returns `current transaction is
aborted`. So in any of these blocks, **getting a result grid back at all
proves the statement before it did not raise.**

**STOP IF:** 4d succeeds. That is an account that can be metered with no
ceiling. Run `ROLLBACK 4` and stop — SECTION 4 without a working cap
constraint is worse than not shipping SECTION 4 at all, because the cap
then *looks* enforced.

---

## STEP 13 — Section 5: narrow the `businesses` UPDATE grant

**Read this before pasting.** `authenticated` holds a **table-level**
UPDATE on `businesses`, and a table-level grant covers every column
**including ones added later**. Grants are evaluated before RLS, and
`biz_update_if_owner` authorises the row, not the column. So as things
stand right now, after STEP 11, any business owner can do this from the
browser with the anon key that ships in the frontend bundle:

```js
await supabase.from('businesses')
  .update({ metered_usage_enabled: true, monthly_spend_cap_gbp: 999999 })
  .eq('id', myBusinessId)
```

That is the spend cap turning itself off. Postgres cannot revoke a subset
of a table-level grant, so the only way to narrow it is to drop it and
re-grant column by column.

**The 26 columns below are exactly the columns `authenticated` holds
UPDATE on today** (STEP 4 confirmed that). Nothing an owner can write
today stops being writable. The only change is that the two new columns
are absent.

**This is not 030b.** `plan_tier`, `is_active`, `feature_flags`, `api_key`
and `subscription_status` have no business being browser-writable either,
and they still are after this step. This section holds the line at "033
does not make things worse". Do not read it as the security fix being done.

```sql
REVOKE UPDATE ON public.businesses FROM authenticated;

GRANT UPDATE (
  id, name, timezone, api_key, created_at, logo_url, plan_tier, is_active,
  trial_ends_at, feature_flags, limits, stripe_customer_id,
  stripe_subscription_id, subscription_status, current_period_end,
  cancel_at_period_end, last_stripe_event_at, onboarding_completed,
  onboarding_completed_at, onboarded_by, brand_color, owner_whatsapp,
  ceo_briefing_enabled, region, tax_registered, tax_number
) ON public.businesses TO authenticated;
```

**EXPECT:** `Success. No rows returned.`

**STOP IF:** the GRANT errors naming a column that does not exist. STEP 4
should have caught that. Run `ROLLBACK 5` immediately —
`REVOKE UPDATE ON public.businesses FROM authenticated;` followed by
`GRANT UPDATE ON public.businesses TO authenticated;` — which restores the
table-level grant exactly, and stop. **Do not leave this half-done:**
between the REVOKE and a successful GRANT, owners cannot update their own
business at all.

---

## STEP 14 — Section 5: verify the narrowing

```sql
SELECT 'update columns' AS check,
       (SELECT count(*)::text FROM information_schema.column_privileges
         WHERE table_schema='public' AND table_name='businesses'
           AND grantee='authenticated' AND privilege_type='UPDATE') AS value
UNION ALL SELECT 'update on the two new columns',
       (SELECT count(*)::text FROM information_schema.column_privileges
         WHERE table_schema='public' AND table_name='businesses'
           AND grantee='authenticated' AND privilege_type='UPDATE'
           AND column_name IN ('metered_usage_enabled','monthly_spend_cap_gbp'))
UNION ALL SELECT 'select columns',
       (SELECT count(*)::text FROM information_schema.column_privileges
         WHERE table_schema='public' AND table_name='businesses'
           AND grantee='authenticated' AND privilege_type='SELECT')
UNION ALL SELECT 'insert columns',
       (SELECT count(*)::text FROM information_schema.column_privileges
         WHERE table_schema='public' AND table_name='businesses'
           AND grantee='authenticated' AND privilege_type='INSERT')
UNION ALL SELECT 'relacl',
       (SELECT string_agg(a, ' | ') FROM (
          SELECT unnest(relacl)::text AS a FROM pg_class
           WHERE oid='public.businesses'::regclass) t
        WHERE a LIKE 'authenticated%')
ORDER BY 1;
```

**EXPECT:**

| check | value |
|---|---|
| insert columns | `28` |
| relacl | `authenticated=ardDxtm/postgres` |
| select columns | `28` |
| update columns | `26` |
| update on the two new columns | **`0`** |

**`28` for SELECT and INSERT is correct, not a mistake.** Only UPDATE was
converted to a column list; SELECT and INSERT remain **table-level**, and
a table-level grant covers the two new columns too. That means:

- `authenticated` can still **SELECT** both new columns. Wanted — PART E
  requires usage and remaining allowance be visible to the customer
  *before* they hit the limit.
- `authenticated` can still name both columns in an **INSERT** of a new
  business row. `businesses_spend_cap_chk` still applies, so it cannot be
  metered without a positive cap, but the cap on a self-created row could
  be anything. That is the same business-creation hole 030b addresses at
  `AdminDashboard.tsx:380`. **Not made worse here, not fixed here.**

In `relacl`, the lowercase `w` (UPDATE) is gone; the lowercase `d` is
DELETE and stays, the uppercase `D` is TRUNCATE.

**STOP IF:** `update on the two new columns` is anything but 0 — the
section did not achieve its one purpose. Or `update columns` is not 26 —
a column was dropped from the list and some customer save is now broken.
Run `ROLLBACK 5` and re-read STEP 4's inventory.

Now prove it as the role itself. All wrapped:

```sql
-- 5e: must FAIL with "permission denied for table businesses"
BEGIN;
  SET LOCAL ROLE authenticated;
  UPDATE public.businesses SET monthly_spend_cap_gbp = 999999;
ROLLBACK;

-- 5e2: must FAIL the same way
BEGIN;
  SET LOCAL ROLE authenticated;
  UPDATE public.businesses SET metered_usage_enabled = true;
ROLLBACK;

-- 5f: must NOT raise permission denied. 0 rows updated is a PASS.
BEGIN;
  SET LOCAL ROLE authenticated;
  UPDATE public.businesses SET owner_whatsapp = owner_whatsapp;
ROLLBACK;

-- 5g: must NOT raise permission denied. 0 is a PASS.
BEGIN;
  SET LOCAL ROLE authenticated;
  SELECT count(*) FROM public.businesses WHERE monthly_spend_cap_gbp IS NULL;
ROLLBACK;
```

**EXPECT:** 5e and 5e2 error with `permission denied for table businesses`
— **the errors are the pass.** 5f reports `UPDATE 0` and 5g returns `0`,
neither raising an error. Both return zero because RLS filters on
`auth.uid()`, which is NULL outside a request. **Zero rows is a pass;
"permission denied" would be a fail.**

**STOP IF:** 5e succeeds — an owner can still raise their own cap, and
the cap is not a cap. Or 5f/5g raise `permission denied` — you have taken
away access that existed before. Run `ROLLBACK 5`.

---

## STEP 15 — Section 6.0: the backup table

Everything from here is reversible **only** through this table. The
transforms are not individually invertible: the OR-merge in STEP 17 loses
which source a `true` came from, and STEP 21 loses which flags were
explicit. A copy of the two columns is exact, costs 6 rows, and is the
only honest rollback available.

```sql
CREATE TABLE IF NOT EXISTS public.zz_033_flags_backup AS
  SELECT id, name, plan_tier, brand_color, feature_flags, now() AS captured_at
    FROM public.businesses;

REVOKE ALL ON public.zz_033_flags_backup FROM anon;
REVOKE ALL ON public.zz_033_flags_backup FROM authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.zz_033_flags_backup TO service_role;
```

The REVOKEs are not optional and the hazard is not theoretical:
`CREATE TABLE AS` inherits `pg_default_acl`, and running exactly this
`CREATE TABLE AS` on staging on 29 Aug 2026 (inside a transaction that was
rolled back) produced **14 grant rows for `anon` and `authenticated`** on
a table holding every business's entitlement state, before any REVOKE ran.

`CREATE TABLE **IF NOT EXISTS**` is not a style choice. The first draft
used `DROP TABLE IF EXISTS` + `CREATE TABLE AS`; the staging rehearsal
caught what that does — re-pasting SECTION 6 after it has already run
re-snapshots the backup **from the already-migrated state**, while the
transforms correctly report `UPDATE 0` so nothing looks wrong, and the
only route back is silently gone. To deliberately re-baseline, drop the
table by hand first. That is the point: it should take a deliberate act.

Then:

```sql
SELECT 'backed up' AS check, (SELECT count(*) FROM public.zz_033_flags_backup)::text AS value
UNION ALL SELECT 'businesses', (SELECT count(*) FROM public.businesses)::text
UNION ALL SELECT 'old keys in backup',
       (SELECT count(*)::text FROM public.zz_033_flags_backup z,
               LATERAL jsonb_object_keys(z.feature_flags) AS k(key)
         WHERE k.key IN ('accounting_enabled','calendar_booking_enabled',
                         'calendar','quoting_enabled','whatsapp_enabled','voice',
                         'brand_color'))
UNION ALL SELECT 'anon or authenticated grants',
       (SELECT count(*)::text FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='zz_033_flags_backup'
           AND grantee IN ('anon','authenticated'))
ORDER BY 1;
```

**EXPECT:** `backed up` = `businesses` = your STEP 1 count.
`old keys in backup` = the total number of legacy keys STEP 5's 6d
showed, **greater than zero** (it was 11 on the 25 Aug data; Business
Hero's `calendar` adds to it). `anon or authenticated grants = 0`.

**STOP IF:**
- **`anon or authenticated grants` is not 0.** `CREATE TABLE AS` inherits
  `pg_default_acl`, so this table — which holds every business's
  entitlement state — would be readable by the public anon key. Re-run
  the REVOKEs.
- **`old keys in backup = 0` on a first run.** The backup captured nothing
  useful. Stop.
- **`old keys in backup = 0` on a RE-run.** The backup was clobbered by an
  older copy of the migration file. **STOP, and do not run ROLLBACK 6 or
  7** — they would write the migrated state back over itself.
- `backed up` ≠ `businesses`. Rows were added between the two counts.

---

## STEP 16 — Section 6.1: `brand_color` moves to its column

R2: **the flag wins unconditionally.** It is what the UI reads, so it is
the true value. New Body's `#475569` overwrites the column's `#3B82F6`.

Both statements are guarded by the same hex predicate as pre-flight 6b, so
a malformed value is left in `feature_flags` rather than written to the
column and then deleted.

```sql
UPDATE public.businesses
   SET brand_color = feature_flags ->> 'brand_color'
 WHERE feature_flags ? 'brand_color'
   AND jsonb_typeof(feature_flags -> 'brand_color') = 'string'
   AND feature_flags ->> 'brand_color' ~ '^#[0-9A-Fa-f]{6}$'
   AND brand_color IS DISTINCT FROM feature_flags ->> 'brand_color';

UPDATE public.businesses
   SET feature_flags = feature_flags - 'brand_color'
 WHERE feature_flags ? 'brand_color'
   AND jsonb_typeof(feature_flags -> 'brand_color') = 'string'
   AND feature_flags ->> 'brand_color' ~ '^#[0-9A-Fa-f]{6}$'
   AND brand_color = feature_flags ->> 'brand_color';
```

**EXPECT:** the first `UPDATE` count = the number of `will_change=true`
rows in STEP 5's 6c; the second = the number of businesses 6c listed at
all. (On the 25 Aug data: `UPDATE 1` then `UPDATE 2` — only New Body's
column disagreed, but both businesses lose the key.)

Then:

```sql
SELECT name, brand_color,
       feature_flags ? 'brand_color' AS still_has_flag
  FROM public.businesses ORDER BY name;
```

**EXPECT:** one row per business, `still_has_flag = false` on **every**
one. MSC `#3B82F6`. **New Body `#475569`.** Test 1–4 `#3B82F6`.

**STOP IF:** any row still has the flag — that is a value that failed the
hex guard and was correctly left behind. Identify it and decide what it
should be; it will not migrate on its own. Or if New Body's column is
still `#3B82F6`, the first UPDATE did not fire and the branding the
customer chose has just been dropped. Run `ROLLBACK 6`.

---

## STEP 17 — Section 6.2: the six renames. **The target wins.**

One statement driven by an explicit pair list, so the pair list is the
thing under review and there is no sixth near-identical UPDATE to get
subtly wrong.

**Read this before pasting — the rule changed on 29 Aug 2026.** It used
to merge source and target with a boolean OR, on the reasoning that "a
rename must never take access away". That is wrong whenever the target
holds a **deliberate denial**, and prod contains exactly that case:
Business Hero holds `calendar: true` **and** `calendar_booking: false`.
Measured on staging 29 Aug 2026, the OR rule turned
`{"calendar": true, "calendar_booking": false}` into
`{"calendar_booking": true}` — silently **granting** a feature an admin
had deliberately switched off. The same thing happened to a probe holding
`accounting_enabled: true` with `accounting: false`. Any source/target
disagreement flipped a denial into a grant.

The rule is now: **a rename FILLS IN a canonical key that is absent; it
never overwrites one that is present.** `calendar_booking: false` is
written by the wizard through `setFeatureFlag`, in the canonical
vocabulary, and it is what the deployed resolver reads. `calendar` is a
legacy alias that gates nothing and the resolver cannot see. The
canonical key wins.

Where the target is **absent** and several sources map to it, they are
still OR'd — `calendar_booking` has two sources, and OR is associative, so
the order cannot change the result.

`merged` is driven off "holds any source key" rather than off `fill`, and
coalesces to `'{}'`. That matters: a business whose only source has a
**present** target contributes no fill row, and if the UPDATE were driven
off `fill` that business would drop out entirely and its source key would
survive — failing STEP 18's first check. Sources are removed either way.

```sql
WITH pairs(src, dst) AS (
  VALUES ('accounting_enabled',       'accounting'),
         ('calendar_booking_enabled', 'calendar_booking'),
         ('calendar',                 'calendar_booking'),
         ('quoting_enabled',          'quoting'),
         ('whatsapp_enabled',         'whatsapp'),
         ('voice',                    'aria_voice')
),
fill AS (
  -- one row per (business, canonical key) where the key is ABSENT and at
  -- least one of its sources is present. A present target yields no row.
  SELECT b.id, p.dst,
         bool_or(coalesce((b.feature_flags ->> p.src)::boolean, false)) AS val
    FROM public.businesses b
    JOIN pairs p ON b.feature_flags ? p.src
   WHERE NOT (b.feature_flags ? p.dst)
   GROUP BY b.id, p.dst
),
merged AS (
  SELECT b.id,
         coalesce((SELECT jsonb_object_agg(f.dst, f.val)
                     FROM fill f WHERE f.id = b.id), '{}'::jsonb) AS newkeys
    FROM public.businesses b
   WHERE EXISTS (SELECT 1 FROM pairs p WHERE b.feature_flags ? p.src)
)
UPDATE public.businesses b
   SET feature_flags =
         (b.feature_flags - ARRAY['accounting_enabled',
                                  'calendar_booking_enabled',
                                  'calendar',
                                  'quoting_enabled',
                                  'whatsapp_enabled',
                                  'voice'])
         || m.newkeys
  FROM merged m
 WHERE m.id = b.id;
```

**EXPECT:** the row count you wrote down at STEP 5 — the number of
businesses carrying at least one of `accounting_enabled`,
`calendar_booking_enabled`, `calendar`, `quoting_enabled`,
`whatsapp_enabled`, `voice`. On the 25 Aug data that was 2 (MSC and New
Body); with Business Hero it is at least 3.

**STOP IF:** the count is lower than that number. A business holding a
source key was not touched, and STEP 18's first check will show its
source surviving.

---

## STEP 18 — Verify the renames, and stop here if you are stopping

```sql
SELECT 'surviving source keys' AS check,
       (SELECT count(*)::text FROM public.businesses b,
               LATERAL jsonb_object_keys(b.feature_flags) AS k(key)
         WHERE k.key IN ('accounting_enabled','calendar_booking_enabled',
                         'calendar','quoting_enabled','whatsapp_enabled','voice')) AS value
UNION ALL SELECT 'filled target turned false',
       (SELECT count(*)::text
          FROM public.businesses b
          JOIN public.zz_033_flags_backup z ON z.id = b.id,
               LATERAL (VALUES ('accounting_enabled','accounting'),
                               ('calendar_booking_enabled','calendar_booking'),
                               ('calendar','calendar_booking'),
                               ('quoting_enabled','quoting'),
                               ('whatsapp_enabled','whatsapp'),
                               ('voice','aria_voice')) x(src,dst)
         WHERE coalesce((z.feature_flags ->> x.src)::boolean, false)
           AND NOT (z.feature_flags ? x.dst)
           AND NOT coalesce((b.feature_flags ->> x.dst)::boolean, false))
UNION ALL SELECT 'present canonical keys altered',
       (SELECT count(*)::text
          FROM public.zz_033_flags_backup z
          JOIN public.businesses b ON b.id = z.id,
               LATERAL jsonb_object_keys(z.feature_flags) AS k(key)
         WHERE k.key IN ('quoting','invoicing','accounting','email','aria_chat',
                         'aria_voice','whatsapp','board_meetings',
                         'calendar_booking','calendar_sync','receptionist','outreach')
           AND b.feature_flags -> k.key IS DISTINCT FROM z.feature_flags -> k.key)
ORDER BY 1;
```

**EXPECT:** all three `0`.

**Note the third predicate on `filled target turned false`** —
`AND NOT (z.feature_flags ? x.dst)`. It excludes sources whose target was
already present, because target-wins discards those deliberately. Without
it, Business Hero's dropped `calendar: true` reports as a failure and
sends you into a rollback you do not want.

**`present canonical keys altered` is the check that matters here**, and
it is new. It asserts that every canonical key already in `feature_flags`
still holds the same value — which is exactly what the OR rule violated.
Verified on staging 29 Aug 2026: run against the OLD OR merge it returns
the two wrongly-granted keys; run against the merge in STEP 17 it returns
0. **VERIFY 7b cannot do this job** — 7b only looks for features that
*lost* access, and the OR bug wrongly *granted* one.

**STOP IF:** any is non-zero. Run `ROLLBACK 6`.
- `surviving source keys` — a legacy key was not removed.
- `filled target turned false` — a rename that should have granted did not.
- `present canonical keys altered` — **a deliberate flag was overwritten.**

> ### ⚠ RUN THIS CHECK **HERE** AND NEVER AGAIN
>
> `filled target turned false` is only valid **before** SECTION 7. Section 7
> deliberately removes the very keys it looks for, so running it
> afterwards returns a row per removed key — every one a false alarm. On
> the staging rehearsal that was eight false alarms. A check that cries
> wolf is worse than no check, especially sharing a file with the one
> check that actually matters.

Then take the checkpoint picture:

```sql
SELECT name, plan_tier, brand_color, jsonb_pretty(feature_flags)
  FROM public.businesses ORDER BY name;
```

**EXPECT:** every business now carries **canonical key names only**. No
`_enabled` suffixes, no `calendar`, no `voice`, no `brand_color`. On the
25 Aug shape: MSC and New Body hold `accounting`, `calendar_booking`,
`quoting`, `whatsapp`, `email`, `receptionist`, and MSC also `aria_chat`
and `aria_voice`; Test 1–4 still `{"receptionist": false}`.
**Business Hero must still show `"calendar_booking": false`** — that is
the denial surviving, and it is the single most important line in this
output.

**Save this output.** It is PART TWO's starting point.

---

### ✅ PART ONE IS COMPLETE AND SELF-CONSISTENT

Sections 1–6 are applied. Nobody's resolved access has changed under
either set of plan defaults — that is what makes this half safe to leave
overnight, or for a week.

**You may stop here.** If you do, leave `zz_033_flags_backup` in place.

---

# PART TWO — SECTION 7

---

## STEP 19 — Stop and read. This is the destructive half.

SECTION 7 removes every `feature_flags` key whose value **equals the plan
default for that business's tier**, so that `feature_flags` holds only
deliberate exceptions and `plan_tier` is the source of truth.

That phrase — "equals the plan default" — has two possible answers, and
they disagree completely:

| | what `pro` grants | effect of SECTION 7 on MSC |
|---|---|---|
| **(a) the OLD deployed table** | `{"email": true}` and nothing else | keeps almost every flag; MSC never reaches `{}` |
| **(b) the canonical PART B table** | ten features | `accounting`, `quoting`, `whatsapp`, `calendar_booking`, `receptionist`, `email` all removed |

**SECTION 7 implements (b).** Under (b), removing a key is harmless: the
plan grants the feature anyway, so resolved access is identical.

**Under (a), removing those same keys is an outage.** The flag was the
only thing granting the feature; delete it and the old default resolves to
`false`. Measured on staging, 25 Aug 2026, against six fixtures seeded row
for row from the exact prod values: **twelve feature losses across the two
live businesses.**

- **MSC (7)** — `accounting`, `aria_chat`, `aria_voice`,
  `calendar_booking`, `quoting`, `receptionist`, `whatsapp`
- **New Body (5)** — `accounting`, `calendar_booking`, `quoting`,
  `receptionist`, `whatsapp`

No error is raised anywhere. Nothing logs. Two paying customers simply
find features missing.

*(The migration file's older comment said EIGHT. That figure came from an
earlier run against reconstructed fixtures and is superseded — see
`033-STAGING-REHEARSAL.md` D1. The real number is worse, not better.)*

**Against the canonical defaults, the same operation produces zero losses.**
The entire difference is which Python dict is deployed.

### Why it is safe now

The canonical table shipped. `backend/auth.py` holds
`PLAN_FEATURE_DEFAULTS` as the single copy in Python, `backend/main.py`
imports it rather than declaring its own, and
`backend/tests/test_entitlement_defaults.py` parses the two copies that
cannot be deduplicated — `frontend/client/src/lib/entitlements.ts` and
SECTION 7's own `plan_defaults` CTE — and fails the build if any of the
three drift. Commit `776604c`.

**That is why the gate exists and not why it can be skipped.** The
constant being in `main` is not the same as it being in the process
answering requests. **STEP 20 checks the deployment, not the repository.**

### One more reason to run it now rather than later

The strip cannot tell a stale merged default from a goodwill grant — both
are just `true` in a JSON column. So a business carrying legacy flags
keeps them through a downgrade: drop MSC from `pro` to `starter` today and
its flags still say `receptionist: true`, so it keeps a feature it no
longer pays for.

SECTION 7 strips against the **current** tier. Both live businesses are
`pro` right now, which is exactly when the strip reduces them to `{}` and
makes later downgrades work. Run it while that is still true.

---

## STEP 20 — THE GATE. Do not skip, do not do from memory.

**Four checks. All four must pass before STEP 21.**

### 20a — the backend actually running is at `776604c` or later

Railway → the Business Hero service → **Deployments**. Read the commit on
the **active** deployment (the one marked live, not the newest build).

**EXPECT:** `776604c` — *"Canonical plan defaults in backend, strip on
both creation paths, wizard exceptions dict"* — or a later commit on
`main`.

**STOP IF:** it is `2a1a026` or earlier, or the newest deploy failed and
an older one is still serving. **Do not continue.** Deploy first, wait for
the healthcheck to go green, then come back. This is the whole gate.

### 20b — the frontend actually served is canonical too

The admin panel resolves features through `entitlements.ts` in the browser
bundle, and it is what you will read the results on. Vercel → the project
→ **Deployments** → the deployment aliased to production.

**EXPECT:** the same commit `776604c` or later.

Then confirm it behaviourally, which costs nothing and proves the bundle
rather than the dashboard. Open the admin panel for **one of the four
`starter` test businesses** — whose `feature_flags` is
`{"receptionist": false}` and nothing else:

**EXPECT:** Quoting, Invoicing, Accounting, Email and Aria Chat all show
**ON**; Receptionist shows **OFF**.

**STOP IF:** they all show OFF. That is the old table, which gave
`starter` `{}` — every feature denied. The bundle is stale. Hard-refresh
first; if it persists, the deploy did not land.

### 20c — VERIFY 7b in its DEPLOYED form, run before the change

This is the migration file's own stated gate: the deployed-defaults form
of VERIFY 7b must return 0 rows **before** you continue. Run it now,
against the pre-SECTION-7 state, so that you know it is 0 for the right
reason:

```sql
WITH deployed(plan_tier, feature, enabled) AS (
  -- the OLD table, verbatim: pro = {"email": true}, starter = {}
  VALUES ('pro','email',true)
),
canonical(plan_tier, feature, enabled) AS (
  VALUES ('pro','quoting',true),('pro','invoicing',true),
         ('pro','accounting',true),('pro','email',true),
         ('pro','aria_chat',true),('pro','aria_voice',true),
         ('pro','whatsapp',true),('pro','board_meetings',true),
         ('pro','calendar_booking',true),('pro','calendar_sync',true),
         ('pro','receptionist',true),('pro','outreach',false),
         ('starter','quoting',true),('starter','invoicing',true),
         ('starter','accounting',true),('starter','email',true),
         ('starter','aria_chat',true),('starter','aria_voice',false),
         ('starter','whatsapp',false),('starter','board_meetings',false),
         ('starter','calendar_booking',false),('starter','calendar_sync',true),
         ('starter','receptionist',false),('starter','outreach',false)
),
features AS (SELECT DISTINCT feature FROM canonical),
resolved AS (
  SELECT b.name, f.feature,
         coalesce(
           CASE WHEN b.feature_flags ? f.feature
                THEN (b.feature_flags ->> f.feature)::boolean END,
           (SELECT d.enabled FROM deployed d
             WHERE d.plan_tier = b.plan_tier AND d.feature = f.feature),
           false) AS under_old_code,
         coalesce(
           CASE WHEN b.feature_flags ? f.feature
                THEN (b.feature_flags ->> f.feature)::boolean END,
           (SELECT c.enabled FROM canonical c
             WHERE c.plan_tier = b.plan_tier AND c.feature = f.feature),
           false) AS under_canonical
    FROM public.businesses b CROSS JOIN features f
)
SELECT name, feature, under_old_code, under_canonical
  FROM resolved
 WHERE under_old_code AND NOT under_canonical
 ORDER BY name, feature;
```

**EXPECT:** `0 rows`. This says the canonical table grants everything the
old one did — deploying it took nothing away. It is the deploy you have
already done, checked after the fact.

**STOP IF:** any row comes back. The canonical table denies something the
old code granted, and that customer lost it at deploy time, not at
migration time. Stop and report the rows; SECTION 7 is not the problem
and running it will not help.

**All three green? Continue. Any one of them not green? Stop.**

---

### 20d — the DEPLOYED backend resolves entitlement, it does not read it

**This check did not exist when the gate was written, and 20a-20c do not
cover it.** They prove the canonical *table* is deployed. They say nothing
about how the running code *asks* it.

The distinction is the whole of PART D. Under PART C a missing key means
"follow the plan". Code that resolves — `auth._is_feature_enabled`,
`entitlements.isFeatureEnabled` — reads a stripped `pro` business as fully
entitled. Code that does `flags.get("receptionist", False)` reads the same
row as denied. Same column, same business, opposite answer. Five readers
were doing the latter, so STEP 21 would have broken them **even with 20a,
20b and 20c all green**.

What it would have looked like, so it is recognisable if the gate is ever
skipped:

| reader | what STEP 21 does to it, pre-PART D |
|---|---|
| receptionist settings (9 endpoints) | 403 for MSC and New Body. Including `PATCH /config/toggle` — **the phone keeps answering and the owner cannot switch it off**, because the Twilio webhook gates on `receptionist_configs.enabled`, a different column, and never checks entitlement |
| onboarding wizard step-skip | marks `receptionist_setup` and `accounting_setup` COMPLETE and moves on. **No error.** `accounting` is true on every tier, so this one hits every business, not just these two |
| admin receptionist overview | `receptionist_enabled: false` for a business that has it |
| admin email chip | reads "Off" for every business — `email` is true on every tier |

**EXPECT:** the active Railway deployment is `57f184a` — *"ENTITLEMENT-SPEC
PART D — the readers resolve, they no longer read raw"* — or later, and
Vercel likewise. Same place you looked in 20a and 20b.

**STOP IF** it is `776604c`..`fc88a7a`. That range has the canonical table
and the raw readers together, which is the exact combination this step
exists to catch.

Then prove it behaviourally on a business that is already stripped, which
is what STEP 21 is about to create. Use one of the four `starter` test
businesses and give it a goodwill grant — admin panel → Receptionist →
**Enable Feature**:

**EXPECT:** `feature_flags` gains `{"receptionist": true}` (a grant against
a denying plan is a real exception, so it is stored), the button flips to
**Disable Feature**, and the receptionist settings load rather than 403.

Now press **Disable Feature**:

**EXPECT:** `feature_flags` goes back to `{}` — **not** to
`{"receptionist": false}`. Storing the plan default is the bug PART D
fixed on this endpoint, and it is the loop that was quietly undoing
SECTION 7: strip the key, admin sees "Enable", admin presses it, key comes
back.

**STOP IF** you land on `{"receptionist": false}`. The deployed backend is
not stripping on this path and STEP 21's work will be reversed by hand the
first time anyone touches that button.

## STEP 21 — Section 7: the strip

A key is removed **only** when it is in the canonical vocabulary **AND**
holds a boolean **AND** that boolean equals the plan default for this
business's tier. Everything else survives, which is R3 falling out for
free — an unknown key never joins `plan_defaults`, so it can never be
removed. An explicit `false` against a default of `true` is a deliberate
**denial** and is likewise never removed: it does not equal its default.

`calendar_sync` appears in the table below and is `true` on every tier. It
gates nothing — Google issues Gmail and Calendar under one consent — and
no business carries the key, so it is a **no-op on current prod data**.

```sql
WITH plan_defaults(plan_tier, feature, enabled) AS (
  VALUES
    ('starter','quoting',true),  ('starter','invoicing',true),
    ('starter','accounting',true),('starter','email',true),
    ('starter','aria_chat',true), ('starter','aria_voice',false),
    ('starter','whatsapp',false), ('starter','board_meetings',false),
    ('starter','calendar_booking',false),('starter','calendar_sync',true),
    ('starter','receptionist',false),
    ('starter','outreach',false),

    ('pro','quoting',true),   ('pro','invoicing',true),
    ('pro','accounting',true),('pro','email',true),
    ('pro','aria_chat',true), ('pro','aria_voice',true),
    ('pro','whatsapp',true),  ('pro','board_meetings',true),
    ('pro','calendar_booking',true),('pro','calendar_sync',true),
    ('pro','receptionist',true),
    ('pro','outreach',false),

    ('business','quoting',true),   ('business','invoicing',true),
    ('business','accounting',true),('business','email',true),
    ('business','aria_chat',true), ('business','aria_voice',true),
    ('business','whatsapp',true),  ('business','board_meetings',true),
    ('business','calendar_booking',true),('business','calendar_sync',true),
    ('business','receptionist',true),
    ('business','outreach',true),

    ('beta','quoting',true),   ('beta','invoicing',true),
    ('beta','accounting',true),('beta','email',true),
    ('beta','aria_chat',true), ('beta','aria_voice',true),
    ('beta','whatsapp',true),  ('beta','board_meetings',true),
    ('beta','calendar_booking',true),('beta','calendar_sync',true),
    ('beta','receptionist',true),
    ('beta','outreach',true)
),
redundant AS (
  SELECT b.id,
         coalesce(array_agg(k.key), ARRAY[]::text[]) AS drop_keys
    FROM public.businesses b
    JOIN LATERAL jsonb_object_keys(b.feature_flags) AS k(key) ON true
    JOIN plan_defaults d
      ON d.plan_tier = b.plan_tier
     AND d.feature   = k.key
   WHERE jsonb_typeof(b.feature_flags -> k.key) = 'boolean'
     AND d.enabled = (b.feature_flags ->> k.key)::boolean
   GROUP BY b.id
)
UPDATE public.businesses b
   SET feature_flags = b.feature_flags - r.drop_keys
  FROM redundant r
 WHERE r.id = b.id
   AND array_length(r.drop_keys, 1) > 0;
```

**EXPECT:** `UPDATE` = the number of businesses holding at least one
canonical boolean equal to its tier default. On the 25 Aug data that was
all 6 — the two `pro` businesses, and all four `starter` ones, whose
`receptionist: false` equals starter's canonical default. Business Hero
is also updated (its `email: true` equals the `pro` default) but does
**not** reach `{}`: `calendar_booking: false` contradicts the `pro`
default of `true` and is therefore a deliberate denial that survives.

**STOP IF:** `UPDATE 0`. Either SECTION 7 has already run, or the tiers do
not match the CTE. Do not re-paste; check `plan_tier` first.

---

## STEP 22 — VERIFY 7b. **The one that matters.**

Per business, per canonical feature: what resolved to enabled **before**
(from the backup, through the defaults the code used at the time) versus
what resolves to enabled **now**. Anything that was enabled and is no
longer enabled is a regression.

Run it in **both** forms. They differ only in which default table the
"before" side uses, and both must return 0 rows.

**What 7b does NOT check:** it looks only for features that *lost* access
(`was_enabled AND NOT is_enabled`). A feature wrongly **granted** passes
7b silently. That is not hypothetical — it is exactly what the old OR
merge did to Business Hero's `calendar_booking`, and 7b would have waved
it through. The check for that is STEP 18's `present canonical keys
altered`, which must have been 0 before you got here.

### 22a — before through the CANONICAL defaults (the strict form)

This is the true comparison now that the canonical table is deployed. It
asserts SECTION 7 changed **nothing** about resolved access.

```sql
WITH canonical(plan_tier, feature, enabled) AS (
  VALUES ('pro','quoting',true),('pro','invoicing',true),
         ('pro','accounting',true),('pro','email',true),
         ('pro','aria_chat',true),('pro','aria_voice',true),
         ('pro','whatsapp',true),('pro','board_meetings',true),
         ('pro','calendar_booking',true),('pro','calendar_sync',true),
         ('pro','receptionist',true),('pro','outreach',false),
         ('starter','quoting',true),('starter','invoicing',true),
         ('starter','accounting',true),('starter','email',true),
         ('starter','aria_chat',true),('starter','aria_voice',false),
         ('starter','whatsapp',false),('starter','board_meetings',false),
         ('starter','calendar_booking',false),('starter','calendar_sync',true),
         ('starter','receptionist',false),('starter','outreach',false)
),
renames(src, dst) AS (
  VALUES ('accounting_enabled','accounting'),
         ('calendar_booking_enabled','calendar_booking'),
         ('calendar','calendar_booking'),
         ('quoting_enabled','quoting'),
         ('whatsapp_enabled','whatsapp'),
         ('voice','aria_voice')
),
features AS (SELECT DISTINCT feature FROM canonical),
before AS (
  SELECT z.id, z.name, f.feature,
         coalesce(
           (SELECT bool_or(coalesce((z.feature_flags ->> x.k)::boolean,false))
              FROM (SELECT f.feature AS k
                    UNION SELECT r.src FROM renames r WHERE r.dst = f.feature) x
             WHERE z.feature_flags ? x.k),
           (SELECT c.enabled FROM canonical c
             WHERE c.plan_tier = z.plan_tier AND c.feature = f.feature),
           false) AS was_enabled
    FROM public.zz_033_flags_backup z CROSS JOIN features f
),
after AS (
  SELECT b.id, f.feature,
         coalesce(
           CASE WHEN b.feature_flags ? f.feature
                THEN (b.feature_flags ->> f.feature)::boolean END,
           (SELECT c.enabled FROM canonical c
             WHERE c.plan_tier = b.plan_tier AND c.feature = f.feature),
           false) AS is_enabled
    FROM public.businesses b CROSS JOIN features f
)
SELECT before.name, before.feature, before.was_enabled, after.is_enabled
  FROM before JOIN after
    ON after.id = before.id AND after.feature = before.feature
 WHERE before.was_enabled AND NOT after.is_enabled
 ORDER BY before.name, before.feature;
```

**EXPECT:** `0 rows`.

**STOP IF:** anything comes back. **A customer has lost access.** Run
`ROLLBACK 7` immediately:

```sql
UPDATE public.businesses b
   SET feature_flags = z.feature_flags,
       brand_color   = z.brand_color
  FROM public.zz_033_flags_backup z
 WHERE z.id = b.id;
```

then confirm you are whole:

```sql
SELECT b.name FROM public.businesses b
  JOIN public.zz_033_flags_backup z ON z.id = b.id
 WHERE b.feature_flags IS DISTINCT FROM z.feature_flags
    OR b.brand_color   IS DISTINCT FROM z.brand_color;
```

**EXPECT after rollback:** `0 rows`.

### 22b — before through the OLD DEPLOYED defaults (the historical form)

The migration file's original VERIFY 7b. It answers a different question:
"would this have been safe against the code that was running before the
deploy?" It should also be 0 — which is what confirms the ordering was
respected rather than merely lucky.

Take 22a's query and replace the `before` CTE's fallback subquery — the
`(SELECT c.enabled FROM canonical c …)` inside `before` **only** — with:

```sql
           (SELECT d.enabled FROM (VALUES ('pro','email',true))
                              AS d(plan_tier, feature, enabled)
             WHERE d.plan_tier = z.plan_tier AND d.feature = f.feature),
```

Leave the `after` CTE on `canonical`. Run it.

**EXPECT:** `0 rows`.

**STOP IF:** it returns rows while 22a returned none. That means the strip
is only safe because of the deploy — which is true and expected — but if
22a passed and 22b did not, **do not roll back on 22b alone.** Resolved
access today is correct; 22b failing is a statement about a code version
that is no longer running. Record the rows and move on. Roll back only on
**22a**.

---

## STEP 23 — VERIFY 7c and 7d: read what survived

**Two queries. RUN THEM SEPARATELY** — pasted together you see only 7d,
and 7c is the list you are required to read.

```sql
-- 7c: every surviving key that is NOT in the canonical vocabulary.
-- Not a pass/fail — a list you must read and confirm.
SELECT b.name, k.key, b.feature_flags -> k.key AS value
  FROM public.businesses b,
       LATERAL jsonb_object_keys(b.feature_flags) AS k(key)
 WHERE k.key NOT IN ('quoting','invoicing','accounting','email',
                     'aria_chat','aria_voice','whatsapp',
                     'board_meetings','calendar_booking','calendar_sync',
                     'receptionist','outreach')
 ORDER BY b.name, k.key;

-- 7d: the end state.
SELECT name, plan_tier, brand_color, jsonb_pretty(feature_flags)
  FROM public.businesses ORDER BY name;
```

**EXPECT:**
- **7c:** `0 rows`, on the values recorded 25 Aug 2026. If prod has since
  acquired an `industry` key from the admin panel, it will show here —
  **that is correct and it must survive.** `industry` is read at
  `backend/quoting_api.py:1151` to build the AI quoting prompt; deleting
  it would silently downgrade every AI quote to the `general` fallback,
  and nothing would error.
- **7d:** every business at `{}` **except** those STEP 5's 6e flagged as
  genuine exceptions. On current prod that means MSC, New Body and
  Test 1–4 at `{}`, and **Business Hero at `{"calendar_booking": false}`**
  — the denial, correctly preserved all the way through. Colours: MSC
  `#3B82F6`, New Body `#475569`, Test 1–4 `#3B82F6`.

**STOP IF:** 7c lists a key you cannot account for — read it before you
walk away, but do not delete it. R3 exists because ignoring an unknown key
and deleting one are not the same operation. Or if 7d shows a business
that is **not** `{}` — that is a surviving exception, so check it is one
you meant: a genuine `false` against a granting plan, or a `true` against
a denying one.

---

## STEP 24 — Final state check

```sql
SELECT 'plan_tier CHECK has business' AS check,
       (SELECT (pg_get_constraintdef(oid) LIKE '%business%')::text
          FROM pg_constraint WHERE conrelid='public.businesses'::regclass
           AND conname='businesses_plan_tier_check') AS value
UNION ALL SELECT 'plan_tier CHECK has paused',
       (SELECT (pg_get_constraintdef(oid) LIKE '%paused%')::text
          FROM pg_constraint WHERE conrelid='public.businesses'::regclass
           AND conname='businesses_plan_tier_check')
UNION ALL SELECT 'plan_definitions enterprise rows',
       (SELECT count(*)::text FROM public.plan_definitions WHERE id='enterprise')
UNION ALL SELECT 'usage_meters RLS',
       (SELECT relrowsecurity::text FROM pg_class
         WHERE oid='public.usage_meters'::regclass)
UNION ALL SELECT 'usage_meters anon privileges',
       (SELECT count(*)::text FROM information_schema.role_table_grants
         WHERE table_schema='public' AND table_name='usage_meters' AND grantee='anon')
UNION ALL SELECT 'businesses metered',
       (SELECT count(*) FILTER (WHERE metered_usage_enabled)::text FROM public.businesses)
UNION ALL SELECT 'spend cap UPDATE grants',
       (SELECT count(*)::text FROM information_schema.column_privileges
         WHERE table_schema='public' AND table_name='businesses'
           AND grantee='authenticated' AND privilege_type='UPDATE'
           AND column_name IN ('metered_usage_enabled','monthly_spend_cap_gbp'))
UNION ALL SELECT 'businesses with non-empty flags',
       (SELECT count(*)::text FROM public.businesses WHERE feature_flags <> '{}'::jsonb)
UNION ALL SELECT 'Business Hero calendar_booking',
       (SELECT coalesce(feature_flags ->> 'calendar_booking','(absent)')
          FROM public.businesses WHERE name ILIKE 'Business Hero%')
UNION ALL SELECT 'brand_color flag survivors',
       (SELECT count(*)::text FROM public.businesses WHERE feature_flags ? 'brand_color')
UNION ALL SELECT 'New Body brand_color',
       (SELECT brand_color FROM public.businesses WHERE name ILIKE 'New Body%')
ORDER BY 1;
```

**EXPECT:**

| check | value |
|---|---|
| Business Hero calendar_booking | **`false`** |
| brand_color flag survivors | `0` |
| businesses metered | `0` |
| businesses with non-empty flags | the number of genuine exceptions from STEP 5's 6e — `1` on current prod |
| New Body brand_color | `#475569` |
| plan_definitions enterprise rows | `0` |
| plan_tier CHECK has business | `true` |
| plan_tier CHECK has paused | `false` |
| spend cap UPDATE grants | `0` |
| usage_meters RLS | `true` |
| usage_meters anon privileges | `0` |

**STOP IF:** any row differs. Note which, and do not consider 033 applied
until it is resolved.

---

## STEP 24b — Regenerate the schema guard's source of truth

**Do this after EVERY migration, not just 033.** It takes one paste.

`audits/live-schema-public.txt` is what `backend/tests/test_schema_conformance.py`
compares the shipped SQL against. The guard exists because
`admin_business_api` wrote `businesses.updated_at` — a column that has never
existed — on two endpoints, and both returned 500 on every request from
030b Release 1 until it was caught. `create_all()` creates tables but never
columns, migration files are not evidence of live state, and the unit fakes
accept any column name on a write. Nothing else looks at this.

A stale dump is a guard that passes for the wrong reason. **033 SECTION 4
makes it stale**: it adds `businesses.metered_usage_enabled` and
`businesses.monthly_spend_cap_gbp`, so as of STEP 24 this file is out of date.

Run `scripts/dump-live-schema.sql` in the SQL editor — **confirm the project
selector reads `oxblcmwhuwtobdhsfgyi` first**. It is a read against
`information_schema`; it touches no data and is safe to run at any time.

**DO NOT BUILD THE FILE WITH `grep`.** The Supabase editor exports CSV, and
CSV quotes any field containing a comma — which is every `numeric(p,s)` and
`character varying(n)` row. `grep "^col "` therefore drops them silently. On
the 2026-09-03 dump that was 111 of 816 rows, including
`businesses.monthly_spend_cap_gbp` and `usage_meters.value`, and it reads
exactly like a partially-applied migration. Parse it as CSV:

```
cd ~/Documents/business-hero-2 && python3 - <<'EOF'
import csv, pathlib
src = pathlib.Path.home()/"Downloads"/"<the downloaded file>.csv"
dst = pathlib.Path("audits/live-schema-public.txt")
rows = [r[0] for r in csv.reader(src.open(newline="")) if r and r[0].startswith("col   ")]
head = dst.read_text().split("col   ")[0]          # keep the header block
dst.write_text(head + "\n".join(rows) + "\n")
print(len(rows), "columns")
EOF
```

Keep the header block, set `coverage: FULL`, and set `UNGUARDED_BUDGET = 0`
in `backend/tests/test_schema_conformance.py`. Update `EXPECTED_COVERED` if
the backend has started writing a table it did not write before.

```
./check.sh
```

**EXPECT:** green, and `test_full_coverage_leaves_nothing_unguarded` RUNS
rather than skips. If `test_every_written_column_exists_in_the_live_schema`
fails, read the named file and line before assuming the dump is wrong — but
if it fails in the dozens, suspect the dump. A truncated source produces mass
failures, not silence, which is the intended behaviour.

**STOP IF:** the parse reports fewer than ~700 columns or ~50 tables. The
2026-09-03 baseline was 816 columns across 59 tables. A table count alone is
not enough of a check — the CSV-quoting drop above loses columns while
leaving all 59 tables present.

---

## STEP 25 — Browser smoke test

Log in as a **normal customer** (Multi Skilled Contractors), not a
platform admin.

1. The app loads and the sidebar shows the same features it did yesterday
2. Quoting opens and an existing quote renders with unchanged totals
3. Invoices list loads
4. Aria chat responds
5. Branding shows **MSC's colour unchanged**
6. Email inbox loads — this is the only endpoint with a server-side
   `require_feature` gate on it (`app/email/router.py:64`, on `email`)

Then as **New Body**:

7. Branding shows **`#475569`**, not the default blue

Then as **platform admin**:

8. Admin → a `starter` test business → its feature toggles read
   Quoting/Invoicing/Accounting/Email/Aria Chat ON, Receptionist OFF,
   with `feature_flags` now empty
9. The business detail chips read **"Calendar Booking: On"** for MSC

Then as **Business Hero**:

10. Calendar booking is still **off**, exactly as it was before tonight

**EXPECT:** nothing visibly changes for any of them. That is the whole
point of this migration — the plan now says what the flags used to say,
and the one deliberate denial is still a denial.

**STOP IF:** step 1, 2 or 6 shows a feature missing for MSC. Run
`ROLLBACK 7` (STEP 22), then re-read STEP 20 — the gate did not hold.
Step 5 or 7 wrong is a branding regression: `ROLLBACK 6`.

Two things this migration **cannot** have broken, worth knowing so you do
not chase them:

- **Executive board meetings** are gated by
  `backend/services/tier_gating.py`, which reads `plan_tier` directly and
  never touches `feature_flags`. SECTION 7 cannot affect them.
- **Calendar booking** is gated by `booking_settings.enabled`, not by the
  `calendar_booking` flag alone and not by any OAuth grant.

---

## STEP 26 — Clean up (NOT tonight)

`zz_033_flags_backup` is **deliberately left in place**. It is the only
route back. Drop it only once the change has been confirmed live for a few
days, and knowing that dropping it removes that route:

```sql
DROP TABLE IF EXISTS public.zz_033_flags_backup;
```

---

## If you need to undo everything

Run the `ROLLBACK` blocks in `033_entitlement.sql` in **reverse order**:
**7 → 6 → 5 → 4 → 3 → 2 → 1**. That exact sequence was executed on
staging and returned the database to its pre-033 state with zero
unexplained diff lines.

Three caveats:

1. **ROLLBACK 7 and ROLLBACK 6 are the same statement** — a copy-back
   from `zz_033_flags_backup`. There is no inverse transform, because the
   merge lost which source a filled-in `true` came from (and which
   discarded sources were dropped under target-wins), and the strip lost
   which flags were explicit. Running it once undoes both sections. It is
   safe to run repeatedly.
2. **ROLLBACK 3 is `DROP TABLE usage_meters` and it destroys data.** It
   is lossless only while the table is empty. Once the application starts
   writing meters, that data is **billing evidence**. Capture it first:
   `CREATE TABLE public.zz_033_meters_rescue AS SELECT * FROM public.usage_meters;`
3. **Run ROLLBACK 5 before ROLLBACK 4.** ROLLBACK 5 restores the
   table-level grant without naming columns, so the order is not strictly
   forced, but 5-then-4 keeps the grant state consistent at every
   intermediate step.

`updated_at` on the renamed `plan_definitions` row cannot be restored to
its pre-migration value. It is a modification timestamp and this was a
modification. Everything else round-trips exactly.

---

## STEP 27 — Record it

```
cd ~/Documents/business-hero-2 && mv ~/Downloads/033-prod-before.csv audits/
```

Then have Claude Code append to `audits/FINDINGS.md`: date applied, which
steps ran, the STEP 3 `plan_definitions` answer (did 025 run on prod or
not — it settles M3 permanently), the STEP 24 final-state values, the
STEP 23 7c key list, smoke test results, and anything skipped or that did
not match EXPECT.

Then update `CLAUDE.md`'s **Current task** section: 033 applied, and the
next item is the invoice PDF.

**What this unblocks:** `plan_tier` is now genuinely the source of truth,
`feature_flags` holds only exceptions, and `usage_meters` exists for
metered billing. Stripe plan enforcement can now be written against one
vocabulary instead of five.
