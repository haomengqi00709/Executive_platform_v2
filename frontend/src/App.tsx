import { useState, useEffect, useCallback } from 'react';
import {
  Settings, Save, CheckCircle2, AlertCircle, LogIn, LogOut,
  Bot, Webhook, User, Loader2, Copy, ExternalLink, Moon, Sun,
  LayoutDashboard, Sparkles, Wrench, UserCircle2, Database,
  BarChart3, Building2, RefreshCw, AlertTriangle, RotateCcw,
} from 'lucide-react';

import DashboardPage from './pages/DashboardPage';
import SkillsPage from './pages/SkillsPage';
import SectionDetailPage from './pages/SectionDetailPage';
import RecordsPage from './pages/RecordsPage';
import ToolsPage from './pages/ToolsPage';
import ProfilePage from './pages/ProfilePage';
import OnboardingWizard from './components/OnboardingWizard';

// ── Types (preserved auth + onboarding + settings) ─────────────────────────

type Page = 'dashboard' | 'skills' | 'section' | 'records' | 'tools' | 'profile' | 'settings';

type ProfileStage = 'pending' | 'awaiting_confirmation' | 'generating' | 'draft_ready' | 'user_confirmed';

type StepStatus = 'pending' | 'in_progress' | 'done' | 'failed';
interface InitStep { key: string; label: string; status: StepStatus; }
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

interface DeviceCode {
  user_code: string; verification_url: string; bot_uid: string; expires_in?: number;
}

// ── Nav items ─────────────────────────────────────────────────────────────

const NAV: { id: Page; label: string; icon: React.ReactNode; color: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, color: 'text-executive-accent' },
  { id: 'skills',    label: 'Skills',    icon: <Sparkles size={16} />,        color: 'text-amber-400' },
  { id: 'records',   label: 'Records',   icon: <Database size={16} />,        color: 'text-emerald-400' },
  { id: 'tools',     label: 'Tools',     icon: <Wrench size={16} />,          color: 'text-violet-400' },
  { id: 'profile',   label: 'Profile',   icon: <UserCircle2 size={16} />,     color: 'text-rose-400' },
];

// ── App shell ──────────────────────────────────────────────────────────────

export default function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [page,  setPage]  = useState<Page>('dashboard');
  const [pendingSkillId, setPendingSkillId] = useState<string | undefined>();
  const [sectionDetailId, setSectionDetailId] = useState<string | undefined>();
  const [user,  setUser]  = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [profileConfirmed, setProfileConfirmed] = useState<boolean | null>(null);

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
        }
      })
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  if (authLoading) return <Spinner />;

  if (!user) return <LoginScreen />;

  if (profileConfirmed === false) {
    return <OnboardingPage onComplete={() => setProfileConfirmed(true)} />;
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
        {page === 'settings'  && <SettingsPage user={user} />}
      </main>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// PRESERVED PAGES & COMPONENTS — DO NOT TOUCH (Settings / Auth / Onboarding)
// ════════════════════════════════════════════════════════════════════════════

function SettingsPage({ user }: { user: AuthUser }) {
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

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'done') {
    return (
      <div className="w-6 h-6 rounded-full bg-emerald-500/15 flex items-center justify-center shrink-0">
        <CheckCircle2 size={14} className="text-emerald-500" />
      </div>
    );
  }
  if (status === 'in_progress') {
    return (
      <div className="w-6 h-6 rounded-full bg-executive-accent/15 flex items-center justify-center shrink-0">
        <Loader2 size={14} className="text-executive-accent animate-spin" />
      </div>
    );
  }
  if (status === 'failed') {
    return (
      <div className="w-6 h-6 rounded-full bg-rose-500/15 flex items-center justify-center shrink-0">
        <AlertCircle size={14} className="text-rose-500" />
      </div>
    );
  }
  return (
    <div className="w-6 h-6 rounded-full border border-executive-border flex items-center justify-center shrink-0">
      <div className="w-1.5 h-1.5 rounded-full bg-executive-muted" />
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

function OnboardingPage({ onComplete }: { onComplete: () => void }) {
  const [status, setStatus]               = useState<InitStatus | null>(null);
  const [businessProfile, setBusinessProfile] = useState('');
  const [marketSegments,  setMarketSegments]  = useState('');
  const [saving, setSaving]               = useState(false);
  const [error, setError]                 = useState('');
  const [pollNonce, setPollNonce]         = useState(0);  // force re-fetch after wizard submit

  const stage = status?.stage || 'pending';

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const s: InitStatus = await fetch('/api/profile/status', { credentials: 'include' }).then(r => r.json());
        if (cancelled) return;
        setStatus(s);
        if (s?.stage === 'draft_ready') {
          const p = await fetch('/api/profile', { credentials: 'include' }).then(r => r.json());
          if (cancelled) return;
          setBusinessProfile(p.business_profile || '');
          setMarketSegments(p.market_segments  || '');
          return;
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
  }, [onComplete, pollNonce]);

  const confirm = async () => {
    setSaving(true); setError('');
    try {
      await Promise.all([
        fetch('/api/profile/business', {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: businessProfile }),
        }),
        fetch('/api/profile/segments', {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: marketSegments }),
        }),
      ]);
      await fetch('/api/profile/confirm', { method: 'POST', credentials: 'include' });
      onComplete();
    } catch (e: any) {
      setError(e?.message || 'Failed to save profile');
      setSaving(false);
    }
  };

  const regenerate = async () => {
    setStatus(s => s ? { ...s, stage: 'generating' } : s);
    await fetch('/api/profile/regenerate', { method: 'POST', credentials: 'include' });
  };

  // Awaiting wizard — show 4-step configuration before kicking off init
  if (stage === 'pending' || stage === 'awaiting_confirmation') {
    return (
      <OnboardingWizard
        onSubmitted={() => {
          // Wizard returned 200 — backend just set stage='generating'.
          // Bump the poll nonce so the effect immediately refetches status
          // and falls through to the checklist UI below.
          setStatus(s => s ? { ...s, stage: 'generating' } : { stage: 'generating', last_update: null, steps: [], current_message: '' });
          setPollNonce(n => n + 1);
        }}
      />
    );
  }

  // Generating state — show step-by-step checklist
  if (stage === 'generating') {
    const steps = status?.steps || [];
    const currentMessage = status?.current_message || '';
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-executive-bg executive-grid p-6">
        <div className="w-full max-w-xl bg-executive-card border border-executive-border rounded-2xl p-8 shadow-sm">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-executive-accent/10 flex items-center justify-center">
              <Loader2 size={20} className="text-executive-accent animate-spin" />
            </div>
            <div>
              <p className="text-xs font-mono uppercase text-executive-muted tracking-widest">First-time setup</p>
              <h1 className="text-lg font-bold">Setting up your AI profile</h1>
            </div>
          </div>

          <p className="text-sm text-executive-muted mb-6 leading-relaxed">
            We're scanning your inbox to build the foundation that every AI feature on the platform will use.
            This usually takes 2–5 minutes on first sign-in.
          </p>

          <ol className="flex flex-col gap-3">
            {steps.map(step => (
              <li key={step.key} className="flex items-start gap-3">
                <StepIcon status={step.status} />
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${
                    step.status === 'done'        ? 'text-executive-text' :
                    step.status === 'in_progress' ? 'text-executive-accent' :
                    step.status === 'failed'      ? 'text-rose-500' :
                                                    'text-executive-muted'
                  }`}>{step.label}</p>
                  {step.status === 'in_progress' && currentMessage && (
                    <p className="text-xs font-mono text-executive-muted mt-0.5 truncate">{currentMessage}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    );
  }

  // Draft ready — show editable form
  return (
    <div className="min-h-screen w-full bg-executive-bg executive-grid overflow-auto">
      <div className="max-w-3xl mx-auto px-8 py-12">
        <div className="mb-8">
          <p className="text-xs font-mono uppercase text-executive-muted tracking-widest mb-2">Welcome — first-time setup</p>
          <h1 className="text-3xl font-bold mb-3">Your profile draft is ready</h1>
          <p className="text-executive-muted leading-relaxed">
            We generated this from your recent emails, CRM contacts, and active projects.
            This profile is the foundation every AI feature on the platform reads — searches, email triage, briefings.
            Edit anything that's wrong, then confirm to continue.
          </p>
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="flex flex-col gap-6">
          <Section icon={<Building2 size={16} />} title="Business Profile" color="text-amber-500">
            <p className="text-xs text-executive-muted -mt-1">What your company does, who you serve, and your strategic focus.</p>
            <textarea
              value={businessProfile}
              onChange={e => setBusinessProfile(e.target.value)}
              rows={18}
              className="w-full p-3 rounded-lg border border-executive-border bg-executive-bg text-sm font-mono text-executive-text focus:border-executive-accent focus:outline-none resize-y"
            />
          </Section>

          <Section icon={<BarChart3 size={16} />} title="Market Segments" color="text-sky-500">
            <p className="text-xs text-executive-muted -mt-1">The markets you operate in. The AI uses this to filter which signals are relevant.</p>
            <textarea
              value={marketSegments}
              onChange={e => setMarketSegments(e.target.value)}
              rows={12}
              className="w-full p-3 rounded-lg border border-executive-border bg-executive-bg text-sm font-mono text-executive-text focus:border-executive-accent focus:outline-none resize-y"
            />
          </Section>
        </div>

        <div className="flex items-center justify-between mt-8">
          <button
            onClick={regenerate}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-executive-border text-sm text-executive-muted hover:text-executive-text transition-all"
          >
            <RefreshCw size={14} /> Regenerate with AI
          </button>
          <button
            onClick={confirm}
            disabled={saving}
            className="flex items-center gap-2 px-6 py-3 rounded-xl bg-executive-accent text-white font-semibold hover:bg-emerald-400 disabled:opacity-50 transition-all shadow-sm"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
            {saving ? 'Saving...' : 'Confirm and continue'}
          </button>
        </div>
      </div>
    </div>
  );
}
