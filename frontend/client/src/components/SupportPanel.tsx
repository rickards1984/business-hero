import React, { useState, useEffect, useRef, useCallback } from 'react';
import { apiRequest } from '@/lib/queryClient';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface SupportMessage {
  id: string;
  conversation_id: string;
  sender_type: 'user' | 'ai' | 'admin';
  sender_name?: string;
  content: string;
  is_internal?: boolean;
  created_at: string;
}

interface SupportConversation {
  id: string;
  business_id: string;
  status: string;
  priority: string;
  category?: string;
  subject?: string;
  ai_resolved: boolean;
  created_at: string;
  updated_at: string;
  last_message_at?: string;
  messages?: SupportMessage[];
}

interface SupportArticle {
  id: string;
  title: string;
  content?: string;
  summary?: string;
  category: string;
  tags?: string[];
}

type PanelView =
  | { type: 'home' }
  | { type: 'chat'; conversationId: string | null }
  | { type: 'article'; article: SupportArticle };

interface SupportPanelProps {
  open: boolean;
  onClose: () => void;
}

/* ------------------------------------------------------------------ */
/*  Status badge helper                                                */
/* ------------------------------------------------------------------ */

const STATUS_MAP: Record<string, { label: string; bg: string; color: string }> = {
  ai_chat:        { label: 'AI Helping',     bg: 'var(--color-info-50)',      color: 'var(--color-info-500)' },
  escalated:      { label: 'Escalated',      bg: 'var(--color-warning-50)',   color: 'var(--color-warning-600)' },
  in_progress:    { label: 'In Progress',    bg: 'var(--color-info-50)',      color: 'var(--color-info-500)' },
  awaiting_reply: { label: 'Awaiting Reply', bg: 'var(--color-neutral-100)',  color: 'var(--color-neutral-600)' },
  resolved:       { label: 'Resolved',       bg: 'var(--color-success-50)',   color: 'var(--color-success-600)' },
  closed:         { label: 'Closed',         bg: 'var(--color-neutral-100)',  color: 'var(--color-neutral-500)' },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? STATUS_MAP.closed;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: '9999px',
        fontSize: 'var(--text-xs)',
        fontWeight: 600,
        background: s.bg,
        color: s.color,
        whiteSpace: 'nowrap',
      }}
    >
      {s.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Relative time helper                                               */
/* ------------------------------------------------------------------ */

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function SupportPanel({ open, onClose }: SupportPanelProps) {
  const [view, setView] = useState<PanelView>({ type: 'home' });

  // Home data
  const [articles, setArticles] = useState<SupportArticle[]>([]);
  const [conversations, setConversations] = useState<SupportConversation[]>([]);
  const [articleSearch, setArticleSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  // Chat state
  const [messages, setMessages] = useState<SupportMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [sending, setSending] = useState(false);
  const [chatStatus, setChatStatus] = useState<string>('ai_chat');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Full article
  const [fullArticle, setFullArticle] = useState<SupportArticle | null>(null);

  /* ---------- Fetch helpers ---------- */

  const fetchArticles = useCallback(async () => {
    try {
      const url = selectedCategory
        ? `/v1/support/articles?category=${encodeURIComponent(selectedCategory)}`
        : '/v1/support/articles';
      const res = await apiRequest('GET', url);
      const data = await res.json();
      setArticles(data);
    } catch {
      /* silent */
    }
  }, [selectedCategory]);

  const fetchConversations = useCallback(async () => {
    try {
      const res = await apiRequest('GET', '/v1/support/conversations');
      const data = await res.json();
      setConversations(data);
    } catch {
      /* silent */
    }
  }, []);

  const fetchConversationMessages = useCallback(async (convId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/support/conversations/${convId}`);
      const data = await res.json();
      setMessages(data.messages ?? []);
      setChatStatus(data.status ?? 'ai_chat');
    } catch {
      /* silent */
    }
  }, []);

  const fetchFullArticle = useCallback(async (articleId: string) => {
    try {
      const res = await apiRequest('GET', `/v1/support/articles/${articleId}`);
      const data = await res.json();
      setFullArticle(data);
    } catch {
      /* silent */
    }
  }, []);

  /* ---------- Effects ---------- */

  useEffect(() => {
    if (open) {
      fetchArticles();
      fetchConversations();
    }
  }, [open, fetchArticles, fetchConversations]);

  useEffect(() => {
    if (open) fetchArticles();
  }, [selectedCategory, open, fetchArticles]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  /* ---------- Chat actions ---------- */

  const handleSend = async () => {
    const text = chatInput.trim();
    if (!text || sending) return;
    setSending(true);
    setChatInput('');

    const convId = view.type === 'chat' ? view.conversationId : null;

    const optimisticMsg: SupportMessage = {
      id: `tmp-${Date.now()}`,
      conversation_id: convId ?? '',
      sender_type: 'user',
      sender_name: 'You',
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticMsg]);

    try {
      const res = await apiRequest('POST', '/v1/support/chat', {
        content: text,
        conversation_id: convId,
      });
      const data = await res.json();

      if (!convId && data.conversation_id) {
        setView({ type: 'chat', conversationId: data.conversation_id });
      }

      setChatStatus(data.status ?? 'ai_chat');

      setMessages((prev) => {
        const withoutOptimistic = prev.filter((m) => m.id !== optimisticMsg.id);
        const next = [...withoutOptimistic];
        if (data.user_message) next.push(data.user_message);
        if (data.ai_response) next.push(data.ai_response);
        return next;
      });
    } catch {
      setMessages((prev) => prev.filter((m) => m.id !== optimisticMsg.id));
    } finally {
      setSending(false);
    }
  };

  const handleEscalate = async () => {
    const convId = view.type === 'chat' ? view.conversationId : null;
    if (!convId) return;
    try {
      await apiRequest('POST', '/v1/support/escalate', { conversation_id: convId });
      setChatStatus('escalated');
      await fetchConversationMessages(convId);
    } catch {
      /* silent */
    }
  };

  const openChat = (conversationId: string | null) => {
    setMessages([]);
    setChatStatus('ai_chat');
    setChatInput('');
    setView({ type: 'chat', conversationId });
    if (conversationId) {
      fetchConversationMessages(conversationId);
    }
  };

  const openArticle = (article: SupportArticle) => {
    setFullArticle(null);
    setView({ type: 'article', article });
    fetchFullArticle(article.id);
  };

  const goHome = () => {
    setView({ type: 'home' });
    fetchConversations();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  /* ---------- Filtered articles ---------- */

  const filteredArticles = articles.filter((a) => {
    if (!articleSearch) return true;
    const q = articleSearch.toLowerCase();
    return (
      a.title.toLowerCase().includes(q) ||
      (a.summary ?? '').toLowerCase().includes(q) ||
      a.category.toLowerCase().includes(q)
    );
  });

  const categories = Array.from(new Set(articles.map((a) => a.category)));

  const isEscalated = ['escalated', 'in_progress', 'awaiting_reply'].includes(chatStatus);

  /* ---------- Render ---------- */

  return (
    <>
      {/* Overlay */}
      <div
        className={`support-panel-overlay${open ? ' support-panel-overlay--open' : ''}`}
        onClick={onClose}
      />

      {/* Panel */}
      <div className={`support-panel${open ? ' support-panel--open' : ''}`}>
        {/* Header */}
        <div className="support-panel__header">
          <h3>
            {view.type === 'home' && <><span>💬</span> Help &amp; Support</>}
            {view.type === 'chat' && (
              <>
                <button className="support-panel__back" onClick={goHome}>← Back</button>
                Chat with Support
              </>
            )}
            {view.type === 'article' && (
              <>
                <button className="support-panel__back" onClick={goHome}>← Back</button>
                {fullArticle?.title ?? 'Loading…'}
              </>
            )}
          </h3>
          <button className="support-panel__close" onClick={onClose}>✕</button>
        </div>

        {/* ----- HOME VIEW ----- */}
        {view.type === 'home' && (
          <div className="support-panel__body">
            {/* Search */}
            <input
              type="text"
              className="support-search"
              placeholder="Search help articles…"
              value={articleSearch}
              onChange={(e) => setArticleSearch(e.target.value)}
            />

            {/* Articles section */}
            <div className="support-section-heading">📚 Help Articles</div>

            {categories.length > 0 && (
              <div className="support-category-pills">
                <button
                  className={`support-category-pill${selectedCategory === null ? ' support-category-pill--active' : ''}`}
                  onClick={() => setSelectedCategory(null)}
                >
                  All
                </button>
                {categories.map((cat) => (
                  <button
                    key={cat}
                    className={`support-category-pill${selectedCategory === cat ? ' support-category-pill--active' : ''}`}
                    onClick={() => setSelectedCategory(cat === selectedCategory ? null : cat)}
                  >
                    {cat.charAt(0).toUpperCase() + cat.slice(1)}
                  </button>
                ))}
              </div>
            )}

            {filteredArticles.length > 0 ? (
              filteredArticles.map((a) => (
                <div key={a.id} className="support-article-item" onClick={() => openArticle(a)}>
                  <div>
                    <div className="support-article-item__title">{a.title}</div>
                    {a.summary && (
                      <div className="support-article-item__cat">{a.summary}</div>
                    )}
                    {!a.summary && (
                      <div className="support-article-item__cat">{a.category}</div>
                    )}
                  </div>
                  <span style={{ color: 'var(--color-neutral-300)', flexShrink: 0 }}>›</span>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 'var(--text-sm)', color: 'var(--color-neutral-400)', textAlign: 'center', padding: 'var(--space-4)' }}>
                {articleSearch ? 'No articles match your search.' : 'No help articles yet.'}
              </div>
            )}

            {/* Divider */}
            <div className="support-divider">or</div>

            {/* Chat CTA */}
            <div className="support-chat-cta">
              <h4>💬 Chat with Support</h4>
              <p>Get instant help from our AI assistant. A human can step in if needed.</p>
              <button className="support-chat-cta__btn" onClick={() => openChat(null)}>
                Start Chat →
              </button>
            </div>

            {/* Past conversations */}
            {conversations.length > 0 && (
              <>
                <div className="support-section-heading">📋 Your Tickets ({conversations.length})</div>
                <div style={{ border: '1px solid var(--color-neutral-100)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
                  {conversations.map((c) => (
                    <div key={c.id} className="support-convo-item" onClick={() => openChat(c.id)}>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div className="support-convo-item__subject">
                          {c.subject || 'Support conversation'}
                        </div>
                        <div className="support-convo-item__time">
                          {timeAgo(c.updated_at)}
                        </div>
                      </div>
                      <StatusBadge status={c.status} />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* ----- CHAT VIEW ----- */}
        {view.type === 'chat' && (
          <>
            <div className="support-panel__body">
              <div className="support-messages">
                {messages.length === 0 && !sending && (
                  <div className="support-msg--ai">
                    <div className="support-msg__sender">🤖 Business Hero Support</div>
                    Hi! I'm here to help. What can I assist you with today?
                  </div>
                )}

                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={
                      m.sender_type === 'user'
                        ? 'support-msg--user'
                        : m.sender_type === 'admin'
                        ? 'support-msg--admin'
                        : 'support-msg--ai'
                    }
                  >
                    {m.sender_type !== 'user' && (
                      <div className="support-msg__sender">
                        {m.sender_type === 'admin' ? '👤' : '🤖'} {m.sender_name || 'Support'}
                      </div>
                    )}
                    <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                  </div>
                ))}

                {sending && (
                  <div className="support-typing">
                    <div className="support-typing__dot" />
                    <div className="support-typing__dot" />
                    <div className="support-typing__dot" />
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>

              {isEscalated && (
                <div className="support-escalated-banner">
                  This conversation has been escalated to our support team. They'll get back to you as soon as possible.
                </div>
              )}

              {!isEscalated && view.conversationId && messages.length > 0 && (
                <button className="support-escalate-btn" onClick={handleEscalate}>
                  🙋 Talk to a human instead
                </button>
              )}
            </div>

            {/* Input bar */}
            <div className="support-input-bar">
              <input
                type="text"
                placeholder="Type your message…"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={sending}
              />
              <button
                className="support-input-bar__send"
                onClick={handleSend}
                disabled={sending || !chatInput.trim()}
                title="Send"
              >
                ➤
              </button>
            </div>
          </>
        )}

        {/* ----- ARTICLE VIEW ----- */}
        {view.type === 'article' && (
          <div className="support-panel__body">
            {fullArticle ? (
              <div className="support-article-detail">
                <h1>{fullArticle.title}</h1>
                {fullArticle.tags && fullArticle.tags.length > 0 && (
                  <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-4)', flexWrap: 'wrap' }}>
                    {fullArticle.tags.map((t) => (
                      <span
                        key={t}
                        style={{
                          padding: '2px 10px',
                          borderRadius: '9999px',
                          fontSize: 'var(--text-xs)',
                          background: 'var(--color-neutral-100)',
                          color: 'var(--color-neutral-600)',
                        }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div style={{ whiteSpace: 'pre-wrap' }}>{fullArticle.content}</div>

                <div className="support-article-feedback">
                  Was this helpful?
                  <button onClick={() => { /* track positive */ }}>👍 Yes</button>
                  <button onClick={() => { /* track negative */ }}>👎 No</button>
                </div>

                <div style={{ textAlign: 'center', paddingTop: 'var(--space-3)' }}>
                  <button className="support-chat-cta__btn" onClick={() => openChat(null)}>
                    Still need help? Start a chat →
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-neutral-400)' }}>
                Loading article…
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}
