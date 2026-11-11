// OUT-13 core: a contact never emailed by their first email's deadline is
// withheld from every screen at that moment, by the browser's own clock too,
// so a stale page or a failed refresh never keeps showing them.
export const WITHHELD_TEXT = "This contact's deadline passed, so their details are withheld.";

export function pastWithholdAt(item: { withhold_at?: string | null } | null | undefined, now = Date.now()): boolean {
  if (!item?.withhold_at) return false;
  const at = Date.parse(item.withhold_at);
  return Number.isFinite(at) && at <= now;
}

const KEEP = new Set(['id', 'prospect_id', 'campaign_id', 'mailbox_id', 'brand_id', 'eligibility', 'stage',
  'state', 'status', 'kind', 'origin', 'direction', 'created_at', 'fetched_at', 'expires_at', 'accepted_at']);

/** The record with its personal details removed once its moment has come. */
export function withheld<T extends Record<string, any>>(item: T, now = Date.now()): T {
  if (!item || item.details_withheld || !pastWithholdAt(item, now)) return item;
  const out: Record<string, any> = { details_withheld: true, withhold_at: item.withhold_at };
  for (const [k, v] of Object.entries(item)) if (KEEP.has(k)) out[k] = v;
  return out as T;
}
