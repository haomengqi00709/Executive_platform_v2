import { useState } from 'react';
import { Users, FolderKanban, Sparkles } from 'lucide-react';
import CrmTab from './records/CrmTab';
import ProjectsTab from './records/ProjectsTab';
import CleanupTab from './records/CleanupTab';

type Tab = 'crm' | 'projects' | 'cleanup';

export default function RecordsPage() {
  const [tab, setTab] = useState<Tab>('crm');

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-executive-text">Records</h1>
        <p className="text-sm text-executive-muted mt-1">
          Your business data stores. Sections read from these — fix anything wrong here and
          downstream skills will respect your changes on next run.
        </p>
      </header>

      {/* Sub-tabs */}
      <div className="flex gap-1 bg-executive-card border border-executive-border rounded-lg p-1 w-fit">
        <TabBtn active={tab === 'crm'}      onClick={() => setTab('crm')}      icon={<Users size={14} />}>
          CRM
        </TabBtn>
        <TabBtn active={tab === 'projects'} onClick={() => setTab('projects')} icon={<FolderKanban size={14} />}>
          Projects
        </TabBtn>
        <TabBtn active={tab === 'cleanup'} onClick={() => setTab('cleanup')} icon={<Sparkles size={14} />}>
          Cleanup
        </TabBtn>
      </div>

      {tab === 'crm'      && <CrmTab />}
      {tab === 'projects' && <ProjectsTab />}
      {tab === 'cleanup'  && <CleanupTab />}
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
