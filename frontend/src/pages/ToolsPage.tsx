import { useEffect, useState } from 'react';
import { Mail, Loader2, Play, ExternalLink, FolderOpen, AlertCircle, Receipt, ChevronDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { runOutreach, getOutreachLast, relativeTime } from '../lib/api';
import type { OutreachLastRun } from '../lib/types';
// Expense remains physically in pages/records/ — moved here as a Tool by intent,
// but the file is left in place because other in-flight work uses it as a template.
import ExpensesTab from './records/ExpensesTab';

export default function ToolsPage() {
  // Independent toggle state — user can have multiple tools open at once.
  // Outreach starts expanded since it's the more "actionable" tool.
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['outreach']));
  const toggle = (id: string) => setExpanded(s => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const [last, setLast] = useState<OutreachLastRun | null>(null);
  const [loadingLast, setLoadingLast] = useState(true);

  useEffect(() => {
    getOutreachLast()
      .then(setLast)
      .catch(() => setLast(null))
      .finally(() => setLoadingLast(false));
  }, []);

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-4">
      <header className="mb-2">
        <h1 className="text-2xl font-semibold text-executive-text">Personal Tools</h1>
        <p className="text-sm text-executive-muted mt-1">
          On-demand workflows and personal utilities. Click a tool to expand it.
        </p>
      </header>

      <ToolPanel
        id="outreach"
        icon={Mail}
        title="Outreach"
        subtitle="Bulk-draft personalised emails from a OneDrive folder of contacts."
        expanded={expanded.has('outreach')}
        onToggle={() => toggle('outreach')}
      >
        <OutreachCard last={last} loadingLast={loadingLast} onRunComplete={() => {
          getOutreachLast().then(setLast).catch(() => undefined);
        }} />
      </ToolPanel>

      <ToolPanel
        id="expenses"
        icon={Receipt}
        title="Expenses"
        subtitle="Receipts auto-captured from email attachments, Teams DMs, and OneDrive."
        expanded={expanded.has('expenses')}
        onToggle={() => toggle('expenses')}
      >
        <ExpensesTab />
      </ToolPanel>

      <div className="bg-executive-card/40 border border-dashed border-executive-border rounded-xl p-6 text-center text-sm text-executive-muted">
        <FolderOpen size={20} className="mx-auto mb-2 opacity-50" />
        More tools will appear here as they're added.
      </div>
    </div>
  );
}

// ── ToolPanel: collapsible card ───────────────────────────

function ToolPanel({
  icon: Icon, title, subtitle, expanded, onToggle, children,
}: {
  id: string;            // accepted for documentation only
  icon: LucideIcon;
  title: string;
  subtitle: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-executive-card border border-executive-border rounded-xl overflow-hidden transition-colors hover:border-executive-border/80">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-4 px-5 py-4 text-left hover:bg-executive-border/15 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${expanded ? 'bg-executive-accent/15 text-executive-accent' : 'bg-executive-border/40 text-executive-muted'}`}>
            <Icon size={16} />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-executive-text">{title}</h2>
            <p className="text-xs text-executive-muted mt-0.5">{subtitle}</p>
          </div>
        </div>
        <ChevronDown
          size={16}
          className={`text-executive-muted shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && (
        <div className="px-5 pb-5 pt-1 border-t border-executive-border/60">
          {children}
        </div>
      )}
    </section>
  );
}

// ───────────────────────────────────────────────────────────

function OutreachCard({
  last, loadingLast, onRunComplete,
}: {
  last: OutreachLastRun | null;
  loadingLast: boolean;
  onRunComplete: () => void;
}) {
  const [folder, setFolder] = useState('');
  const [note, setNote] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const handleRun = async () => {
    if (!folder.trim()) {
      setError('OneDrive folder path is required.');
      return;
    }
    setError(null);
    setSuccess(null);
    setRunning(true);
    try {
      await runOutreach(folder.trim(), note.trim());
      setSuccess('Outreach is running in the background. Drafts will appear in Outlook Drafts as they finish.');
      onRunComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-executive-card border border-executive-border rounded-xl p-6">
      <div className="flex items-start gap-4 mb-4">
        <div className="p-2.5 rounded-lg bg-executive-accent/10 text-executive-accent">
          <Mail size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-base font-semibold text-executive-text">Outreach</h2>
          <p className="text-sm text-executive-muted mt-1">
            Generate personalized email drafts from a OneDrive folder of contact files (CSVs, business
            card scans, attendee lists). Each contact becomes one Outlook Draft you can review and send.
          </p>
        </div>
      </div>

      <div className="space-y-3 mt-4">
        <FormField label="OneDrive folder path" hint="e.g. /Contacts/Conference Q2/">
          <input
            type="text"
            value={folder}
            onChange={e => setFolder(e.target.value)}
            placeholder="/Contacts/Conference Q2/"
            className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-lg text-executive-text placeholder:text-executive-muted/60 focus:outline-none focus:border-executive-accent/60"
          />
        </FormField>

        <FormField label="Context note" hint="Optional. Will be used to personalize each email.">
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="Met you at Berlin AI Summit, want to follow up on the agentic systems discussion…"
            rows={3}
            className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-lg text-executive-text placeholder:text-executive-muted/60 focus:outline-none focus:border-executive-accent/60 resize-y"
          />
        </FormField>

        {error && (
          <div className="flex items-start gap-2 px-3 py-2 bg-rose-400/10 border border-rose-400/30 rounded-lg text-xs text-rose-300">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {success && (
          <div className="px-3 py-2 bg-emerald-400/10 border border-emerald-400/30 rounded-lg text-xs text-emerald-300">
            {success}
          </div>
        )}

        <div className="flex items-center justify-between pt-2">
          <div className="text-xs text-executive-muted">
            {loadingLast ? (
              <span className="flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Loading…</span>
            ) : last?.ran_at ? (
              <span>
                Last run {relativeTime(last.ran_at)} ·{' '}
                <span className="text-executive-text">{last.drafts_created ?? 0}</span> drafts created
                {(last.errors ?? 0) > 0 && (
                  <span className="text-rose-400"> · {last.errors} errors</span>
                )}
              </span>
            ) : (
              <span>No previous runs.</span>
            )}
          </div>
          <button
            onClick={handleRun}
            disabled={running || !folder.trim()}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-executive-accent text-white hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? 'Starting…' : 'Run Outreach'}
          </button>
        </div>

        {last?.log && last.log.length > 0 && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-executive-muted hover:text-executive-text inline-flex items-center gap-1">
              <ExternalLink size={11} /> View last run log
            </summary>
            <pre className="mt-2 p-3 bg-executive-bg border border-executive-border rounded-lg text-executive-muted overflow-x-auto max-h-60">
              {last.log.join('\n')}
            </pre>
          </details>
        )}
      </div>
    </div>
  );
}

function FormField({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-xs font-medium text-executive-text mb-1">{label}</div>
      {hint && <div className="text-[11px] text-executive-muted mb-1.5">{hint}</div>}
      {children}
    </label>
  );
}
