import { useState } from 'react';
import { Receipt, FolderOpen, ChevronDown } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
// Expense remains physically in pages/records/ — surfaced here as a Tool by
// intent, but the file is left in place because other in-flight work uses it
// as a template.
import ExpensesTab from './records/ExpensesTab';

export default function ToolsPage() {
  // Independent toggle state — user can have multiple tools open at once.
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['expenses']));
  const toggle = (id: string) => setExpanded(s => {
    const next = new Set(s);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-4">
      <header className="mb-2">
        <h1 className="text-2xl font-semibold text-executive-text">Personal Tools</h1>
        <p className="text-sm text-executive-muted mt-1">
          On-demand workflows and personal utilities. Click a tool to expand it.
        </p>
      </header>

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
