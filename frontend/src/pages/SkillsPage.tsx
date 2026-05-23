import { useEffect, useState } from 'react';
import { Loader2, CalendarClock, Zap, Sliders } from 'lucide-react';
import { getSchedules } from '../lib/api';
import type { SchedulesResponse } from '../lib/api';
import BriefingsTab from './skills/BriefingsTab';
import AutoTriggerTab from './skills/AutoTriggerTab';
import CustomizeTab from './skills/CustomizeTab';

type Tab = 'briefings' | 'autotrigger' | 'customize';

interface SkillsPageProps {
  initialSectionId?: string;
  onClearInitial: () => void;
}

export default function SkillsPage({ initialSectionId, onClearInitial }: SkillsPageProps) {
  const [tab, setTab] = useState<Tab>(initialSectionId ? 'customize' : 'briefings');
  const [schedules, setSchedules] = useState<SchedulesResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const s = await getSchedules();
      setSchedules(s);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-executive-text">Skills</h1>
        <p className="text-sm text-executive-muted mt-1">
          Configure scheduled briefings, auto-triggered tools, and per-skill customization.
        </p>
      </header>

      <div className="flex gap-1 bg-executive-card border border-executive-border rounded-lg p-1 w-fit">
        <TabBtn active={tab === 'briefings'}   onClick={() => setTab('briefings')}   icon={<CalendarClock size={14} />}>Scheduled Briefings</TabBtn>
        <TabBtn active={tab === 'autotrigger'} onClick={() => setTab('autotrigger')} icon={<Zap size={14} />}>Auto-triggered</TabBtn>
        <TabBtn active={tab === 'customize'}   onClick={() => setTab('customize')}   icon={<Sliders size={14} />}>Customize Skills</TabBtn>
      </div>

      {loading || !schedules ? (
        <div className="flex items-center justify-center py-16 text-executive-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : (
        <>
          {tab === 'briefings'   && <BriefingsTab schedules={schedules} onChange={refresh} />}
          {tab === 'autotrigger' && <AutoTriggerTab schedules={schedules} onChange={refresh} />}
          {tab === 'customize'   && <CustomizeTab initialSectionId={initialSectionId} onClearInitial={onClearInitial} />}
        </>
      )}
    </div>
  );
}

function TabBtn({
  active, onClick, icon, children,
}: {
  active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
        active
          ? 'bg-executive-accent/10 text-executive-accent'
          : 'text-executive-muted hover:text-executive-text'
      }`}
    >
      {icon}
      {children}
    </button>
  );
}
