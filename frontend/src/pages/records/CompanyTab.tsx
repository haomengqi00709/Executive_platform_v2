import { useEffect, useMemo, useState } from 'react';
import {
  Loader2, Search, ChevronDown, ChevronRight, Plus, Save, X,
  Eye, EyeOff, Building2, Trash2, RefreshCw, Users, FolderKanban,
} from 'lucide-react';
import {
  getCompanies, patchCompany, createCompany, deleteCompany, scanCompanies, relativeTime,
} from '../../lib/api';
import type { Company } from '../../lib/api';

const STATUS_OPTIONS = ['client', 'prospect', 'partner', 'investor', 'vendor', 'internal', 'other'];
const PRIORITY_OPTIONS = ['high', 'medium', 'low'];

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: 'last_activity_desc', label: 'Last activity ↓' },
  { value: 'name_asc',           label: 'Name A→Z' },
  { value: 'contacts_desc',      label: 'Contacts ↓' },
  { value: 'threads_desc',       label: 'Threads ↓' },
  { value: 'status_asc',         label: 'Status A→Z' },
];

const STATUS_COLOR: Record<string, string> = {
  client:   'bg-emerald-400/15 text-emerald-300',
  prospect: 'bg-sky-400/15 text-sky-300',
  partner:  'bg-violet-400/15 text-violet-300',
  investor: 'bg-indigo-400/15 text-indigo-300',
  vendor:   'bg-amber-400/15 text-amber-300',
  internal: 'bg-slate-400/15 text-slate-300',
  other:    'bg-executive-border/40 text-executive-muted',
};

export default function CompanyTab() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [lastScan, setLastScan]   = useState<string | null>(null);
  const [loading, setLoading]     = useState(true);
  const [search, setSearch]       = useState('');
  const [statusFilter, setStatusFilter]     = useState<string>('all');
  const [monitorFilter, setMonitorFilter]   = useState<'all' | 'monitored' | 'unmonitored'>('all');
  const [sortBy, setSortBy]                 = useState<string>('last_activity_desc');
  const [showIgnored, setShowIgnored]       = useState(false);
  const [expandedKey, setExpandedKey]       = useState<string | null>(null);
  const [savingKey, setSavingKey]           = useState<string | null>(null);
  const [creating, setCreating]             = useState(false);
  const [scanning, setScanning]             = useState(false);

  const refresh = () => {
    setLoading(true);
    getCompanies()
      .then(d => {
        setCompanies(d.companies || []);
        setLastScan(d.last_scan);
      })
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const update = async (key: string, patch: Partial<Company>) => {
    setSavingKey(key);
    try {
      const updated = await patchCompany(key, patch);
      setCompanies(cs => cs.map(c => c.key === key ? { ...c, ...updated } : c));
    } finally {
      setSavingKey(null);
    }
  };

  const remove = async (c: Company) => {
    const detail = c.manual
      ? `Delete "${c.name}"? It was user-added, so removal is permanent.`
      : `Delete "${c.name}"? It was derived from CRM/Projects, so the next rebuild will re-create it. To suppress permanently, toggle Ignore instead.`;
    if (!confirm(detail)) return;
    try {
      await deleteCompany(c.key);
      setExpandedKey(null);
      refresh();
    } catch (e: any) {
      alert(`Delete failed: ${e?.message || 'unknown error'}`);
    }
  };

  const rescan = async () => {
    setScanning(true);
    try {
      await scanCompanies();
      // Rebuild is cheap (no AI/Graph) — wait a couple seconds and reload.
      setTimeout(() => { refresh(); setScanning(false); }, 1500);
    } catch (e: any) {
      alert(`Rebuild failed: ${e?.message || 'unknown error'}`);
      setScanning(false);
    }
  };

  const visible = useMemo(() => {
    const filtered = companies.filter(c => {
      if (!showIgnored && c.ignore) return false;
      if (statusFilter !== 'all' && (c.derived_status || 'other') !== statusFilter) return false;
      if (monitorFilter === 'monitored'   && !c.monitor_intelligence) return false;
      if (monitorFilter === 'unmonitored' &&  c.monitor_intelligence) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        const hay = [
          c.name, c.key, ...(c.aliases || []),
          ...(c.contacts || []).map(x => x.email),
          ...(c.contacts || []).map(x => x.name),
        ].filter(Boolean).join(' ').toLowerCase();
        return hay.includes(q);
      }
      return true;
    });
    const txt = (v: unknown) => (v ?? '').toString().toLowerCase();
    const sorted = [...filtered];
    switch (sortBy) {
      case 'name_asc':
        sorted.sort((a, b) => txt(a.name).localeCompare(txt(b.name)));
        break;
      case 'contacts_desc':
        sorted.sort((a, b) => (b.contact_count ?? 0) - (a.contact_count ?? 0));
        break;
      case 'threads_desc':
        sorted.sort((a, b) => (b.thread_count_total ?? 0) - (a.thread_count_total ?? 0));
        break;
      case 'status_asc':
        sorted.sort((a, b) => txt(a.derived_status || 'other').localeCompare(txt(b.derived_status || 'other')));
        break;
      case 'last_activity_desc':
      default:
        sorted.sort((a, b) => txt(b.last_activity).localeCompare(txt(a.last_activity)));
        break;
    }
    return sorted;
  }, [companies, search, statusFilter, monitorFilter, showIgnored, sortBy]);

  const monitoredCount = useMemo(
    () => companies.filter(c => c.monitor_intelligence && !c.ignore).length,
    [companies],
  );

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3 justify-between">
        <div className="text-xs text-executive-muted">
          {loading ? 'Loading…' : (
            <>
              {companies.length} companies · {monitoredCount} monitored by Company Intelligence · last build {relativeTime(lastScan ?? undefined)}
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-executive-muted" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search company / contact…"
              className="pl-7 pr-3 py-1.5 text-xs bg-executive-bg border border-executive-border rounded-lg w-64 focus:outline-none focus:border-executive-accent/60"
            />
          </div>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-2 py-1.5 text-xs bg-executive-bg border border-executive-border rounded-lg focus:outline-none focus:border-executive-accent/60"
          >
            <option value="all">All status</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={monitorFilter}
            onChange={e => setMonitorFilter(e.target.value as 'all' | 'monitored' | 'unmonitored')}
            title="Filter by monitoring opt-in"
            className="px-2 py-1.5 text-xs bg-executive-bg border border-executive-border rounded-lg focus:outline-none focus:border-executive-accent/60"
          >
            <option value="all">All</option>
            <option value="monitored">Monitored</option>
            <option value="unmonitored">Not monitored</option>
          </select>
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value)}
            title="Sort companies"
            className="px-2 py-1.5 text-xs bg-executive-bg border border-executive-border rounded-lg focus:outline-none focus:border-executive-accent/60"
          >
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <label className="flex items-center gap-1.5 text-xs text-executive-muted">
            <input
              type="checkbox"
              checked={showIgnored}
              onChange={e => setShowIgnored(e.target.checked)}
              className="accent-executive-accent"
            />
            Show ignored
          </label>
          <button
            onClick={rescan}
            disabled={scanning}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-executive-border text-executive-muted hover:text-executive-text hover:bg-executive-border/40 disabled:opacity-50"
            title="Rebuild companies from current CRM + Projects (user fields preserved)"
          >
            {scanning ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            {scanning ? 'Rebuilding…' : 'Rebuild'}
          </button>
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-executive-accent text-white hover:opacity-90"
          >
            <Plus size={12} /> Add Company
          </button>
        </div>
      </header>

      <p className="text-xs text-executive-muted">
        Companies are derived from CRM contacts and Projects. The <b>Monitor</b> toggle decides
        which companies the <i>Company Intelligence</i> section researches each day (top {25} by priority + status).
      </p>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-executive-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center text-sm text-executive-muted py-12">
          No companies match the filter.
        </div>
      ) : (
        <div className="bg-executive-card border border-executive-border rounded-xl overflow-hidden">
          {visible.map(c => (
            <div key={c.key} className={`border-b border-executive-border/60 last:border-b-0 ${c.ignore ? 'opacity-50' : ''}`}>
              <button
                onClick={() => setExpandedKey(expandedKey === c.key ? null : c.key)}
                className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-executive-border/10 text-left"
              >
                <span className="text-executive-muted shrink-0">
                  {expandedKey === c.key ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
                <div className="flex-1 min-w-0 grid grid-cols-12 gap-3 items-center">
                  <div className="col-span-4 min-w-0 flex items-center gap-2">
                    <Building2 size={12} className="text-executive-muted shrink-0" />
                    <div className="min-w-0">
                      <div className="font-medium text-executive-text text-sm truncate flex items-center gap-2">
                        {c.name}
                        {c.manual && (
                          <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-executive-accent/15 text-executive-accent">
                            manual
                          </span>
                        )}
                      </div>
                      {c.aliases && c.aliases.length > 1 && (
                        <div className="text-xs text-executive-muted/70 truncate">
                          {c.aliases.filter(a => a !== c.name).join(' · ')}
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="col-span-2">
                    <span className={`text-xs px-2 py-1 rounded-md ${STATUS_COLOR[c.derived_status || 'other'] ?? STATUS_COLOR.other}`}>
                      {c.derived_status || 'other'}
                    </span>
                  </div>
                  <div className="col-span-2 text-xs text-executive-muted">
                    {c.contact_count ?? 0} contacts · {c.project_count ?? 0} projects
                  </div>
                  <div className="col-span-2 text-xs flex items-center gap-1.5">
                    {c.monitor_intelligence ? (
                      <><Eye size={11} className="text-emerald-400" /><span className="text-emerald-300/80">monitored</span></>
                    ) : (
                      <><EyeOff size={11} className="text-executive-muted" /><span className="text-executive-muted">off</span></>
                    )}
                  </div>
                  <div className="col-span-2 text-xs text-executive-muted text-right whitespace-nowrap">
                    {c.last_activity ? c.last_activity.slice(0, 10) : '—'}
                  </div>
                </div>
              </button>

              {expandedKey === c.key && (
                <CompanyDetail
                  company={c}
                  saving={savingKey === c.key}
                  onSave={patch => update(c.key, patch)}
                  onDelete={() => remove(c)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {creating && (
        <NewCompanyModal
          onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); refresh(); }}
        />
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function CompanyDetail({
  company, saving, onSave, onDelete,
}: {
  company: Company;
  saving: boolean;
  onSave: (patch: Partial<Company>) => Promise<void>;
  onDelete: () => void;
}) {
  const [draft, setDraft] = useState<Company>(company);

  useEffect(() => { setDraft(company); }, [company]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(company);

  const handleSave = async () => {
    const patch: Partial<Company> = {};
    (['name', 'monitor_intelligence', 'ignore', 'priority', 'notes'] as const).forEach(k => {
      if (draft[k] !== company[k]) {
        // @ts-expect-error — generic assignment
        patch[k] = draft[k];
      }
    });
    if (Object.keys(patch).length > 0) await onSave(patch);
  };

  return (
    <div className="bg-executive-bg/40 px-6 py-4 border-t border-executive-border/40">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div className="md:col-span-2">
          <Label>Display name</Label>
          <input
            type="text"
            value={draft.name}
            onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
            className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
          />
          {(draft.aliases || []).length > 1 && (
            <div className="mt-1 text-[11px] text-executive-muted">
              Seen as: {(draft.aliases || []).join(' · ')}
            </div>
          )}
        </div>
        <div>
          <Label>Priority</Label>
          <select
            value={draft.priority || 'medium'}
            onChange={e => setDraft(d => ({ ...d, priority: e.target.value }))}
            className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md"
          >
            {PRIORITY_OPTIONS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
          <div className="text-[11px] text-executive-muted mt-1">
            High-priority companies are researched first when over the 25-company cap.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <ToggleRow
          label="Monitor by Company Intelligence"
          help="When ON, the Company Intelligence section searches news, LinkedIn, and X for this company each run."
          checked={!!draft.monitor_intelligence}
          onChange={v => setDraft(d => ({ ...d, monitor_intelligence: v }))}
          icon={<Eye size={12} />}
        />
        <ToggleRow
          label="Ignore"
          help="Skip this company everywhere — Company Intelligence will not research it."
          checked={!!draft.ignore}
          onChange={v => setDraft(d => ({ ...d, ignore: v }))}
          icon={<EyeOff size={12} />}
        />
      </div>

      <div className="mb-4">
        <Label>Notes</Label>
        <textarea
          value={draft.notes || ''}
          onChange={e => setDraft(d => ({ ...d, notes: e.target.value }))}
          rows={2}
          className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
          placeholder="Why are you tracking this company? Anything to remember."
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
        <DerivedList
          icon={<Users size={11} />}
          title={`Contacts at this company (${company.contacts?.length ?? 0})`}
          empty="No CRM contacts attached."
          items={(company.contacts || []).map(ct => ({
            primary: ct.name || ct.email,
            secondary: [ct.role, ct.status, ct.email].filter(Boolean).join(' · '),
          }))}
        />
        <DerivedList
          icon={<FolderKanban size={11} />}
          title={`Projects (${company.projects?.length ?? 0})`}
          empty="No projects attached."
          items={(company.projects || []).map(pr => ({
            primary: pr.name,
            secondary: [pr.status, pr.last_activity].filter(Boolean).join(' · '),
          }))}
        />
      </div>

      <div className="flex items-center justify-between mt-4 pt-3 border-t border-executive-border/40">
        <button
          onClick={onDelete}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md text-rose-300 hover:bg-rose-400/10 transition-colors"
          title={company.manual ? 'Permanently delete this user-added company' : 'Remove this record (will reappear on next rebuild)'}
        >
          <Trash2 size={12} />
          Delete
        </button>
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
        </button>
      </div>
    </div>
  );
}

function NewCompanyModal({
  onClose, onCreated,
}: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [priority, setPriority] = useState('medium');
  const [monitor, setMonitor] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Company name is required.');
      return;
    }
    setSaving(true); setError(null);
    try {
      await createCompany({
        name: name.trim(),
        notes: notes.trim(),
        priority,
        monitor_intelligence: monitor,
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-executive-card border border-executive-border rounded-xl max-w-md w-full p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-executive-text">Add Company</h2>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text">
            <X size={18} />
          </button>
        </div>

        <p className="text-xs text-executive-muted mb-4">
          Add a company you want Company Intelligence to monitor, even if it isn't yet in your CRM
          or Projects. If CRM contacts or projects with this company show up later, they'll be linked
          on the next rebuild.
        </p>

        <div className="space-y-3">
          <div>
            <Label>Company name *</Label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
              placeholder="e.g. Acme Corp"
            />
          </div>

          <div>
            <Label>Priority</Label>
            <select
              value={priority}
              onChange={e => setPriority(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md"
            >
              {PRIORITY_OPTIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>

          <label className="flex items-center gap-2 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={monitor}
              onChange={e => setMonitor(e.target.checked)}
              className="accent-executive-accent"
            />
            <span>Monitor by Company Intelligence</span>
          </label>

          <div>
            <Label>Notes</Label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none resize-y"
              placeholder="Optional."
            />
          </div>
        </div>

        {error && (
          <div className="mt-3 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-3 py-2">{error}</div>
        )}

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-executive-border text-executive-muted hover:text-executive-text">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-50">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {saving ? 'Adding…' : 'Add Company'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{children}</div>;
}

function ToggleRow({
  label, help, checked, onChange, icon,
}: {
  label: string;
  help: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  icon: React.ReactNode;
}) {
  return (
    <label className="flex items-start gap-3 px-3 py-2 bg-executive-bg border border-executive-border rounded-md cursor-pointer hover:border-executive-accent/40">
      <input
        type="checkbox"
        checked={checked}
        onChange={e => onChange(e.target.checked)}
        className="mt-0.5 accent-executive-accent"
      />
      <div className="flex-1">
        <div className="text-sm font-medium text-executive-text flex items-center gap-1.5">
          {icon}
          {label}
        </div>
        <div className="text-xs text-executive-muted mt-0.5">{help}</div>
      </div>
    </label>
  );
}

function DerivedList({
  icon, title, items, empty,
}: {
  icon: React.ReactNode;
  title: string;
  items: { primary: string; secondary?: string }[];
  empty: string;
}) {
  return (
    <div className="bg-executive-bg/60 border border-executive-border/60 rounded-md px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1.5 flex items-center gap-1.5">
        {icon}
        {title}
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-executive-muted italic py-1">{empty}</div>
      ) : (
        <ul className="space-y-1 max-h-48 overflow-auto pr-1">
          {items.map((it, i) => (
            <li key={i} className="text-xs">
              <div className="text-executive-text truncate">{it.primary}</div>
              {it.secondary && <div className="text-executive-muted truncate">{it.secondary}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
