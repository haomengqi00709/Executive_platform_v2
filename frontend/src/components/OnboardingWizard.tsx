import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ArrowLeft, ArrowRight, CheckCircle2, Loader2, Copy, ExternalLink,
  Globe, Shield, Bot, AlertCircle, Sparkles, ChevronRight,
} from 'lucide-react';
import {
  submitOnboardingPreferences, enrichCompanyWebsite,
} from '../lib/api';
import type { WebsiteEnrichment } from '../lib/api';

interface Props {
  /** Called once Step 3 (bot) completes (or is skipped) and the backend has
   *  begun the init chain. Parent (App.tsx) re-polls /api/profile/status and
   *  transitions to the reveal page. */
  onSubmitted: () => void;
  /** Display name from OAuth (Microsoft Graph /me). Shown on the confirm
   *  page as the friendly "Setting up for X" header. Falls back to "you"
   *  if empty. */
  displayName?: string;
}

type StepNum = 1 | 2 | 3;

const STEPS: { n: StepNum; label: string }[] = [
  { n: 1, label: 'Website' },
  { n: 2, label: 'Confirm' },
  { n: 3, label: 'AI assistant' },
];

// ═══════════════════════════════════════════════════════════════════
//                        WIZARD CONTAINER
// ═══════════════════════════════════════════════════════════════════

export default function OnboardingWizard({ onSubmitted, displayName = '' }: Props) {
  const [step, setStep] = useState<StepNum>(1);

  // Step 1 data
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [enrichment, setEnrichment] = useState<WebsiteEnrichment | null>(null);
  const [enriching, setEnriching] = useState(false);

  // Step 2 data — editable company name + optional freeform context
  // (legacy field name `linkedin_bio` kept to avoid backend churn; UX no
  // longer mentions LinkedIn — see profile_init.py for how it's used).
  const [companyName, setCompanyName] = useState('');
  const [extraContext, setExtraContext] = useState('');

  // Step 3 (bot) state
  const [submittingPrefs, setSubmittingPrefs] = useState(false);
  const [prefsSubmitted, setPrefsSubmitted] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  // When user confirms Step 2, we POST preferences in the background while
  // they go through Step 3. The init chain starts immediately; Step 3's
  // device flow runs in parallel. This way the long inbox scan begins
  // ~30 seconds earlier than if we waited for the bot.
  //
  // Returns true on success so the caller can advance immediately —
  // checking globalError state after the await would read a stale value.
  const fireSubmitPreferences = async (): Promise<boolean> => {
    setSubmittingPrefs(true);
    setGlobalError(null);
    try {
      await submitOnboardingPreferences({
        company_website_url:     websiteUrl.trim(),
        company_name:            companyName.trim(),
        company_what_they_do:    enrichment?.what_they_do || enrichment?.description || '',
        company_headquarters:    enrichment?.headquarters || '',
        company_business_lines:  enrichment?.business_lines || [],
        company_products:        enrichment?.products || [],
        company_market_segments: enrichment?.segments || [],
        company_role_emails:     enrichment?.role_emails || [],
        linkedin_bio:            extraContext.trim(),
      });
      setPrefsSubmitted(true);
      return true;
    } catch (e) {
      setGlobalError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setSubmittingPrefs(false);
    }
  };

  // Triggered when Step 4 finishes (bot connected) or user skips.
  // Backend init chain is already running (or about to run); parent will
  // detect stage='generating' on its next status poll and show Step 5.
  const finishOnboarding = () => {
    onSubmitted();
  };

  return (
    <div className="min-h-screen w-full bg-executive-bg executive-grid overflow-auto py-10 px-6">
      <div className="max-w-2xl mx-auto">
        <Header step={step} />

        {globalError && (
          <div className="mb-4 flex items-start gap-2 text-sm text-rose-400 bg-rose-400/8 border border-rose-400/30 rounded-lg px-3 py-2">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{globalError}</span>
          </div>
        )}

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22, ease: [0.32, 0.72, 0, 1] }}
            className="bg-executive-card border border-executive-border rounded-2xl p-8 shadow-sm"
          >
            {step === 1 && (
              <Step1Website
                value={websiteUrl}
                onChange={setWebsiteUrl}
                enrichment={enrichment}
                enriching={enriching}
                onNext={async () => {
                  const url = websiteUrl.trim();
                  if (!url) return;
                  // Enrichment is fired non-blocking so Step 2 mounts
                  // immediately and the user sees the loading state there.
                  // Step 2's confirm button is disabled while `enriching`
                  // is true so a fast click can't submit empty company_name.
                  setEnriching(true);
                  enrichCompanyWebsite(url)
                    .then((r) => {
                      setEnrichment(r);
                      if (r.company_name) setCompanyName(r.company_name);
                    })
                    .catch(() => {/* graceful — Step 2 will show empty */})
                    .finally(() => setEnriching(false));
                  setStep(2);
                }}
              />
            )}

            {step === 2 && (
              <Step2Confirm
                displayName={displayName}
                extraContext={extraContext}
                onExtraContextChange={setExtraContext}
                enrichment={enrichment}
                enriching={enriching}
                submitting={submittingPrefs}
                onBack={() => setStep(1)}
                onConfirm={async () => {
                  // companyName is silently captured from enrichment (may be
                  // empty if extraction failed) — user no longer required to
                  // confirm it here. Falls back gracefully downstream.
                  const ok = await fireSubmitPreferences();
                  if (ok) setStep(3);
                }}
              />
            )}

            {step === 3 && (
              <Step3ConnectBot
                onBack={() => setStep(2)}
                onSkip={finishOnboarding}
                onDone={finishOnboarding}
                prefsSubmitted={prefsSubmitted}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//                            HEADER + BAR
// ═══════════════════════════════════════════════════════════════════

function Header({ step }: { step: StepNum }) {
  return (
    <header className="mb-6">
      <p className="text-xs font-mono uppercase text-executive-muted tracking-widest mb-2">
        Set up your AI assistant — step {step} of {STEPS.length}
      </p>
      <h1 className="text-2xl font-bold text-executive-text">
        {step === 1 && "Let's start with your company"}
        {step === 2 && 'Confirm and start'}
        {step === 3 && 'Connect Audrey to Teams'}
      </h1>
      <div className="mt-4 flex items-center gap-2">
        {STEPS.map((s, i) => (
          <div key={s.n} className="flex items-center gap-2 flex-1">
            <div className={`flex items-center gap-1.5 ${s.n <= step ? 'text-executive-accent' : 'text-executive-muted'}`}>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-semibold border ${
                s.n === step ? 'border-executive-accent bg-executive-accent/15'
                : s.n < step  ? 'border-executive-accent bg-executive-accent text-white'
                              : 'border-executive-border'
              }`}>
                {s.n < step ? '✓' : s.n}
              </div>
              <span className="text-[11px] font-medium hidden sm:inline">{s.label}</span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`flex-1 h-px ${s.n < step ? 'bg-executive-accent' : 'bg-executive-border'}`} />
            )}
          </div>
        ))}
      </div>
    </header>
  );
}

// ═══════════════════════════════════════════════════════════════════
//                              STEP 1
// ═══════════════════════════════════════════════════════════════════

function Step1Website({
  value, onChange, enrichment, enriching, onNext,
}: {
  value: string;
  onChange: (v: string) => void;
  enrichment: WebsiteEnrichment | null;
  enriching: boolean;
  onNext: () => void;
}) {
  const canSubmit = value.trim().length > 0 && !enriching;
  return (
    <div>
      <StepHeader
        icon={Globe}
        color="text-sky-400"
        title="What's your company website?"
        subtitle="We'll use this to learn what your business does, so the AI gets it right from day one."
      />

      <label className="text-xs text-executive-muted block mb-2 mt-2">Company website URL</label>
      <input
        type="url"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="https://your-company.com"
        autoFocus
        onKeyDown={e => { if (e.key === 'Enter' && canSubmit) onNext(); }}
        className="w-full px-4 py-3 text-sm bg-executive-bg border border-executive-border rounded-lg focus:outline-none focus:border-executive-accent/60"
      />

      {enrichment && (
        <p className="mt-2 text-xs text-emerald-400">
          ✓ Pre-scanned — we'll confirm what we found in Step 3
        </p>
      )}

      <div className="mt-8 flex items-center justify-end">
        <NextButton onClick={onNext} disabled={!canSubmit}>
          {enriching ? 'Scanning...' : 'Next'}
        </NextButton>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//                              STEP 2
// ═══════════════════════════════════════════════════════════════════

function Step2Confirm({
  displayName,
  extraContext, onExtraContextChange,
  enrichment, enriching, submitting,
  onBack, onConfirm,
}: {
  displayName: string;
  extraContext: string;
  onExtraContextChange: (v: string) => void;
  enrichment: WebsiteEnrichment | null;
  enriching: boolean;
  submitting: boolean;
  onBack: () => void;
  onConfirm: () => void;
}) {
  // Headline shows the user's OAuth display name — always available, always
  // correct. Falls back to "you" if Microsoft Graph didn't return one (rare).
  const headerName = displayName.trim() || 'you';

  return (
    <div>
      <StepHeader
        icon={Sparkles}
        color="text-amber-400"
        title="Almost ready"
        subtitle="Review what's about to happen and start your setup."
      />

      <div>
        <p className="text-[10px] font-mono uppercase text-executive-muted tracking-wider mb-1">
          Setting up for
        </p>
        <p className="text-2xl font-bold text-executive-text leading-tight">{headerName}</p>
        {enriching && (
          <p className="mt-2 text-xs text-executive-muted flex items-center gap-1.5">
            <Loader2 size={11} className="animate-spin" />
            Still reading your website…
          </p>
        )}
      </div>

      {enrichment && (enrichment.what_they_do || enrichment.description
                      || enrichment.headquarters || enrichment.business_lines?.length
                      || enrichment.products?.length || enrichment.segments?.length
                      || enrichment.role_emails?.length) && (
        <div className="mt-4 p-3 rounded-lg bg-executive-bg border border-executive-border space-y-2">
          <p className="text-[10px] font-mono uppercase text-executive-muted tracking-wider">
            What we learned from your site
          </p>

          {(enrichment.what_they_do || enrichment.description) && (
            <p className="text-xs text-executive-text leading-relaxed">
              {enrichment.what_they_do || enrichment.description}
            </p>
          )}

          {enrichment.headquarters && (
            <p className="text-[11px] text-executive-muted">
              <span className="text-executive-text font-medium">HQ:</span> {enrichment.headquarters}
            </p>
          )}

          {enrichment.business_lines?.length > 0 && (
            <div>
              <p className="text-[11px] text-executive-text font-medium mb-0.5">Business lines</p>
              <ul className="text-[11px] text-executive-muted list-disc ml-4 space-y-0.5">
                {enrichment.business_lines.map(b => <li key={b}>{b}</li>)}
              </ul>
            </div>
          )}

          {enrichment.products?.length > 0 && (
            <p className="text-[11px] text-executive-muted">
              <span className="text-executive-text font-medium">Products:</span>{' '}
              {enrichment.products.join(', ')}
            </p>
          )}

          {enrichment.segments?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {enrichment.segments.map(s => (
                <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-executive-accent/10 text-executive-accent">
                  {s}
                </span>
              ))}
            </div>
          )}

          {enrichment.role_emails?.length > 0 && (
            <p className="text-[11px] text-executive-muted">
              <span className="text-executive-text font-medium">Contact:</span>{' '}
              {enrichment.role_emails.join(' · ')}
            </p>
          )}
        </div>
      )}

      {/* Optional freeform context — replaces the deleted "About you" step.
          Stored under the legacy `linkedin_bio` settings key. */}
      <div className="mt-6">
        <label className="text-xs text-executive-muted block mb-2">
          Anything else you'd like the AI to know? <span className="italic text-executive-muted/70">(optional — you can edit later in Profile)</span>
        </label>
        <textarea
          value={extraContext}
          onChange={e => onExtraContextChange(e.target.value)}
          placeholder="Anything that would help the AI understand you better — your background, working style, languages you speak, key preferences. Optional, you can edit later."
          rows={3}
          className="w-full p-3 rounded-lg bg-executive-bg border border-executive-border text-sm text-executive-text resize-y focus:border-executive-accent focus:outline-none"
        />
      </div>

      <div className="mt-6">
        <p className="text-sm text-executive-text font-medium mb-2">What we'll set up for you:</p>
        <ul className="space-y-1.5 text-xs text-executive-muted">
          {[
            'Scan the last 12 months of your inbox',
            'Build your contact, project, and company databases',
            'Draft your personal, business, and market-segment profiles',
            'Schedule a daily morning briefing in Teams',
            'Push new important emails to Teams as they arrive',
            'Watch OneDrive for meeting recordings — summarize automatically',
            'Capture invoices and receipts from email attachments',
          ].map(t => (
            <li key={t} className="flex items-start gap-2">
              <ChevronRight size={11} className="mt-0.5 text-executive-accent shrink-0" />
              <span>{t}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-5 flex items-start gap-3 p-3 rounded-lg bg-emerald-500/8 border border-emerald-500/20">
        <Shield size={16} className="text-emerald-500 mt-0.5 shrink-0" />
        <div className="text-xs text-executive-text">
          <p className="font-semibold text-emerald-500 mb-0.5">Your data stays on your Microsoft Azure</p>
          <p className="text-executive-muted">
            Nothing leaves your tenant. The platform runs inside your own cloud and only your
            Microsoft Graph API sees the email content.
          </p>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between">
        <BackButton onClick={onBack} disabled={submitting} />
        {/* Disable Start setup while enrichment is still running — otherwise
            a fast click submits before the website extraction returns, which
            leaves settings.company_name empty downstream (race condition that
            caused the empty-sidebar bug). */}
        <NextButton onClick={onConfirm} disabled={submitting || enriching}>
          {submitting
            ? <><Loader2 size={14} className="animate-spin" /> Starting…</>
            : enriching
              ? <><Loader2 size={14} className="animate-spin" /> Reading site…</>
              : 'Start setup →'}
        </NextButton>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//                              STEP 3 (bot device flow)
// ═══════════════════════════════════════════════════════════════════

interface DeviceCode {
  user_code: string;
  verification_url: string;
}

function Step3ConnectBot({
  onBack, onSkip, onDone, prefsSubmitted,
}: {
  onBack: () => void;
  onSkip: () => void;
  onDone: () => void;
  prefsSubmitted: boolean;
}) {
  const [deviceCode, setDeviceCode] = useState<DeviceCode | null>(null);
  const [status, setStatus] = useState<'idle' | 'starting' | 'polling' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Auto-start as soon as preferences are submitted (smooth handoff).
  useEffect(() => {
    if (prefsSubmitted && status === 'idle') {
      startFlow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefsSubmitted]);

  const startFlow = async () => {
    setStatus('starting');
    setErrorMsg(null);
    try {
      const r = await fetch('/api/teams/bot/auth-start', {
        method: 'POST', credentials: 'include',
      });
      if (!r.ok) throw new Error('Failed to start device flow');
      setDeviceCode(await r.json());
      setStatus('polling');
      pollLoop();
    } catch (e) {
      setStatus('error');
      setErrorMsg(e instanceof Error ? e.message : 'Could not start');
    }
  };

  const pollLoop = async () => {
    const startedAt = Date.now();
    const tick = async () => {
      if (Date.now() - startedAt > 5 * 60 * 1000) {
        setStatus('error');
        setErrorMsg('Device code expired — please try again.');
        setDeviceCode(null);
        return;
      }
      try {
        const r = await fetch('/api/teams/bot/auth-poll', {
          method: 'POST', credentials: 'include',
        });
        const d = await r.json();
        if (d.status === 'success') {
          // The bot's tokens are saved + in MSAL cache (commit a28518c).
          // Now bind owner_uid via activate. If the user signed in as
          // themselves (Fix C in commit ab53705), we get a 400 here.
          const activateRes = await fetch(`/api/teams/bot/activate?bot_uid=${d.bot_uid}`, {
            method: 'POST', credentials: 'include',
          });
          if (!activateRes.ok) {
            const err = await activateRes.json().catch(() => ({} as any));
            const detail: string = err?.detail || '';
            let msg: string;
            if (activateRes.status === 409) {
              msg = 'This AI assistant account is already claimed by another user. '
                  + 'Ask that user to disconnect first, or contact your admin.';
            } else if (activateRes.status === 400) {
              msg = detail || 'You signed in as yourself. The AI assistant must be a '
                  + 'separate Microsoft account in your tenant (e.g. audrey@your-company.com).';
            } else {
              msg = `Activation failed (HTTP ${activateRes.status})${detail ? ': ' + detail : ''}`;
            }
            setStatus('error');
            setErrorMsg(msg);
            setDeviceCode(null);
            return;
          }
          setStatus('success');
          setDeviceCode(null);
          // Tiny pause so the success state is visible, then advance.
          setTimeout(onDone, 900);
        } else if (d.status === 'pending' || d.status === 'authorization_pending') {
          setTimeout(tick, 4000);
        } else {
          setStatus('error');
          setErrorMsg(d.message || 'Authentication failed');
          setDeviceCode(null);
        }
      } catch {
        setTimeout(tick, 5000);
      }
    };
    tick();
  };

  const copyCode = () => {
    if (!deviceCode) return;
    navigator.clipboard.writeText(deviceCode.user_code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div>
      <StepHeader
        icon={Bot}
        color="text-sky-500"
        title="Connect Audrey to Microsoft Teams"
        subtitle="Audrey is a separate Microsoft account in your tenant that talks to you 1:1 in Teams. Set up by your IT — sign in as her below."
      />

      {!prefsSubmitted && (
        <p className="text-xs text-executive-muted italic">Waiting for setup to start…</p>
      )}

      {status === 'success' && (
        <SuccessBlock />
      )}

      {status === 'error' && (
        <div className="mb-4 flex items-start gap-2 p-3 rounded-lg bg-rose-500/8 border border-rose-500/30 text-sm">
          <AlertCircle size={16} className="text-rose-500 mt-0.5 shrink-0" />
          <div className="flex-1 text-executive-text">
            <p className="font-semibold text-rose-500 mb-0.5">Connection failed</p>
            <p className="text-xs text-executive-muted">{errorMsg}</p>
            <button
              onClick={startFlow}
              className="mt-2 text-xs text-executive-accent hover:underline font-medium"
            >
              Try again →
            </button>
          </div>
        </div>
      )}

      {status === 'polling' && deviceCode && (
        <div className="flex flex-col gap-4">
          <a
            href={deviceCode.verification_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-sm text-executive-accent hover:underline font-mono"
          >
            <ExternalLink size={13} />
            Open {deviceCode.verification_url}
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
              <Copy size={11} /> {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>

          <div className="text-xs text-executive-muted leading-relaxed">
            <p className="font-semibold text-executive-text mb-1">⚠️ Important</p>
            <p>
              When Microsoft asks who to sign in as, choose the <strong>AI assistant account</strong>
              {' '}(e.g. <code className="text-executive-text">audrey@your-company.com</code>) —{' '}
              <strong>not your own login</strong>. If you sign in as yourself,
              Audrey becomes a clone of you instead of a separate assistant.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs text-executive-muted font-mono mt-1">
            <Loader2 size={11} className="animate-spin" />
            Waiting for Microsoft sign-in…
          </div>

        </div>
      )}

      {status === 'starting' && (
        <div className="flex items-center gap-2 text-xs text-executive-muted font-mono">
          <Loader2 size={11} className="animate-spin" />
          Getting a device code from Microsoft…
        </div>
      )}

      <div className="mt-8 flex items-center justify-between">
        <BackButton onClick={onBack} disabled={status === 'polling'} />
        <button
          onClick={onSkip}
          className="text-sm text-executive-muted hover:text-executive-text underline-offset-2 hover:underline transition-colors"
        >
          {status === 'success' ? 'Continue →' : 'Set up later — skip for now'}
        </button>
      </div>
    </div>
  );
}

function SuccessBlock() {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      className="mb-4 flex items-start gap-3 p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/30"
    >
      <CheckCircle2 size={20} className="text-emerald-500 mt-0.5 shrink-0" />
      <div className="text-sm text-executive-text">
        <p className="font-semibold text-emerald-500 mb-0.5">Audrey is connected!</p>
        <p className="text-xs text-executive-muted">
          She'll appear in your Microsoft Teams 1:1 list shortly. Let's see what we built…
        </p>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//                            SHARED BITS
// ═══════════════════════════════════════════════════════════════════

function StepHeader({
  icon: Icon, color, title, subtitle,
}: {
  icon: typeof Globe;
  color: string;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={18} className={color} />
        <h2 className="text-lg font-semibold text-executive-text">{title}</h2>
      </div>
      <p className="text-sm text-executive-muted leading-relaxed">{subtitle}</p>
    </div>
  );
}

function NextButton({
  children, onClick, disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-executive-accent text-white font-semibold text-sm hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
    >
      {children} <ArrowRight size={14} />
    </button>
  );
}

function BackButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-1.5 px-3 py-2 text-sm text-executive-muted hover:text-executive-text disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
    >
      <ArrowLeft size={13} /> Back
    </button>
  );
}
