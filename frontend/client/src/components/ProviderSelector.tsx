import { CircularProgress } from '@mui/material';

interface AccountingProvider {
  id: string;
  name: string;
  description: string;
  is_available: boolean;
  is_configured: boolean;
}

interface ProviderSelectorProps {
  providers: AccountingProvider[];
  loading?: boolean;
  connectingId: string | null;
  onConnect: (providerId: string) => void;
}

const PROVIDER_INITIALS: Record<string, string> = {
  xero: 'X',
  freeagent: 'FA',
  quickbooks: 'QB',
};

export default function ProviderSelector({
  providers,
  loading,
  connectingId,
  onConnect,
}: ProviderSelectorProps) {
  if (loading) {
    return (
      <div className="provider-selector">
        <CircularProgress size={32} />
      </div>
    );
  }

  return (
    <div className="provider-selector">
      <h2 style={{ fontSize: 'var(--text-2xl)', fontWeight: 'var(--font-bold)', color: 'var(--color-neutral-900)', margin: 0 }}>
        Connect Your Accounting Software
      </h2>
      <p className="provider-selector__subtitle">
        Link your accounting platform to sync transactions, invoices, and financial
        reports automatically.
      </p>

      <div className="provider-selector__grid">
        {providers.map((provider) => {
          const disabled = !provider.is_configured;
          const connecting = connectingId === provider.id;

          return (
            <div
              key={provider.id}
              className={`provider-card${disabled ? ' provider-card--disabled' : ''}`}
            >
              <div className={`provider-card__icon provider-card__icon--${provider.id}`}>
                {PROVIDER_INITIALS[provider.id] ?? provider.name.charAt(0)}
              </div>
              <span className="provider-card__name">{provider.name}</span>
              <p className="provider-card__description">{provider.description}</p>

              {disabled ? (
                <span className="provider-card__coming-soon">Coming soon</span>
              ) : (
                <button
                  className="bh-btn-primary"
                  style={{ width: '100%' }}
                  disabled={connecting}
                  onClick={() => onConnect(provider.id)}
                >
                  {connecting ? (
                    <>
                      <CircularProgress size={16} sx={{ color: 'white', mr: 1 }} />
                      Connecting…
                    </>
                  ) : (
                    `Connect ${provider.name}`
                  )}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
