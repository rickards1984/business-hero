import { useMe } from '@/hooks/useMe';
import { isFeatureEnabled } from '@/lib/entitlements';
import { useOutreachOwner } from '@/hooks/useOutreachData';
import { useSetupStatus } from '@/components/OutreachSetupWizard';

/**
 * OUT-17 — where Outreach shows itself. The menu tab and the home introduction
 * appear only when the business has Outreach (plan or admin toggle). This is
 * presentation only; the server refuses every outreach request without it.
 */
export function useOutreachEnabled() {
  const { data: me } = useMe();
  return !!me?.id && isFeatureEnabled(me?.plan_tier, me?.feature_flags, 'outreach');
}

/** Setup progress for the owner's introduction; nothing is fetched without Outreach. */
export function useOutreachEntry() {
  const { data: me } = useMe();
  const enabled = useOutreachEnabled();
  const owner = useOutreachOwner(enabled ? me?.id : undefined);
  const setup = useSetupStatus(me?.id || '', enabled);
  return { enabled, owner: !!owner.data, setup };
}
