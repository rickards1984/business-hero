import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOutreachEntry } from '@/hooks/useOutreachEntry';
import { STEPS } from '@/components/OutreachSetupWizard';
import './OutreachIntro.css';

/**
 * OUT-17 — the owner's introduction to Outreach on the Aria home. Shown only
 * to the active owner of a business with Outreach, until setup is finished.
 * Every claim here is something the product does today (North Star P2).
 */

const SNOOZE_DAYS = 7;
const snoozeKey = (businessId: string) => `bh:outreach-intro-snoozed:${businessId}`;

function snoozedUntil(businessId: string): number {
  try { return Number(localStorage.getItem(snoozeKey(businessId))) || 0; } catch { return 0; }
}

const POINTS = [
  { title: 'Finds the right people', text: "Switch on research and Aria looks for up to 20 new contacts a day who match the customers you describe, favouring the people who make the decision. She checks each business on its own website and at Companies House before suggesting it." },
  { title: 'Writes in your voice', text: 'She drafts each email from the facts you have approved, sent under your brand, from your mailbox, with the privacy notice you approve linked.' },
  { title: 'You stay in control', text: 'Nothing is sent until you approve it. Replies come straight back to your home screen, and one switch pauses everything.' },
];

export default function OutreachIntro({ businessId }: { businessId: string }) {
  const navigate = useNavigate();
  const { enabled, owner, setup } = useOutreachEntry();
  const [hidden, setHidden] = useState(() => snoozedUntil(businessId) > Date.now());
  if (!enabled || !owner || !setup.data || setup.data.started || hidden) return null;

  const required = STEPS.filter(s => !s.optional);
  const done = required.filter(s => setup.data!.steps[s.key] === 'done').length;
  const begun = done > 0;
  const next = STEPS.find(s => s.key === setup.data!.next);
  const snooze = () => {
    try { localStorage.setItem(snoozeKey(businessId), String(Date.now() + SNOOZE_DAYS * 86_400_000)); } catch { /* the card simply returns next visit */ }
    setHidden(true);
  };

  return (
    <section className="outreach-intro" aria-labelledby="outreach-intro-title">
      <div className="outreach-intro-head">
        <span className="outreach-intro-badge">{begun ? 'Outreach · in progress' : 'New · Outreach'}</span>
        <h2 id="outreach-intro-title">{begun ? 'Finish setting up Outreach' : 'Win new customers with Aria'}</h2>
        <p>
          {begun
            ? `${done} of ${required.length} steps done. Your progress is saved${next ? ` — next: ${next.label.toLowerCase()}` : ''}.`
            : 'Outreach is switched on for your business. Tell Aria who you want to reach; she helps find them, checks them and drafts the emails for you to approve.'}
        </p>
      </div>

      {begun ? (
        <div className="outreach-intro-progress" role="progressbar" aria-valuemin={0} aria-valuemax={required.length} aria-valuenow={done} aria-label="Setup progress">
          {required.map(s => <span key={s.key} className={setup.data!.steps[s.key] === 'done' ? 'is-done' : ''} title={s.label} />)}
        </div>
      ) : (
        <ul className="outreach-intro-points">
          {POINTS.map(p => <li key={p.title}><strong>{p.title}</strong><span>{p.text}</span></li>)}
        </ul>
      )}

      <div className="outreach-intro-foot">
        {!begun && <span className="outreach-intro-steps">{required.length} short steps · saved as you go</span>}
        <div className="outreach-intro-actions">
          <button type="button" className="outreach-intro-later" onClick={snooze}>Not now</button>
          <button type="button" className="outreach-intro-go" onClick={() => navigate('/app/outreach')}>
            {begun ? 'Continue setup' : 'Set up outreach'}
          </button>
        </div>
      </div>
    </section>
  );
}
