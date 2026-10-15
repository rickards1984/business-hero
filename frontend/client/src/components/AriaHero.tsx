import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMe } from '@/hooks/useMe';
import { apiRequest } from '@/lib/queryClient';
import { briefingLines, useDashboardData } from '@/hooks/useDashboardData';

/**
 * NS-B7 Stage 2 — Aria front and centre (round-2 option A). On desktop it
 * fills the dark band on the home page; on a phone it is the first card.
 * The briefing says only what the business's own data says (P2).
 */

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
}

export default function AriaHero({ variant }: { variant: 'band' | 'card' }) {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const data = useDashboardData(me?.id);
  const [question, setQuestion] = useState('');
  const [ownerName, setOwnerName] = useState('');

  useEffect(() => {
    if (!me?.id) return;
    apiRequest('GET', '/v1/whatsapp/config')
      .then(r => r.json())
      .then(c => { if (c?.owner_name) setOwnerName(c.owner_name.split(' ')[0]); })
      .catch(() => {});
  }, [me?.id]);

  const loading = [data.actions, data.invoices, data.emails, data.calls].some(q => q.isLoading);
  const lines = briefingLines(data);
  const failed = [data.invoices, data.emails, data.calls].filter(q => q.isError).length;
  const today = new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });

  const ask = (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    navigate(q ? `/app/assistant/chat?prompt=${encodeURIComponent(q)}` : '/app/assistant/chat');
  };

  return (
    <section className={`aria-hero aria-hero-${variant}`} aria-label="Aria, your AI business partner">
      <div className="aria-hero-portrait">
        <img
          className="aria-hero-avatar"
          src="/aria-avatar-320.webp"
          srcSet="/aria-avatar-160.webp 160w, /aria-avatar-320.webp 320w, /aria-avatar-640.jpg 640w"
          sizes={variant === 'band' ? '168px' : '72px'}
          alt="Aria, your AI business partner"
        />
        {variant === 'band' && (
          <span className="aria-hero-status"><span className="aria-hero-dot" />ONLINE</span>
        )}
      </div>
      <div className="aria-hero-body">
        <div className="aria-hero-meta">Aria · your AI business partner · {today}</div>
        <h1 className="aria-hero-greeting">{greeting()}{ownerName ? `, ${ownerName}` : ''}.</h1>
        <p className="aria-hero-briefing" aria-live="polite">
          {loading && lines.length === 0
            ? 'Catching up on your business…'
            : lines.length > 0
              ? lines.join(' ')
              : failed > 0
                ? 'Some of your figures could not be loaded just now. Ask me and I will check directly.'
                : 'Nothing needs you right now.'}
        </p>
        <form className="aria-hero-ask" onSubmit={ask}>
          <label htmlFor={`aria-ask-${variant}`} className="aria-hero-visually-hidden">Ask Aria</label>
          <input
            id={`aria-ask-${variant}`}
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder="Ask Aria anything — “how did we do this month compared with last?”"
            autoComplete="off"
          />
          <button type="submit" className="aria-hero-send" aria-label="Ask">Ask</button>
          <button type="button" className="aria-hero-talk" onClick={() => navigate('/app/assistant/chat?voice=1')}
            aria-label="Talk to Aria">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />
            </svg>
            <span>Talk</span>
          </button>
        </form>
      </div>
    </section>
  );
}
