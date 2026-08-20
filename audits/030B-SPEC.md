# 030b — Move admin business writes to the backend

RED tier. Tests written and reviewed before implementation, same discipline as
the money engine.

**Acceptance criteria only. No implementation detail.**

Evidence gathered read-only against prod and `origin/main`, 20 Aug 2026. Every
file:line below was verified at that commit.

---

## The hole

Four frontend sites write `businesses` directly through `supabase-js`, using
the browser's anon key as `authenticated`. The only thing standing in front of
them is `biz_update_if_owner`:

```
biz_update_if_owner | UPDATE | {authenticated}
USING/CHECK: caller is an active member of this business with role='owner'
```

**Column-blind**, behind a **table-wide UPDATE grant** — `authenticated` holds
UPDATE on all 26 columns of `businesses`. So any owner can set their own
`plan_tier`, `is_active`, `feature_flags`, `subscription_status` and
`current_period_end` from the browser. The screens are labelled "admin"; the
enforcement is not.

030a deferred this deliberately:

> DELIBERATELY NOT IN THIS MIGRATION (see 030b): REVOKE UPDATE ON businesses
> FROM authenticated — 4 admin write sites must move to backend endpoints first

This spec is those four sites.

---

## PART A — Four endpoints

All four under `Depends(get_platform_admin_context)`. That dependency already
chains `get_access_token` → `verify_supabase_token` → `is_platform_admin_user`
(`SELECT 1 FROM platform_admins WHERE user_id = :user_id`), and the frontend
already sends `Authorization: Bearer <supabase access_token>` on every
`apiRequest` call. **No new auth machinery is required.**

### A1 — Update business overview
Replaces `AdminBusinessDetail.tsx:453` (`handleSaveOverview`).

- [ ] Accepts exactly: `plan_tier`, `is_active`, `trial_ends_at`,
      `feature_flags`, `limits`. Any other key in the body is a **400**, not
      silently ignored — a typo must not look like a success
- [ ] Every field optional; omitted means unchanged. Explicit `null` for
      `trial_ends_at` means clear it, and is distinguishable from omission
- [ ] Returns the updated row so the client need not refetch to stay correct

### A2 — Set business active state
Replaces `AdminBusinessDetail.tsx:551` and `AdminDashboard.tsx:342`.

Both sites today send `!business.is_active` — **an inversion of a value the
client is holding in memory**, with no server-side check that the client's view
is current. Two admins on the same business, or one stale tab, and the toggle
flips the wrong way with no error.

- [ ] Accepts `is_active` as an **explicit boolean state**, never a toggle. The
      request says what it wants to be true, not what it wants to change
- [ ] Setting `is_active` to its current value is a **success, not an error** —
      idempotent, so a retry after a dropped response is safe
- [ ] Returns the resulting state so the UI renders from the server's answer
      rather than its own optimistic inversion
- [ ] One endpoint serves both call sites

### A3 — Create business
Replaces `AdminDashboard.tsx:380`.

- [ ] Accepts: `name`, `timezone`, `plan_tier`, `is_active`, `trial_ends_at`,
      `feature_flags`, `limits`
- [ ] **Does not accept `api_key`.** See PART D
- [ ] `name` required and non-empty after trimming
- [ ] Returns the created row **including** the generated `api_key`, since this
      is the only moment it is displayable

### A4 — Read business for the admin detail view
Replaces the `select('*')` at `AdminBusinessDetail.tsx:184`.

- [ ] Returns exactly the ten columns that page reads (PART B), and **never**
      `api_key`
- [ ] Listed here because the same page's write moves in A1; leaving its read
      on `select('*')` keeps a second reason for the grant to exist

### Shared validation — all four

- [ ] **`plan_tier` validated against the canonical set.** An unrecognised
      value is a **400 naming the value and the permitted set**. No silent
      remap — the `("premium", "elite") → "business"` rewrite at
      `backend/main.py:836` is exactly the pattern being removed, and must not
      be reproduced in the new endpoints
- [ ] **`feature_flags` is a validated shape, not free-form.** Today it comes
      from a textarea via `JSON.parse` (`AdminBusinessDetail.tsx:438`), so
      whatever was typed is what gets stored. Minimum: must be a JSON object;
      every value must be a boolean; nesting rejected; non-object rejected
- [ ] **`limits` likewise** — object, no nesting, values numeric. See the scope
      note on `limits` below before writing this one
- [ ] A malformed body is a 400 **before any write occurs**. No partial application
- [ ] Every endpoint is idempotent enough that a client retry after a timeout
      cannot produce a second business or a flipped state

---

## PART B — Narrow the reads

Three sites use `select('*')`, which is why `SELECT` on every column is
currently needed. Verified column usage — none reads `api_key`:

- [ ] `BusinessDashboard.tsx:205` → `id, name, timezone, logo_url`
- [ ] `BrandingSettings.tsx:160` → `id, logo_url, feature_flags`
- [ ] `AdminBusinessDetail.tsx:184` → `id, name, timezone, plan_tier,
      is_active, trial_ends_at, feature_flags, limits, subscription_status,
      current_period_end` (or replaced entirely by A4)
- [ ] `BillingSettings.tsx:55` already explicit — **no change**
- [ ] A test asserts no frontend file contains `.from('businesses').select('*')`

---

## PART C — One auth scheme for the admin surface

The admin surface currently mixes two. `verify_master_key` is used by exactly
**two** endpoints, both of which this spec touches:

| Endpoint | Auth today |
|---|---|
| `POST /v1/admin/businesses` (`main.py:505`) | `verify_master_key` |
| `GET /v1/admin/businesses` (`main.py:523`) | `verify_master_key` |
| `GET /v1/admin/me` (`main.py:545`) | `get_platform_admin_context` |
| `GET /v1/admin/businesses/{id}/health` (`main.py:554`) | `get_platform_admin_context` |
| all of `onboarding_api.py` | `get_platform_admin_context` |

- [ ] **`get_platform_admin_context` is the single scheme** for the admin
      surface. It is already the majority, it is per-user and revocable by
      deleting a `platform_admins` row, and it leaves an attributable user id;
      a shared static secret does none of those
- [ ] The two `verify_master_key` endpoints move to it, or are retired in
      favour of A3/A4 which supersede them
- [ ] `create_business` (`main.py:505`) writes only `name` and `timezone` —
      five of A3's seven fields are missing. Extend it or retire it; do not
      leave a second, weaker create path
- [ ] **Confirm no external consumer** (GPT Action, script, integration) holds
      `MASTER_ADMIN_KEY` before retiring it. This cannot be determined from
      the repo and is the one item here needing a human check
- [ ] If `verify_master_key` survives for a non-admin purpose, it is documented
      where and why

---

## PART D — `api_key`

Today `AdminDashboard.tsx:380` mints the key in the browser:

```
'bh_' + 32 chars from Math.random()
```

`Math.random()` is not a CSPRNG, and `api_key` is an authentication credential
— `get_current_business` accepts it as bearer auth.

- [ ] `api_key` is generated **server-side** with `secrets.token_urlsafe(32)`
- [ ] `api_key` is **never accepted from the client** on any endpoint. Present
      in a request body is a 400, not a silent drop
- [ ] `generateApiKey()` is deleted from `AdminDashboard.tsx`
- [ ] One format only. Prod currently holds three (see scope note)
- [ ] `api_key` is returned exactly once, at creation (A3), and by no read
      endpoint

---

## PART E — The migration

- [ ] **`REVOKE INSERT, UPDATE ON businesses FROM authenticated`.** Not
      column-level. After PART A there are zero frontend writes to this table,
      so the whole privilege goes — stronger and simpler than 030a's
      column-grant approach on `business_members`, which was constrained by a
      write path that had to survive
- [ ] `SELECT` is **retained** — PART B narrows what is read, not whether
- [ ] A verify asserts `authenticated` holds `SELECT` and `TRIGGER` only
- [ ] `anon` is already down to `SELECT, TRIGGER` from 030a — assert it is
      unchanged
- [ ] **RULED: `biz_update_if_owner` is DROPPED**, in the same migration as
      the revoke, in Release 2. With the grant gone the policy is already
      unreachable, so dropping it removes nothing that works. The reason to
      drop rather than leave: a policy that reads as live protection but
      enforces nothing is worse than no policy, because the next person to
      restore an UPDATE grant — for a feature that seems to need one — would
      find an owner-scoped policy sitting there and reasonably conclude the
      table was still protected. It would re-open the paywall hole silently.
      After this, the protection is stated in exactly one place: the absence
      of the grant
- [ ] Dropping the policy and revoking the grant are **one migration**, not
      two. Split across releases they would leave a window with neither
- [ ] Rehearsed on staging with a before-snapshot, rollback proven, per 031/032

---

## Release ordering — two releases, in this order

**Release 1 — endpoints and call sites. No grant change.**

1. Ship A1–A4
2. Switch all four frontend write sites to `apiRequest`
3. Narrow the three `select('*')` calls
4. Confirm in prod that the admin screens work through the new endpoints

**Release 2 — the revoke.** Only after Release 1 is confirmed working.

5. Apply PART E

**Why it must be this way round.** The grant is what makes the current admin UI
function. Revoking first — or in the same release, before the frontend is
confirmed on the new path — takes down business creation, the plan editor and
both active toggles, with the failure surfacing as a permission error inside a
`catch` that renders `setError(...)` in a corner of the page. There is no
staged rollout on a Vercel deploy; it is atomic per release. Two releases makes
the dangerous half independently revertible.

**The corollary:** Release 1 is not "done" when it merges. It is done when
someone has created a business, changed a plan and toggled active through the
new endpoints **in prod**. Release 2 depends on that confirmation, not on the
code being written.

---

## Scope notes — things I read differently from the brief

These are flagged, not decided.

### 1. One of the four sites is an INSERT, and INSERT must be revoked too

"Four write sites" reads as four updates. `AdminDashboard.tsx:380` is an
**INSERT**. `REVOKE UPDATE` alone leaves business creation open from the
browser — including `plan_tier`, `is_active` and `feature_flags` on the new
row, which is the same paywall hole through a different verb. PART E says
`REVOKE INSERT, UPDATE` for this reason.

### 2. `feature_flags` shape validation is blocked on ENTITLEMENT-SPEC PART B

The brief asks for validated JSON shapes rather than free-form. Agreed — but
**there is no canonical feature vocabulary yet**. ENTITLEMENT-SPEC PART B
defines one and is not built. Prod currently holds eleven distinct flag keys
including `accounting` *and* `accounting_enabled`, and `brand_color`, which is
a **colour string, not a boolean**, on both real businesses.

So a strict "object of booleans" validator **rejects the data that is in the
table today**. Two options, and this needs choosing before the validator is
written:

- **(a)** 030b validates *structure only* — object, flat, boolean values —
  and explicitly permits the known non-boolean `brand_color` until PART B
  moves it out. Key-set validation deferred to `033`
- **(b)** 030b waits for PART B and ships with full key-set validation

**RULED: option (a).** 030b validates *structure only* — object, flat,
boolean values — and explicitly permits the known non-boolean `brand_color`
until ENTITLEMENT-SPEC PART B moves it out. Key-set validation is deferred to
`033`.

The reasoning: this is a security fix, and coupling it to an unfinished
data-model decision delays the part that is urgent. Structure-only validation
already removes what matters — arbitrary nested JSON arriving from a textarea
— without asserting a vocabulary nobody has agreed yet.

- [ ] The `brand_color` exemption is written as a **named, temporary
      exception with a pointer to `033`**, not a general "strings allowed"
      loophole. When PART B moves it to its own column, the exemption is
      deleted and the validator tightens with no other change
- [ ] A test asserts the exemption covers `brand_color` and nothing else

### 3. `limits` is never read for anything

Verified: `limits` is written by the admin textarea, copied from
`plan_definitions` at onboarding, and returned by the admin list query
(`main.py:571`). **No code reads it to enforce a limit.** Validating its shape
defines a contract for a column nothing consumes.

**RULED: `limits` is KEPT and accepted opaquely, with structure-only
validation.** It is not dropped from the endpoint surface.

Structure-only means: must be a JSON object, must be flat, and that is all.
Values are not constrained and keys are not checked against any list.

The reasoning for keeping rather than dropping: the column holds data today,
`033`'s `usage_meters` has not been built, and removing the only way to write
a populated column would mean either losing the ability to correct it or
reinstating the endpoint later. Opaque acceptance costs nothing and keeps the
column reachable.

The reasoning for structure-only: a strict validator would invent a schema no
consumer has asked for, and would have to be rewritten the moment
`usage_meters` defines the real one.

- [ ] `limits` accepted as any flat JSON object; values unconstrained
- [ ] Nested objects and non-object bodies rejected — the same floor as
      `feature_flags`
- [ ] A comment at the validator records that this is deliberately permissive
      pending `033`, so it is not mistaken for an oversight

### 4. Key rotation is narrower — and wider — than "bh_ keys"

The brief says flag `bh_`-prefixed keys for rotation. Prod actually holds
**three** formats:

| Format | Entropy | Businesses |
|---|---|---|
| `bh_` + 32 chars `Math.random()` | predictable | 1 — **Test Business C** |
| `sk_` + 14 chars | short | 2 — **Test_Business_A**, **Test_Business_B** |
| `sk_` + 43 chars (`token_urlsafe(32)`) | correct | 3 — **MSC**, **New Body**, TEST_BUSINESS_4_1441 |

**Both real businesses already hold correctly generated keys.** Every weak key
belongs to a test row. So this is not a customer-facing rotation with
coordination and downtime — it is cleanup, and deleting the test businesses
resolves it outright.

The `sk_` + 14-char format is not mentioned in the brief and is a second
undocumented generator worth locating before it is used again.

**RULED: this is test-row cleanup, not a customer rotation.** Both real
businesses already hold correct 43-char keys, so there is no coordinated
rotation, no customer notification and no downtime. Reframed accordingly.

- [ ] The three weak-keyed rows — Test Business C (`bh_`), Test_Business_A and
      Test_Business_B (`sk_` 14-char) — are **deleted**, not rotated. They are
      test data; rotating a key on a row that should not exist is work spent
      preserving something nobody wants
- [ ] **The 14-char `sk_` generator is located before Release 1 ships.** It is
      an undocumented second server-side generator and it is the more
      concerning of the two weak formats: `bh_` at least announces itself by
      prefix, whereas a short `sk_` key is indistinguishable from a correct one
      at a glance. Until it is found, there is no guarantee it is not still
      reachable
- [ ] If the 14-char generator is still live, it is removed in Release 1 — not
      deferred. It is a credential generator, not a cosmetic inconsistency
- [ ] A test asserts a newly created business's key is `sk_` + 43 characters
- [ ] A test asserts no business row holds a key shorter than 46 characters
      total, run against staging after cleanup

### 5. `trial_ends_at` is load-bearing for entitlement

A1 and A3 both write it, and `require_feature` reads it: the gate is
`if not business.is_active and _is_trial_expired(business.trial_ends_at)`, an
**and**. `_is_trial_expired(None)` returns `True`. So an admin clearing
`trial_ends_at` on an inactive business changes access, from a field that reads
like metadata.

**RULED: `trial_ends_at` is documented as an entitlement field, and the admin
UI carries a warning.** It is not treated as metadata.

- [ ] The endpoint contract for A1 and A3 states that `trial_ends_at`
      **affects access**, with the exact rule: `require_feature` denies when
      `not is_active AND _is_trial_expired(trial_ends_at)`, and
      `_is_trial_expired(None)` is `True`, so clearing the field on an
      inactive business removes access immediately
- [ ] The admin UI shows a **warning adjacent to the field**, not in a tooltip
      or help page — it must be visible to someone editing the field without
      having gone looking for documentation
- [ ] The warning states the consequence in plain terms: clearing this on an
      inactive business locks the customer out now
- [ ] Revisited under ENTITLEMENT-SPEC DECISION 3, which makes
      `subscription_status` the driver of access and leaves this interaction
      underspecified. 030b documents the current behaviour; it does not change
      it

---

## Out of scope

- The RLS policy sprawl on other tables. 030b is `businesses` only
- `feature_flags` key consolidation — ENTITLEMENT-SPEC PART B, migration `033`
- Server-side entitlement enforcement — ENTITLEMENT-SPEC PART D. 030b stops
  owners *writing* their plan; it does not start enforcing what a plan means
- `stripe_events` and the webhook. Separate finding, separate work

---

## Order of work

1. ~~Answer the open items~~ — **done, 20 Aug 2026.** All five scope
   questions ruled: `feature_flags` option (a); `limits` kept, opaque,
   structure-only; key rotation is test-row cleanup; `trial_ends_at`
   documented with a UI warning; `biz_update_if_owner` dropped in Release 2
2. Confirm no external consumer holds `MASTER_ADMIN_KEY` (PART C) — **the one
   remaining human check**
2a. Locate the 14-char `sk_` generator (scope note 4)
3. Tests written. **Michael reviews the tests**
4. Implementation until green
5. **Release 1** — endpoints, call sites, narrowed reads. Confirm in prod
6. Migration for PART E, rehearsed on staging, rollback proven
7. **Release 2** — the revoke, via runbook
8. Verify: an owner attempting `plan_tier` self-promotion through the anon key
   is refused at the grant layer, not merely absent from the UI
