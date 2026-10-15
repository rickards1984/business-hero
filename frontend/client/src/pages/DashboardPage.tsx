import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert } from '@mui/material';
import { useMe } from '@/hooks/useMe';
import { useIsMobile } from '@/hooks/use-mobile';
import { apiRequest } from '@/lib/queryClient';
import TasksPanel from '@/components/TasksPanel';
import ApprovalCard from '@/components/ApprovalCard';
import AriaHero from '@/components/AriaHero';
import { isBlocking } from '@/components/ReceptionistUsage';
import { useDashboardData } from '@/hooks/useDashboardData';
import './DashboardPage.css';

/**
 * NS-B7 Stage 2 — the Aria home (round-2 option A). On desktop the hero sits
 * in the shell's dark band (AriaShellHeader); on a phone it is the first card
 * here. Below: what needs the owner, the business at a glance, and tasks.
 * Every figure is the business's own data; a figure that failed to load says
 * so rather than showing zero (North Star P2).
 */

const money = (n: number) => `£${n.toLocaleString('en-GB', { maximumFractionDigits: 0 })}`;

function Tile({ name, figure, line, onClick, loading, failed }: {
  name: string; figure?: ReactNode; line?: ReactNode; onClick: () => void;
  loading: boolean; failed: boolean;
}) {
  return (
    <button type="button" className="home-tile" onClick={onClick}>
      <span className="home-tile-name">{name}</span>
      {loading ? (
        <><span className="skeleton" style={{ height: 26, width: '55%' }} /><span className="skeleton" style={{ height: 14, width: '80%' }} /></>
      ) : failed ? (
        <span className="home-tile-line">Couldn't load just now.</span>
      ) : (
        <><span className="home-tile-figure">{figure}</span><span className="home-tile-line">{line}</span></>
      )}
    </button>
  );
}

export default function DashboardPage() {
  const { data: me } = useMe();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const businessId = me?.id;
  const d = useDashboardData(businessId);
  const [showTasks, setShowTasks] = useState(false);

  // Warm the email cache in the background, non-blocking. /sync/ensure returns
  // instantly and only schedules a background sync if the cache is stale.
  useEffect(() => {
    if (businessId) apiRequest('POST', '/v1/email/sync/ensure').catch(() => {});
  }, [businessId]);

  if (!businessId) return null;

  const usage = d.usage.data;
  const cards = d.actions.data ?? [];

  return (
    <div className="home">
      {usage && isBlocking(usage) && (
        <Alert severity="error" sx={{ mb: 2 }}
          action={<button className="btn btn-sm" onClick={() => navigate('/app/ai?tab=receptionist')}>Manage</button>}>
          {usage.state === 'spend_cap_reached'
            ? 'Your monthly cap for extra voice minutes has been reached: the receptionist is not answering new calls and Aria\'s voice is paused.'
            : 'This month\'s voice minutes are used up: the receptionist is not answering new calls and Aria\'s voice is paused.'}
        </Alert>
      )}

      {isMobile && <AriaHero variant="card" />}

      <section className="home-section" aria-label="Needs you">
        <div className="home-section-head">
          <h2>Needs you</h2>
          <span>Aria drafts. You approve. She acts once, signed as your AI assistant.</span>
        </div>
        {d.actions.isLoading ? (
          <div className="home-empty"><span className="skeleton" style={{ height: 16, width: '40%' }} /></div>
        ) : d.actions.isError ? (
          <div className="home-empty">Your drafts couldn't be loaded just now.</div>
        ) : cards.length === 0 ? (
          <div className="home-empty">
            Nothing is waiting for your approval. Ask Aria to draft an email, chase an invoice,
            book something or add a task, and it will appear here for a tap.
          </div>
        ) : (
          <div className="home-cards">
            {cards.map(card => <ApprovalCard key={card.id} proposal={card} />)}
          </div>
        )}
      </section>

      <section className="home-section" aria-label="Your business">
        <div className="home-section-head"><h2>Your business</h2></div>
        <div className="home-tiles">
          <Tile name="Invoices" onClick={() => navigate('/app/finance?tab=invoices')}
            loading={d.invoices.isLoading} failed={d.invoices.isError}
            figure={d.invoices.data && (d.invoices.data.overdueCount > 0
              ? `${money(d.invoices.data.overdueAmount)} overdue`
              : money(d.invoices.data.unpaidAmount))}
            line={d.invoices.data && `${d.invoices.data.unpaidCount} unpaid${d.invoices.data.overdueCount > 0 ? `, ${d.invoices.data.overdueCount} overdue` : ', none overdue'}`} />
          <Tile name="Email" onClick={() => navigate('/app/comms?tab=emails')}
            loading={d.emails.isLoading} failed={d.emails.isError}
            figure={d.emails.data && (d.emails.data.emailsActionRequired > 0
              ? `${d.emails.data.emailsActionRequired} need a reply` : 'All clear')}
            line={d.emails.data && `${d.emails.data.emailsToday} received today`} />
          <Tile name="Calls" onClick={() => navigate('/app/comms?tab=calls')}
            loading={d.calls.isLoading} failed={d.calls.isError}
            figure={d.calls.data && `${d.calls.data.callsToday} today`}
            line={d.calls.data && `${d.calls.data.callsThisWeek} this week · receptionist resolved ${d.calls.data.aiResolutionRate}%`} />
          <Tile name="Voice minutes" onClick={() => navigate('/app/ai?tab=receptionist')}
            loading={d.usage.isLoading} failed={d.usage.isError}
            figure={usage && `${usage.used_minutes} of ${usage.allowance_minutes}`}
            line={usage && (usage.by_source
              ? `Receptionist ${usage.by_source.receptionist ?? '0.0'} · Aria ${usage.by_source.aria_voice ?? '0.0'}`
              : `${usage.remaining_minutes} left this month`)} />
          <Tile name="Tasks" onClick={() => setShowTasks(true)}
            loading={d.tasks.isLoading} failed={d.tasks.isError}
            figure={d.tasks.data && `${d.tasks.data.openTasks} open`}
            line={d.tasks.data && (d.tasks.data.highPriorityTasks > 0
              ? `${d.tasks.data.highPriorityTasks} high priority` : 'Nothing high priority')} />
          <Tile name="Board meeting" onClick={() => navigate('/app/board-meeting')}
            loading={false} failed={false}
            figure="Hold one" line="Aria reviews the month with you and what you committed to" />
        </div>
      </section>

      <section className="home-section" aria-label="Tasks">
        <div className="home-section-head">
          <h2>Tasks</h2>
          <button type="button" className="home-link" onClick={() => setShowTasks(!showTasks)}>
            {showTasks ? 'Hide' : 'Show all'}
          </button>
        </div>
        {showTasks && <TasksPanel businessId={businessId} />}
      </section>
    </div>
  );
}
