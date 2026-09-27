# BH-001 Q4b — RC1 P0-3 is CONFIRMED OPEN

**Run:** 27 Sep 2026, Supabase SQL editor, project `oxblcmwhuwtobdhsfgyi`,
read-only. Raw output committed verbatim as
`audits/BH-001-prod-Q4b-businesses-column-grants-2026-09-27.csv`.

This closes the one question `BH-001-FINDINGS.md` §3 could not answer, because
the Q4 export of 24 Sep was truncated at 100 rows and never reached
`businesses`.

## The result

| privilege_type | columns | table-level or column-list? |
|---|---|---|
| INSERT | 28 | table-level (reported once per column) |
| REFERENCES | 28 | table-level |
| SELECT | 28 | table-level |
| **UPDATE** | **26** | **a column list — and these are the 26** |

```
api_key, brand_color, cancel_at_period_end, ceo_briefing_enabled, created_at,
current_period_end, feature_flags, id, is_active, last_stripe_event_at, limits,
logo_url, name, onboarded_by, onboarding_completed, onboarding_completed_at,
owner_whatsapp, plan_tier, region, stripe_customer_id, stripe_subscription_id,
subscription_status, tax_number, tax_registered, timezone, trial_ends_at
```

## Three checks, run rather than eyeballed

1. **Internal consistency.** Each row's `columns` count equals the length of
   its own `cols` list. All four rows OK.
2. **Against the migration.** The 26 columns were parsed out of
   `backend/migrations/033_entitlement.sql` SECTION 5's `GRANT UPDATE (…)`
   clause and compared as sets and in order: **identical, with nothing in prod
   that 033 does not declare and nothing declared that prod lacks.** So
   SECTION 5 landed exactly as its runbook records.
3. **Against the local replay.** `scripts/rls-local.sh`'s migration replay
   returns the same four privilege types with the same column lists —
   **identical on all four.** One more point of prod/replay agreement, on
   grants this time rather than policies (FINDINGS §2.1 covered policies only).

**033 SECTION 5 achieved its own purpose.** `metered_usage_enabled` and
`monthly_spend_cap_gbp` are absent from the UPDATE list, so an owner cannot
raise their own spend cap. They *are* in the INSERT list, which is correct and
expected: INSERT was never converted to a column list, and a table-level grant
covers columns added later. That is the gap `030b` Release 2 closes by revoking
INSERT as well.

## P0-3: what a business owner can write from the browser

Grants are evaluated before RLS, and `biz_update_if_owner` authorises the ROW
for an owner. So with the anon key that ships in the frontend bundle:

| Column | Consequence |
|---|---|
| `plan_tier` | **Set your own tier.** The paywall. |
| `feature_flags` | Grant yourself any individual feature. |
| `limits` | Raise your own usage limits. |
| `is_active` | Undo an admin suspension. |
| `subscription_status` | **Make an unpaid account look paid** — and after BH-006 this is the column the access resolver reads, so writing `active` here restores full access without paying. |
| `api_key` | **Set your own API key to a chosen value.** `get_current_business` accepts `api_key` as bearer auth (`auth.py`), so this is writing an authentication credential. `030b` PART D moved *generation* server-side; the grant still permits a direct write, and only the revoke closes it. |

```js
// Reachable today, as any owner, with the public anon key:
await supabase.from('businesses')
  .update({ plan_tier: 'business', subscription_status: 'active' })
  .eq('id', myBusinessId)
```

**RC1 P0-3 is confirmed open with production evidence**, not inferred from
migration files. `backend/tests/test_tenant_isolation_rls_path.py`'s four
`xfail(strict=True)` tests (BH-003, PR #9) encode exactly this, and
`audits/030b-PROD-RUNBOOK.md` is what closes it.

## What this does NOT establish

- **Effective privileges.** `information_schema.column_privileges` shows grants
  to `authenticated` directly. A grant to `PUBLIC`, or one inherited through
  role membership, would not appear here and **would survive a revoke aimed at
  `authenticated`**. That is STEP 0's `0d`, which uses
  `has_column_privilege`.
- **Other routes to the same columns:** a client-callable SECURITY DEFINER
  function, or a writable view over `businesses`. Neither is reached by
  revoking a grant. STEP 0's `0e` and `0f`.
- **Who revoked what, and when.** Q4b is a snapshot. It happens to agree with
  033's record, which is the reassuring case.

## Consequence for the runbook

`audits/030b-PROD-RUNBOOK.md` STEP 0 now has **both** its grant expectations
pre-confirmed against production: `0a` by Q6 on 24 Sep (no table-level UPDATE)
and `0b` by this query (the 26-column list, exactly). Neither `STOP IF` fires.
`0c` (the three policies) was confirmed by Q2 on 24 Sep. **Nothing in STEP 0
blocks Release 2.** STEP 0 should still be RUN on the night — it is the
before-snapshot the rollback depends on, and it is read-only.
