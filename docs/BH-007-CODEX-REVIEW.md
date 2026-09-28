# BH-007 — Codex review (ORIGINAL, UNEDITED)

| | Review 1 |
|---|---|
| Commit | `a7c78e1` (on `main` @ `2cc2b62`) |
| Session | `01a0e942-c3d4-7410-aeac-705adc451335` |
| Tokens reported | 44,322 |
| Verdict | REQUEST-CHANGES — 3 items, all taken |

Reviewer: Codex CLI 0.153.4, `gpt-5.6-sol`, `workspace-write`. Left the tree
clean.

**It found a second, worse bug behind the one being fixed**, and it is an
entitlement escalation rather than an inconvenience:

`onboarding_api.save_wizard_step` validated NOTHING. Its `plan_features`
branch takes an untyped dict — the declared `PlanFeaturesStep` model is not
applied — so a canonical feature could be stored as a STRING. Verified
empirically before accepting the finding:

```
business.feature_flags = {"receptionist": "false"}   # a STRING
_is_feature_enabled(business, "receptionist")        # -> True
starter's own default for receptionist               # -> False
```

`bool("false")` is True, so a value spelled like a denial GRANTED the feature.
The wizard could persist it, and the admin editor then refused every
subsequent save of that business — one missing validator, an escalation and a
blocked admin. I had fixed the validator in one writer and claimed an
admin-wide invariant while leaving the other open.

**And it corrected a claim of mine that was simply wrong.** I wrote that
metadata keys are "inert by construction". They are not:
`_is_feature_enabled` does not restrict lookups to the vocabulary, so asking
it for `receptionis` on `{"receptionis": True}` returns True. Metadata is
inert because no caller passes a non-canonical name — inert by CONVENTION.
Corrected in the code comment, the validator docstring and the test.

What changed in response:

1. `validate_feature_flags` moved to `auth.py`, beside the vocabulary it
   enforces, and BOTH writers now call it. A test asserts they are the same
   function object rather than trusting it.
2. Tests strengthened where Codex showed they were satisfiable by a wrong
   validator: metadata is now exercised with every scalar type (string,
   int, float, bool, None) and every canonical key is tested for ACCEPTING
   both booleans, not only for rejecting bad ones. Create-path metadata
   preservation added. 220 subtests.
3. Claims corrected: "inert by construction"; "cannot drift" (it rests on
   every tier declaring the same keys, which now has its own test); and
   "limits is permissive", which is true of values and false of structure —
   a nested stored `limits` would block a whole-form save exactly as
   `feature_flags` did. The read that would settle it is recorded.
4. The admin-completeness gaps it confirmed and extended are recorded in
   `audits/030B-SPEC.md` as explicit follow-up scope, deliberately not
   folded into a validator fix.

One point where I did not follow it: it suggested the two tests that error
with `AttributeError` on the old module are "not demonstrations of changed
runtime validation". Correct, and they were never meant to be — they assert
the vocabulary derivation. The behavioural regressions are the other three,
plus the four new onboarding tests, all verified failing against the
unfixed writer.

---

## REVIEW 1 — a7c78e1

The change fixes the reported `industry` rejection. I found no current entitlement consumer where a misspelled flag grants access. However, boolean enforcement is incomplete across admin paths, and the tests leave part of the new scalar contract unprotected.

1. **The rule is safe for current consumers, but the explanation overstates why.**  
   [`auth.py:595`](/Users/michaelrickards/dev/bh2-BH-007/backend/auth.py:595) does **not** restrict lookups to canonical keys: it returns the truthiness of any matching flag. Consequently, `_is_feature_enabled(business, "receptionis")` would return true for that typo.

   Current callers request canonical features, so `receptionis` grants no actual feature. I found no non-canonical flag controlling access, entitlement, or billing. `industry` affects quoting content, not entitlement. Frontend [`entitlements.ts:91`](/Users/michaelrickards/dev/bh2-BH-007/frontend/client/src/lib/entitlements.ts:91) likewise uses exact lookup, with canonical typing and canonical current callers.

   [`strip_plan_defaults`, auth.py:564](/Users/michaelrickards/dev/bh2-BH-007/backend/auth.py:564) preserves metadata correctly, including booleans: an absent default cannot equal either boolean. All current plan dictionaries contain the same vocabulary. The claim that this “cannot drift” depends on maintaining that invariant.

2. **Boolean enforcement is complete in the three named endpoints, but not across admin onboarding.**  
   Create validates before stripping defaults; overview validates supplied flags; the active endpoint rejects additional fields. Omission creates `{}` on create and preserves existing flags on update—it does not repair malformed existing values.

   **The bypass is [`onboarding_api.py:336`](/Users/michaelrickards/dev/bh2-BH-007/backend/onboarding_api.py:336).** `save_wizard_step` accepts an untyped dictionary, and its `plan_features` branch at line 390 passes flags directly through `strip_plan_defaults`. The declared `PlanFeaturesStep` model is not used there.

   Thus `{"receptionist": "false"}` survives, enables receptionist through Python truthiness, and subsequently blocks overview saves when the UI reposts that object. Nested metadata can also enter through this route and block later saves. This is pre-existing, but directly contradicts the claimed admin-wide invariant.

3. **Replacing the old test was legitimate.**  
   The rejected `industry` string is an intentional producer/consumer contract, so retaining that assertion would preserve the bug. Boolean enforcement and flat structure retain the relevant protections. The class docstring at [`test_admin_business_api.py:273`](/Users/michaelrickards/dev/bh2-BH-007/backend/tests/test_admin_business_api.py:273) still describes the superseded rule and should be updated.

4. **The new tests constrain the implementation, but incompletely.**  
   A validator that accepts metadata **only when it is a string or boolean**, rejecting metadata numbers and null, would pass these tests while violating “any scalar.” Also, most canonical keys are tested only for rejection; a validator rejecting both valid booleans for an otherwise unexercised key could pass.

   The “five fail against old validator” claim is technically correct by static inspection:

   - Three fail because the old validator rejects the supplied metadata strings.
   - Two error because the old module lacks `PLAN_FEATURE_VOCABULARY`.

   Those last two are not demonstrations of changed runtime validation. The typo test already passes against the old validator, which accepts arbitrary boolean flags.

5. **The claim that other validators cannot reject live data is too broad.**  
   [`admin_business_api.py:178`](/Users/michaelrickards/dev/bh2-BH-007/backend/admin_business_api.py:178) requires `limits` to be a flat object. The schema snapshot permits JSONB without establishing that shape, so nested or non-object stored limits would prevent a whole-form save. I found no evidence that such rows currently exist.

   The snapshot supports non-null boolean `is_active` and nullable timestamp `trial_ends_at`; their normal serialized values pass. The 033 runbook specifies the canonical tier CHECK, and `CURRENT_STATE.md` records completion, but I did not independently query production constraints. Name/timezone validators are pass-through, though create separately requires a nonempty string name. Arbitrary timestamp strings can pass validation and still fail at the database.

6. **Admin completeness remains materially incomplete, independently of this diff.**

   - **Name/timezone:** confirmed absent from [`OVERVIEW_FIELDS`, line 59](/Users/michaelrickards/dev/bh2-BH-007/backend/admin_business_api.py:59). Timezone is explicitly disabled in [`AdminBusinessDetail.tsx:802`](/Users/michaelrickards/dev/bh2-BH-007/frontend/client/src/pages/AdminBusinessDetail.tsx:802).
   - **Subscription status/current period end:** displayed but not editable through the overview API. This matters because [`auth.py:445`](/Users/michaelrickards/dev/bh2-BH-007/backend/auth.py:445) gives unpaid/canceled status precedence over activation and trial extensions. An admin cannot resolve that state using those controls alone. Any remedy needs a deliberate billing workflow, not simply unrestricted status editing.
   - **Cross-business support:** [`dependencies.py:38`](/Users/michaelrickards/dev/bh2-BH-007/backend/dependencies.py:38) and line 82 resolve only the caller’s own business. They do not forward a target business ID. Consequently, endpoints such as business settings, logo, brand color and integrations cannot target another customer through these dependencies. The admin exemption bypasses access restrictions only **after** business selection.
   - **Onboarding owner account:** [`onboarding_api.py:373`](/Users/michaelrickards/dev/bh2-BH-007/backend/onboarding_api.py:373) records the owner details and marks the checklist; it does not create the account or send an invitation.
   - The detail page shows email/calendar connection diagnostics without repair controls; accounting connection explicitly requires owner action. OAuth consent is a legitimate external dependency, but this is not fully autonomous admin onboarding.

Verification: the requested command passed **76 tests and 117 subtests**. I did not run `check.sh`, edit files, or access production. Final `git status --porcelain` was empty.

Behavioral confirmation after fixes: open an onboarded business carrying `industry`, change its plan, save, and reload; verify the plan and metadata persist. Separately exercise malformed canonical values through onboarding and confirm rejection before any write.

**VERDICT: REQUEST-CHANGES**

1. Apply shared canonical-boolean and flat-object validation to the onboarding flag writer; add regression coverage proving invalid values cannot be persisted there.
2. Test every metadata scalar type and both booleans for every canonical key, including create-path metadata preservation.
3. Correct the “inert by construction,” “cannot drift,” and admin-completeness claims. Record the pre-existing support gaps as explicit follow-up scope; they should not silently become a broad rewrite inside this validator fix.