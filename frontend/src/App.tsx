import { useState, useEffect, useCallback } from 'react';
import {
  Settings, Save, CheckCircle2, AlertCircle, LogIn, LogOut,
  Bot, Webhook, User, Loader2, Copy, ExternalLink, Moon, Sun,
} from 'lucide-react';

// ── Types ──────────────────────────────────────────────────────────────────

interface AuthUser {
  username?: string;
  user_id?: string;
}

interface BotStatus {
  enabled: boolean;
  is_registered_bot?: boolean;
  connected?: boolean;
  peer_email?: string;
  bot_uid?: string;
}

interface DeviceCode {
  user_code: string;
  verification_url: string;
  bot_uid: string;
  expires_in?: number;
}

// ── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  return (
    <div className="min-h-screen w-full bg-executive-bg text-executive-text executive-grid">
      {/* Header */}
      <header className="h-14 border-b border-executive-border glass sticky top-0 z-10 px-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-executive-accent flex items-center justify-center font-bold text-white text-sm">
            EA
          </div>
          <span className="font-medium text-sm">CEO Platform v2</span>
        </div>
        <button
          onClick={() => setTheme(t => t === 'light' ? 'dark' : 'light')}
          className="p-2 rounded-lg text-executive-muted hover:text-executive-text hover:bg-executive-card transition-colors"
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      {/* Content */}
      <main className="max-w-2xl mx-auto py-12 px-6">
        <SettingsPage />
      </main>
    </div>
  );
}

// ── Settings Page ──────────────────────────────────────────────────────────

function SettingsPage() {
  const [user, setUser]           = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  const [settings, setSettings]   = useState<Record<string, string>>({});
  const [settLoading, setSettLoading] = useState(false);
  const [saved, setSaved]         = useState(false);
  const [saveError, setSaveError] = useState('');

  const [botStatus, setBotStatus] = useState<BotStatus | null>(null);
  const [deviceCode, setDeviceCode] = useState<DeviceCode | null>(null);
  const [botPolling, setBotPolling] = useState(false);
  const [botConnecting, setBotConnecting] = useState(false);
  const [botError, setBotError]   = useState('');
  const [botSuccess, setBotSuccess] = useState('');
  const [copied, setCopied]       = useState(false);

  // ── Auth check ─────────────────────────────────────────────────────────

  const checkAuth = useCallback(async () => {
    try {
      const r = await fetch('/api/auth/me', { credentials: 'include' });
      const d = await r.json();
      setUser(d?.user_id ? d : null);
    } catch {
      setUser(null);
    } finally {
      setAuthLoading(false);
    }
  }, []);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  // ── Load settings + bot status once authed ─────────────────────────────

  useEffect(() => {
    if (!user) return;
    setSettLoading(true);
    Promise.all([
      fetch('/api/settings', { credentials: 'include' }).then(r => r.ok ? r.json() : {}),
      fetch('/api/teams/bot', { credentials: 'include' }).then(r => r.ok ? r.json() : null),
    ]).then(([s, b]) => {
      setSettings(s || {});
      setBotStatus(b);
    }).finally(() => setSettLoading(false));
  }, [user]);

  // ── Save settings ──────────────────────────────────────────────────────

  const save = async () => {
    setSaveError('');
    try {
      const r = await fetch('/api/settings', {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!r.ok) throw new Error('Save failed');
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      setSaveError(e.message || 'Save failed');
    }
  };

  // ── Bot: start device code flow ────────────────────────────────────────

  const startBotAuth = async () => {
    setBotError('');
    setBotSuccess('');
    setBotConnecting(true);
    try {
      const r = await fetch('/api/teams/bot/auth-start', {
        method: 'POST',
        credentials: 'include',
      });
      if (!r.ok) throw new Error('Failed to start device flow');
      const d = await r.json();
      setDeviceCode(d);
      pollBotAuth(d.bot_uid);
    } catch (e: any) {
      setBotError(e.message || 'Could not start bot authentication');
      setBotConnecting(false);
    }
  };

  // ── Bot: poll until complete ───────────────────────────────────────────

  const pollBotAuth = useCallback(async (botUid: string) => {
    setBotPolling(true);
    const start = Date.now();
    const timeout = 5 * 60 * 1000; // 5 min

    const tick = async () => {
      if (Date.now() - start > timeout) {
        setBotError('Device code expired — please try again.');
        setBotPolling(false);
        setBotConnecting(false);
        setDeviceCode(null);
        return;
      }
      try {
        const r = await fetch('/api/teams/bot/auth-poll', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bot_uid: botUid }),
        });
        const d = await r.json();
        if (d.status === 'success' || d.connected) {
          // Activate bot for this user
          await fetch(`/api/teams/bot/activate?bot_uid=${botUid}`, {
            method: 'POST',
            credentials: 'include',
          });
          setBotSuccess('AI assistant connected! Open Microsoft Teams to start chatting.');
          setBotPolling(false);
          setBotConnecting(false);
          setDeviceCode(null);
          // Refresh bot status
          const bs = await fetch('/api/teams/bot', { credentials: 'include' });
          if (bs.ok) setBotStatus(await bs.json());
        } else if (d.status === 'pending' || d.status === 'authorization_pending') {
          setTimeout(tick, 4000);
        } else {
          setBotError(d.message || 'Authentication failed');
          setBotPolling(false);
          setBotConnecting(false);
          setDeviceCode(null);
        }
      } catch {
        setTimeout(tick, 5000);
      }
    };
    tick();
  }, []);

  // ── Bot: disconnect ────────────────────────────────────────────────────

  const disconnectBot = async () => {
    setBotError('');
    try {
      await fetch('/api/teams/bot/disable', { method: 'POST', credentials: 'include' });
      setBotStatus(s => s ? { ...s, enabled: false, connected: false } : null);
      setBotSuccess('');
    } catch {
      setBotError('Failed to disconnect bot');
    }
  };

  // ── Copy helper ────────────────────────────────────────────────────────

  const copyCode = () => {
    if (deviceCode?.user_code) {
      navigator.clipboard.writeText(deviceCode.user_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // ── Render: loading / not logged in ───────────────────────────────────

  if (authLoading) {
    return (
      <div className="flex items-center justify-center py-32 text-executive-muted gap-3">
        <Loader2 size={20} className="animate-spin" />
        <span className="font-mono text-sm">Loading...</span>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center py-32 gap-8">
        <div className="w-16 h-16 rounded-2xl bg-executive-accent/10 flex items-center justify-center">
          <Settings size={32} className="text-executive-accent" />
        </div>
        <div className="text-center">
          <h1 className="text-3xl font-bold mb-2">CEO Platform</h1>
          <p className="text-executive-muted">Sign in with your Microsoft account to continue.</p>
        </div>
        <a
          href="/auth/login"
          className="flex items-center gap-3 px-8 py-4 bg-executive-accent text-white rounded-2xl font-semibold hover:bg-emerald-400 transition-all shadow-sm"
        >
          <LogIn size={20} />
          Sign in with Microsoft
        </a>
      </div>
    );
  }

  // ── Render: settings ──────────────────────────────────────────────────

  const botConnected = botStatus?.enabled && botStatus?.connected !== false;

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex items-end justify-between mb-2">
        <div>
          <p className="text-xs font-mono uppercase text-executive-accent tracking-[0.25em] mb-2">Configuration</p>
          <h1 className="text-4xl font-bold tracking-tight">Settings</h1>
        </div>
        <button
          onClick={save}
          disabled={settLoading}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all ${
            saved
              ? 'bg-emerald-500 text-white'
              : 'bg-executive-accent text-white hover:bg-emerald-400 shadow-sm'
          }`}
        >
          {saved ? <CheckCircle2 size={16} /> : <Save size={16} />}
          {saved ? 'Saved!' : 'Save Changes'}
        </button>
      </div>

      {saveError && <ErrorBanner message={saveError} />}

      {/* Profile */}
      <Section icon={<User size={16} />} title="Profile" color="text-executive-accent">
        <Field
          label="Display Name"
          value={settings.display_name || ''}
          onChange={v => setSettings(p => ({ ...p, display_name: v }))}
          placeholder="e.g. Daniel"
        />
        <Field
          label="Report Email"
          value={settings.report_email || ''}
          onChange={v => setSettings(p => ({ ...p, report_email: v }))}
          placeholder="daniel@company.com"
          type="email"
        />
        <div className="flex items-center justify-between pt-2 border-t border-executive-border">
          <div>
            <p className="text-xs font-mono uppercase text-executive-muted tracking-wider mb-0.5">Signed in as</p>
            <p className="text-sm font-medium">{user.username}</p>
          </div>
          <a
            href="/auth/logout"
            className="flex items-center gap-1.5 text-xs text-executive-muted hover:text-rose-500 transition-colors font-mono"
          >
            <LogOut size={13} />
            Sign out
          </a>
        </div>
      </Section>

      {/* AI Assistant (Teams Bot) */}
      <Section icon={<Bot size={16} />} title="AI Assistant" color="text-sky-500">
        {botConnected ? (
          /* Connected state */
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3 p-4 bg-emerald-500/8 border border-emerald-500/20 rounded-xl">
              <CheckCircle2 size={18} className="text-emerald-500 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">AI assistant connected</p>
                <p className="text-xs text-executive-muted">
                  {botStatus?.peer_email
                    ? `Signed in as ${botStatus.peer_email}`
                    : 'Open Microsoft Teams and start a 1:1 chat with your AI assistant.'}
                </p>
              </div>
            </div>
            <button
              onClick={disconnectBot}
              className="self-start flex items-center gap-1.5 px-4 py-2 rounded-lg border border-rose-300 text-rose-500 text-xs font-mono hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-all"
            >
              <LogOut size={12} />
              Disconnect
            </button>
          </div>
        ) : deviceCode ? (
          /* Device code pending state */
          <div className="flex flex-col gap-4">
            <p className="text-sm text-executive-muted">
              Go to the link below and enter the code to connect your AI assistant to Teams:
            </p>
            <a
              href={deviceCode.verification_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-executive-accent hover:underline font-mono"
            >
              <ExternalLink size={14} />
              {deviceCode.verification_url}
            </a>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 px-5 py-3 bg-executive-bg border-2 border-executive-accent rounded-xl">
                <span className="text-2xl font-mono font-bold tracking-[0.3em] text-executive-text">
                  {deviceCode.user_code}
                </span>
              </div>
              <button
                onClick={copyCode}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-mono transition-all ${
                  copied
                    ? 'border-emerald-500 text-emerald-500'
                    : 'border-executive-border text-executive-muted hover:border-executive-accent hover:text-executive-accent'
                }`}
              >
                <Copy size={12} />
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <div className="flex items-center gap-2 text-xs text-executive-muted font-mono">
              <Loader2 size={12} className="animate-spin" />
              Waiting for authorization...
            </div>
            <button
              onClick={() => { setDeviceCode(null); setBotConnecting(false); setBotPolling(false); }}
              className="self-start text-xs font-mono text-executive-muted hover:text-executive-text transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          /* Not connected state */
          <div className="flex flex-col gap-4">
            <p className="text-sm text-executive-muted leading-relaxed">
              Connect an AI assistant account to enable two-way AI chat in Microsoft Teams.
              You'll be asked to sign in as the assistant using a device code.
            </p>
            {botError && <ErrorBanner message={botError} />}
            {botSuccess && <SuccessBanner message={botSuccess} />}
            <button
              onClick={startBotAuth}
              disabled={botConnecting}
              className="flex items-center gap-2 self-start px-5 py-2.5 bg-sky-500 text-white rounded-xl text-sm font-semibold hover:bg-sky-400 disabled:opacity-50 transition-all"
            >
              {botConnecting ? <Loader2 size={15} className="animate-spin" /> : <Bot size={15} />}
              {botConnecting ? 'Starting...' : 'Connect AI Assistant'}
            </button>
          </div>
        )}
      </Section>

      {/* Teams Webhook */}
      <Section icon={<Webhook size={16} />} title="Teams Webhook" color="text-purple-400">
        <p className="text-xs text-executive-muted -mt-1">
          Optional — used for push notifications via Power Automate.
        </p>
        <Field
          label="Webhook URL"
          value={settings.teams_webhook_url || ''}
          onChange={v => setSettings(p => ({ ...p, teams_webhook_url: v }))}
          placeholder="https://..."
        />
      </Section>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Section({
  icon, title, color, children,
}: {
  icon: React.ReactNode;
  title: string;
  color: string;
  children: React.ReactNode;
}) {
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

function Field({
  label, value, onChange, placeholder, type = 'text',
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-mono uppercase text-executive-muted tracking-wider">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-executive-bg border border-executive-border rounded-xl px-4 py-2.5 text-sm text-executive-text focus:outline-none focus:border-executive-accent transition-colors placeholder:text-executive-muted/40"
      />
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 p-3 bg-rose-500/8 border border-rose-500/20 rounded-xl text-rose-500 text-xs font-mono">
      <AlertCircle size={14} className="shrink-0" />
      {message}
    </div>
  );
}

function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 p-3 bg-emerald-500/8 border border-emerald-500/20 rounded-xl text-emerald-600 dark:text-emerald-400 text-xs font-mono">
      <CheckCircle2 size={14} className="shrink-0" />
      {message}
    </div>
  );
}
