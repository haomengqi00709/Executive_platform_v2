import { useState, useEffect, useCallback, createContext, useContext } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Settings, Save, CheckCircle2, AlertCircle, LogIn, LogOut,
  Bot, Webhook, User, Loader2, Copy, ExternalLink, Moon, Sun,
  LayoutDashboard, Sparkles, Wrench, UserCircle2, Database,
  BarChart3, Building2, RefreshCw, AlertTriangle, RotateCcw,
  Users, FolderKanban, FileText, ArrowRight, ChevronDown,
} from 'lucide-react';

import DashboardPage from './pages/DashboardPage';
import SkillsPage from './pages/SkillsPage';
import SectionDetailPage from './pages/SectionDetailPage';
import RecordsPage from './pages/RecordsPage';
import ToolsPage from './pages/ToolsPage';
import ProfilePage from './pages/ProfilePage';
import OnboardingWizard from './components/OnboardingWizard';
import { ActivityProvider } from './components/ActivityDrawer';
import { BulkEmailContext } from './lib/bulkEmail';

// ── Types (preserved auth + onboarding + settings) ─────────────────────────

type Page = 'dashboard' | 'skills' | 'section' | 'records' | 'tools' | 'profile' | 'settings';

type ProfileStage = 'pending' | 'awaiting_confirmation' | 'generating' | 'draft_ready' | 'user_confirmed';

type StepStatus = 'pending' | 'in_progress' | 'done' | 'failed';
interface InitStep {
  key: string;
  label: string;
  status: StepStatus;
  reveal_data?: { count?: number; samples?: string[]; preview?: string };
}
interface InitStatus {
  stage: ProfileStage;
  last_update: string | null;
  steps: InitStep[];
  current_message: string;
}

interface AuthUser { username?: string; user_id?: string; }

interface BotStatus {
  enabled: boolean; is_registered_bot?: boolean; connected?: boolean;
  peer_email?: string; bot_uid?: string;
}

interface AuthHealthAccount {
  label: string;
  user_id: string;
  dot: 'green' | 'yellow' | 'red';
  consecutive_failures: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  broken_since: string | null;
  classification: { message: string; action: 're-login' | 'contact-admin'; code: number | null } | null;
}

interface AuthHealth {
  overall: 'green' | 'yellow' | 'red';
  accounts: AuthHealthAccount[];
}

interface DeviceCode {
  user_code: string; verification_url: string; bot_uid: string; expires_in?: number;
}

// ── Nav items ─────────────────────────────────────────────────────────────

const NAV: { id: Page; label: string; icon: React.ReactNode; color: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, color: 'text-executive-accent' },
  { id: 'skills',    label: 'Skills',    icon: <Sparkles size={16} />,        color: 'text-amber-400' },
  { id: 'records',   label: 'Data',      icon: <Database size={16} />,        color: 'text-emerald-400' },
  { id: 'tools',     label: 'Tools',     icon: <Wrench size={16} />,          color: 'text-violet-400' },
  { id: 'profile',   label: 'Profile',   icon: <UserCircle2 size={16} />,     color: 'text-rose-400' },
];

// Per-user bot display name (e.g. "Audrey", "Edileen"). Read from
// settings.bot_display_name; defaults to "Audrey" for backwards compat with
// the original Daniel/Jason setups. Any component that mentions the assistant
// by name in user-facing text should pull it from here rather than hardcoding.
export const BrandingContext = createContext<{ bot: string }>({ bot: 'Audrey' });
export const useBotName = (): string => useContext(BrandingContext).bot;

function brandInitials(name: string): string {
  const cleaned = (name || '').trim();
  if (!cleaned) return '';
  const words = cleaned.split(/\s+/).filter(Boolean);
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

// ── App shell ──────────────────────────────────────────────────────────────

export default function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [page,  setPage]  = useState<Page>('dashboard');
  const [bulkResume, setBulkResume] = useState(false);
  const requestResume = useCallback(() => { setPage('records'); setBulkResume(true); }, []);
  const clearResume   = useCallback(() => setBulkResume(false), []);
  const [pendingSkillId, setPendingSkillId] = useState<string | undefined>();
  const [sectionDetailId, setSectionDetailId] = useState<string | undefined>();
  const [user,  setUser]  = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [profileConfirmed, setProfileConfirmed] = useState<boolean | null>(null);
  const [authHealth, setAuthHealth] = useState<AuthHealth | null>(null);
  const [brandCompany, setBrandCompany] = useState<string>('');
  const [brandDisplay, setBrandDisplay] = useState<string>('');
  const [brandBot,     setBrandBot]     = useState<string>('Audrey');

  const loadBranding = useCallback(async () => {
    try {
      const s: Record<string, string> = await fetch('/api/settings', { credentials: 'include' })
        .then(r => r.ok ? r.json() : {});
      setBrandCompany((s?.company_name || '').toString().trim());
      setBrandDisplay((s?.display_name || '').toString().trim());
      setBrandBot((s?.bot_display_name || '').toString().trim() || 'Audrey');
      // Lazy-fire signature extraction when the field is empty. Avoids
      // forcing the user through a full Restart Onboarding just to populate
      // settings.email_signature. Fire-and-forget — the response takes
      // 3-5s and the user isn't blocked on it; next time they ask Audrey
      // to draft an email the signature is already there.
      if (!(s?.email_signature || '').toString().trim()) {
        fetch('/api/profile/refresh-signature', { method: 'POST', credentials: 'include' })
          .catch(() => {/* best-effort */});
      }
    } catch {}
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    fetch('/api/auth/me', { credentials: 'include', headers: { 'X-Timezone': Intl.DateTimeFormat().resolvedOptions().timeZone } })
      .then(r => r.json())
      .then(async d => {
        const u = d?.user_id ? d : null;
        setUser(u);
        if (u) {
          try {
            const s = await fetch('/api/profile/status', { credentials: 'include' }).then(r => r.json());
            setProfileConfirmed(s?.stage === 'user_confirmed');
          } catch {
            setProfileConfirmed(false);
          }
          loadBranding();
        }
      })
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, [loadBranding]);

  useEffect(() => {
    if (!user) return;
    const poll = () => {
      fetch('/api/auth/health', { credentials: 'include' })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setAuthHealth(d); })
        .catch(() => {});
    };
    poll();
    const t = setInterval(poll, 30000);
    return () => clearInterval(t);
  }, [user]);

  if (authLoading) return <Spinner />;

  if (!user) return <LoginScreen />;

  if (profileConfirmed === false) {
    return (
      <BrandingContext.Provider value={{ bot: brandBot }}>
        <OnboardingPage
          displayName={brandDisplay}
          botName={brandBot}
          onComplete={() => { setProfileConfirmed(true); loadBranding(); }}
        />
      </BrandingContext.Provider>
    );
  }
  if (profileConfirmed === null) return <Spinner />;

  const goToSkill = (sid: string) => {
    setSectionDetailId(sid);
    setPage('section');
  };
  const goToCustomize = (sid: string) => {
    setPendingSkillId(sid);
    setPage('skills');
  };

  return (
    <BrandingContext.Provider value={{ bot: brandBot }}>
    <ActivityProvider>
    <BulkEmailContext.Provider value={{ resumeRequested: bulkResume, requestResume, clearResume }}>
    <div className="flex h-screen w-full bg-executive-bg text-executive-text overflow-hidden executive-grid">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 h-full flex flex-col border-r border-executive-border bg-executive-card z-10">
        {/* Brand */}
        <div className="h-14 flex items-center gap-3 px-5 border-b border-executive-border">
          <div className="w-7 h-7 rounded-lg bg-executive-accent flex items-center justify-center font-bold text-white text-xs shrink-0">
            {brandInitials(brandCompany) || 'EA'}
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-sm truncate leading-tight">
              {brandCompany || 'CEO Platform'}
            </p>
            {brandDisplay && (
              <p className="text-[10px] text-executive-muted truncate leading-tight mt-0.5">
                {brandDisplay} · Executive Assistant
              </p>
            )}
          </div>
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
            <HealthDot health={authHealth} onFixClick={() => setPage('settings')} />
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
        {page === 'dashboard' && <DashboardPage goToSkill={goToSkill} />}
        {page === 'section'   && sectionDetailId && (
          <SectionDetailPage
            sectionId={sectionDetailId}
            goBack={() => setPage('dashboard')}
            goToCustomize={goToCustomize}
          />
        )}
        {page === 'skills'    && (
          <SkillsPage
            initialSectionId={pendingSkillId}
            onClearInitial={() => setPendingSkillId(undefined)}
          />
        )}
        {page === 'records'   && <RecordsPage />}
        {page === 'tools'     && <ToolsPage />}
        {page === 'profile'   && <ProfilePage />}
        {page === 'settings'  && <SettingsPage user={user} onBrandingChange={loadBranding} />}
      </main>
    </div>
    </BulkEmailContext.Provider>
    </ActivityProvider>
    </BrandingContext.Provider>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PRESERVED PAGES & COMPONENTS — DO NOT TOUCH (Settings / Auth / Onboarding)
// ════════════════════════════════════════════════════════════════════════════

function SettingsPage({ user, onBrandingChange }: { user: AuthUser; onBrandingChange?: () => void }) {
  const [settings, setSettings]       = useState<Record<string, string>>({});
  const [settLoading, setSettLoading] = useState(false);
  const [saved, setSaved]             = useState(false);
  const [saveError, setSaveError]     = useState('');

  const [businessProfile, setBusinessProfile] = useState('');
  const [marketSegments,  setMarketSegments]  = useState('');

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
      fetch('/api/profile',    { credentials: 'include' }).then(r => r.ok ? r.json() : { business_profile: '', market_segments: '' }),
    ]).then(([s, b, p]) => {
      setSettings(s || {});
      setBotStatus(b);
      setBusinessProfile(p.business_profile || '');
      setMarketSegments(p.market_segments || '');
    }).finally(() => setSettLoading(false));
  }, []);

  const save = async () => {
    setSaveError('');
    try {
      const settingsReq = fetch('/api/settings', {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      const businessReq = fetch('/api/profile/business', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: businessProfile }),
      });
      const segmentsReq = fetch('/api/profile/segments', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: marketSegments }),
      });
      const [r1, r2, r3] = await Promise.all([settingsReq, businessReq, segmentsReq]);
      if (!r1.ok || !r2.ok || !r3.ok) throw new Error('Save failed');
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      // Sidebar shows company_name + display_name. Either could have changed
      // — bump the parent so the sidebar re-renders without a page reload.
      onBrandingChange?.();
    } catch (e: any) { setSaveError(e.message || 'Save failed'); }
  };

  const [regenerating, setRegenerating] = useState(false);
  const regenerateProfile = async () => {
    if (!confirm('Regenerate both profile docs from your emails? This will overwrite the current content.')) return;
    setRegenerating(true);
    try {
      const before = await fetch('/api/profile/status', { credentials: 'include' }).then(r => r.json());
      const beforeTs = before?.last_update || '';
      await fetch('/api/profile/regenerate', { method: 'POST', credentials: 'include' });
      const start = Date.now();
      const tick = async () => {
        if (Date.now() - start > 10 * 60 * 1000) { setRegenerating(false); return; }
        const s = await fetch('/api/profile/status', { credentials: 'include' }).then(r => r.json());
        if (s?.last_update && s.last_update !== beforeTs) {
          const p = await fetch('/api/profile', { credentials: 'include' }).then(r => r.json());
          setBusinessProfile(p.business_profile || '');
          setMarketSegments(p.market_segments || '');
          setRegenerating(false);
        } else {
          setTimeout(tick, 5000);
        }
      };
      setTimeout(tick, 5000);
    } catch {
      setRegenerating(false);
    }
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
          // The token is now in our session, but the bot isn't yet bound to
          // this user — activate does the binding. Without checking the
          // activate response, a 409 ("already claimed") or 400 ("can't bind
          // your own account as the bot") would silently look like success
          // to the user, then bite them hours later when nothing works.
          const activateRes = await fetch(`/api/teams/bot/activate?bot_uid=${d.bot_uid}`, {
            method: 'POST', credentials: 'include',
          });
          setBotPolling(false); setBotConnecting(false); setDeviceCode(null);

          if (!activateRes.ok) {
            const err = await activateRes.json().catch(() => ({} as any));
            const detail: string = err?.detail || err?.message || '';
            let msg: string;
            if (activateRes.status === 409) {
              msg = 'This AI assistant account is already claimed by another user. '
                  + 'Ask that user to disconnect first, or contact your admin to unbind.';
            } else if (activateRes.status === 400) {
              msg = detail || 'Cannot bind: the AI assistant must be a different '
                  + 'Microsoft account than your own. When prompted at '
                  + 'microsoft.com/devicelogin, sign in as the AI assistant '
                  + 'account, not your personal account.';
            } else if (activateRes.status === 404) {
              msg = 'Bot account not found after device flow. Please retry.';
            } else {
              msg = `Activation failed (HTTP ${activateRes.status})${detail ? ': ' + detail : ''}`;
            }
            setBotError(msg);
            return;
          }

          setBotSuccess('AI assistant connected! Open Microsoft Teams to start chatting.');
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
  void botPolling;

  const [restarting, setRestarting] = useState(false);
  const restartOnboarding = async () => {
    const ok = confirm(
      'Restart onboarding?\n\n' +
      'This will:\n' +
      '  • Delete your current CRM and project database\n' +
      '  • Wipe your scheduled briefings + email monitor config\n' +
      '  • Send you back through the 4-step setup wizard\n\n' +
      'Your personal profile, business profile, and Outlook drafts will NOT be touched.\n\n' +
      'Continue?'
    );
    if (!ok) return;
    setRestarting(true);
    try {
      const r = await fetch('/api/onboarding/restart', { method: 'POST', credentials: 'include' });
      if (!r.ok) throw new Error(`Server returned ${r.status}`);
      window.location.reload();
    } catch (e: any) {
      setRestarting(false);
      alert(`Restart failed: ${e?.message || e}`);
    }
  };

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
          <Field label="Company Name" value={settings.company_name || ''} onChange={v => setSettings(p => ({ ...p, company_name: v }))} placeholder="Shown in your sidebar" />
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

        <Section icon={<Building2 size={16} />} title="Business Profile" color="text-amber-500">
          <p className="text-xs text-executive-muted -mt-1">Describe your company — products, scale, customers, strategic focus. The AI reads this every time it searches, summarises, or scores emails.</p>
          <textarea
            value={businessProfile}
            onChange={e => setBusinessProfile(e.target.value)}
            rows={14}
            className="w-full p-3 rounded-lg border border-executive-border bg-executive-bg text-sm font-mono text-executive-text focus:border-executive-accent focus:outline-none resize-y"
            placeholder="# Business Profile&#10;&#10;## What the company does&#10;..."
          />
        </Section>

        <Section icon={<BarChart3 size={16} />} title="Market Segments" color="text-sky-500">
          <p className="text-xs text-executive-muted -mt-1">List the market segments your company operates in. The AI uses this to decide which industry signals and competitor moves are actually relevant to you.</p>
          <textarea
            value={marketSegments}
            onChange={e => setMarketSegments(e.target.value)}
            rows={10}
            className="w-full p-3 rounded-lg border border-executive-border bg-executive-bg text-sm font-mono text-executive-text focus:border-executive-accent focus:outline-none resize-y"
            placeholder="# Market Segments&#10;&#10;## Primary segments&#10;..."
          />
          <div className="pt-2 border-t border-executive-border flex items-center justify-between">
            <p className="text-xs text-executive-muted">Re-run AI generation from current email history. Overwrites both docs above.</p>
            <button
              onClick={regenerateProfile}
              disabled={regenerating}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-executive-border text-xs font-mono text-executive-muted hover:text-executive-text disabled:opacity-50 transition-all"
            >
              {regenerating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              {regenerating ? 'Regenerating...' : 'Regenerate with AI'}
            </button>
          </div>
        </Section>

        <Section icon={<Webhook size={16} />} title="Teams Webhook" color="text-purple-400">
          <p className="text-xs text-executive-muted -mt-1">Optional — used for push notifications via Power Automate.</p>
          <Field label="Webhook URL" value={settings.teams_webhook_url || ''} onChange={v => setSettings(p => ({ ...p, teams_webhook_url: v }))} placeholder="https://..." />
        </Section>

        <Section icon={<Database size={16} />} title="DB Cleanup Preferences" color="text-emerald-500">
          <p className="text-xs text-executive-muted -mt-1">Controls how the weekly scan (Monday 07:00 UTC) handles duplicates and stale records found by AI.</p>
          <Toggle
            label="Auto-merge high-confidence duplicates"
            description="AI-confirmed exact duplicates merge without asking. Medium and low candidates still require review."
            checked={settings.auto_merge_high_confidence === 'true'}
            onChange={v => setSettings(p => ({ ...p, auto_merge_high_confidence: v ? 'true' : 'false' }))}
          />
          <Toggle
            label="Auto-archive stale records"
            description="Completed projects >6 months old and dormant contacts >12 months old are archived automatically."
            checked={settings.auto_archive_stale === 'true'}
            onChange={v => setSettings(p => ({ ...p, auto_archive_stale: v ? 'true' : 'false' }))}
          />
          <Toggle
            label="Send weekly cleanup digest to Teams"
            description="Pushes the scan summary to your Teams chat every Monday."
            checked={settings.cleanup_digest_enabled !== 'false'}
            onChange={v => setSettings(p => ({ ...p, cleanup_digest_enabled: v ? 'true' : 'false' }))}
          />
        </Section>

        {/* Danger zone — destructive actions live at the bottom, isolated visually */}
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/[0.03] p-6 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} className="text-rose-400" />
            <h3 className="text-sm font-semibold text-rose-300 uppercase tracking-wider">Danger zone</h3>
          </div>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-sm font-medium text-executive-text">Restart onboarding</p>
              <p className="text-xs text-executive-muted mt-1 leading-relaxed">
                Wipes your CRM, project database, scheduled briefings, and email-monitor config,
                then returns you to the 4-step setup wizard. Use this to re-pick history depth
                or re-tune briefing schedules from scratch. Personal & business profile are kept.
              </p>
            </div>
            <button
              onClick={restartOnboarding}
              disabled={restarting}
              className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-rose-500 hover:bg-rose-600 text-white text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {restarting ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
              {restarting ? 'Restarting…' : 'Restart onboarding'}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}

function Toggle({ label, description, checked, onChange }: {
  label: string; description?: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer py-1">
      <input
        type="checkbox"
        checked={checked}
        onChange={e => onChange(e.target.checked)}
        className="mt-0.5 w-4 h-4 rounded border-executive-border text-executive-accent focus:ring-executive-accent"
      />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {description && <p className="text-xs text-executive-muted leading-snug mt-0.5">{description}</p>}
      </div>
    </label>
  );
}

// ── Shared utility components (used by Settings + Onboarding) ─────────────

function PageHeader({ label, title }: { label: string; title: string }) {
  return (
    <div>
      <p className="text-xs font-mono uppercase text-executive-accent tracking-[0.25em] mb-1">{label}</p>
      <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
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

function HealthDot({ health, onFixClick }: { health: AuthHealth | null; onFixClick: () => void }) {
  const [open, setOpen] = useState(false);
  if (!health) {
    return <span className="w-2 h-2 rounded-full bg-executive-muted/40 mx-2" title="Loading status…" />;
  }
  const color = health.overall === 'red'
    ? 'bg-rose-500'
    : health.overall === 'yellow'
      ? 'bg-amber-400'
      : 'bg-emerald-500';
  const ring = health.overall === 'red' ? 'ring-2 ring-rose-500/30 animate-pulse' : '';

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="AI assistant status"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => { if (health.overall === 'red') onFixClick(); }}
        className={`w-2.5 h-2.5 rounded-full mx-1.5 ${color} ${ring} ${health.overall === 'red' ? 'cursor-pointer' : 'cursor-default'}`}
      />
      {open && (
        <div className="absolute bottom-full right-0 mb-2 w-72 p-3 rounded-lg bg-executive-card border border-executive-border shadow-lg text-xs z-50">
          <div className="font-mono uppercase tracking-wider text-executive-muted mb-2">AI Assistant Status</div>
          {health.accounts.map(acc => (
            <div key={acc.user_id} className="mb-2 last:mb-0">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${
                  acc.dot === 'red' ? 'bg-rose-500'
                  : acc.dot === 'yellow' ? 'bg-amber-400'
                  : 'bg-emerald-500'
                }`} />
                <span className="font-medium">{acc.label}</span>
              </div>
              {acc.dot === 'red' && acc.classification ? (
                <div className="mt-1 ml-4 text-executive-muted">
                  <div>{acc.classification.message}</div>
                  <button
                    onClick={(e) => { e.stopPropagation(); onFixClick(); }}
                    className="mt-1.5 text-executive-accent hover:underline font-medium"
                  >
                    {acc.classification.action === 're-login' ? 'Reconnect in Settings →' : 'Contact your IT admin →'}
                  </button>
                </div>
              ) : acc.dot === 'yellow' ? (
                <div className="mt-1 ml-4 text-executive-muted">
                  Connection unstable, retrying… ({acc.consecutive_failures} failed attempt{acc.consecutive_failures === 1 ? '' : 's'})
                </div>
              ) : acc.last_success_at ? (
                <div className="mt-1 ml-4 text-executive-muted">
                  Connected · last sync {new Date(acc.last_success_at).toLocaleTimeString()}
                </div>
              ) : (
                <div className="mt-1 ml-4 text-executive-muted">Connected</div>
              )}
            </div>
          ))}
        </div>
      )}
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

function OnboardingPage({
  onComplete, displayName, botName,
}: { onComplete: () => void; displayName: string; botName: string }) {
  const [status, setStatus]       = useState<InitStatus | null>(null);
  const [thinkingLog, setThinkingLog] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState('');

  // null = haven't decided yet (waiting for initial status fetch).
  // false = show wizard. true = wizard handed off, show reveal page.
  //
  // On a fresh refresh mid-init we land here with stage='generating' even
  // though the user already completed the wizard in a prior session —
  // honor that by skipping the wizard.
  const [wizardDone, setWizardDone] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s: InitStatus = await fetch('/api/profile/status', { credentials: 'include' }).then(r => r.json());
        if (cancelled) return;
        setStatus(s);
        // Accumulate AI "thinking" messages — current_message overwrites
        // server-side per phase, but the user wants to see the trail.
        const msg = s?.current_message?.trim();
        if (msg) {
          setThinkingLog(prev => (prev[prev.length - 1] === msg ? prev : [...prev, msg]));
        }
        if (wizardDone === null) {
          // First fetch decides which UI to show
          setWizardDone(['generating', 'draft_ready', 'user_confirmed'].includes(s?.stage));
        }
        if (s?.stage === 'user_confirmed') {
          onComplete();
          return;
        }
      } catch {}
      if (!cancelled) setTimeout(poll, 3000);
    };
    poll();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onComplete]);

  const allDone = (status?.steps || []).length > 0
    && (status?.steps || []).every(s => s.status === 'done');

  const enterAssistant = async () => {
    setConfirming(true); setConfirmError('');
    try {
      const r = await fetch('/api/profile/confirm', { method: 'POST', credentials: 'include' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onComplete();
    } catch (e: any) {
      setConfirmError(e?.message || 'Failed to confirm');
      setConfirming(false);
    }
  };

  if (wizardDone === null) return <Spinner />;

  if (!wizardDone) {
    return (
      <OnboardingWizard
        displayName={displayName}
        botName={botName}
        onSubmitted={() => setWizardDone(true)}
      />
    );
  }

  return (
    <RevealPage
      steps={status?.steps || []}
      currentMessage={status?.current_message || ''}
      thinkingLog={thinkingLog}
      allDone={allDone}
      confirming={confirming}
      error={confirmError}
      onEnter={enterAssistant}
    />
  );
}

// ── Onboarding reveal page (two-pane) ──────────────────────────────────────
//
// Left pane shows the AI's progress: 6 compact step rows + a scrolling
// "thinking" feed that accumulates current_message values over time.
// Right pane shows generated artifacts as cards that appear when each
// step completes (DB counts + sample chips for crm/projects/companies,
// markdown previews for the three profile docs).

const REVEAL_ICONS: Record<string, { Icon: typeof Users; color: string }> = {
  crm:               { Icon: Users,         color: 'text-emerald-400' },
  projects:          { Icon: FolderKanban,  color: 'text-amber-400' },
  companies:         { Icon: Building2,     color: 'text-sky-400' },
  personal_profile:  { Icon: UserCircle2,   color: 'text-rose-400' },
  business_profile:  { Icon: FileText,      color: 'text-violet-400' },
  market_segments:   { Icon: BarChart3,     color: 'text-cyan-400' },
};

const REVEAL_TITLES: Record<string, string> = {
  crm:              'CRM Database',
  projects:         'Active Projects',
  companies:        'Company Map',
  personal_profile: 'Personal Profile',
  business_profile: 'Business Profile',
  market_segments:  'Market Segments',
};

// Profile docs go to the top of the right pane (per UX brief). Within each
// group (profiles vs DBs) preserve the natural INIT_STEPS order so the user
// reads `Personal → Business → Market` then `CRM → Projects → Companies`.
const PROFILE_KEYS = new Set(['personal_profile', 'business_profile', 'market_segments']);
function sortForRightPane(steps: InitStep[]): InitStep[] {
  return [...steps].sort((a, b) => {
    const aProfile = PROFILE_KEYS.has(a.key) ? 0 : 1;
    const bProfile = PROFILE_KEYS.has(b.key) ? 0 : 1;
    return aProfile - bProfile;
  });
}

// Expanded card content — fetched on demand from real endpoints.
interface ExpandedContent {
  // For profile keys: the full markdown text
  markdown?: string;
  // For DB keys: list of items to render (top N already sliced)
  items?:    { primary: string; secondary?: string }[];
  total?:    number;
}

function RevealPage({
  steps, currentMessage, thinkingLog, allDone, confirming, error, onEnter,
}: {
  steps: InitStep[];
  currentMessage: string;
  thinkingLog: string[];
  allDone: boolean;
  confirming: boolean;
  error: string;
  onEnter: () => void;
}) {
  const doneSteps = steps.filter(s => s.status === 'done' && s.reveal_data);

  return (
    <div className="min-h-screen w-full bg-executive-bg executive-grid overflow-auto py-8 px-6">
      <div className="max-w-6xl mx-auto">
        <header className="mb-6 text-center">
          <p className="text-xs font-mono uppercase text-executive-muted tracking-widest mb-2">
            Building your assistant
          </p>
          <h1 className="text-2xl font-bold text-executive-text">
            {allDone ? 'Everything is ready' : 'Setting up your AI assistant…'}
          </h1>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
          <LeftPanel steps={steps} currentMessage={currentMessage} thinkingLog={thinkingLog} />
          <RightPanel doneSteps={sortForRightPane(doneSteps)} />
        </div>

        {error && (
          <div className="mt-6 max-w-2xl mx-auto flex items-start gap-2 text-sm text-rose-400 bg-rose-400/8 border border-rose-400/30 rounded-lg px-3 py-2">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <motion.div
          initial={false}
          animate={{ opacity: allDone ? 1 : 0.35 }}
          className="mt-8 flex flex-col items-center gap-2"
        >
          <button
            onClick={onEnter}
            disabled={!allDone || confirming}
            className="flex items-center gap-2 px-6 py-3 rounded-xl bg-executive-accent text-white font-semibold text-sm hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity shadow-sm"
          >
            {confirming ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            {confirming ? 'Opening…' : 'Enter your assistant'}
          </button>
          <p className="text-[11px] text-executive-muted">
            {allDone ? 'You can review and edit any of these in Profile later.' : 'Hang tight — this usually takes 2–5 minutes.'}
          </p>
        </motion.div>
      </div>
    </div>
  );
}

// ── Left pane: progress + thinking feed ────────────────────────────────────

function LeftPanel({
  steps, currentMessage, thinkingLog,
}: {
  steps: InitStep[];
  currentMessage: string;
  thinkingLog: string[];
}) {
  // Show the most recent thoughts at the top, cap at ~8 to keep it readable
  const recentThoughts = [...thinkingLog].slice(-8).reverse();

  return (
    <div className="bg-executive-card border border-executive-border rounded-2xl p-5">
      <p className="text-[10px] font-mono uppercase text-executive-muted tracking-widest mb-3">
        AI is thinking
      </p>

      <ol className="flex flex-col gap-1.5 mb-5">
        {steps.length === 0 && (
          <li className="flex items-center gap-2 py-2 text-executive-muted text-sm">
            <Loader2 size={14} className="animate-spin" /> Starting up…
          </li>
        )}
        {steps.map(step => <StepRow key={step.key} step={step} />)}
      </ol>

      {(currentMessage || recentThoughts.length > 0) && (
        <div className="pt-4 border-t border-executive-border">
          <p className="text-[10px] font-mono uppercase text-executive-muted tracking-widest mb-2">
            Thoughts
          </p>
          <ul className="flex flex-col gap-1.5 text-xs text-executive-muted">
            <AnimatePresence initial={false}>
              {recentThoughts.map((t, i) => (
                <motion.li
                  key={`${t}-${thinkingLog.length - i}`}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: i === 0 ? 1 : 0.55 - i * 0.07 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25 }}
                  className={`flex items-start gap-2 font-mono leading-relaxed ${
                    i === 0 ? 'text-executive-text' : ''
                  }`}
                >
                  <span className="text-executive-accent shrink-0">›</span>
                  <span className="break-words">{t}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </div>
  );
}

function StepRow({ step }: { step: InitStep }) {
  const meta = REVEAL_ICONS[step.key] || { Icon: CheckCircle2, color: 'text-executive-muted' };
  const { Icon } = meta;
  const done = step.status === 'done';
  const inProgress = step.status === 'in_progress';
  const failed = step.status === 'failed';

  const restart = async () => {
    if (!confirm('Restart onboarding from scratch? Current data will be cleared.')) return;
    await fetch('/api/onboarding/restart', { method: 'POST', credentials: 'include' });
    window.location.reload();
  };

  return (
    <li className="flex items-center gap-3 py-1.5">
      <div className="w-5 h-5 flex items-center justify-center shrink-0">
        {done
          ? <CheckCircle2 size={14} className="text-emerald-500" />
          : inProgress
            ? <Loader2 size={14} className="text-executive-accent animate-spin" />
            : failed
              ? <AlertCircle size={14} className="text-rose-500" />
              : <Icon size={13} className={meta.color + ' opacity-40'} />}
      </div>
      <p className={`text-sm flex-1 ${
        done       ? 'text-executive-text' :
        inProgress ? 'text-executive-accent font-medium' :
        failed     ? 'text-rose-500' :
                     'text-executive-muted'
      }`}>
        {step.label}
      </p>
      {failed && (
        <button
          onClick={restart}
          className="text-[11px] px-2 py-0.5 rounded border border-rose-500/40 text-rose-500 hover:bg-rose-500/10 transition-colors shrink-0"
        >
          Restart
        </button>
      )}
    </li>
  );
}

// ── Right pane: generated artifacts ────────────────────────────────────────

const DB_FETCH_LIMIT = 15;  // top-N items rendered when a DB card expands

async function fetchExpandedContent(key: string): Promise<ExpandedContent | null> {
  try {
    if (PROFILE_KEYS.has(key)) {
      const r = await fetch('/api/profile', { credentials: 'include' });
      if (!r.ok) return null;
      const all = await r.json();
      return { markdown: all[key] || '' };
    }
    if (key === 'crm') {
      const r = await fetch('/api/crm', { credentials: 'include' });
      if (!r.ok) return null;
      const d = await r.json();
      const contacts = (d.contacts || []).slice(0, DB_FETCH_LIMIT);
      return {
        total: d.total ?? contacts.length,
        items: contacts.map((c: { name?: string; email?: string; role?: string; company?: string }) => ({
          primary:   c.name || c.email || '(no name)',
          secondary: [c.role, c.company].filter(Boolean).join(' · '),
        })),
      };
    }
    if (key === 'projects') {
      const r = await fetch('/api/projects', { credentials: 'include' });
      if (!r.ok) return null;
      const d = await r.json();
      const list = (d.projects || d.items || []).slice(0, DB_FETCH_LIMIT);
      return {
        total: d.total ?? list.length,
        items: list.map((p: { name?: string; summary?: string; category?: string; status?: string }) => ({
          primary:   p.name || '(unnamed)',
          secondary: p.summary || [p.category, p.status].filter(Boolean).join(' · '),
        })),
      };
    }
    if (key === 'companies') {
      const r = await fetch('/api/companies', { credentials: 'include' });
      if (!r.ok) return null;
      const d = await r.json();
      const list = (d.companies || d.items || []).slice(0, DB_FETCH_LIMIT);
      return {
        total: d.total ?? list.length,
        items: list.map((c: { name?: string; contact_count?: number; status?: string }) => ({
          primary:   c.name || '(unknown)',
          secondary: [c.contact_count ? `${c.contact_count} contacts` : '', c.status].filter(Boolean).join(' · '),
        })),
      };
    }
  } catch {
    return null;
  }
  return null;
}

function RightPanel({ doneSteps }: { doneSteps: InitStep[] }) {
  // Per-key expand state + cached fetched content. Fetch is fired the first
  // time a card is expanded; subsequent toggles just show/hide.
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [contentByKey, setContentByKey] = useState<Record<string, ExpandedContent | null>>({});
  const [loadingKeys,  setLoadingKeys]  = useState<Set<string>>(new Set());

  const toggleExpand = async (key: string) => {
    setExpandedKeys(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
    if (!(key in contentByKey)) {
      setLoadingKeys(prev => new Set(prev).add(key));
      const result = await fetchExpandedContent(key);
      setContentByKey(prev => ({ ...prev, [key]: result }));
      setLoadingKeys(prev => {
        const next = new Set(prev); next.delete(key); return next;
      });
    }
  };

  return (
    <div className="bg-executive-card border border-executive-border rounded-2xl p-5 min-h-[400px]">
      <p className="text-[10px] font-mono uppercase text-executive-muted tracking-widest mb-3">
        Generated for you
      </p>

      {doneSteps.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-executive-muted text-xs">
          <FileText size={28} className="opacity-30 mb-2" />
          <p>Files will appear here as the AI finishes each one.</p>
        </div>
      ) : (
        <ol className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {doneSteps.map(step => (
              <OutputCard
                key={step.key}
                step={step}
                expanded={expandedKeys.has(step.key)}
                loading={loadingKeys.has(step.key)}
                content={contentByKey[step.key] ?? null}
                onToggle={() => toggleExpand(step.key)}
              />
            ))}
          </AnimatePresence>
        </ol>
      )}
    </div>
  );
}

function OutputCard({
  step, expanded, loading, content, onToggle,
}: {
  step: InitStep;
  expanded: boolean;
  loading: boolean;
  content: ExpandedContent | null;
  onToggle: () => void;
}) {
  const meta = REVEAL_ICONS[step.key] || { Icon: FileText, color: 'text-executive-muted' };
  const { Icon } = meta;
  const title = REVEAL_TITLES[step.key] || step.label;
  const data = step.reveal_data;
  if (!data) return null;

  return (
    <motion.li
      layout
      initial={{ opacity: 0, scale: 0.96, y: 6 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.3, ease: [0.32, 0.72, 0, 1] }}
      className="rounded-xl border border-executive-border bg-executive-bg overflow-hidden hover:border-executive-accent/40 transition-colors"
    >
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-3 p-4 text-left hover:bg-executive-border/20 transition-colors"
      >
        <div className="w-7 h-7 rounded-lg bg-executive-border/30 flex items-center justify-center shrink-0 mt-0.5">
          <Icon size={14} className={meta.color} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-executive-text">{title}</p>
          <div className="mt-1.5">
            <RevealDetail data={data} />
          </div>
        </div>
        <motion.div
          animate={{ rotate: expanded ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="text-executive-muted mt-1"
        >
          <ChevronDown size={16} />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.32, 0.72, 0, 1] }}
            className="overflow-hidden border-t border-executive-border"
          >
            <ExpandedView stepKey={step.key} loading={loading} content={content} />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.li>
  );
}

function ExpandedView({
  stepKey, loading, content,
}: {
  stepKey: string;
  loading: boolean;
  content: ExpandedContent | null;
}) {
  if (loading) {
    return (
      <div className="p-4 flex items-center gap-2 text-xs text-executive-muted">
        <Loader2 size={12} className="animate-spin" /> Loading content…
      </div>
    );
  }
  if (!content) {
    return (
      <div className="p-4 text-xs text-executive-muted italic">
        (Couldn't load — refresh to retry)
      </div>
    );
  }

  if (typeof content.markdown === 'string') {
    return (
      <div className="p-4 max-h-[400px] overflow-auto">
        {content.markdown.trim() ? (
          <pre className="text-xs text-executive-text leading-relaxed whitespace-pre-wrap font-mono">
            {content.markdown}
          </pre>
        ) : (
          <p className="text-xs text-executive-muted italic">(empty — AI didn't produce this yet)</p>
        )}
      </div>
    );
  }

  if (content.items) {
    return (
      <div className="p-4 max-h-[400px] overflow-auto">
        {content.items.length === 0 ? (
          <p className="text-xs text-executive-muted italic">(no records found)</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {content.items.map((it, i) => (
              <li key={i} className="text-xs leading-tight">
                <p className="text-executive-text font-medium">{it.primary}</p>
                {it.secondary && (
                  <p className="text-executive-muted">{it.secondary}</p>
                )}
              </li>
            ))}
            {content.total && content.total > content.items.length && (
              <li className="pt-1 text-[10px] text-executive-muted italic">
                + {(content.total - content.items.length).toLocaleString()} more — view all in Records
              </li>
            )}
          </ol>
        )}
      </div>
    );
  }

  return null;
}

function RevealDetail({ data }: { data: NonNullable<InitStep['reveal_data']> }) {
  if (typeof data.count === 'number') {
    return (
      <div>
        <p className="text-2xl font-bold text-executive-text leading-tight">
          {data.count.toLocaleString()}
        </p>
        {data.samples && data.samples.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {data.samples.slice(0, 3).map(s => (
              <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-executive-border/40 text-executive-muted">
                {s}
              </span>
            ))}
            {data.count > (data.samples?.length || 0) && (
              <span className="text-[10px] px-2 py-0.5 text-executive-muted italic">
                + {(data.count - (data.samples?.length || 0)).toLocaleString()} more
              </span>
            )}
          </div>
        )}
      </div>
    );
  }
  if (data.preview) {
    return (
      <p className="text-xs text-executive-muted leading-relaxed italic line-clamp-4">
        {data.preview}
      </p>
    );
  }
  return null;
}
