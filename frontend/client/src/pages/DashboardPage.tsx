import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Alert } from '@mui/material';
import { useMe } from '@/hooks/useMe';
import { useShellMobile } from '@/hooks/useShellMobile';
import type { Proposal } from '@/components/ApprovalCard';
import { apiRequest } from '@/lib/queryClient';
import TasksPanel from '@/components/TasksPanel';
import ApprovalCard from '@/components/ApprovalCard';
import ReplyCard, { type ChaseReply } from '@/components/ReplyCard';
import AriaHero from '@/components/AriaHero';
import { isBlocking } from '@/components/ReceptionistUsage';
import { ago, useDashboardData } from '@/hooks/useDashboardData';
import './DashboardPage.css';

/**
 * NS-B7 Stage 2 — the Aria home (round-2 option A). On desktop the hero sits
 * in the shell's dark band (AriaShellHeader); on a phone it is the first card
 * here. Below: what needs the owner, the business at a glance, and tasks.
 * Every figure is the business's own data; a figure that failed to load says
 * so rather than showing zero (North Star P2).
 */

const money = (n: number) => `£${n.toLocaleString('en-GB', { maximumFractionDigits: 0 })}`;

function Tile({ name, figure, line, age, onClick, loading, failed }: {
  name: string; figure?: ReactNode; line?: ReactNode; age?: string | null; onClick: () => void;
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
        <><span className="home-tile-figure">{figure}</span><span className="home-tile-line">{line}</span>
          {age && <span className="home-tile-age">{age}</span>}</>
      )}
    </button>
  );
}

export default function DashboardPage() {
  const { data: me } = useMe();
  const isMobile = useShellMobile();  // the shell's own decision (review 1, finding 7)
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const businessId = me?.id;
  const d = useDashboardData(businessId);
  const [showTasks, setShowTasks] = useState(false);
  // The open drafts are the server's list, refreshed (an edit or dismissal
  // made elsewhere updates or removes its card — Codex NS-B7 review 2). A card
  // that FINISHED here (sent, failed, dismissed, unconfirmed) is kept on
  // screen so it can show its result rather than vanish; an edit is not a
  // finish, so an edited draft simply follows the server (review 3).
  const [finished, setFinished] = useState<Record<string, Proposal>>({});
  // AUTO-2: a reply the owner just decided stays on screen with its result.
  const [settled, setSettled] = useState<Record<string, ChaseReply>>({});
  const replyChanged = (reply: ChaseReply) => {
    setSettled(prev => ({ ...prev, [reply.id]: reply }));
    queryClient.invalidateQueries({ queryKey: ['home-summary'] });
  };
  const cardChanged = (card: Proposal) => {
    if (card.status !== 'proposed') setFinished(prev => ({ ...prev, [card.id]: card }));
    queryClient.invalidateQueries({ queryKey: ['aria-actions'] });
    queryClient.invalidateQueries({ queryKey: ['home-summary'] });
  };

  // Warm the email cache in the background, non-blocking. /sync/ensure returns
  // instantly and only schedules a background sync if the cache is stale.
  useEffect(() => {
    if (businessId) apiRequest('POST', '/v1/email/sync/ensure').catch(() => {});
  }, [businessId]);

  if (!businessId) return null;

  const usage = d.usage.data;
  const open = d.actions.data ?? [];
  const cards = [...open, ...Object.values(finished).filter(c => !open.some(o => o.id === c.id))];
  const openReplies = d.summary.data?.replies ?? [];
  const replies = [...openReplies, ...Object.values(settled).filter(r => !openReplies.some(o => o.id === r.id))];
  const inv = d.summary.data?.invoices;
  const em = d.summary.data?.emails;
  const synced = d.summary.data?.synced;

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
        {replies.length > 0 && (
          <div className="home-cards" style={{ marginBottom: 16 }}>
            {replies.map(r => <ReplyCard key={r.id} reply={r} onChanged={() => replyChanged(r)} />)}
          </div>
        )}
        {d.actions.isLoading && cards.length === 0 ? (
          <div className="home-empty"><span className="skeleton" style={{ height: 16, width: '40%' }} /></div>
        ) : d.actions.isError && cards.length === 0 ? (
          <div className="home-empty">Your drafts couldn't be loaded just now.</div>
        ) : cards.length === 0 && replies.length > 0 ? null : cards.length === 0 ? (
          <div className="home-empty">
            Nothing is waiting for your approval. Ask Aria to draft an email, chase an invoice,
            book something or add a task, and it will appear here for a tap.
          </div>
        ) : (
          <div className="home-cards">
            {cards.map(card => (
              // Keyed by version: a draft edited elsewhere is shown afresh.
              <ApprovalCard key={`${card.id}:${card.version}`} proposal={card}
                onChanged={cardChanged} />
            ))}
          </div>
        )}
      </section>

      {(d.summary.data?.automated?.length ?? 0) > 0 && (
        <section className="home-section" aria-label="What Aria did on her own">
          <div className="home-section-head">
            <h2>What Aria did on her own</h2>
            <button type="button" className="home-link" onClick={() => navigate('/app/settings/aria')}>Rules</button>
          </div>
          <ul className="home-tasks">
            {d.summary.data!.automated!.map((a, i) => (
              <li key={i}>
                <span className="home-task-title">
                  Chased {a.customer_name || 'a customer'} for {a.invoice_number || 'an invoice'} (stage {a.stage})
                </span>
                {a.sent_at && <span className="home-task-due">{ago(a.sent_at)}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="home-section" aria-label="Your business">
        <div className="home-section-head"><h2>Your business</h2></div>
        <div className="home-tiles">
          <Tile name="Invoices" onClick={() => navigate('/app/finance?tab=invoices')}
            loading={d.summary.isLoading} failed={d.summary.isError}
            figure={inv && (inv.overdue_count > 0 ? `${money(inv.overdue_total)} overdue` : money(inv.outstanding_total))}
            line={inv && `${money(inv.outstanding_total)} owed on ${inv.outstanding_count} invoice${inv.outstanding_count === 1 ? '' : 's'}${inv.overdue_count > 0 ? `, ${inv.overdue_count} overdue` : ', none overdue'}`}
            age={synced && (synced.accounting ? `Accounts synced ${ago(synced.accounting)}` : 'Not synced from your accounts software')} />
          <Tile name="Email" onClick={() => navigate('/app/comms?tab=emails')}
            loading={d.summary.isLoading} failed={d.summary.isError}
            figure={em && (em.action_required > 0 ? `${em.action_required} need action` : 'None flagged')}
            line={em && `Flagged for action in the last ${em.window_days} days`}
            age={synced && (synced.email ? `Email synced ${ago(synced.email)}` : 'Email not connected or not yet synced')} />
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
          <h2>Your tasks</h2>
          <button type="button" className="home-link" onClick={() => setShowTasks(!showTasks)}>
            {showTasks ? 'Hide the full list' : 'Manage all tasks'}
          </button>
        </div>
        {d.tasks.isError ? (
          <div className="home-empty">Your tasks couldn't be loaded just now.</div>
        ) : d.tasks.data && d.tasks.data.upcoming.length === 0 ? (
          <div className="home-empty">No open tasks.</div>
        ) : d.tasks.data ? (
          <ul className="home-tasks">
            {d.tasks.data.upcoming.map(t => (
              <li key={t.id}>
                <span className={`home-task-priority home-task-${t.priority || 'medium'}`} aria-hidden="true" />
                <span className="home-task-title">{t.title}</span>
                {t.source === 'assistant' && <span className="home-task-chip">Added by Aria</span>}
                {t.due_at && <span className="home-task-due">
                  {new Date(t.due_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</span>}
              </li>
            ))}
          </ul>
        ) : null}
        {showTasks && <TasksPanel businessId={businessId} />}
      </section>
    </div>
  );
}
