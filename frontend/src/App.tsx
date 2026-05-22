import { useState, useEffect, useCallback } from 'react';
import {
  Settings, Save, CheckCircle2, AlertCircle, LogIn, LogOut,
  Bot, Webhook, User, Loader2, Copy, ExternalLink, Moon, Sun,
  LayoutDashboard, Mail, CalendarDays, BarChart3, Users, CreditCard,
  Search, RefreshCw, Building2, Phone, Linkedin, ChevronRight,
} from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────

type Page = 'dashboard' | 'email' | 'meetings' | 'intelligence' | 'crm' | 'expenses' | 'settings';

interface AuthUser { username?: string; user_id?: string; }

interface BotStatus {
  enabled: boolean; is_registered_bot?: boolean; connected?: boolean;
  peer_email?: string; bot_uid?: string;
}

interface DeviceCode {
  user_code: string; verification_url: string; bot_uid: string; expires_in?: number;
}

interface CrmContact {
  email: string; name?: string; company?: string; role?: string;
  phone?: string; linkedin?: string; status?: string; summary?: string;
  writing_style?: string; thread_count?: number; last_contact?: string;
  priority?: string; updated_at?: string;
}

interface CrmData {
  last_scan?: string; months_scanned?: number; total?: number;
  contacts: CrmContact[];
}

// ── Nav items ─────────────────────────────────────────────────────────────

const NAV: { id: Page; label: string; icon: React.ReactNode; color: string }[] = [
  { id: 'dashboard',    label: 'Dashboard',    icon: <LayoutDashboard size={16} />, color: 'text-executive-accent' },
  { id: 'email',        label: 'Email',        icon: <Mail size={16} />,            color: 'text-sky-400' },
  { id: 'meetings',     label: 'Meetings',     icon: <CalendarDays size={16} />,    color: 'text-violet-400' },
  { id: 'intelligence', label: 'Intelligence', icon: <BarChart3 size={16} />,       color: 'text-amber-400' },
  { id: 'crm',          label: 'CRM',          icon: <Users size={16} />,           color: 'text-rose-400' },
  { id: 'expenses',     label: 'Expenses',     icon: <CreditCard size={16} />,      color: 'text-teal-400' },
];

// ── App shell ──────────────────────────────────────────────────────────────

export default function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [page,  setPage]  = useState<Page>('dashboard');
  const [user,  setUser]  = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include' })
      .then(r => r.json())
      .then(d => setUser(d?.user_id ? d : null))
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  if (authLoading) return <Spinner />;

  if (!user) return <LoginScreen />;

  return (
    <div className="flex h-screen w-full bg-executive-bg text-executive-text overflow-hidden executive-grid">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 h-full flex flex-col border-r border-executive-border bg-executive-card z-10">
        {/* Brand */}
        <div className="h-14 flex items-center gap-3 px-5 border-b border-executive-border">
          <div className="w-7 h-7 rounded-lg bg-executive-accent flex items-center justify-center font-bold text-white text-xs">
            EA
          </div>
          <span className="font-semibold text-sm">CEO Platform</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 flex flex-col gap-0.5">
          {NAV.map(item => (
            <button
              key={item.id}
              onClick={() => setPage(item.id)}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all w-full text-left ${
                page === item.id
                  ? 'bg-executive-accent/10 text-executive-accent'
                  : 'text-executive-muted hover:text-executive-text hover:bg-executive-border/40'
              }`}
            >
              <span className={page === item.id ? 'text-executive-accent' : item.color}>
                {item.icon}
              </span>
              {item.label}
            </button>
          ))}

          <div className="mt-auto pt-4 border-t border-executive-border">
            <button
              onClick={() => setPage('settings')}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all w-full text-left ${
                page === 'settings'
                  ? 'bg-executive-accent/10 text-executive-accent'
                  : 'text-executive-muted hover:text-executive-text hover:bg-executive-border/40'
              }`}
            >
              <Settings size={16} />
              Settings
            </button>
          </div>
        </nav>

        {/* User + theme */}
        <div className="px-4 py-3 border-t border-executive-border flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-6 h-6 rounded-full bg-executive-accent/20 flex items-center justify-center text-executive-accent text-xs font-bold shrink-0">
              {(user.username || 'U')[0].toUpperCase()}
            </div>
            <span className="text-xs text-executive-muted truncate">{user.username?.split('@')[0]}</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setTheme(t => t === 'light' ? 'dark' : 'light')}
              className="p-1.5 rounded-md text-executive-muted hover:text-executive-text transition-colors"
            >
              {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
            </button>
            <a href="/auth/logout" className="p-1.5 rounded-md text-executive-muted hover:text-rose-500 transition-colors">
              <LogOut size={13} />
            </a>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        {page === 'dashboard'    && <DashboardPage />}
        {page === 'email'        && <PlaceholderPage title="Email Intelligence" icon={<Mail size={24} />} color="text-sky-400" sections={['reply_needed', 'followup_needed', 'upcoming_commitments', 'commitments_extract', 'followup_tracking', 'invoices_contracts']} />}
        {page === 'meetings'     && <PlaceholderPage title="Meeting Intelligence" icon={<CalendarDays size={24} />} color="text-violet-400" sections={['recent_meetings', 'meeting_action_items']} />}
        {page === 'intelligence' && <PlaceholderPage title="Business Intelligence" icon={<BarChart3 size={24} />} color="text-amber-400" sections={['relationship_health', 'business_insights', 'market_intelligence']} />}
        {page === 'crm'          && <CrmPage />}
        {page === 'expenses'     && <PlaceholderPage title="Expense Capture" icon={<CreditCard size={24} />} color="text-teal-400" sections={['expenses']} />}
        {page === 'settings'     && <SettingsPage user={user} />}
      </main>
    </div>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────

interface SectionResult {
  id: string;
  status: 'not_run' | 'running' | 'fresh' | 'stale' | 'error';
  last_run?: string;
  started_at?: string;
  items?: any[];
  count?: number;
  empty?: boolean;
  briefing?: string;
  error?: string;
  logs?: string[];
}

const SECTION_DEFS = [
  { id: 'ai_summary',            title: 'Morning Briefing',        module: 'M01', color: 'text-executive-accent' },
  { id: 'market_intelligence',   title: 'Market Intelligence',     module: 'M01', color: 'text-executive-accent' },
  { id: 'reply_needed',          title: 'Emails Awaiting Reply',   module: 'M02', color: 'text-sky-400' },
  { id: 'followup_needed',       title: 'Sent — No Response',      module: 'M02', color: 'text-sky-400' },
  { id: 'upcoming_commitments',  title: 'Upcoming Commitments',    module: 'M02', color: 'text-sky-400' },
  { id: 'commitments_extract',   title: 'Commitments Extracted',   module: 'M02', color: 'text-sky-400' },
  { id: 'invoices_contracts',    title: 'Invoices & Contracts',    module: 'M02', color: 'text-sky-400' },
  { id: 'recent_meetings',       title: 'Recent Meetings',         module: 'M03', color: 'text-violet-400' },
  { id: 'meeting_action_items',  title: 'Meeting Action Items',    module: 'M03', color: 'text-violet-400' },
  { id: 'relationship_health',   title: 'Relationship Health',     module: 'M04', color: 'text-amber-400' },
  { id: 'business_insights',     title: 'Business Insights',       module: 'M04', color: 'text-amber-400' },
  { id: 'expenses',              title: 'Expense Capture',         module: 'M05', color: 'text-teal-400' },
];

function useSectionRunner(sectionId: string) {
  const [result, setResult] = useState<SectionResult | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/sections/${sectionId}`, { credentials: 'include' });
      if (r.ok) setResult(await r.json());
    } catch {}
  }, [sectionId]);

  useEffect(() => { load(); }, [load]);

  const run = async () => {
    setRunning(true);
    try {
      const r = await fetch(`/api/sections/${sectionId}/run`, { method: 'POST', credentials: 'include' });
      if (!r.ok) { setRunning(false); return; }
      const poll = setInterval(async () => {
        try {
          const r2 = await fetch(`/api/sections/${sectionId}`, { credentials: 'include' });
          const d: SectionResult = await r2.json();
          if (d.status !== 'running') {
            setResult(d); setRunning(false); clearInterval(poll);
          }
        } catch {}
      }, 3000);
      setTimeout(() => { clearInterval(poll); setRunning(false); }, 5 * 60 * 1000);
    } catch { setRunning(false); }
  };

  return { result, running, run };
}

function StatusBadge({ status }: { status: SectionResult['status'] }) {
  const map: Record<string, string> = {
    not_run: 'bg-executive-border text-executive-muted',
    running: 'bg-amber-500/20 text-amber-400',
    fresh:   'bg-emerald-500/20 text-emerald-400',
    stale:   'bg-sky-500/20 text-sky-400',
    error:   'bg-rose-500/20 text-rose-400',
  };
  return (
    <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${map[status] ?? map.not_run}`}>
      {status.replace('_', ' ')}
    </span>
  );
}

function SectionPreview({ def, result }: { def: typeof SECTION_DEFS[0]; result: SectionResult }) {
  if (def.id === 'ai_summary' && result.briefing) {
    return (
      <p className="text-xs text-executive-muted leading-relaxed line-clamp-4">
        {result.briefing}
      </p>
    );
  }
  const count = result.count ?? result.items?.length ?? 0;
  return (
    <p className="text-xs text-executive-muted font-mono">
      {count > 0 ? `${count} item${count !== 1 ? 's' : ''}` : 'No items'}
    </p>
  );
}

function SectionCard({ def }: { def: typeof SECTION_DEFS[0] }) {
  const { result, running, run } = useSectionRunner(def.id);
  const status = result?.status ?? 'not_run';

  return (
    <div className="glass rounded-xl p-4 flex flex-col gap-3 min-h-[140px]">
      <div className="flex items-center justify-between">
        <span className={`text-xs font-mono uppercase tracking-widest ${def.color}`}>{def.module}</span>
        <StatusBadge status={status} />
      </div>

      <p className="text-sm font-semibold">{def.title}</p>

      {status === 'running' && result?.logs && result.logs.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {result.logs.slice(-4).map((log, i) => (
            <p key={i} className="text-xs text-executive-muted font-mono truncate">
              <span className="text-amber-400 mr-1">›</span>{log}
            </p>
          ))}
        </div>
      )}
      {status === 'fresh' && result && (
        <SectionPreview def={def} result={result} />
      )}
      {status === 'error' && (
        <div className="flex flex-col gap-1">
          {result?.error && <p className="text-xs text-rose-400 font-mono line-clamp-2">{result.error}</p>}
          {result?.logs && result.logs.length > 0 && (
            <p className="text-xs text-executive-muted font-mono truncate">
              Last: {result.logs[result.logs.length - 1]}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-between mt-auto pt-2 border-t border-executive-border">
        <span className="text-xs text-executive-muted font-mono">
          {result?.last_run ? result.last_run.slice(0, 16).replace('T', ' ') : '—'}
        </span>
        <button
          onClick={run}
          disabled={running}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-executive-accent/10 text-executive-accent rounded-lg text-xs font-semibold hover:bg-executive-accent/20 disabled:opacity-40 transition-all"
        >
          {running ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {running ? 'Running…' : 'Run'}
        </button>
      </div>
    </div>
  );
}

function DashboardPage() {
  return (
    <div className="p-8">
      <PageHeader label="Overview" title="Dashboard" />
      <div className="grid grid-cols-3 gap-4 mt-8">
        {SECTION_DEFS.map(s => <SectionCard key={s.id} def={s} />)}
      </div>
    </div>
  );
}

// ── CRM Page ──────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, string> = {
  client:   'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  prospect: 'bg-sky-500/10 text-sky-600 dark:text-sky-400',
  partner:  'bg-violet-500/10 text-violet-600 dark:text-violet-400',
  vendor:   'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  other:    'bg-executive-border text-executive-muted',
};

function CrmPage() {
  const [crm,     setCrm]     = useState<CrmData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [search,  setSearch]  = useState('');
  const [selected, setSelected] = useState<CrmContact | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetch('/api/crm', { credentials: 'include' })
      .then(r => r.ok ? r.json() : null)
      .then(d => setCrm(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const runScan = async () => {
    setScanning(true);
    try {
      await fetch('/api/crm/scan', { method: 'POST', credentials: 'include' });
      // poll for completion every 5s
      const poll = setInterval(async () => {
        const r = await fetch('/api/crm', { credentials: 'include' });
        const d = await r.json();
        if (d.last_scan !== crm?.last_scan) {
          setCrm(d);
          setScanning(false);
          clearInterval(poll);
        }
      }, 5000);
      setTimeout(() => { clearInterval(poll); setScanning(false); }, 3 * 60 * 1000);
    } catch {
      setScanning(false);
    }
  };

  const contacts = (crm?.contacts || []).filter(c => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      c.name?.toLowerCase().includes(q) ||
      c.company?.toLowerCase().includes(q) ||
      c.email?.toLowerCase().includes(q) ||
      c.role?.toLowerCase().includes(q)
    );
  });

  const statusCounts = (crm?.contacts || []).reduce<Record<string, number>>((acc, c) => {
    const s = c.status || 'other';
    acc[s] = (acc[s] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-8 pt-8 pb-4 shrink-0">
        <div className="flex items-end justify-between">
          <PageHeader label="Context Layer" title="CRM" />
          <div className="flex items-center gap-3">
            {crm?.last_scan && (
              <span className="text-xs text-executive-muted font-mono">
                Scanned {crm.last_scan.slice(0, 10)}
              </span>
            )}
            <button
              onClick={runScan}
              disabled={scanning}
              className="flex items-center gap-2 px-4 py-2 bg-rose-500 text-white rounded-xl text-sm font-semibold hover:bg-rose-400 disabled:opacity-50 transition-all"
            >
              {scanning ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {scanning ? 'Scanning…' : 'Run Scan'}
            </button>
          </div>
        </div>

        {/* Stats */}
        {crm && (crm.total ?? 0) > 0 && (
          <div className="flex items-center gap-4 mt-4">
            <Stat label="Total" value={crm.total ?? 0} />
            {Object.entries(statusCounts).map(([s, n]) => (
              <Stat key={s} label={s} value={n} />
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={24} className="animate-spin text-executive-muted" />
        </div>
      ) : !crm || (crm.total ?? 0) === 0 ? (
        <EmptyState
          title="No contacts yet"
          description="Run a CRM scan to build your contact database from email history."
          action={<button onClick={runScan} disabled={scanning} className="flex items-center gap-2 px-5 py-2.5 bg-rose-500 text-white rounded-xl text-sm font-semibold hover:bg-rose-400 disabled:opacity-50 transition-all">
            {scanning ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            {scanning ? 'Scanning…' : 'Run Scan'}
          </button>}
        />
      ) : (
        <div className="flex flex-1 min-h-0">
          {/* Contact list */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Search */}
            <div className="px-8 pb-3 shrink-0">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-executive-muted" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search contacts…"
                  className="w-full bg-executive-bg border border-executive-border rounded-xl pl-9 pr-4 py-2 text-sm focus:outline-none focus:border-executive-accent transition-colors placeholder:text-executive-muted/40"
                />
              </div>
            </div>

            {/* Table */}
            <div className="flex-1 overflow-auto px-8 pb-8">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-executive-border">
                    {['Name', 'Company', 'Role', 'Status', 'Last Contact', 'Threads'].map(h => (
                      <th key={h} className="text-left py-2 px-3 text-xs font-mono uppercase tracking-widest text-executive-muted first:pl-0">
                        {h}
                      </th>
                    ))}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {contacts.map(c => (
                    <tr
                      key={c.email}
                      onClick={() => setSelected(selected?.email === c.email ? null : c)}
                      className={`border-b border-executive-border/50 cursor-pointer transition-colors ${
                        selected?.email === c.email
                          ? 'bg-executive-accent/5'
                          : 'hover:bg-executive-border/20'
                      }`}
                    >
                      <td className="py-3 pl-0 pr-3">
                        <div className="font-medium">{c.name || c.email.split('@')[0]}</div>
                        <div className="text-xs text-executive-muted">{c.email}</div>
                      </td>
                      <td className="py-3 px-3">{c.company || '—'}</td>
                      <td className="py-3 px-3 text-executive-muted">{c.role || '—'}</td>
                      <td className="py-3 px-3">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-mono ${STATUS_STYLE[c.status || 'other'] || STATUS_STYLE.other}`}>
                          {c.status || 'other'}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-executive-muted font-mono text-xs">{c.last_contact || '—'}</td>
                      <td className="py-3 px-3 text-executive-muted">{c.thread_count ?? '—'}</td>
                      <td className="py-3 pl-3 pr-0">
                        <ChevronRight size={14} className={`text-executive-muted transition-transform ${selected?.email === c.email ? 'rotate-90' : ''}`} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Detail panel */}
          {selected && (
            <div className="w-72 shrink-0 border-l border-executive-border overflow-auto p-6 flex flex-col gap-5">
              <div>
                <div className="w-10 h-10 rounded-full bg-rose-500/10 flex items-center justify-center text-rose-500 font-bold text-sm mb-3">
                  {(selected.name || selected.email)[0].toUpperCase()}
                </div>
                <h3 className="font-semibold">{selected.name || selected.email.split('@')[0]}</h3>
                <p className="text-xs text-executive-muted">{selected.email}</p>
              </div>

              <span className={`self-start px-2 py-0.5 rounded-full text-xs font-mono ${STATUS_STYLE[selected.status || 'other'] || STATUS_STYLE.other}`}>
                {selected.status || 'other'}
              </span>

              {selected.company && (
                <DetailRow icon={<Building2 size={13} />} label="Company" value={selected.company} />
              )}
              {selected.role && (
                <DetailRow icon={<User size={13} />} label="Role" value={selected.role} />
              )}
              {selected.phone && (
                <DetailRow icon={<Phone size={13} />} label="Phone" value={selected.phone} />
              )}
              {selected.linkedin && (
                <DetailRow icon={<Linkedin size={13} />} label="LinkedIn" value={
                  <a href={selected.linkedin} target="_blank" rel="noopener noreferrer" className="text-executive-accent hover:underline truncate">
                    Profile
                  </a>
                } />
              )}

              {selected.summary && (
                <div>
                  <p className="text-xs font-mono uppercase text-executive-muted tracking-wider mb-1.5">Summary</p>
                  <p className="text-xs text-executive-text leading-relaxed">{selected.summary}</p>
                </div>
              )}

              {selected.writing_style && (
                <div>
                  <p className="text-xs font-mono uppercase text-executive-muted tracking-wider mb-1.5">Writing Style</p>
                  <p className="text-xs text-executive-muted leading-relaxed">{selected.writing_style}</p>
                </div>
              )}

              <div className="pt-2 border-t border-executive-border text-xs text-executive-muted font-mono space-y-1">
                <p>{selected.thread_count} emails · last {selected.last_contact}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Placeholder page ──────────────────────────────────────────────────────

function PlaceholderPage({
  title, icon, color, sections,
}: { title: string; icon: React.ReactNode; color: string; sections: string[] }) {
  return (
    <div className="p-8">
      <div className="flex items-center gap-3 mb-8">
        <span className={color}>{icon}</span>
        <div>
          <p className="text-xs font-mono uppercase text-executive-muted tracking-widest mb-1">Module</p>
          <h1 className="text-2xl font-bold">{title}</h1>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {sections.map(s => (
          <div key={s} className="glass rounded-xl p-5 flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono px-2 py-0.5 rounded-full bg-executive-border text-executive-muted">
                not run
              </span>
            </div>
            <p className="text-sm font-medium capitalize">{s.replace(/_/g, ' ')}</p>
            <p className="text-xs text-executive-muted">Module not yet run.</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Settings Page ──────────────────────────────────────────────────────────

function SettingsPage({ user }: { user: AuthUser }) {
  const [settings, setSettings]       = useState<Record<string, string>>({});
  const [settLoading, setSettLoading] = useState(false);
  const [saved, setSaved]             = useState(false);
  const [saveError, setSaveError]     = useState('');

  const [botStatus, setBotStatus]     = useState<BotStatus | null>(null);
  const [deviceCode, setDeviceCode]   = useState<DeviceCode | null>(null);
  const [botPolling, setBotPolling]   = useState(false);
  const [botConnecting, setBotConnecting] = useState(false);
  const [botError, setBotError]       = useState('');
  const [botSuccess, setBotSuccess]   = useState('');
  const [copied, setCopied]           = useState(false);

  useEffect(() => {
    setSettLoading(true);
    Promise.all([
      fetch('/api/settings', { credentials: 'include', headers: { 'X-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone } }).then(r => r.ok ? r.json() : {}),
      fetch('/api/teams/bot',  { credentials: 'include' }).then(r => r.ok ? r.json() : null),
    ]).then(([s, b]) => {
      setSettings(s || {});
      setBotStatus(b);
    }).finally(() => setSettLoading(false));
  }, []);

  const save = async () => {
    setSaveError('');
    try {
      const r = await fetch('/api/settings', {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!r.ok) throw new Error('Save failed');
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) { setSaveError(e.message || 'Save failed'); }
  };

  const startBotAuth = async () => {
    setBotError(''); setBotSuccess(''); setBotConnecting(true);
    try {
      const r = await fetch('/api/teams/bot/auth-start', { method: 'POST', credentials: 'include' });
      if (!r.ok) throw new Error('Failed to start device flow');
      setDeviceCode(await r.json());
      pollBotAuth();
    } catch (e: any) { setBotError(e.message || 'Could not start bot authentication'); setBotConnecting(false); }
  };

  const pollBotAuth = useCallback(async () => {
    setBotPolling(true);
    const start = Date.now();
    const tick = async () => {
      if (Date.now() - start > 5 * 60 * 1000) {
        setBotError('Device code expired — please try again.');
        setBotPolling(false); setBotConnecting(false); setDeviceCode(null);
        return;
      }
      try {
        const r = await fetch('/api/teams/bot/auth-poll', { method: 'POST', credentials: 'include' });
        const d = await r.json();
        if (d.status === 'success') {
          await fetch(`/api/teams/bot/activate?bot_uid=${d.bot_uid}`, { method: 'POST', credentials: 'include' });
          setBotSuccess('AI assistant connected! Open Microsoft Teams to start chatting.');
          setBotPolling(false); setBotConnecting(false); setDeviceCode(null);
          const bs = await fetch('/api/teams/bot', { credentials: 'include' });
          if (bs.ok) setBotStatus(await bs.json());
        } else if (d.status === 'pending' || d.status === 'authorization_pending') {
          setTimeout(tick, 4000);
        } else {
          setBotError(d.message || 'Authentication failed');
          setBotPolling(false); setBotConnecting(false); setDeviceCode(null);
        }
      } catch { setTimeout(tick, 5000); }
    };
    tick();
  }, []);

  const disconnectBot = async () => {
    setBotError('');
    try {
      await fetch('/api/teams/bot/disable', { method: 'POST', credentials: 'include' });
      setBotStatus(s => s ? { ...s, enabled: false, connected: false } : null);
      setBotSuccess('');
    } catch { setBotError('Failed to disconnect bot'); }
  };

  const copyCode = () => {
    if (deviceCode?.user_code) {
      navigator.clipboard.writeText(deviceCode.user_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const botConnected = botStatus?.enabled && botStatus?.connected !== false;

  return (
    <div className="p-8 max-w-2xl">
      <div className="flex items-end justify-between mb-8">
        <PageHeader label="Configuration" title="Settings" />
        <button
          onClick={save}
          disabled={settLoading}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all ${
            saved ? 'bg-emerald-500 text-white' : 'bg-executive-accent text-white hover:bg-emerald-400 shadow-sm'
          }`}
        >
          {saved ? <CheckCircle2 size={16} /> : <Save size={16} />}
          {saved ? 'Saved!' : 'Save Changes'}
        </button>
      </div>

      {saveError && <ErrorBanner message={saveError} />}

      <div className="flex flex-col gap-6">
        <Section icon={<User size={16} />} title="Profile" color="text-executive-accent">
          <Field label="Display Name" value={settings.display_name || ''} onChange={v => setSettings(p => ({ ...p, display_name: v }))} placeholder="e.g. Daniel" />
          <Field label="Report Email" value={settings.report_email || ''} onChange={v => setSettings(p => ({ ...p, report_email: v }))} placeholder="daniel@company.com" type="email" />
          <div className="flex items-center justify-between pt-2 border-t border-executive-border">
            <div>
              <p className="text-xs font-mono uppercase text-executive-muted tracking-wider mb-0.5">Signed in as</p>
              <p className="text-sm font-medium">{user.username}</p>
            </div>
            <a href="/auth/logout" className="flex items-center gap-1.5 text-xs text-executive-muted hover:text-rose-500 transition-colors font-mono">
              <LogOut size={13} /> Sign out
            </a>
          </div>
        </Section>

        <Section icon={<Bot size={16} />} title="AI Assistant" color="text-sky-500">
          {botConnected ? (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3 p-4 bg-emerald-500/8 border border-emerald-500/20 rounded-xl">
                <CheckCircle2 size={18} className="text-emerald-500 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">AI assistant connected</p>
                  <p className="text-xs text-executive-muted">{botStatus?.peer_email ? `Signed in as ${botStatus.peer_email}` : 'Open Microsoft Teams and start a 1:1 chat with your AI assistant.'}</p>
                </div>
              </div>
              <button onClick={disconnectBot} className="self-start flex items-center gap-1.5 px-4 py-2 rounded-lg border border-rose-300 text-rose-500 text-xs font-mono hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-all">
                <LogOut size={12} /> Disconnect
              </button>
            </div>
          ) : deviceCode ? (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-executive-muted">Go to the link below and enter the code:</p>
              <a href={deviceCode.verification_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 text-sm text-executive-accent hover:underline font-mono">
                <ExternalLink size={14} />{deviceCode.verification_url}
              </a>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 px-5 py-3 bg-executive-bg border-2 border-executive-accent rounded-xl">
                  <span className="text-2xl font-mono font-bold tracking-[0.3em] text-executive-text">{deviceCode.user_code}</span>
                </div>
                <button onClick={copyCode} className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-mono transition-all ${copied ? 'border-emerald-500 text-emerald-500' : 'border-executive-border text-executive-muted hover:border-executive-accent hover:text-executive-accent'}`}>
                  <Copy size={12} />{copied ? 'Copied!' : 'Copy'}
                </button>
              </div>
              <div className="flex items-center gap-2 text-xs text-executive-muted font-mono">
                <Loader2 size={12} className="animate-spin" /> Waiting for authorization...
              </div>
              <button onClick={() => { setDeviceCode(null); setBotConnecting(false); setBotPolling(false); }} className="self-start text-xs font-mono text-executive-muted hover:text-executive-text transition-colors">
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <p className="text-sm text-executive-muted leading-relaxed">Connect an AI assistant account to enable two-way AI chat in Microsoft Teams.</p>
              {botError && <ErrorBanner message={botError} />}
              {botSuccess && <SuccessBanner message={botSuccess} />}
              <button onClick={startBotAuth} disabled={botConnecting} className="flex items-center gap-2 self-start px-5 py-2.5 bg-sky-500 text-white rounded-xl text-sm font-semibold hover:bg-sky-400 disabled:opacity-50 transition-all">
                {botConnecting ? <Loader2 size={15} className="animate-spin" /> : <Bot size={15} />}
                {botConnecting ? 'Starting...' : 'Connect AI Assistant'}
              </button>
            </div>
          )}
        </Section>

        <Section icon={<Webhook size={16} />} title="Teams Webhook" color="text-purple-400">
          <p className="text-xs text-executive-muted -mt-1">Optional — used for push notifications via Power Automate.</p>
          <Field label="Webhook URL" value={settings.teams_webhook_url || ''} onChange={v => setSettings(p => ({ ...p, teams_webhook_url: v }))} placeholder="https://..." />
        </Section>
      </div>
    </div>
  );
}

// ── Shared components ─────────────────────────────────────────────────────

function PageHeader({ label, title }: { label: string; title: string }) {
  return (
    <div>
      <p className="text-xs font-mono uppercase text-executive-accent tracking-[0.25em] mb-1">{label}</p>
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="glass rounded-xl px-4 py-2 flex items-center gap-3">
      <span className="text-xl font-bold">{value}</span>
      <span className="text-xs font-mono text-executive-muted capitalize">{label}</span>
    </div>
  );
}

function DetailRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-executive-muted mt-0.5 shrink-0">{icon}</span>
      <div>
        <p className="text-xs font-mono text-executive-muted uppercase tracking-wider">{label}</p>
        <p className="text-sm">{value}</p>
      </div>
    </div>
  );
}

function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
      <div className="w-12 h-12 rounded-2xl bg-executive-border/50 flex items-center justify-center">
        <Users size={24} className="text-executive-muted" />
      </div>
      <div>
        <h3 className="font-semibold mb-1">{title}</h3>
        <p className="text-sm text-executive-muted max-w-xs">{description}</p>
      </div>
      {action}
    </div>
  );
}

function Section({ icon, title, color, children }: { icon: React.ReactNode; title: string; color: string; children: React.ReactNode }) {
  return (
    <section className="p-7 glass rounded-2xl flex flex-col gap-5">
      <div className="flex items-center gap-2">
        <span className={color}>{icon}</span>
        <h2 className={`text-xs font-mono uppercase tracking-[0.25em] ${color}`}>{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Field({ label, value, onChange, placeholder, type = 'text' }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-mono uppercase text-executive-muted tracking-wider">{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="bg-executive-bg border border-executive-border rounded-xl px-4 py-2.5 text-sm text-executive-text focus:outline-none focus:border-executive-accent transition-colors placeholder:text-executive-muted/40" />
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 p-3 bg-rose-500/8 border border-rose-500/20 rounded-xl text-rose-500 text-xs font-mono">
      <AlertCircle size={14} className="shrink-0" />{message}
    </div>
  );
}

function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 p-3 bg-emerald-500/8 border border-emerald-500/20 rounded-xl text-emerald-600 dark:text-emerald-400 text-xs font-mono">
      <CheckCircle2 size={14} className="shrink-0" />{message}
    </div>
  );
}

function Spinner() {
  return (
    <div className="h-screen w-full flex items-center justify-center text-executive-muted gap-3 bg-executive-bg">
      <Loader2 size={20} className="animate-spin" />
      <span className="font-mono text-sm">Loading...</span>
    </div>
  );
}

function LoginScreen() {
  return (
    <div className="h-screen w-full flex flex-col items-center justify-center gap-8 bg-executive-bg executive-grid">
      <div className="w-16 h-16 rounded-2xl bg-executive-accent/10 flex items-center justify-center">
        <Settings size={32} className="text-executive-accent" />
      </div>
      <div className="text-center">
        <h1 className="text-3xl font-bold mb-2">CEO Platform</h1>
        <p className="text-executive-muted">Sign in with your Microsoft account to continue.</p>
      </div>
      <a href="/auth/login" className="flex items-center gap-3 px-8 py-4 bg-executive-accent text-white rounded-2xl font-semibold hover:bg-emerald-400 transition-all shadow-sm">
        <LogIn size={20} /> Sign in with Microsoft
      </a>
    </div>
  );
}
