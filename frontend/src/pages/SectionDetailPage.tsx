import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  ArrowLeft, RefreshCw, Loader2, Sliders, ExternalLink,
  Check, Clock, X, Mail, Send, Video, AlertTriangle,
  CheckCircle2, CalendarDays, HeartPulse, Sparkles,
} from 'lucide-react';
import DraftComposer from '../components/DraftComposer';
import type { LucideIcon } from 'lucide-react';
import {
  getSection, runSection,
  markCommitmentDone, snoozeCommitment, updateProject, updateCrmContact,
  relativeTime,
} from '../lib/api';
import { SECTION_BY_ID } from '../lib/sections';
import { useActivity } from '../components/ActivityDrawer';
import type {
  SectionResult, ReplyNeededItem, FollowupItem, CommitmentItem,
  MeetingTodayItem, ProjectItem, RelationshipItem,
} from '../lib/types';

interface Props {
  sectionId: string;          // initial tab — from dashboard click
  goBack: () => void;
  goToCustomize: (sectionId: string) => void;
}

interface TabDef { id: string; label: string; icon: LucideIcon; color: string; }

const TABS: TabDef[] = [
  { id: 'reply_needed',               label: 'Reply Needed',    icon: Mail,          color: 'text-sky-400' },
  { id: 'followup_needed',            label: 'Sent — No Resp',  icon: Send,          color: 'text-orange-400' },
  { id: 'due_today',                  label: 'Due Today',       icon: CheckCircle2,  color: 'text-emerald-400' },
  { id: 'meetings_today',             label: 'Meetings Today',  icon: CalendarDays,  color: 'text-violet-400' },
  { id: 'projects_needing_attention', label: 'Projects Attn',   icon: AlertTriangle, color: 'text-rose-400' },
  { id: 'relationship_health',        label: 'Cooling Rels',    icon: HeartPulse,    color: 'text-pink-400' },
];

export default function SectionDetailPage({ sectionId, goBack, goToCustomize }: Props) {
  // The active tab — starts at whichever stat the user clicked on dashboard.
  const [activeId, setActiveId] = useState<string>(sectionId);

  // Cache results per tab so switching tabs doesn't re-fetch + lose state.
  const [results, setResults] = useState<Record<string, SectionResult | null>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actioned, setActioned] = useState<Record<string, Set<string>>>({});
  const activity = useActivity();

  const meta = SECTION_BY_ID[activeId];
  const activeResult = results[activeId] ?? null;

  // Fetch all 6 tabs on mount so tab labels can show counts immediately.
  const fetchAll = useCallback(async () => {
    setLoading(true);
    const ids = TABS.map(t => t.id);
    const fetched = await Promise.all(ids.map(id => getSection(id).catch(() => null)));
    const map: Record<string, SectionResult | null> = {};
    ids.forEach((id, i) => (map[id] = fetched[i]));
    setResults(map);
    setActioned({});
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // If the dashboard re-opens the page with a different initial section, follow it.
  useEffect(() => { setActiveId(sectionId); }, [sectionId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    activity.start(activeId);
    try {
      await runSection(activeId);
      const start = Date.now();
      while (Date.now() - start < 90_000) {
        await new Promise(r => setTimeout(r, 2500));
        const fresh = await getSection(activeId).catch(() => null);
        if (fresh && fresh.status !== 'running') {
          setResults(r => ({ ...r, [activeId]: fresh }));
          setActioned(a => ({ ...a, [activeId]: new Set() }));
          break;
        }
      }
    } finally {
      setRefreshing(false);
    }
  };

  const items = useMemo(() => {
    const dismissed = actioned[activeId] ?? new Set();
    return ((activeResult?.items as Record<string, unknown>[] | undefined) ?? [])
      .filter((it) => !dismissed.has(itemKey(activeId, it)));
  }, [activeResult, actioned, activeId]);

  const markActioned = (item: Record<string, unknown>) => {
    setActioned(prev => {
      const next = { ...prev };
      const set = new Set(next[activeId] ?? []);
      set.add(itemKey(activeId, item));
      next[activeId] = set;
      return next;
    });
  };

  // Per-tab visible count (after local actioned filter, just like main body).
  const countFor = (id: string): number => {
    const r = results[id];
    if (!r) return 0;
    const dismissed = actioned[id] ?? new Set();
    if (id === 'relationship_health') {
      // dashboard "Cooling Rels" definition — only count health=cooling/at_risk/stalled
      const its = (r.items as RelationshipItem[] | undefined) ?? [];
      return its.filter(it =>
        !dismissed.has(itemKey(id, it as unknown as Record<string, unknown>))
        && (it.health === 'cooling' || it.health === 'at_risk' || it.health === 'stalled'),
      ).length;
    }
    const its = (r.items as Record<string, unknown>[] | undefined) ?? [];
    return its.filter(it => !dismissed.has(itemKey(id, it))).length;
  };

  if (!meta) {
    return (
      <div className="p-8 max-w-6xl mx-auto">
        <button onClick={goBack} className="text-sm text-executive-muted hover:text-executive-text">
          ← Back
        </button>
        <p className="mt-4 text-executive-muted">Unknown section: {activeId}</p>
      </div>
    );
  }

  const totalCount = items.length;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-5">
      {/* Back link */}
      <button
        onClick={goBack}
        className="flex items-center gap-1.5 text-xs text-executive-muted hover:text-executive-text transition-colors"
      >
        <ArrowLeft size={13} />
        Back to Dashboard
      </button>

      {/* Tab bar — one segmented strip like the dashboard's, but with active state */}
      <nav
        className="bg-executive-card border border-executive-border rounded-xl overflow-hidden
                   flex divide-x divide-executive-border"
      >
        {TABS.map(t => {
          const Icon = t.icon;
          const active = t.id === activeId;
          const v = countFor(t.id);
          return (
            <button
              key={t.id}
              onClick={() => setActiveId(t.id)}
              className={`group relative flex-1 min-w-0 px-4 py-3 text-left transition-colors
                          ${active ? 'bg-executive-border/30' : 'hover:bg-executive-border/15'}`}
            >
              {active && (
                <span className={`absolute inset-x-0 top-0 h-0.5 ${t.color.replace('text-', 'bg-')}`} />
              )}
              <div className="flex items-center gap-2 mb-1">
                <Icon size={14} className={t.color} />
                <span className={`text-lg font-semibold tabular-nums ${active ? 'text-executive-text' : 'text-executive-text/80'}`}>
                  {loading ? '—' : v}
                </span>
              </div>
              <div className={`text-[11px] truncate ${active ? 'text-executive-text' : 'text-executive-muted'}`}>
                {t.label}
              </div>
            </button>
          );
        })}
      </nav>

      {/* Section header */}
      <header className="flex items-end justify-between gap-4 flex-wrap pt-2">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.14em] font-semibold text-executive-muted">
            {totalCount} {totalCount === 1 ? 'item' : 'items'}
            {activeResult?.last_run && <span> · synced {relativeTime(activeResult.last_run)}</span>}
          </p>
          <p className="text-sm text-executive-muted mt-1">{meta.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => goToCustomize(activeId)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-muted hover:text-executive-text transition-colors"
          >
            <Sliders size={12} />
            Customize
          </button>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-muted hover:text-executive-text transition-colors disabled:opacity-50"
          >
            {refreshing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {/* Body */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-executive-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState sectionId={activeId} />
      ) : (
        <ul className="space-y-3">
          {items.map((it, i) => (
            <li key={itemKey(activeId, it) + '-' + i}>
              {renderCard(activeId, it, () => markActioned(it))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────
// Stable item identity per section — needed so the actioned
// set can hide items even if the backend hasn't refreshed yet.

function itemKey(sectionId: string, item: Record<string, unknown>): string {
  switch (sectionId) {
    case 'reply_needed':
    case 'followup_needed':
      return String(item.email_id ?? item.subject ?? Math.random());
    case 'due_today':
      return String(item.id ?? item.email_id ?? Math.random());
    case 'meetings_today':
      return String(item.id ?? item.subject ?? Math.random());
    case 'projects_needing_attention':
      return String(item.project_id ?? item.id ?? Math.random());
    case 'relationship_health':
      return String(item.contact_email ?? item.id ?? Math.random());
    default:
      return String(item.id ?? Math.random());
  }
}

function renderCard(
  sectionId: string,
  item: Record<string, unknown>,
  onActioned: () => void,
) {
  switch (sectionId) {
    case 'reply_needed':
      return <ReplyNeededCard item={item as unknown as ReplyNeededItem} onActioned={onActioned} />;
    case 'followup_needed':
      return <FollowupCard item={item as unknown as FollowupItem} onActioned={onActioned} />;
    case 'due_today':
      return <DueTodayCard item={item as unknown as CommitmentItem} onActioned={onActioned} />;
    case 'meetings_today':
      return <MeetingCard item={item as unknown as MeetingTodayItem} />;
    case 'projects_needing_attention':
      return <ProjectCard item={item as unknown as ProjectItem} onActioned={onActioned} />;
    case 'relationship_health':
      return <RelationshipCard item={item as unknown as RelationshipItem} onActioned={onActioned} />;
    default:
      return <GenericCard item={item} />;
  }
}

function EmptyState({ sectionId }: { sectionId: string }) {
  const msg: Record<string, string> = {
    reply_needed:                'Inbox clean — nothing waiting on you.',
    followup_needed:             'No pending follow-ups. Everyone has responded.',
    due_today:                   'Nothing due today.',
    meetings_today:              'No meetings on your calendar today.',
    projects_needing_attention:  'All projects are on track.',
    relationship_health:         'All key relationships look healthy.',
  };
  return (
    <div className="bg-executive-card border border-executive-border rounded-xl py-14 text-center">
      <p className="text-sm text-executive-muted italic">
        {msg[sectionId] ?? 'Nothing to show.'}
      </p>
    </div>
  );
}

// ───────────────────────────────────────────────────────────
// Reusable bits

const PRIORITY_TAG: Record<string, string> = {
  high:   'bg-rose-400/15 text-rose-300 border-rose-400/30',
  medium: 'bg-amber-400/15 text-amber-300 border-amber-400/30',
  low:    'bg-emerald-400/15 text-emerald-300 border-emerald-400/30',
};

function PriorityBadge({ priority }: { priority?: string }) {
  if (!priority) return null;
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold border ${PRIORITY_TAG[priority] ?? 'bg-executive-border text-executive-muted border-executive-border'}`}>
      {priority}
    </span>
  );
}

function ActionBar({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-3 pt-3 border-t border-executive-border/60 flex items-center justify-end gap-2">
      {children}
    </div>
  );
}

interface BtnProps {
  onClick?: () => void;
  href?: string;
  icon?: React.ReactNode;
  variant?: 'primary' | 'ghost' | 'danger';
  disabled?: boolean;
  children: React.ReactNode;
}

function Btn({ onClick, href, icon, variant = 'ghost', disabled, children }: BtnProps) {
  const base = "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-50";
  const styles =
    variant === 'primary'
      ? 'bg-executive-accent/10 hover:bg-executive-accent/20 border-executive-accent/30 text-executive-accent'
      : variant === 'danger'
        ? 'border-rose-400/30 text-rose-400 hover:bg-rose-400/10'
        : 'border-executive-border hover:bg-executive-border/30 text-executive-muted hover:text-executive-text';
  const cls = `${base} ${styles}`;
  if (href) {
    return <a href={href} target="_blank" rel="noreferrer" className={cls}>{icon}{children}</a>;
  }
  return <button onClick={onClick} disabled={disabled} className={cls}>{icon}{children}</button>;
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-executive-card border border-executive-border rounded-xl p-4 hover:border-executive-border/80 transition-colors">
      {children}
    </div>
  );
}

// ───────────────────────────────────────────────────────────
// Per-section item cards

function ReplyNeededCard({ item, onActioned }: { item: ReplyNeededItem; onActioned: () => void }) {
  const [drafting, setDrafting] = useState(false);
  const outlookUrl = item.email_id
    ? `https://outlook.office.com/mail/inbox/id/${encodeURIComponent(item.email_id)}`
    : 'https://outlook.office.com/mail/inbox';
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-semibold text-executive-text leading-snug min-w-0 flex-1">
          {item.subject || '(no subject)'}
        </h3>
        <PriorityBadge priority={item.priority} />
      </div>
      <p className="text-xs text-executive-muted">
        <Mail size={11} className="inline mr-1 -mt-0.5" />
        {item.from_name || item.from_email || 'Unknown sender'}
        {item.from_email && item.from_name && <span className="opacity-60"> · {item.from_email}</span>}
        {item.received && <span className="opacity-60"> · {item.received.slice(0, 10)}</span>}
      </p>
      {item.reason && (
        <p className="text-sm text-executive-text/85 mt-3">
          <span className="text-executive-muted">Why: </span>{item.reason}
        </p>
      )}
      {item.suggested_opening && (
        <p className="text-sm text-executive-text/70 italic mt-2 pl-3 border-l-2 border-amber-400/40">
          "{item.suggested_opening}"
        </p>
      )}
      <ActionBar>
        <Btn
          onClick={() => setDrafting(d => !d)}
          icon={<Sparkles size={12} />}
          variant="primary"
        >
          {drafting ? 'Hide draft' : 'Draft reply'}
        </Btn>
        <Btn href={outlookUrl} icon={<ExternalLink size={12} />}>Open in Outlook</Btn>
        <Btn onClick={onActioned} icon={<Check size={12} />}>Mark handled</Btn>
      </ActionBar>
      {drafting && (
        <DraftComposer
          emailId={item.email_id}
          mode="reply"
          hints={{
            reason: item.reason,
            suggested_opening: item.suggested_opening,
            reply_tone: item.reply_tone,
          }}
          onClose={() => setDrafting(false)}
        />
      )}
    </Card>
  );
}

function FollowupCard({ item, onActioned }: { item: FollowupItem; onActioned: () => void }) {
  const [drafting, setDrafting] = useState(false);
  const outlookUrl = item.email_id
    ? `https://outlook.office.com/mail/sentitems/id/${encodeURIComponent(item.email_id)}`
    : 'https://outlook.office.com/mail/sentitems';
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-semibold text-executive-text leading-snug min-w-0 flex-1">
          {item.subject || '(no subject)'}
        </h3>
        <PriorityBadge priority={item.urgency} />
      </div>
      <p className="text-xs text-executive-muted">
        <Send size={11} className="inline mr-1 -mt-0.5" />
        To {item.to_name || item.to_email || '—'}
        {typeof item.days_waiting === 'number' && (
          <span className="opacity-80"> · waiting {item.days_waiting}d</span>
        )}
      </p>
      {item.reason && (
        <p className="text-sm text-executive-text/85 mt-3">
          <span className="text-executive-muted">Why nudge: </span>{item.reason}
        </p>
      )}
      <ActionBar>
        <Btn
          onClick={() => setDrafting(d => !d)}
          icon={<Sparkles size={12} />}
          variant="primary"
        >
          {drafting ? 'Hide draft' : 'Draft follow-up'}
        </Btn>
        <Btn href={outlookUrl} icon={<ExternalLink size={12} />}>Open thread</Btn>
        <Btn onClick={onActioned} icon={<X size={12} />}>Dismiss</Btn>
      </ActionBar>
      {drafting && (
        <DraftComposer
          emailId={item.email_id}
          mode="followup"
          hints={{
            reason: item.reason,
            urgency: item.urgency,
            days_waiting: item.days_waiting,
          }}
          onClose={() => setDrafting(false)}
        />
      )}
    </Card>
  );
}

function DueTodayCard({ item, onActioned }: { item: CommitmentItem; onActioned: () => void }) {
  const [busy, setBusy] = useState(false);
  const handleDone = async () => {
    setBusy(true);
    try { await markCommitmentDone(item.id); onActioned(); }
    finally { setBusy(false); }
  };
  const handleSnooze = async () => {
    setBusy(true);
    try { await snoozeCommitment(item.id, 3); onActioned(); }
    finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-1">
        <h3 className="text-sm font-medium text-executive-text leading-snug min-w-0 flex-1">
          {item.description}
        </h3>
        <PriorityBadge priority={item.priority} />
      </div>
      <p className="text-xs text-executive-muted">
        {item.due_date && <span>Due {item.due_date.slice(0, 10)}</span>}
        {item.contact_name && <span> · {item.contact_name}</span>}
        {!item.contact_name && item.contact_email && <span> · {item.contact_email}</span>}
        {item.type === 'their_commitment' && <span className="ml-2 text-amber-400">↩ they owe you</span>}
      </p>
      {item.subject && (
        <p className="text-xs text-executive-muted/70 mt-2 italic truncate">
          from email: "{item.subject}"
        </p>
      )}
      <ActionBar>
        <Btn onClick={handleDone} disabled={busy} icon={<Check size={12} />} variant="primary">
          Mark done
        </Btn>
        <Btn onClick={handleSnooze} disabled={busy} icon={<Clock size={12} />}>Snooze 3d</Btn>
      </ActionBar>
    </Card>
  );
}

function MeetingCard({ item }: { item: MeetingTodayItem }) {
  const teamsUrl = (item.body_preview || '').match(/https:\/\/teams\.microsoft\.com\/\S+/)?.[0];
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-semibold text-executive-text leading-snug min-w-0 flex-1">
          {item.subject || '(no subject)'}
        </h3>
        {item.start_time && (
          <span className="text-xs font-semibold tabular-nums text-violet-400 flex-shrink-0">
            {item.start_time}{item.end_time ? `–${item.end_time}` : ''}
          </span>
        )}
      </div>
      {(item.attendees?.length ?? 0) > 0 && (
        <p className="text-xs text-executive-muted">
          with {item.attendees.slice(0, 4).join(', ')}
          {item.attendees.length > 4 && <span> +{item.attendees.length - 4}</span>}
        </p>
      )}
      {item.location && (
        <p className="text-xs text-executive-muted mt-1 truncate">📍 {item.location}</p>
      )}
      <ActionBar>
        {teamsUrl && (
          <Btn href={teamsUrl} icon={<Video size={12} />} variant="primary">Join Teams</Btn>
        )}
        <Btn href="https://outlook.office.com/calendar/view/day" icon={<ExternalLink size={12} />}>
          Open calendar
        </Btn>
      </ActionBar>
    </Card>
  );
}

function ProjectCard({ item, onActioned }: { item: ProjectItem; onActioned: () => void }) {
  const [busy, setBusy] = useState(false);
  const handleResolve = async () => {
    setBusy(true);
    try { await updateProject(item.project_id, { status: 'ongoing' }); onActioned(); }
    finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="text-sm font-semibold text-executive-text leading-snug min-w-0 flex-1">
          {item.name}
        </h3>
        <PriorityBadge priority={item.priority} />
      </div>
      <p className="text-xs text-executive-muted">
        <AlertTriangle size={11} className="inline mr-1 -mt-0.5" />
        {item.status} · {item.momentum} momentum
        {item.last_activity && <span> · last active {item.last_activity.slice(0, 10)}</span>}
      </p>
      {item.summary && (
        <p className="text-sm text-executive-text/85 mt-3">{item.summary}</p>
      )}
      {item.next_action && (
        <p className="text-sm text-executive-text/70 mt-2 pl-3 border-l-2 border-emerald-400/40">
          <span className="text-executive-muted">Next: </span>{item.next_action}
        </p>
      )}
      <ActionBar>
        <Btn onClick={handleResolve} disabled={busy} icon={<Check size={12} />} variant="primary">
          Mark resolved
        </Btn>
      </ActionBar>
    </Card>
  );
}

function RelationshipCard({ item, onActioned }: { item: RelationshipItem; onActioned: () => void }) {
  const [busy, setBusy] = useState(false);
  const handleIgnore = async () => {
    setBusy(true);
    try { await updateCrmContact(item.contact_email, { ignore: true }); onActioned(); }
    finally { setBusy(false); }
  };
  const m = item.metrics;
  return (
    <Card>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-executive-text leading-snug">
            {item.contact_name || item.contact_email}
          </h3>
          {item.company && (
            <p className="text-xs text-executive-muted mt-0.5">{item.company}</p>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-[10px] uppercase font-semibold text-rose-300 bg-rose-400/15 px-1.5 py-0.5 rounded border border-rose-400/30">
            {item.health}
          </span>
          <PriorityBadge priority={item.priority} />
        </div>
      </div>
      <p className="text-xs text-executive-muted">
        {m.emails_in_30d ?? 0} in · {m.emails_out_30d ?? 0} out (last 30d)
        {typeof m.trend_pct === 'number' && (
          <span className={m.trend_pct < 0 ? ' text-rose-400' : ' text-emerald-400'}>
            {' · '}{m.trend_pct >= 0 ? '+' : ''}{m.trend_pct}% vs prior
          </span>
        )}
        {m.days_since_inbound !== undefined && m.days_since_inbound !== null && (
          <span className="opacity-70"> · {m.days_since_inbound}d since they wrote</span>
        )}
      </p>
      {item.suggested_action && (
        <p className="text-sm text-executive-text/85 mt-3">
          <span className="text-executive-muted">Suggested: </span>{item.suggested_action}
        </p>
      )}
      <ActionBar>
        <Btn
          href={`mailto:${item.contact_email}`}
          icon={<Mail size={12} />}
          variant="primary"
        >
          Reach out
        </Btn>
        <Btn onClick={handleIgnore} disabled={busy} icon={<X size={12} />}>
          Ignore contact
        </Btn>
      </ActionBar>
    </Card>
  );
}

function GenericCard({ item }: { item: Record<string, unknown> }) {
  return (
    <Card>
      <pre className="text-xs text-executive-muted whitespace-pre-wrap">
        {JSON.stringify(item, null, 2)}
      </pre>
    </Card>
  );
}
