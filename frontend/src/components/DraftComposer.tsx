import { useEffect, useState } from 'react';
import { Loader2, X, Send, ExternalLink, Sparkles, Check } from 'lucide-react';
import { generateDraft, refineDraft, saveDraft } from '../lib/api';
import type { DraftMode, DraftHints } from '../lib/api';

interface ChatTurn { role: 'user' | 'ai'; text: string; }

interface Props {
  emailId: string;
  mode?: DraftMode;       // 'reply' (default) | 'followup'
  hints?: DraftHints;     // reason / opening / tone / urgency / days_waiting
  onClose: () => void;
}

export default function DraftComposer({ emailId, mode = 'reply', hints, onClose }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  const [subject, setSubject] = useState('');
  const [to, setTo]           = useState('');
  const [body, setBody]       = useState('');

  const [chat, setChat]           = useState<ChatTurn[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [refining, setRefining]   = useState(false);

  const [saving, setSaving]       = useState(false);
  const [savedLink, setSavedLink] = useState<string | null>(null);

  const label = mode === 'followup' ? 'Draft Follow-up' : 'Draft Reply';

  // First-time generate on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await generateDraft(emailId, mode, hints);
        if (cancelled) return;
        setSubject(res.subject);
        setTo(res.to);
        setBody(res.body);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // hints intentionally not in deps — they're captured at first mount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emailId, mode]);

  const handleSendChat = async () => {
    const req = chatInput.trim();
    if (!req || refining) return;
    setChatInput('');
    setChat(c => [...c, { role: 'user', text: req }]);
    setRefining(true);
    try {
      const res = await refineDraft(emailId, body, req);
      setBody(res.body);
      setChat(c => [...c, { role: 'ai', text: 'Draft updated above.' }]);
    } catch (e) {
      setChat(c => [...c, { role: 'ai', text: `Error: ${e instanceof Error ? e.message : String(e)}` }]);
    } finally {
      setRefining(false);
    }
  };

  const handleSave = async () => {
    if (saving || savedLink !== null) return;
    setSaving(true);
    setError(null);
    try {
      const res = await saveDraft(to, subject, body);
      setSavedLink(res.web_link || '');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3 border-t border-executive-border pt-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-amber-400" />
          <h4 className="text-xs font-semibold uppercase tracking-wider text-executive-text">
            {label}
          </h4>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-executive-muted hover:text-executive-text hover:bg-executive-border/40 transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* To / Subject */}
      <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-2 text-xs">
        <div>
          <label className="text-executive-muted block mb-1">
            To {!loading && !to && <span className="text-rose-400">· required</span>}
          </label>
          <input
            value={to}
            onChange={e => setTo(e.target.value)}
            disabled={loading || savedLink !== null}
            placeholder={!loading && !to ? 'no sender on original — type recipient' : ''}
            className={`w-full bg-executive-bg border rounded px-2 py-1.5 text-executive-text disabled:opacity-60 ${
              !loading && !to ? 'border-rose-400/60' : 'border-executive-border'
            }`}
          />
        </div>
        <div>
          <label className="text-executive-muted block mb-1">Subject</label>
          <input
            value={subject}
            onChange={e => setSubject(e.target.value)}
            disabled={loading || savedLink !== null}
            className="w-full bg-executive-bg border border-executive-border rounded px-2 py-1.5 text-executive-text disabled:opacity-60"
          />
        </div>
      </div>

      {/* Body */}
      <div>
        <label className="text-xs text-executive-muted block mb-1">Body</label>
        {loading ? (
          <div className="h-32 flex items-center justify-center bg-executive-bg border border-executive-border rounded">
            <Loader2 size={16} className="animate-spin text-executive-muted" />
            <span className="ml-2 text-xs text-executive-muted">Generating draft…</span>
          </div>
        ) : (
          <textarea
            value={body}
            onChange={e => setBody(e.target.value)}
            rows={Math.min(14, Math.max(6, body.split('\n').length + 1))}
            disabled={savedLink !== null}
            className="w-full bg-executive-bg border border-executive-border rounded p-3 text-sm text-executive-text leading-relaxed resize-y disabled:opacity-70 font-mono"
          />
        )}
        {error && <p className="text-xs text-rose-400 mt-1">{error}</p>}
      </div>

      {/* Chat refine */}
      {!loading && savedLink === null && (
        <div className="space-y-2">
          {chat.length > 0 && (
            <div className="space-y-1.5 max-h-40 overflow-y-auto bg-executive-bg/50 border border-executive-border rounded p-2">
              {chat.map((m, i) => (
                <div key={i} className="text-xs">
                  <span className={m.role === 'user' ? 'text-sky-400 font-semibold' : 'text-amber-400 font-semibold'}>
                    {m.role === 'user' ? 'You' : 'AI'}:
                  </span>
                  <span className="ml-2 text-executive-text/85">{m.text}</span>
                </div>
              ))}
              {refining && (
                <div className="text-xs flex items-center gap-1.5 text-executive-muted">
                  <Loader2 size={11} className="animate-spin" /> rewriting…
                </div>
              )}
            </div>
          )}
          <div className="flex gap-2">
            <input
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendChat(); }
              }}
              placeholder="Ask AI to refine — e.g. “make it shorter”, “more casual”, “add: looking forward”"
              disabled={refining}
              className="flex-1 bg-executive-bg border border-executive-border rounded px-3 py-1.5 text-xs text-executive-text placeholder:text-executive-muted/60"
            />
            <button
              onClick={handleSendChat}
              disabled={refining || !chatInput.trim()}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-executive-border hover:bg-executive-border/30 text-executive-muted hover:text-executive-text transition-colors disabled:opacity-40"
            >
              <Send size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Save */}
      <div className="flex items-center justify-end gap-2 pt-2 border-t border-executive-border/60">
        {savedLink !== null ? (
          <a
            href={savedLink || 'https://outlook.office.com/mail/drafts'}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 hover:text-emerald-200 transition-colors"
          >
            <Check size={12} />
            Saved · Open in Outlook
            <ExternalLink size={11} />
          </a>
        ) : (
          <button
            onClick={handleSave}
            disabled={saving || loading || !body}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-executive-accent/10 hover:bg-executive-accent/20 border border-executive-accent/30 text-executive-accent transition-colors disabled:opacity-40"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
            {saving ? 'Saving…' : 'Save to Outlook Drafts'}
          </button>
        )}
      </div>
    </div>
  );
}
