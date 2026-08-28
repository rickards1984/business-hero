/**
 * Canonical feature vocabulary — ENTITLEMENT-SPEC PART B.
 *
 * This is the frontend's single definition. It must stay byte-identical to
 * `_plan_feature_defaults` in the backend and to the `plan_defaults` CTE in
 * `backend/migrations/033_entitlement.sql` (SECTION 7). Three copies is the
 * problem PART A exists to end; until the backend exposes this over the API,
 * keeping them in step is a review item on any change to any one of them.
 *
 * Rules that come with this vocabulary:
 *   - `plan_tier` is the source of truth. `feature_flags` holds ONLY
 *     deliberate per-business exceptions — a beta grant, a goodwill grant, a
 *     feature switched off for one customer. Empty is the normal state.
 *   - Never write a value into `feature_flags` that merely restates the plan
 *     default. Migration 033 SECTION 7 strips exactly those, and anything
 *     that writes them back undoes it.
 */

export const CANONICAL_FEATURES = [
  'quoting',
  'invoicing',
  'accounting',
  'email',
  'aria_chat',
  'aria_voice',
  'whatsapp',
  'board_meetings',
  'calendar_booking',
  // Gates NOTHING today, deliberately. Google issues Gmail and Calendar under
  // ONE consent, so a business that has connected email has already granted
  // calendar access — there is no separate state to check. It is named so the
  // concept has a word, and it is true on every tier because it rides on
  // `email`, which is true on every tier. Making it a real gate would mean
  // splitting the OAuth grant into two scopes first; the flag is not the
  // missing piece, the grant is.
  'calendar_sync',
  'receptionist',
  'outreach',
] as const;

export type CanonicalFeature = (typeof CANONICAL_FEATURES)[number];

export type PlanTier = 'starter' | 'pro' | 'business' | 'beta';

/** PART A's canonical set. `paused` is deliberately absent — DECISION 3. */
export const PLAN_TIERS: PlanTier[] = ['starter', 'pro', 'business', 'beta'];

/**
 * PART B's table. `beta` mirrors `business` for testing parity, matching both
 * backend copies of `_plan_feature_defaults`.
 */
export const PLAN_FEATURE_DEFAULTS: Record<PlanTier, Record<CanonicalFeature, boolean>> = {
  starter: {
    quoting: true, invoicing: true, accounting: true, email: true,
    aria_chat: true, aria_voice: false, whatsapp: false, board_meetings: false,
    calendar_booking: false, calendar_sync: true,
    receptionist: false, outreach: false,
  },
  pro: {
    quoting: true, invoicing: true, accounting: true, email: true,
    aria_chat: true, aria_voice: true, whatsapp: true, board_meetings: true,
    calendar_booking: true, calendar_sync: true,
    receptionist: true, outreach: false,
  },
  business: {
    quoting: true, invoicing: true, accounting: true, email: true,
    aria_chat: true, aria_voice: true, whatsapp: true, board_meetings: true,
    calendar_booking: true, calendar_sync: true,
    receptionist: true, outreach: true,
  },
  beta: {
    quoting: true, invoicing: true, accounting: true, email: true,
    aria_chat: true, aria_voice: true, whatsapp: true, board_meetings: true,
    calendar_booking: true, calendar_sync: true,
    receptionist: true, outreach: true,
  },
};

/** Fails closed: an unrecognised tier gets `starter`, the least-privileged. */
export function planDefaults(planTier: string | null | undefined): Record<CanonicalFeature, boolean> {
  const key = (planTier || 'starter').toLowerCase() as PlanTier;
  return PLAN_FEATURE_DEFAULTS[key] ?? PLAN_FEATURE_DEFAULTS.starter;
}

/**
 * The PART C resolution rule:
 *   flags[feature] if present, else the plan default, else false.
 * This is presentation only. The server-side gate is the enforcement — see
 * PART D. Hiding a button is not the same as refusing the request.
 */
export function isFeatureEnabled(
  planTier: string | null | undefined,
  flags: Record<string, unknown> | null | undefined,
  feature: CanonicalFeature,
): boolean {
  const f = flags || {};
  if (Object.prototype.hasOwnProperty.call(f, feature)) return Boolean(f[feature]);
  return planDefaults(planTier)[feature] ?? false;
}

/**
 * Write a toggle without polluting `feature_flags` with plan defaults.
 * If the requested value matches the plan default the key is REMOVED, so the
 * business follows its plan live; only a genuine exception is stored.
 */
export function setFeatureFlag(
  planTier: string | null | undefined,
  flags: Record<string, unknown> | null | undefined,
  feature: CanonicalFeature,
  value: boolean,
): Record<string, unknown> {
  const next = { ...(flags || {}) };
  if (planDefaults(planTier)[feature] === value) {
    delete next[feature];
  } else {
    next[feature] = value;
  }
  return next;
}
