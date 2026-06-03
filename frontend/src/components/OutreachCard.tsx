import { useEffect, useMemo, useState } from 'react';
import {
  Loader2, ExternalLink, Inbox, ChevronDown, ChevronRight,
  FolderOpen, Tag, Clock, AlertCircle,
} from 'lucide-react';
import { getOutreachLast, relativeTime } from '../lib/api';
import type { OutreachLastRun } from '../lib/types';
import { useBotName } from '../App';

/** Body content for the Outreach tool — rendered inside the Tools page
 *  ToolPanel. Display-only: the table lists the most recent run's drafts.
 *  Runs are triggered via the Teams bot (see EmptyState hints). */
export default function OutreachCard() {
  const [data, setData] = useState<OutreachLastRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [skippedOpen, setSkippedOpen] = useState(false);

  useEffect(() => {
    getOutreachLast()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  const drafts = useMemo(() => data?.drafts_created ?? [], [data]);
  const skipped = useMemo(() => data?.contacts_skipped ?? [], [data]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-executive-muted py-4">
        <Loader2 size={14} className="animate-spin" /> Loading outreach drafts…
      </div>
    );
  }

  const hasRun = data?.status === 'fresh' && drafts.length > 0;

  if (!hasRun) return <EmptyState />;

  return (
    <div className="space-y-4">
      <RunSummary data={data!} />
      <DraftsTable drafts={drafts} />
      {skipped.length > 0 && (
        <SkippedSection
          skipped={skipped}
          open={skippedOpen}
          onToggle={() => setSkippedOpen(o => !o)}
        />
      )}
    </div>
  );
}

// ── Run summary card (folder/tag, time, count) ──────────────────────

function RunSummary({ data }: { data: OutreachLastRun }) {
  const sourceLabel = describeSource(data);
  const SourceIcon = sourceLabel.icon;
  const lastRun = data.last_run || data.ran_at;
  const count = data.summary?.drafts ?? data.drafts_created?.length ?? 0;
  const errorCount = data.summary?.errors ?? 0;

  return (
    <section className="bg-executive-bg/40 border border-executive-border rounded-lg px-4 py-3">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4 text-sm text-executive-muted">
          {lastRun && (
            <span className="flex items-center gap-1.5">
              <Clock size={13} />
              Last run <span className="text-executive-text">{relativeTime(lastRun)}</span>
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <SourceIcon size={13} />
            <span className="text-executive-text">{sourceLabel.label}</span>
          </span>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="px-2.5 py-1 rounded-md bg-emerald-400/10 text-emerald-300 font-medium">
            ✓ {count} drafts
          </span>
          {errorCount > 0 && (
            <span className="px-2.5 py-1 rounded-md bg-rose-400/10 text-rose-300 font-medium">
              {errorCount} errors
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

// ── Drafts table ────────────────────────────────────────────────────

function DraftsTable({ drafts }: { drafts: NonNullable<OutreachLastRun['drafts_created']> }) {
  return (
    <section className="bg-executive-bg/40 border border-executive-border rounded-lg overflow-hidden">
      <div className="grid grid-cols-[2fr_1.5fr_2fr_1.2fr_auto] gap-4 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-executive-muted border-b border-executive-border bg-executive-border/10">
        <div>Contact</div>
        <div>Company</div>
        <div>Subject</div>
        <div>Source</div>
        <div className="text-right pr-1">Open</div>
      </div>
      {drafts.map((d, i) => (
        <div
          key={`${d.to}-${i}`}
          className={`grid grid-cols-[2fr_1.5fr_2fr_1.2fr_auto] gap-4 px-4 py-3 items-start text-sm ${
            i < drafts.length - 1 ? 'border-b border-executive-border/60' : ''
          }`}
        >
          <div className="min-w-0">
            <div className="text-executive-text font-medium truncate">{d.name || '—'}</div>
            <div className="text-xs text-executive-muted truncate">{d.to}</div>
          </div>
          <div className="text-executive-text truncate">{d.company || '—'}</div>
          <div className="text-executive-text truncate" title={d.subject}>{d.subject}</div>
          <div className="text-xs text-executive-muted truncate" title={d.source_file}>
            {prettySource(d.source_file)}
          </div>
          <div className="text-right">
            {d.web_link ? (
              <a
                href={d.web_link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs text-executive-accent hover:bg-executive-accent/10 transition-colors"
              >
                <ExternalLink size={12} />
                Open
              </a>
            ) : (
              <span className="text-xs text-executive-muted">—</span>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

// ── Skipped section (collapsible) ───────────────────────────────────

function SkippedSection({
  skipped, open, onToggle,
}: {
  skipped: NonNullable<OutreachLastRun['contacts_skipped']>;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <section className="bg-executive-bg/30 border border-executive-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm text-executive-muted hover:bg-executive-border/15 transition-colors"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <AlertCircle size={13} className="text-amber-400" />
        <span>
          <span className="text-executive-text font-medium">{skipped.length}</span>{' '}
          contact{skipped.length === 1 ? '' : 's'} skipped
        </span>
      </button>
      {open && (
        <div className="px-4 pb-3 pt-1 space-y-2 text-sm border-t border-executive-border/60">
          {skipped.map((s, i) => {
            const c = s.contact || {};
            const who = c.name || c.email || 'Unknown contact';
            const email = c.email && c.email !== who ? ` (${c.email})` : '';
            return (
              <div key={i} className="flex items-baseline gap-3 py-1">
                <span className="text-executive-text">{who}{email}</span>
                <span className="text-executive-muted">—</span>
                <span className="text-xs text-executive-muted">{prettyReason(s.reason)}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

// ── Empty state ─────────────────────────────────────────────────────

function EmptyState() {
  const botName = useBotName();
  return (
    <section className="bg-executive-bg/40 border border-executive-border rounded-lg p-8 text-center">
      <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-executive-border/30 flex items-center justify-center">
        <Inbox size={20} className="text-executive-muted" />
      </div>
      <h3 className="text-base font-medium text-executive-text mb-2">No outreach drafts yet</h3>
      <p className="text-sm text-executive-muted mb-5 max-w-md mx-auto">
        Ask {botName} in Teams to draft outreach emails. Each contact becomes one Outlook Draft
        you can review and send.
      </p>
      <div className="inline-block text-left bg-executive-bg/60 border border-executive-border rounded-lg px-4 py-3 space-y-1.5 text-sm">
        <ExampleLine>"draft outreach for everyone in <em>/Contacts/Berlin AI Summit</em>"</ExampleLine>
        <ExampleLine>"draft outreach for everyone tagged <em>TechConf 2026</em>"</ExampleLine>
        <ExampleLine>"draft outreach for contacts I added today"</ExampleLine>
      </div>
    </section>
  );
}

function ExampleLine({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-executive-muted">
      <span className="text-executive-accent mr-2">›</span>
      <span className="text-executive-text/90">{children}</span>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────

function describeSource(data: OutreachLastRun): { label: string; icon: typeof FolderOpen } {
  const mode = (data as { mode?: string }).mode;
  const src = (data as { source?: string }).source;
  if (mode === 'crm') {
    if (src && src.startsWith('recent_')) {
      const hours = src.replace('recent_', '').replace('h', '');
      return { label: `Contacts added in last ${hours}h`, icon: Clock };
    }
    return { label: `Tag: ${src || 'CRM'}`, icon: Tag };
  }
  return { label: data.folder || '—', icon: FolderOpen };
}

function prettySource(s?: string): string {
  if (!s) return '—';
  if (s.startsWith('CRM:')) {
    const rest = s.slice(4);
    if (rest === 'recent' || rest.startsWith('recent_')) return 'CRM (recent)';
    return `Tag: ${rest}`;
  }
  return s;
}

function prettyReason(reason: string): string {
  switch (reason) {
    case 'no_email':         return 'No email address';
    case 'draft_gen_failed': return 'AI draft generation failed';
    default:                 return reason;
  }
}
