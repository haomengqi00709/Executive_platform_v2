import { useEffect, useRef, useState } from 'react';
import {
  X, Loader2, Send, FileText, Users, ChevronDown, ChevronRight,
  AlertTriangle, CheckCircle2, ExternalLink, Wand2, Trash2, Minimize2,
} from 'lucide-react';
import { bulkGenerate, getBulkPreview, bulkCommit } from '../../lib/api';
import type { CrmContact, BulkPreviewItem } from '../../lib/api';
import type { OutreachLastRun } from '../../lib/types';

type Phase = 'compose' | 'generating' | 'review' | 'committing' | 'done';

// Generated bodies are simple <p>/<br> HTML — show them as plain text for
// editing; the backend re-wraps to HTML on commit (_ensure_html).
function htmlToText(html: string): string {
  return (html || '')
    .replace(/<\/p>\s*<p>/gi, '\n\n')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?p>/gi, '')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .trim();
}

export default function BulkEmailModal({
  recipients, onClose, resumeMode = false, onMinimize, onCommit,
}: {
  recipients: CrmContact[];
  onClose: () => void;
  resumeMode?: boolean;
  onMinimize?: (hint: 'generating' | 'committing') => void;
  onCommit?: () => void;
}) {
  const [phase, setPhase] = useState<Phase>('compose');

  // compose inputs
  const [subject, setSubject] = useState('');
  const [intent, setIntent] = useState('');
  const [personalize, setPersonalize] = useState(true);
  const [showList, setShowList] = useState(false);

  // generated, editable previews
  const [items, setItems] = useState<BulkPreviewItem[]>([]);
  const [skippedCount, setSkippedCount] = useState(0);
  const [genProgress, setGenProgress] = useState(0);
  const [genTotal, setGenTotal] = useState(0);

  const [result, setResult] = useState<OutreachLastRun | null>(null);
  const [committedSend, setCommittedSend] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const emails = recipients.map(r => r.email).filter(Boolean);
  const canGenerate = emails.length > 0 && intent.trim().length > 0 && (personalize || subject.trim().length > 0);

  const stopPoll = () => { if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; } };

  // ── Phase 1 poll: previews ────────────────────────────────
  useEffect(() => {
    if (phase !== 'generating') return;
    const tick = async () => {
      try {
        const p = await getBulkPreview();
        setGenProgress(p.items?.length ?? 0);
        setGenTotal(p.total ?? emails.length);
        if (p.status && p.status !== 'running') {
          stopPoll();
          if (p.status === 'error') { setError(p.error || 'Generation failed.'); setPhase('compose'); return; }
          setItems((p.items || []).map(it => ({ ...it, body: htmlToText(it.body) })));
          setSkippedCount(p.skipped?.length ?? 0);
          setPhase('review');
        }
      } catch { /* transient — keep polling */ }
    };
    tick();
    pollRef.current = window.setInterval(tick, 2000);
    return stopPoll;
  }, [phase]);

  // ── Phase 2 poll: commit results ──────────────────────────
  useEffect(() => {
    if (phase !== 'committing') return;
    const tick = async () => {
      try {
        const { getOutreachLast } = await import('../../lib/api');
        const r = await getOutreachLast();
        setResult(r);
        if (r.status && r.status !== 'running') { stopPoll(); setPhase('done'); }
      } catch { /* transient */ }
    };
    tick();
    pollRef.current = window.setInterval(tick, 2000);
    return stopPoll;
  }, [phase]);

  // Resume mode: opened from the task console — skip compose, load preview.json.
  useEffect(() => {
    if (!resumeMode) return;
    (async () => {
      try {
        const p = await getBulkPreview();
        if (p.status === 'running') {
          setGenProgress(p.items?.length ?? 0);
          setGenTotal(p.total ?? 0);
          setPhase('generating');
        } else if (p.status === 'fresh') {
          setItems((p.items || []).map(it => ({ ...it, body: htmlToText(it.body) })));
          setSkippedCount(p.skipped?.length ?? 0);
          setPhase('review');
        } else {
          setPhase('compose');
        }
      } catch { setPhase('compose'); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeMode]);

  const minimize = (hint: 'generating' | 'committing') => {
    stopPoll();
    onMinimize?.(hint);
    onClose();
  };

  // Top-right X: while there's an un-committed batch (generating or awaiting
  // review), keep it in the task console instead of throwing it away.
  const handleClose = () => {
    if (onMinimize && (phase === 'generating' || phase === 'review')) {
      minimize('generating');
    } else {
      onClose();
    }
  };

  const generate = async () => {
    setError(null);
    try {
      await bulkGenerate({ emails, subject: subject.trim(), body: intent.trim(), personalize });
      setGenProgress(0);
      setGenTotal(emails.length);
      setPhase('generating');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const commit = async (send: boolean) => {
    setError(null);
    if (send) {
      const ok = window.confirm(
        `Send ${items.length} real email${items.length === 1 ? '' : 's'} now from your Outlook?\n\n` +
        `They go out immediately and cannot be recalled.`
      );
      if (!ok) return;
    }
    try {
      setCommittedSend(send);
      await bulkCommit({ items, send });
      onCommit?.();   // user acted on this batch → drop the console "pending" task
      setPhase('committing');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const editItem = (i: number, patch: Partial<BulkPreviewItem>) =>
    setItems(prev => prev.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  const removeItem = (i: number) => setItems(prev => prev.filter((_, idx) => idx !== i));

  const s = result?.summary;
  const sent = s?.sent ?? 0;
  const drafted = s?.drafts ?? 0;
  const errored = s?.errors ?? 0;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        onClick={e => e.stopPropagation()}
        className="bg-executive-card border border-executive-border rounded-xl max-w-2xl w-full p-6 shadow-xl max-h-[90vh] overflow-y-auto"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-executive-text flex items-center gap-2">
            <Send size={16} /> Bulk Email
          </h2>
          <button onClick={handleClose} className="text-executive-muted hover:text-executive-text">
            <X size={18} />
          </button>
        </div>

        {/* Recipients summary (compose only) */}
        {phase === 'compose' && (
          <>
            <button
              onClick={() => setShowList(v => !v)}
              className="w-full flex items-center gap-2 text-xs text-executive-muted hover:text-executive-text mb-3"
            >
              {showList ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Users size={12} />
              {emails.length} recipient{emails.length === 1 ? '' : 's'}
            </button>
            {showList && (
              <div className="mb-4 max-h-28 overflow-y-auto rounded-md border border-executive-border/60 bg-executive-bg/40 px-3 py-2 text-xs text-executive-muted space-y-1">
                {recipients.map(r => (
                  <div key={r.email} className="truncate">{r.name || r.email} <span className="text-executive-muted/60">· {r.email}</span></div>
                ))}
              </div>
            )}

            <div className="space-y-3">
              <div>
                <Label>Subject {personalize && <span className="normal-case font-normal text-executive-muted/60">(optional — AI writes one per contact if blank)</span>}</Label>
                <input
                  type="text" value={subject} onChange={e => setSubject(e.target.value)}
                  placeholder={personalize ? 'Leave blank to let AI write each subject' : 'Subject (supports {name}, {company})'}
                  className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
                />
              </div>
              <div>
                <Label>{personalize ? 'Message / brief' : 'Body'}</Label>
                <textarea
                  value={intent} onChange={e => setIntent(e.target.value)} rows={6}
                  placeholder={personalize
                    ? 'What is this email about? The AI rewrites it for each contact in their tone, weaving in your history with them. You review & edit every email before anything is saved or sent.'
                    : 'Exact body sent to everyone. Placeholders: {name}, {first_name}, {company}, {role}.'}
                  className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
                />
              </div>
              <Toggle
                checked={personalize} onChange={setPersonalize}
                title="Personalize per contact"
                desc="AI rewrites the message for each person in their tone, using your stored history. Off = the exact body above goes to everyone (with placeholders)."
              />
            </div>

            {error && <div className="mt-3 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-3 py-2">{error}</div>}

            <div className="flex justify-end gap-2 mt-5">
              <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-executive-border text-executive-muted hover:text-executive-text">Cancel</button>
              <button
                onClick={generate} disabled={!canGenerate}
                className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
              >
                <Wand2 size={14} /> Generate {emails.length} email{emails.length === 1 ? '' : 's'}
              </button>
            </div>
          </>
        )}

        {phase === 'generating' && (
          <div className="py-10 flex flex-col items-center gap-3 text-executive-muted">
            <Loader2 size={28} className="animate-spin text-executive-accent" />
            <div className="text-sm">Generating previews… {genProgress}/{genTotal || emails.length}</div>
            <div className="text-xs">Nothing is saved or sent yet — you'll review every email next.</div>
            {onMinimize && (
              <button
                onClick={() => minimize('generating')}
                className="mt-2 flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md border border-executive-border text-executive-muted hover:text-executive-text"
              >
                <Minimize2 size={12} /> Run in background
              </button>
            )}
          </div>
        )}

        {phase === 'review' && (
          <>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-executive-muted">
                Review &amp; edit each email. Nothing is saved or sent until you choose below.
                {skippedCount > 0 && <span className="text-amber-300"> · {skippedCount} skipped</span>}
              </p>
            </div>

            {items.length === 0 ? (
              <div className="text-center text-sm text-executive-muted py-8">No emails were generated.</div>
            ) : (
              <div className="space-y-3 max-h-[50vh] overflow-y-auto pr-1">
                {items.map((it, i) => (
                  <div key={`${it.to}-${i}`} className="rounded-lg border border-executive-border/60 bg-executive-bg/40 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-executive-text truncate">
                        {it.name || it.to} <span className="text-executive-muted/60">· {it.to}</span>
                      </span>
                      <button onClick={() => removeItem(i)} title="Remove from batch" className="text-executive-muted hover:text-rose-300 shrink-0">
                        <Trash2 size={13} />
                      </button>
                    </div>
                    <input
                      type="text" value={it.subject} onChange={e => editItem(i, { subject: e.target.value })}
                      placeholder="Subject"
                      className="w-full mb-2 px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
                    />
                    <textarea
                      value={it.body} onChange={e => editItem(i, { body: e.target.value })} rows={5}
                      className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
                    />
                  </div>
                ))}
              </div>
            )}

            {error && <div className="mt-3 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-3 py-2">{error}</div>}

            <div className="flex items-center justify-between gap-2 mt-5 pt-3 border-t border-executive-border/40">
              <button onClick={() => { setError(null); setPhase('compose'); }} className="px-3 py-2 text-xs rounded-md border border-executive-border text-executive-muted hover:text-executive-text">
                ← Back
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => commit(false)} disabled={items.length === 0}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
                >
                  <FileText size={14} /> Save {items.length} to Drafts
                </button>
                <button
                  onClick={() => commit(true)} disabled={items.length === 0}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-md bg-rose-500 text-white hover:opacity-90 disabled:opacity-40"
                >
                  <Send size={14} /> Send all
                </button>
              </div>
            </div>
          </>
        )}

        {phase === 'committing' && (
          <div className="py-10 flex flex-col items-center gap-3 text-executive-muted">
            <Loader2 size={28} className="animate-spin text-executive-accent" />
            <div className="text-sm">{committedSend ? 'Sending' : 'Saving drafts'}…</div>
            <div className="text-xs">You can close this — it keeps running, and Teams will ping you when it's done.</div>
          </div>
        )}

        {phase === 'done' && (
          <div className="py-4">
            {result?.status === 'error' ? (
              <div className="text-sm text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-3 py-2">{result?.error || 'Failed.'}</div>
            ) : (
              <>
                <div className="flex items-center gap-2 text-emerald-300 mb-3">
                  <CheckCircle2 size={18} />
                  <span className="text-sm font-medium">
                    {committedSend ? `${sent} sent` : `${drafted} drafts saved`}{errored > 0 && ` · ${errored} errors`}
                  </span>
                </div>
                {!committedSend && <p className="text-xs text-executive-muted mb-3">Drafts are in your Outlook Drafts folder — review and send them there.</p>}
                <div className="max-h-48 overflow-y-auto rounded-md border border-executive-border/60 bg-executive-bg/40 divide-y divide-executive-border/40">
                  {(result?.drafts_created || []).map((d, i) => (
                    <div key={i} className="flex items-center justify-between gap-2 px-3 py-1.5 text-xs">
                      <span className="truncate text-executive-text">{d.name || d.to} <span className="text-executive-muted/60">· {d.subject}</span></span>
                      {d.web_link
                        ? <a href={d.web_link} target="_blank" rel="noreferrer" className="text-executive-accent shrink-0 flex items-center gap-0.5">open <ExternalLink size={10} /></a>
                        : <span className="text-emerald-300/70 shrink-0">{committedSend ? 'sent' : ''}</span>}
                    </div>
                  ))}
                </div>
                {errored > 0 && (
                  <div className="mt-2 max-h-24 overflow-y-auto text-xs text-rose-300/80 space-y-0.5">
                    {(result?.errors || []).map((e, i) => <div key={i} className="truncate">{e.contact || e.file}: {e.error}</div>)}
                  </div>
                )}
              </>
            )}
            <div className="flex justify-end mt-5">
              <button onClick={onClose} className="px-4 py-2 text-sm rounded-md bg-executive-accent text-white hover:opacity-90">Done</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{children}</div>;
}

function Toggle({
  checked, onChange, title, desc,
}: {
  checked: boolean; onChange: (v: boolean) => void; title: string; desc: string;
}) {
  return (
    <label className="flex items-start gap-2.5 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="mt-0.5 accent-executive-accent" />
      <span>
        <span className="text-sm text-executive-text">{title}</span>
        <span className="block text-xs text-executive-muted">{desc}</span>
      </span>
    </label>
  );
}
