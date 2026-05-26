import { useEffect, useState, useCallback } from 'react';
import {
  Mail, Send, CheckCircle2, CalendarDays, AlertTriangle,
  HeartPulse, RefreshCw, Sunrise, Loader2, ChevronRight,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { getSection, runSection, relativeTime } from '../lib/api';
import type {
  SectionResult, RelationshipItem,
} from '../lib/types';

interface DashboardPageProps {
  goToSkill: (sectionId: string) => void;
}

interface StatDef {
  id: string;
  label: string;
  icon: LucideIcon;
  color: string;
  countKey?: 'count' | 'cooling';
}

const STATS: StatDef[] = [
  { id: 'reply_needed',                label: 'Reply Needed',    icon: Mail,           color: 'text-sky-400' },
  { id: 'followup_needed',             label: 'Sent — No Resp',  icon: Send,           color: 'text-orange-400' },
  { id: 'due_today',                   label: 'Due Today',       icon: CheckCircle2,   color: 'text-emerald-400' },
  { id: 'meetings_today',              label: 'Meetings Today',  icon: CalendarDays,   color: 'text-violet-400' },
  { id: 'projects_needing_attention',  label: 'Projects Attn',   icon: AlertTriangle,  color: 'text-rose-400' },
  { id: 'relationship_health',         label: 'Cooling Rels',    icon: HeartPulse,     color: 'text-pink-400', countKey: 'cooling' },
];

export default function DashboardPage({ goToSkill }: DashboardPageProps) {
  const [briefing, setBriefing] = useState<SectionResult | null>(null);
  const [stats, setStats] = useState<Record<string, SectionResult | null>>({});
  const [loading, setLoading] = useState(true);
  const [rerunning, setRerunning] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    const ids = ['ai_summary', ...STATS.map(s => s.id)];
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
      const start = Date.now();
      // ai_summary depends on 9 sub-sections; first run of the day refreshes
      // all of them serially, which can take ~3 minutes. Give it 5 min headroom.
      while (Date.now() - start < 300_000) {
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

  // Compute value for each stat — most are .count; cooling rels derives from health field.
  const valueFor = (s: StatDef): number => {
    const r = stats[s.id];
    if (s.countKey === 'cooling') {
      const items = (r?.items as RelationshipItem[] | undefined) ?? [];
      return items.filter(it => it.health === 'cooling' || it.health === 'at_risk' || it.health === 'stalled').length;
    }
    return r?.count ?? 0;
  };

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

      {/* Segmented stat strip — one shared container, internal dividers */}
      <section
        className="bg-executive-card border border-executive-border rounded-xl overflow-hidden
                   flex divide-x divide-executive-border"
      >
        {STATS.map(s => {
          const Icon = s.icon;
          const v = valueFor(s);
          return (
            <button
              key={s.id}
              onClick={() => goToSkill(s.id)}
              className="group relative flex-1 min-w-0 px-4 py-4 text-left
                         hover:bg-executive-border/20 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <Icon size={16} className={`${s.color} transition-transform group-hover:scale-110`} />
              </div>
              <div className="text-2xl font-semibold text-executive-text tabular-nums">
                {loading ? '—' : v}
              </div>
              <div className="text-xs text-executive-muted mt-0.5 truncate">{s.label}</div>
            </button>
          );
        })}
        {/* Trailing arrow hint — visually wraps the whole strip as "clickable" */}
        <div className="flex items-center px-4 text-executive-muted/50">
          <ChevronRight size={16} />
        </div>
      </section>
    </div>
  );
}
