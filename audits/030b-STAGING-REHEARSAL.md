# 030b RELEASE 2 — STAGING REHEARSAL RECORD

**Migration:** `backend/migrations/030b_release2_revoke.sql`
**Target rehearsed:** business-hero-staging (`gzcrsrqmygublveuzqyg`)
**Date:** 18 Sep 2026
**Prod (`oxblcmwhuwtobdhsfgyi`) was not touched.** The rehearsal script
refuses any URL that does not contain the staging ref, and `.env.staging`
holds `STAGING_DB_URL` and nothing else.

Before-snapshot: `audits/030b-staging-before.txt`

## What was rehearsed

Section 1 applied → VERIFY 1a–1d → `ROLLBACK 1` → before-snapshot compared
field for field (grants, column grants, **policy expressions**) → re-applied
→ applied twice more (idempotent). Section 2 applied → verified → applied
twice more → `ROLLBACK 2`. Then a full undo (`ROLLBACK 1`) compared against
the before-snapshot again. Finally Section 1 re-applied and **left applied**;
Section 2 **left rolled back** — the instructed scope (INSERT + UPDATE), so
staging now models prod-after-Release-2 exactly as instructed. If Section 2
is ruled in, apply it to staging first (one statement, rehearsed, rollback
proven below).

Every check passed. Result of every step follows, verbatim from the run.

## Two things the rehearsal established that the spec did not say

1. **`authenticated`'s UPDATE on `businesses` is column-level, not
   table-level.** 033 SECTION 5 replaced the table grant with a 26-column
   list. `docs/CURRENT_STATE.md` §8 still says "table-wide". The hole is the
   same size — the list contains `plan_tier`, `is_active`, `feature_flags`,
   `limits`, `subscription_status` — but the ROLLBACK must restore the
   26-column list, not a table grant, and it does. STEP 0 STOP IF covers
   the case where prod differs.
2. **`REVOKE UPDATE ON table` does clear the column grants.** Postgres
   documents it; VERIFY 1b checks `column_privileges` directly anyway and
   returned zero rows every time.

## The run

```
030b RELEASE 2 — STAGING REHEARSAL 2026-09-18T20:26:50.640250 UTC
target: ('postgres', '2a05:d018:a0:6000:335:8640:4823:1dd3') project gzcrsrqmygublveuzqyg

[STEP 0 0a BEFORE]
   anon | SELECT, TRIGGER
   authenticated | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE
   postgres | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
   service_role | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE

[STEP 0 0b BEFORE]
   anon | SELECT | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at
   authenticated | INSERT | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at
   authenticated | REFERENCES | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at
   authenticated | SELECT | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at
   authenticated | UPDATE | 26 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at

[STEP 0 0c BEFORE]
   Platform admins can manage all businesses | * | True | (EXISTS ( SELECT 1
   FROM platform_admins
  WHERE (platform_admins.user_id = auth.uid()))) | 
   biz_select_if_member | r | True | (EXISTS ( SELECT 1
   FROM business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))) | 
   biz_update_if_owner | w | True | (EXISTS ( SELECT 1
   FROM business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.role = 'owner'::text) AND (bm.is_active = true)))) | (EXISTS ( SELECT 1
   FROM business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.role = 'owner'::text) AND (bm.is_active = true))))
  PASS  0a authenticated has no table-level UPDATE  DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE
  PASS  0b authenticated UPDATE on exactly 26 columns  26
  PASS  0b no UPDATE on the two 033 columns  
  PASS  0c exactly three policies incl. biz_update_if_owner  

[STEP 1]
   postgres | 3 | 0
  PASS  STEP 2 table owner is postgres  postgres
  PASS  STEP 4 UPDATE permitted before the change (UPDATE 0, no error)  ('ok', 0)

=== SECTION 1 apply

[S1 apply 1a]
   anon | SELECT, TRIGGER
   authenticated | DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE

[S1 apply 1b]

[S1 apply 1c]
   Platform admins can manage all businesses | *
   biz_select_if_member | r
  PASS  S1 apply 1a anon SELECT, TRIGGER  
  PASS  S1 apply 1a authenticated no INSERT/UPDATE  DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE
  PASS  S1 apply 1b zero column grants  []
  PASS  S1 apply 1c two policies, owner policy gone  
  PASS  S1 apply 1d denied: UPDATE public.businesses SET plan_tier = 'bus  permission denied for table businesses
  PASS  S1 apply 1d denied: UPDATE public.businesses SET feature_flags =   permission denied for table businesses
  PASS  S1 apply 1d denied: INSERT INTO public.businesses (name, api_key)  permission denied for table businesses
  PASS  S1 apply 1d-4 SELECT still permitted, returns 0  ('ok', [(0,)])

=== ROLLBACK 1
  PASS  S1 rollback 0a restored exactly  
   now=[('anon', 'SELECT, TRIGGER'), ('authenticated', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE'), ('postgres', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE'), ('service_role', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE')]
   was=[('anon', 'SELECT, TRIGGER'), ('authenticated', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE'), ('postgres', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE'), ('service_role', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE')]
  PASS  S1 rollback 0b restored exactly  
  PASS  S1 rollback 0c restored exactly (policy expressions identical)  
  PASS  S1 rollback UPDATE permitted again  ('ok', 0)

=== SECTION 1 re-apply

[S1 re-apply 1a]
   anon | SELECT, TRIGGER
   authenticated | DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE

[S1 re-apply 1b]

[S1 re-apply 1c]
   Platform admins can manage all businesses | *
   biz_select_if_member | r
  PASS  S1 re-apply 1a anon SELECT, TRIGGER  
  PASS  S1 re-apply 1a authenticated no INSERT/UPDATE  DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE
  PASS  S1 re-apply 1b zero column grants  []
  PASS  S1 re-apply 1c two policies, owner policy gone  
  PASS  S1 re-apply 1d denied: UPDATE public.businesses SET plan_tier = 'bus  permission denied for table businesses
  PASS  S1 re-apply 1d denied: UPDATE public.businesses SET feature_flags =   permission denied for table businesses
  PASS  S1 re-apply 1d denied: INSERT INTO public.businesses (name, api_key)  permission denied for table businesses
  PASS  S1 re-apply 1d-4 SELECT still permitted, returns 0  ('ok', [(0,)])

=== SECTION 1 idempotency x2

[S1 idem 1a]
   anon | SELECT, TRIGGER
   authenticated | DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE

[S1 idem 1b]

[S1 idem 1c]
   Platform admins can manage all businesses | *
   biz_select_if_member | r
  PASS  S1 idem 1a anon SELECT, TRIGGER  
  PASS  S1 idem 1a authenticated no INSERT/UPDATE  DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE
  PASS  S1 idem 1b zero column grants  []
  PASS  S1 idem 1c two policies, owner policy gone  
  PASS  S1 idem 1d denied: UPDATE public.businesses SET plan_tier = 'bus  permission denied for table businesses
  PASS  S1 idem 1d denied: UPDATE public.businesses SET feature_flags =   permission denied for table businesses
  PASS  S1 idem 1d denied: INSERT INTO public.businesses (name, api_key)  permission denied for table businesses
  PASS  S1 idem 1d-4 SELECT still permitted, returns 0  ('ok', [(0,)])

=== SECTION 2 apply

[S2 1a]
   anon | SELECT, TRIGGER
   authenticated | SELECT, TRIGGER
  PASS  S2 authenticated SELECT, TRIGGER only  SELECT, TRIGGER
  PASS  S2 DELETE denied  ('denied', 'permission denied for table businesses')
  PASS  S2 SELECT still ok  ('ok', [(0,)])

=== SECTION 2 idempotency x2
  PASS  S2 idem  

=== ROLLBACK 2

[R2 1a]
   anon | SELECT, TRIGGER
   authenticated | DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE
  PASS  R2 authenticated back to DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE  DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE

=== FULL UNDO: ROLLBACK 1 (Section 2 already rolled back)
  PASS  full undo 0a restored exactly  
   now=[('anon', 'SELECT, TRIGGER'), ('authenticated', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE'), ('postgres', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE'), ('service_role', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE')]
   was=[('anon', 'SELECT, TRIGGER'), ('authenticated', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE'), ('postgres', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE'), ('service_role', 'DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE')]
  PASS  full undo 0b restored exactly  
  PASS  full undo 0c restored exactly (policy expressions identical)  
  PASS  full undo UPDATE permitted again  ('ok', 0)

=== FINAL: leave staging with SECTION 1 APPLIED, SECTION 2 NOT (the instructed scope)

[final 1a]
   anon | SELECT, TRIGGER
   authenticated | DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE

[final 1b]

[final 1c]
   Platform admins can manage all businesses | *
   biz_select_if_member | r
  PASS  final 1a anon SELECT, TRIGGER  
  PASS  final 1a authenticated no INSERT/UPDATE  DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE
  PASS  final 1b zero column grants  []
  PASS  final 1c two policies, owner policy gone  
  PASS  final 1d denied: UPDATE public.businesses SET plan_tier = 'bus  permission denied for table businesses
  PASS  final 1d denied: UPDATE public.businesses SET feature_flags =   permission denied for table businesses
  PASS  final 1d denied: INSERT INTO public.businesses (name, api_key)  permission denied for table businesses
  PASS  final 1d-4 SELECT still permitted, returns 0  ('ok', [(0,)])

[FINAL 0a]
   anon | SELECT, TRIGGER
   authenticated | DELETE, REFERENCES, SELECT, TRIGGER, TRUNCATE
   postgres | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE
   service_role | DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE

[FINAL 0b]
   anon | SELECT | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at
   authenticated | REFERENCES | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at
   authenticated | SELECT | 28 | api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at, current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits, logo_url, metered_usage_enabled, monthly_spend_cap_gbp, name, onboarded_by, onboarding_completed, onboarding_completed_at, owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id, subscription_status, tax_number, tax_registered, timezone, trial_ends_at

[FINAL 0c]
   Platform admins can manage all businesses | * | True | (EXISTS ( SELECT 1
   FROM platform_admins
  WHERE (platform_admins.user_id = auth.uid()))) | 
   biz_select_if_member | r | True | (EXISTS ( SELECT 1
   FROM business_members bm
  WHERE ((bm.business_id = businesses.id) AND (bm.user_id = auth.uid()) AND (bm.is_active = true)))) | 

REHEARSAL COMPLETE
```

## Addendum, 19 Sep 2026 — after Codex review 1

Codex asked for the post-apply role check to cover all five entitlement
columns, and for the live pre-checks (0d/0e/0f). Staging is in the
final state above (Section 1 applied). Run verbatim:

```
0d (post-apply): (0, 0, 0, 28) -> PASS (0 | 0 | 0 | 28; pre-state on the local replay is 26 | 28 | 0 | 28)
0e: [] -> PASS (0 rows)
0f: [] -> PASS (0 rows)
1d is_active: permission denied for table businesses -> PASS
1d "limits": permission denied for table businesses -> PASS
1d subscription_status: permission denied for table businesses -> PASS
```
