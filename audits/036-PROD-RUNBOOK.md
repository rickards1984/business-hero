# 036 — PRODUCTION RUNBOOK: chase_replies (replies to invoice chases)

**For:** Mike. **Ticket:** AUTO-2. **Migration:** `backend/migrations/036_chase_replies.sql`.

**Rehearsed:** `audits/036-STAGING-REHEARSAL.md` (19 Oct 2026). On staging it
was applied, verified, rolled back to the before-state, and re-applied.

**Risk:** RED, as all production SQL is. Low in practice:
- one new, empty table;
- nothing existing is changed;
- the public (anon) role gets no access, and signed-in users can only read
  their own business's rows.

Takes about 10 minutes.

**Run every step ONE AT A TIME in the Supabase SQL editor.** Check the EXPECT
before moving on. If anything matches STOP IF, stop and send me the output.

**Before you start:** the AUTO-2 code is NOT deployed yet and must not be.
This migration goes first; the code follows once STEP 3 is done.

---

## STEP 0 — Confirm the project, and capture the before-state (READ-ONLY)

In the project selector, confirm it reads **business-hero (`oxblcmwhuwtobdhsfgyi`)**, not staging. Then:

```sql
SELECT current_database(),
       (SELECT count(*) FROM public.businesses)       AS businesses,
       (SELECT count(*) FROM public.business_members) AS members,
       to_regclass('public.chase_replies') IS NOT NULL AS already_there,
       (SELECT count(*) FROM pg_proc
         WHERE proname IN ('is_business_member', 'is_platform_admin')
           AND pronamespace = 'public'::regnamespace)   AS policy_functions,
       (SELECT string_agg(conrelid::regclass::text || ':' || conname, ', ' ORDER BY 1)
          FROM pg_constraint
         WHERE contype IN ('p', 'u')
           AND conrelid IN ('public.email_messages'::regclass,
                            'public.email_accounts'::regclass,
                            'public.email_outbox'::regclass))  AS email_keys;
```

**EXPECT:**
- `postgres`;
- businesses and members as before (8 and 5 at 035), or more;
- `already_there` = **false**;
- `policy_functions` = **2**;
- `email_keys` lists whatever keys the email tables have. 036 doesn't need
  them; the column is there so that 037 (outreach) knows. On staging they
  have none.

**STOP IF:**
- members is 0 (that is staging);
- `already_there` is true;
- `policy_functions` is not 2.

Send me the row either way. It is the before-snapshot.

---

## STEP 1 — Apply SECTION 1

Paste **only** this. It is SECTION 1, copied exactly from the migration file:
the table, three CHECKs, two indexes, RLS, one read policy and the grants.

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS public.chase_replies (
  id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid         NOT NULL
                                REFERENCES public.businesses(id) ON DELETE CASCADE,
  email_message_id uuid,
  customer_email   text         NOT NULL,
  invoice_ids      jsonb        NOT NULL DEFAULT '[]'::jsonb,
  category         text         NOT NULL,
  summary          text,
  status           text         NOT NULL DEFAULT 'open',
  resolved_by      uuid,
  resolved_at      timestamptz,
  created_at       timestamptz  NOT NULL DEFAULT now(),
  updated_at       timestamptz  NOT NULL DEFAULT now()
);

ALTER TABLE public.chase_replies
  DROP CONSTRAINT IF EXISTS chase_replies_status_chk;
ALTER TABLE public.chase_replies
  ADD CONSTRAINT chase_replies_status_chk
  CHECK (status IN ('open', 'resumed', 'stopped'));

ALTER TABLE public.chase_replies
  DROP CONSTRAINT IF EXISTS chase_replies_category_chk;
ALTER TABLE public.chase_replies
  ADD CONSTRAINT chase_replies_category_chk
  CHECK (category IN ('paid', 'promise', 'dispute', 'question', 'other', 'unknown'));

ALTER TABLE public.chase_replies
  DROP CONSTRAINT IF EXISTS chase_replies_invoice_ids_chk;
ALTER TABLE public.chase_replies
  ADD CONSTRAINT chase_replies_invoice_ids_chk
  CHECK (jsonb_typeof(invoice_ids) = 'array');

-- One reply per business per message (a scan twice flags it once).
CREATE UNIQUE INDEX IF NOT EXISTS chase_replies_biz_message_uq
  ON public.chase_replies USING btree (business_id, email_message_id);

-- "This business's replies awaiting the owner" and the autopilot's check.
CREATE INDEX IF NOT EXISTS idx_chase_replies_biz_status
  ON public.chase_replies USING btree (business_id, status, created_at DESC);

ALTER TABLE public.chase_replies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chase_replies_member_read ON public.chase_replies;
CREATE POLICY chase_replies_member_read
  ON public.chase_replies
  AS PERMISSIVE FOR SELECT TO authenticated
  USING (public.is_business_member(auth.uid(), chase_replies.business_id)
         OR public.is_platform_admin(auth.uid()));

REVOKE ALL ON public.chase_replies FROM anon;
REVOKE ALL ON public.chase_replies FROM authenticated;
GRANT SELECT ON public.chase_replies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.chase_replies TO service_role;

COMMIT;
```

**STOP IF:** any error. Nothing will have changed, because it is one
transaction. Send me the error.

---

## STEP 2 — VERIFY (READ-ONLY)

```sql
SELECT
  (SELECT count(*) FROM information_schema.columns
    WHERE table_schema='public' AND table_name='chase_replies')             AS columns,
  (SELECT relrowsecurity FROM pg_class
    WHERE oid='public.chase_replies'::regclass)                             AS rls_on,
  (SELECT count(*) FROM pg_policies
    WHERE schemaname='public' AND tablename='chase_replies')                AS policies,
  (SELECT count(*) FROM information_schema.role_table_grants
    WHERE table_schema='public' AND table_name='chase_replies'
      AND grantee='anon')                                                   AS anon_privileges,
  (SELECT string_agg(privilege_type, ',' ORDER BY privilege_type)
     FROM information_schema.role_table_grants
    WHERE table_schema='public' AND table_name='chase_replies'
      AND grantee='authenticated')                                          AS authenticated_privileges,
  (SELECT count(*) FROM public.chase_replies)                               AS rows;
```

**EXPECT:**
- `columns` **12**;
- `rls_on` **true**;
- `policies` **1**;
- `anon_privileges` **0**;
- `authenticated_privileges` **SELECT**;
- `rows` **0**.

**STOP IF:** anything differs, and above all if `anon_privileges` is not 0 or
`authenticated_privileges` is anything other than `SELECT`. In that case run
STEP 4 and send me the output.

---

## STEP 3 — Regenerate the schema dump (READ-ONLY)

This is what lets the AUTO-2 code pass its safety check.

1. Confirm the project selector still reads `oxblcmwhuwtobdhsfgyi`.
2. **Set the SQL editor's row limit to "No limit"**, then run the whole of
   `scripts/dump-live-schema.sql`.
3. **Download → CSV**, and drag the file into the repo folder as you did for 035.

It should hold about **844 rows**: the previous 832 plus the 12 new columns.
If it holds 100, the limit was on.

---

## STEP 4 — ROLLBACK (only if STEP 2 failed)

```sql
BEGIN;
DROP TABLE IF EXISTS public.chase_replies;
COMMIT;
```

Then re-run STEP 0's query: `already_there` should be **false**. On staging
this restored the before-state exactly.

---

## Afterwards

Send me STEP 0's row and STEP 2's row, and drag in the CSV. I will then:
1. regenerate `audits/live-schema-public.txt`;
2. record the run here;
3. push AUTO-2 and open its pull request.
