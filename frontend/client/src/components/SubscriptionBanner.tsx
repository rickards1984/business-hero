import { Alert, Button, Box } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useMe } from '@/hooks/useMe';

/**
 * ENTITLEMENT-SPEC DECISION 3's banner.
 *
 * The decision requires that `past_due` "sets a user-visible warning state — a
 * banner, not a silent flag". BH-006's first implementation returned
 * `payment_warning` from `GET /v1/billing/status` and stopped there, which is
 * precisely the silent flag the decision rules out: nothing rendered it, and
 * the billing page reads Supabase directly rather than that endpoint. Codex
 * caught it.
 *
 * Read-only (`unpaid` / `canceled`) gets a banner too, because a customer whose
 * writes are being refused server-side must be told why — otherwise the product
 * looks broken rather than unpaid. The server is the enforcement
 * (`auth.enforce_access`); this is the explanation.
 *
 * It renders the SERVER's own answer (`access_level`, `payment_warning` from
 * GET /v1/me, produced by `auth.resolve_access_level`) rather than mapping
 * statuses to meanings a second time in the client. A second mapping is a
 * second thing to keep in step, and the two disagreeing is worse than either
 * being wrong: the banner would say one thing while the API did another.
 */

export default function SubscriptionBanner() {
  const navigate = useNavigate();
  const { data: me } = useMe();

  const isReadOnly = me?.read_only === true || me?.access_level === 'read_only';
  const isWarning = me?.payment_warning === true;
  if (!isReadOnly && !isWarning) return null;

  const goToBilling = (
    <Button color="inherit" size="small" onClick={() => navigate('/app/settings/billing')}>
      Update payment
    </Button>
  );

  return (
    <Box sx={{ px: 2, pt: 2 }}>
      {isWarning ? (
        <Alert severity="warning" action={goToBilling} data-testid="banner-past-due">
          <strong>We couldn&apos;t take your last payment.</strong> Everything still
          works — we&apos;ll keep retrying your card. Update your payment details to
          avoid interruption.
        </Alert>
      ) : (
        <Alert severity="error" action={goToBilling} data-testid="banner-read-only">
          <strong>Your subscription isn&apos;t active, so this account is read-only.</strong>{' '}
          You can still view and export your quotes and invoices. Update your payment
          details to restore full access.
        </Alert>
      )}
    </Box>
  );
}
