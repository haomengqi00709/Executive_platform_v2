import { useState } from 'react';
import { Users, FolderKanban, Receipt } from 'lucide-react';
import CrmTab from './records/CrmTab';
import ProjectsTab from './records/ProjectsTab';
import ExpensesTab from './records/ExpensesTab';

type Tab = 'crm' | 'projects' | 'expenses';

export default function RecordsPage() {
  const [tab, setTab] = useState<Tab>('crm');

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-executive-text">Records</h1>
        <p className="text-sm text-executive-muted mt-1">
          Your three editable data stores. Sections read from these — fix anything wrong here and
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
        <TabBtn active={tab === 'expenses'} onClick={() => setTab('expenses')} icon={<Receipt size={14} />}>
          Expenses
        </TabBtn>
      </div>

      {tab === 'crm'      && <CrmTab />}
      {tab === 'projects' && <ProjectsTab />}
      {tab === 'expenses' && <ExpensesTab />}
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
