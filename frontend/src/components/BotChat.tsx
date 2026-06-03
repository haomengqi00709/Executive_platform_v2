import { useEffect, useRef, useState } from 'react';
import { Send, Loader2, MessageCircle } from 'lucide-react';
import { botChat, getBotHistory } from '../lib/api';
import type { BotTurn } from '../lib/api';
import { useBotName } from '../App';

interface BotChatProps {
  /** Optional preamble inserted as the first message into the AI conversation
   * when the user sends their first message in this session. Hidden from UI. */
  contextPreamble?: string;
  /** Optional placeholder shown in the empty input. Defaults to "Ask <bot>…". */
  placeholder?: string;
  /** Optional starter suggestions shown when there's no history. */
  suggestions?: string[];
  /** How many recent turns to load on mount. Defaults to 10. */
  historyLimit?: number;
}

export default function BotChat({
  contextPreamble,
  placeholder,
  suggestions = [],
  historyLimit = 10,
}: BotChatProps) {
  const botName = useBotName();
  const effectivePlaceholder = placeholder ?? `Ask ${botName}…`;
  const [turns, setTurns] = useState<BotTurn[]>([]);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasUsedContext, setHasUsedContext] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);

  // Initial load
  useEffect(() => {
    let cancelled = false;
    getBotHistory(historyLimit)
      .then(d => { if (!cancelled) setTurns(d.turns || []); })
      .catch(() => { /* leave empty */ })
      .finally(() => { if (!cancelled) setLoadingHistory(false); });
    return () => { cancelled = true; };
  }, [historyLimit]);

  // Live refresh — poll every 5s while the panel is mounted so users see
  // briefing pushes, meeting prep, Test Run output etc. arriving from the
  // background scheduler.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const d = await getBotHistory(historyLimit);
        if (cancelled) return;
        setTurns(prev => {
          // Skip update if the latest ts hasn't changed
          const prevLast = prev[prev.length - 1]?.ts ?? 0;
          const nextLast = d.turns?.[d.turns.length - 1]?.ts ?? 0;
          if (nextLast <= prevLast) return prev;
          return d.turns || [];
        });
      } catch { /* swallow */ }
    };
    const id = window.setInterval(tick, 5000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [historyLimit]);

  useEffect(() => {
    if (scrollerRef.current) {
      scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
    }
  }, [turns.length, sending]);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setError(null);

    // Inject preamble on first message (hidden from UI)
    let toSend = trimmed;
    if (contextPreamble && !hasUsedContext) {
      toSend = `${contextPreamble}\n\nUser message: ${trimmed}`;
      setHasUsedContext(true);
    }

    // Optimistic UI
    const tsNow = Date.now() / 1000;
    setTurns(t => [...t, { role: 'user', content: trimmed, ts: tsNow }]);
    setDraft('');
    setSending(true);
    try {
      const res = await botChat(toSend);
      setTurns(t => [...t, { role: 'model', content: res.response, ts: Date.now() / 1000 }]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      // Keep user turn but show error inline
    } finally {
      setSending(false);
    }
  };

  const showSuggestions = !loadingHistory && turns.length === 0 && suggestions.length > 0;

  return (
    <div className="flex flex-col bg-executive-bg border border-executive-border rounded-lg overflow-hidden">
      <div className="px-3 py-2 border-b border-executive-border flex items-center gap-2">
        <MessageCircle size={12} className="text-executive-accent" />
        <span className="text-xs font-semibold text-executive-text">Chat with {botName}</span>
        <span className="text-[10px] text-executive-muted ml-auto">Shared with Teams</span>
      </div>

      {/* History */}
      <div ref={scrollerRef} className="max-h-72 overflow-y-auto px-3 py-3 space-y-2.5">
        {loadingHistory && (
          <div className="flex items-center gap-2 text-xs text-executive-muted">
            <Loader2 size={12} className="animate-spin" />
            Loading recent conversation…
          </div>
        )}
        {!loadingHistory && turns.length === 0 && !showSuggestions && (
          <p className="text-xs text-executive-muted italic">
            No conversation yet. Ask {botName} to refine this briefing — e.g. "Add yesterday recap to this".
          </p>
        )}
        {turns.map((t, i) => (
          <ChatBubble key={i} role={t.role} content={t.content} />
        ))}
        {sending && (
          <div className="flex items-center gap-2 text-xs text-executive-muted">
            <Loader2 size={12} className="animate-spin" />
            {botName} is thinking…
          </div>
        )}
        {error && (
          <div className="text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-2 py-1.5">
            {error}
          </div>
        )}
      </div>

      {/* Suggestions */}
      {showSuggestions && (
        <div className="px-3 pb-2 flex flex-wrap gap-1.5">
          {suggestions.map(s => (
            <button
              key={s}
              onClick={() => send(s)}
              className="text-[11px] px-2 py-1 rounded-md bg-executive-card border border-executive-border text-executive-muted hover:text-executive-text hover:border-executive-accent/40 transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={e => { e.preventDefault(); send(draft); }}
        className="flex items-center gap-2 px-2.5 py-2 border-t border-executive-border bg-executive-card"
      >
        <input
          type="text"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder={effectivePlaceholder}
          disabled={sending}
          className="flex-1 px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={sending || !draft.trim()}
          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
        >
          {sending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          Send
        </button>
      </form>
    </div>
  );
}

function ChatBubble({ role, content }: { role: string; content: string }) {
  const isUser = role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] text-sm rounded-lg px-3 py-1.5 whitespace-pre-wrap break-words leading-relaxed ${
        isUser
          ? 'bg-executive-accent/15 text-executive-text'
          : 'bg-executive-card border border-executive-border text-executive-text'
      }`}>
        {content}
      </div>
    </div>
  );
}
