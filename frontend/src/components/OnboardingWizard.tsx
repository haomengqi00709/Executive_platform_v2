import { useState } from 'react';
import {
  ArrowLeft, ArrowRight, CheckCircle2, Loader2,
  Clock, Calendar, Mail, User, Sliders, ChevronLeft,
  Briefcase, Inbox, Settings as SettingsIcon,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { submitOnboardingPreferences } from '../lib/api';
import type {
  BriefingsPreset, MonitorPreset, OnboardingPreferences,
} from '../lib/api';

interface Props {
  onSubmitted: () => void;
}

// ── Persona presets bundle everything ─────────────────────

const PERSONAS: {
  id: 'standard' | 'highvolume';
  icon: LucideIcon;
  title: string;
  tagline: string;
  features: string[];
  recommended?: boolean;
  prefs: Omit<OnboardingPreferences, 'personal_profile'>;
}[] = [
  {
    id: 'standard',
    icon: Briefcase,
    title: 'Standard Executive',
    tagline: 'Most executives — balanced briefings, moderate alerts',
    recommended: true,
    prefs: {
      history_months:   12,
      briefings_preset: 'recommended',
      monitor_preset:   'recommended',
    },
    features: [
      '1 year of email history scanned',
      '3 scheduled briefings — daily 7 AM + weekly Mon 8 AM + market intel every 3 days',
      'Email checks every 15 minutes (8 AM–8 PM)',
      'Immediate Teams push for high-priority emails',
    ],
  },
  {
    id: 'highvolume',
    icon: Inbox,
    title: 'High-volume Inbox',
    tagline: '100+ emails/day — quieter pings, focused brief',
    prefs: {
      history_months:   6,
      briefings_preset: 'minimal',
      monitor_preset:   'quiet',
    },
    features: [
      '6 months of email history (faster initial setup)',
      'One daily 7 AM morning brief — no weekly or intel noise',
      'Email batches every 60 minutes (9 AM–6 PM)',
      'No immediate pushes — strictly batched',
    ],
  },
];

// ── Main wizard ───────────────────────────────────────────

export default function OnboardingWizard({ onSubmitted }: Props) {
  const [view, setView] = useState<'cards' | 'customize'>('cards');
  const [submittingPersona, setSubmittingPersona] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pickPersona = async (personaId: string) => {
    const persona = PERSONAS.find(p => p.id === personaId);
    if (!persona) return;
    setSubmittingPersona(personaId);
    setError(null);
    try {
      await submitOnboardingPreferences({ ...persona.prefs });
      onSubmitted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmittingPersona(null);
    }
  };

  if (view === 'customize') {
    return (
      <CustomizeFlow
        onBack={() => setView('cards')}
        onSubmitted={onSubmitted}
      />
    );
  }

  return (
    <div className="min-h-screen w-full bg-executive-bg executive-grid overflow-auto py-12 px-6">
      <div className="max-w-5xl mx-auto">
        <header className="mb-10 text-center">
          <p className="text-xs font-mono uppercase text-executive-muted tracking-widest mb-2">
            First-time setup
          </p>
          <h1 className="text-3xl font-bold text-executive-text">Pick a setup that fits you</h1>
          <p className="text-sm text-executive-muted mt-3 max-w-xl mx-auto">
            One click configures your AI history depth, briefing schedule, and email
            monitoring. You can change anything later in Settings.
          </p>
        </header>

        {error && (
          <div className="mb-6 text-sm text-rose-400 bg-rose-400/10 border border-rose-400/30 rounded-lg px-3 py-2 max-w-2xl mx-auto">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {PERSONAS.map(p => (
            <PersonaCard
              key={p.id}
              persona={p}
              busy={submittingPersona === p.id}
              disabled={submittingPersona !== null && submittingPersona !== p.id}
              onClick={() => pickPersona(p.id)}
            />
          ))}
          <CustomizeCard
            disabled={submittingPersona !== null}
            onClick={() => setView('customize')}
          />
        </div>

        <p className="text-center text-xs text-executive-muted mt-8">
          Not sure? Pick <span className="text-executive-text font-medium">Standard Executive</span> —
          works for almost everyone.
        </p>
      </div>
    </div>
  );
}

// ── Persona card ──────────────────────────────────────────

interface PersonaCardProps {
  persona: typeof PERSONAS[number];
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
}

function PersonaCard({ persona, busy, disabled, onClick }: PersonaCardProps) {
  const Icon = persona.icon;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`relative text-left p-6 rounded-2xl border transition-all flex flex-col h-full
                  ${persona.recommended
                    ? 'border-executive-accent/50 bg-executive-card shadow-lg shadow-executive-accent/5'
                    : 'border-executive-border bg-executive-card'}
                  ${!disabled && !busy ? 'hover:-translate-y-1 hover:shadow-xl hover:border-executive-accent' : ''}
                  ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                  `}
    >
      {persona.recommended && (
        <span className="absolute -top-2.5 left-5 px-2.5 py-0.5 rounded-full text-[10px] uppercase tracking-wider font-semibold bg-executive-accent text-white shadow-sm">
          Recommended
        </span>
      )}

      <div className="flex items-center gap-3 mb-4">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center
                         ${persona.recommended ? 'bg-executive-accent/15' : 'bg-executive-border/40'}`}>
          <Icon size={20} className={persona.recommended ? 'text-executive-accent' : 'text-executive-text'} />
        </div>
        <div className="min-w-0">
          <h3 className="text-lg font-bold text-executive-text leading-tight">{persona.title}</h3>
          <p className="text-xs text-executive-muted mt-0.5">{persona.tagline}</p>
        </div>
      </div>

      <ul className="space-y-2.5 mb-5 flex-1">
        {persona.features.map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-executive-muted leading-relaxed">
            <CheckCircle2 size={12} className="text-executive-accent/70 mt-0.5 flex-shrink-0" />
            <span>{f}</span>
          </li>
        ))}
      </ul>

      <div className={`flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg font-semibold text-sm transition-colors
                       ${persona.recommended
                         ? 'bg-executive-accent text-white'
                         : 'bg-executive-border/60 text-executive-text'}
                       ${busy ? 'opacity-80' : ''}`}>
        {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
        {busy ? 'Setting up…' : 'Start with this'}
      </div>
    </button>
  );
}

// ── Customize card ────────────────────────────────────────

function CustomizeCard({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`relative text-left p-6 rounded-2xl border border-dashed border-executive-border bg-executive-card/50 transition-all flex flex-col h-full
                  ${!disabled ? 'hover:bg-executive-card hover:border-executive-accent/60 cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}
    >
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-executive-border/40">
          <SettingsIcon size={20} className="text-executive-muted" />
        </div>
        <div className="min-w-0">
          <h3 className="text-lg font-bold text-executive-text leading-tight">Customize</h3>
          <p className="text-xs text-executive-muted mt-0.5">Tune every setting yourself</p>
        </div>
      </div>

      <ul className="space-y-2.5 mb-5 flex-1">
        {[
          'Slider for history depth (3–24 months)',
          'Pick each briefing schedule individually',
          'Configure monitor interval + active hours',
          'Add a personal profile for AI signatures',
        ].map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-executive-muted leading-relaxed">
            <span className="text-executive-muted/60 mt-0.5">›</span>
            <span>{f}</span>
          </li>
        ))}
      </ul>

      <div className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-executive-border text-executive-muted text-sm font-medium">
        Configure manually <ArrowRight size={14} />
      </div>
    </button>
  );
}

// ═══════════════════════════════════════════════════════════
//                  CUSTOMIZE 4-STEP FLOW
// (only shown when user clicks the Customize card)
// ═══════════════════════════════════════════════════════════

type Step = 1 | 2 | 3 | 4;

const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: 'History' },
  { n: 2, label: 'Briefings' },
  { n: 3, label: 'Email Monitor' },
  { n: 4, label: 'About You' },
];

function CustomizeFlow({ onBack, onSubmitted }: { onBack: () => void; onSubmitted: () => void }) {
  const [step, setStep] = useState<Step>(1);
  const [historyMonths, setHistoryMonths] = useState(12);
  const [briefingsPreset, setBriefingsPreset] = useState<BriefingsPreset>('recommended');
  const [monitorPreset, setMonitorPreset] = useState<MonitorPreset>('recommended');
  const [personalProfile, setPersonalProfile] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const next = () => setStep(s => Math.min(4, s + 1) as Step);
  const prev = () => setStep(s => Math.max(1, s - 1) as Step);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await submitOnboardingPreferences({
        history_months:   historyMonths,
        briefings_preset: briefingsPreset,
        monitor_preset:   monitorPreset,
        personal_profile: personalProfile.trim() || undefined,
      });
      onSubmitted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-executive-bg executive-grid overflow-auto py-12 px-6">
      <div className="max-w-3xl mx-auto">
        <button
          onClick={onBack}
          disabled={submitting}
          className="flex items-center gap-1.5 text-xs text-executive-muted hover:text-executive-text mb-6 transition-colors"
        >
          <ChevronLeft size={12} />
          Back to preset cards
        </button>

        <header className="mb-8">
          <p className="text-xs font-mono uppercase text-executive-muted tracking-widest mb-2">
            Customize setup — Step {step} of 4
          </p>
          <h1 className="text-2xl font-bold text-executive-text">Fine-tune every option</h1>
        </header>

        <StepBar current={step} />

        <div className="mt-6 bg-executive-card border border-executive-border rounded-2xl p-8 shadow-sm">
          {step === 1 && <Step1History months={historyMonths} setMonths={setHistoryMonths} />}
          {step === 2 && <Step2Briefings preset={briefingsPreset} setPreset={setBriefingsPreset} />}
          {step === 3 && <Step3Monitor preset={monitorPreset} setPreset={setMonitorPreset} />}
          {step === 4 && <Step4Personal text={personalProfile} setText={setPersonalProfile} />}
        </div>

        {error && (
          <div className="mt-4 text-sm text-rose-400 bg-rose-400/10 border border-rose-400/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <div className="mt-6 flex items-center justify-between">
          <button
            onClick={prev}
            disabled={step === 1 || submitting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-executive-muted hover:text-executive-text disabled:opacity-30 transition-colors"
          >
            <ArrowLeft size={14} /> Back
          </button>
          {step < 4 ? (
            <button
              onClick={next}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-executive-accent text-white font-semibold hover:opacity-90 transition-opacity"
            >
              Next <ArrowRight size={14} />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={submitting}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-executive-accent text-white font-semibold hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {submitting ? 'Starting setup…' : 'Confirm & start setup'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── StepBar + step bodies (Customize flow only) ───────────

function StepBar({ current }: { current: Step }) {
  return (
    <div className="flex items-center gap-2">
      {STEPS.map((s, i) => (
        <div key={s.n} className="flex items-center gap-2 flex-1">
          <div className={`flex items-center gap-2 ${s.n <= current ? 'text-executive-accent' : 'text-executive-muted'}`}>
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold border ${
              s.n === current ? 'border-executive-accent bg-executive-accent/15'
              : s.n < current ? 'border-executive-accent bg-executive-accent text-white'
              : 'border-executive-border'
            }`}>
              {s.n < current ? '✓' : s.n}
            </div>
            <span className="text-xs font-medium hidden md:inline">{s.label}</span>
          </div>
          {i < STEPS.length - 1 && (
            <div className={`flex-1 h-px ${s.n < current ? 'bg-executive-accent' : 'bg-executive-border'}`} />
          )}
        </div>
      ))}
    </div>
  );
}

function StepHeader({ icon: Icon, color, title, subtitle }: {
  icon: LucideIcon; color: string; title: string; subtitle: string;
}) {
  return (
    <div className="mb-5">
      <div className="flex items-center gap-3 mb-2">
        <Icon size={18} className={color} />
        <h2 className="text-lg font-semibold text-executive-text">{title}</h2>
      </div>
      <p className="text-sm text-executive-muted">{subtitle}</p>
    </div>
  );
}

function Step1History({ months, setMonths }: { months: number; setMonths: (m: number) => void }) {
  return (
    <div>
      <StepHeader
        icon={Calendar}
        color="text-amber-400"
        title="How much email history?"
        subtitle="More history = richer AI context but longer initial scan (~1 min per month)."
      />
      <div className="bg-executive-bg border border-executive-border rounded-xl p-6">
        <label className="text-xs text-executive-muted block mb-3">Months of email history</label>
        <div className="flex items-center gap-4">
          <input
            type="range"
            min={3}
            max={24}
            step={1}
            value={months}
            onChange={e => setMonths(parseInt(e.target.value, 10))}
            className="flex-1 accent-executive-accent"
          />
          <div className="w-20 text-center">
            <div className="text-2xl font-semibold text-executive-text tabular-nums">{months}</div>
            <div className="text-xs text-executive-muted">months</div>
          </div>
        </div>
        <div className="mt-3 flex justify-between text-[10px] text-executive-muted uppercase tracking-wider">
          <span>3 mo</span><span>12 mo</span><span>24 mo</span>
        </div>
        <p className="mt-4 text-xs text-executive-muted">
          Estimated scan: <span className="text-executive-text font-medium">~{Math.round(months * 0.8)}–{Math.round(months * 1.5)} minutes</span>
        </p>
      </div>
    </div>
  );
}

function Step2Briefings({ preset, setPreset }: { preset: BriefingsPreset; setPreset: (p: BriefingsPreset) => void }) {
  return (
    <div>
      <StepHeader
        icon={Clock}
        color="text-emerald-400"
        title="Scheduled briefings"
        subtitle="Pushed to your Teams chat on a cron schedule. Changeable later in Skills."
      />
      <div className="space-y-2">
        <RowOption active={preset === 'recommended'} onClick={() => setPreset('recommended')}
          label="Recommended" desc="3 briefings: daily 7 AM + weekly Mon 8 AM + market intel every 3 days" />
        <RowOption active={preset === 'minimal'} onClick={() => setPreset('minimal')}
          label="Minimal" desc="One daily morning brief at 7 AM. No weekly, no intel." />
        <RowOption active={preset === 'none'} onClick={() => setPreset('none')}
          label="None" desc="No scheduled pushes. I'll check the dashboard myself." />
        <RowOption active={preset === 'custom'} onClick={() => setPreset('custom')}
          label="Skip preset — configure later in Skills → Briefings" desc="" />
      </div>
    </div>
  );
}

function Step3Monitor({ preset, setPreset }: { preset: MonitorPreset; setPreset: (p: MonitorPreset) => void }) {
  return (
    <div>
      <StepHeader
        icon={Mail}
        color="text-sky-400"
        title="Email monitor"
        subtitle="Batches non-priority emails. High-priority can bypass the batch."
      />
      <div className="space-y-2">
        <RowOption active={preset === 'recommended'} onClick={() => setPreset('recommended')}
          label="Recommended" desc="Every 15 min (8 AM–8 PM) + immediate push for high-priority" />
        <RowOption active={preset === 'quiet'} onClick={() => setPreset('quiet')}
          label="Quiet" desc="Every 60 min (9 AM–6 PM), no immediate pushes" />
        <RowOption active={preset === 'off'} onClick={() => setPreset('off')}
          label="Off" desc="No email push notifications (you'll see new mail in dashboard)" />
        <RowOption active={preset === 'custom'} onClick={() => setPreset('custom')}
          label="Skip preset — configure later in Skills → Auto-triggered" desc="" />
      </div>
    </div>
  );
}

function Step4Personal({ text, setText }: { text: string; setText: (s: string) => void }) {
  const placeholder = `# Personal Profile

## Name and title
Daniel Zhang, CEO

## Company
i3D Model Inc.

## Contact
- Email: daniel.zhang@imodel3d.com
- Location: Toronto, Canada

## Languages
English, Mandarin

## Working hours preference
9 AM – 6 PM ET, no meetings before 10 AM

## Other preferences AI should know
Prefer concise emails. Always close with "Bests, Daniel".`;
  return (
    <div>
      <StepHeader
        icon={User}
        color="text-rose-400"
        title="About you (optional)"
        subtitle="AI uses this when drafting emails — signatures, address forms, tone."
      />
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={placeholder}
        rows={14}
        className="w-full p-3 rounded-lg bg-executive-bg border border-executive-border text-sm font-mono text-executive-text resize-y focus:border-executive-accent focus:outline-none"
      />
      <p className="mt-2 text-xs text-executive-muted italic">
        Leave blank to skip — fill it later under Profile → Personal Profile.
      </p>
    </div>
  );
}

function RowOption({ active, onClick, label, desc }: {
  active: boolean; onClick: () => void; label: string; desc: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-4 rounded-xl border transition-all ${
        active
          ? 'border-executive-accent bg-executive-accent/8'
          : 'border-executive-border hover:bg-executive-border/30'
      }`}
    >
      <p className={`text-sm font-semibold ${active ? 'text-executive-accent' : 'text-executive-text'}`}>{label}</p>
      {desc && <p className="text-xs text-executive-muted mt-1">{desc}</p>}
    </button>
  );
}

// Avoid unused-warnings on lucide imports we keep around for the customize flow
void Sliders;
