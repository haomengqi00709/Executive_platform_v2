import { useEffect, useState, useCallback } from 'react';
import {
  Mail, Send, CheckCircle2, CalendarDays, AlertTriangle,
  HeartPulse, RefreshCw, ChevronRight, Sunrise, Loader2,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import {
  getSection, runSection, relativeTime,
} from '../lib/api';
import type {
  SectionResult, ReplyNeededItem, CommitmentItem, ProjectItem, RelationshipItem,
} from '../lib/types';

interface DashboardPageProps {
  goToSkill: (sectionId: string) => void;
}

export default function DashboardPage({ goToSkill }: DashboardPageProps) {
  const [briefing, setBriefing] = useState<SectionResult | null>(null);
  const [stats, setStats] = useState<Record<string, SectionResult | null>>({});
  const [loading, setLoading] = useState(true);
  const [rerunning, setRerunning] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    const ids = [
      'ai_summary',
      'reply_needed', 'followup_needed', 'due_today',
      'meetings_today', 'projects_needing_attention', 'relationship_health',
    ];
    const results = await Promise.all(
      ids.map(id => getSection(id).catch(() => null)),
    );
    const map: Record<string, SectionResult | null> = {};
    ids.forEach((id, i) => (map[id] = results[i]));
    setBriefing(map.ai_summary);
    setStats(map);
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleRerunBriefing = async () => {
    setRerunning(true);
    try {
      await runSection('ai_summary');
      // Poll for completion (briefing usually finishes in ~30s)
      const start = Date.now();
      while (Date.now() - start < 90_000) {
        await new Promise(r => setTimeout(r, 3000));
        const fresh = await getSection('ai_summary').catch(() => null);
        if (fresh && fresh.status !== 'running') {
          setBriefing(fresh);
          break;
        }
      }
    } finally {
      setRerunning(false);
    }
  };

  const replyItems = (stats.reply_needed?.items as ReplyNeededItem[] | undefined) ?? [];
  const dueItems = (stats.due_today?.items as CommitmentItem[] | undefined) ?? [];
  const attnItems = (stats.projects_needing_attention?.items as ProjectItem[] | undefined) ?? [];
  const rhItems = (stats.relationship_health?.items as RelationshipItem[] | undefined) ?? [];
  const coolingCount = rhItems.filter(it => it.health === 'cooling' || it.health === 'at_risk' || it.health === 'stalled').length;

  const today = new Date().toLocaleDateString(undefined, {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <header>
        <h1 className="text-2xl font-semibold text-executive-text">Dashboard</h1>
        <p className="text-sm text-executive-muted mt-1">
          {today}
          {briefing?.last_run && <span> · Last sync {relativeTime(briefing.last_run)}</span>}
        </p>
      </header>

      {/* Briefing hero */}
      <section className="bg-executive-card border border-executive-border rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex items-center gap-2">
            <Sunrise size={18} className="text-amber-400" />
            <h2 className="text-sm font-semibold text-executive-text uppercase tracking-wider">
              AI Morning Briefing
            </h2>
          </div>
          <button
            onClick={handleRerunBriefing}
            disabled={rerunning}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-muted hover:text-executive-text transition-colors disabled:opacity-50"
          >
            {rerunning ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            {rerunning ? 'Refreshing…' : 'Re-run'}
          </button>
        </div>
        {loading ? (
          <div className="h-20 flex items-center justify-center text-executive-muted">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : briefing?.briefing ? (
          <p className="text-sm leading-relaxed text-executive-text whitespace-pre-wrap">
            {briefing.briefing}
          </p>
        ) : (
          <p className="text-sm text-executive-muted italic">
            No briefing available yet. Click Re-run to generate one.
          </p>
        )}
      </section>

      {/* Stat cards grid */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard
          icon={Mail} label="Reply Needed"
          value={stats.reply_needed?.count ?? 0}
          color="text-sky-400"
          onClick={() => goToSkill('reply_needed')}
          loading={loading}
        />
        <StatCard
          icon={Send} label="Sent — No Resp"
          value={stats.followup_needed?.count ?? 0}
          color="text-orange-400"
          onClick={() => goToSkill('followup_needed')}
          loading={loading}
        />
        <StatCard
          icon={CheckCircle2} label="Due Today"
          value={stats.due_today?.count ?? 0}
          color="text-emerald-400"
          onClick={() => goToSkill('due_today')}
          loading={loading}
        />
        <StatCard
          icon={CalendarDays} label="Meetings Today"
          value={stats.meetings_today?.count ?? 0}
          color="text-violet-400"
          onClick={() => goToSkill('meetings_today')}
          loading={loading}
        />
        <StatCard
          icon={AlertTriangle} label="Projects Attn"
          value={stats.projects_needing_attention?.count ?? 0}
          color="text-rose-400"
          onClick={() => goToSkill('projects_needing_attention')}
          loading={loading}
        />
        <StatCard
          icon={HeartPulse} label="Cooling Rels"
          value={coolingCount}
          color="text-pink-400"
          onClick={() => goToSkill('relationship_health')}
          loading={loading}
        />
      </section>

      {/* Today's priorities */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <PriorityList
          title="Top emails to reply"
          icon={Mail}
          accent="text-sky-400"
          totalCount={stats.reply_needed?.count ?? 0}
          onSeeAll={() => goToSkill('reply_needed')}
          items={replyItems.slice(0, 3).map(it => ({
            primary: it.subject || '(no subject)',
            secondary: it.from_name || it.from_email || '—',
            badge: it.priority,
          }))}
          emptyMsg="Inbox clean."
        />
        <PriorityList
          title="Top commitments due"
          icon={CheckCircle2}
          accent="text-emerald-400"
          totalCount={stats.due_today?.count ?? 0}
          onSeeAll={() => goToSkill('due_today')}
          items={dueItems.slice(0, 3).map(it => ({
            primary: it.description || '—',
            secondary: it.contact_name || it.contact_email || '',
            badge: it.priority,
          }))}
          emptyMsg="Nothing due today."
        />
        <PriorityList
          title="Top projects needing attention"
          icon={AlertTriangle}
          accent="text-rose-400"
          totalCount={stats.projects_needing_attention?.count ?? 0}
          onSeeAll={() => goToSkill('projects_needing_attention')}
          items={attnItems.slice(0, 3).map(it => ({
            primary: it.name || '—',
            secondary: `${it.status} · ${it.momentum} momentum`,
            badge: it.priority,
          }))}
          emptyMsg="All clear."
        />
      </section>
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function StatCard({
  icon: Icon, label, value, color, onClick, loading,
}: {
  icon: LucideIcon; label: string; value: number; color: string;
  onClick: () => void; loading: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className="bg-executive-card border border-executive-border rounded-xl p-4 text-left hover:border-executive-accent/40 transition-colors group"
    >
      <div className="flex items-center justify-between mb-2">
        <Icon size={16} className={color} />
        <ChevronRight size={14} className="text-executive-muted group-hover:text-executive-text transition-colors" />
      </div>
      <div className="text-2xl font-semibold text-executive-text tabular-nums">
        {loading ? '—' : value}
      </div>
      <div className="text-xs text-executive-muted mt-0.5">{label}</div>
    </button>
  );
}

interface PriorityListItem {
  primary: string;
  secondary: string;
  badge?: string;
}

function PriorityList({
  title, icon: Icon, accent, items, totalCount, onSeeAll, emptyMsg,
}: {
  title: string;
  icon: LucideIcon;
  accent: string;
  items: PriorityListItem[];
  totalCount: number;
  onSeeAll: () => void;
  emptyMsg: string;
}) {
  const priorityTag: Record<string, string> = {
    high:   'bg-rose-400/15 text-rose-300',
    medium: 'bg-amber-400/15 text-amber-300',
    low:    'bg-emerald-400/15 text-emerald-300',
  };

  return (
    <div className="bg-executive-card border border-executive-border rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Icon size={14} className={accent} />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-executive-text">
            {title}
          </h3>
        </div>
        {totalCount > 3 && (
          <button
            onClick={onSeeAll}
            className="text-xs text-executive-muted hover:text-executive-text transition-colors"
          >
            View all {totalCount} →
          </button>
        )}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-executive-muted italic py-3">{emptyMsg}</p>
      ) : (
        <ul className="space-y-2.5">
          {items.map((it, i) => (
            <li key={i} className="flex items-start gap-2 min-w-0">
              <span className="text-executive-muted text-xs mt-0.5 tabular-nums">{i + 1}.</span>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-executive-text truncate">{it.primary}</div>
                <div className="flex items-center gap-2 mt-0.5">
                  {it.secondary && (
                    <span className="text-xs text-executive-muted truncate">{it.secondary}</span>
                  )}
                  {it.badge && it.badge !== 'medium' && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase font-semibold ${priorityTag[it.badge] ?? 'bg-executive-border text-executive-muted'}`}>
                      {it.badge}
                    </span>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
