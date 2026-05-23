import { useEffect, useState } from 'react';
import {
  Mail, Calendar, Loader2, Save, CheckCircle2, AlertCircle,
} from 'lucide-react';
import type {
  SchedulesResponse, EmailMonitorConfig, MeetingConfig,
} from '../../lib/api';
import { putEmailMonitorConfig, putMeetingConfig, browserTimezone } from '../../lib/api';

interface Props {
  schedules: SchedulesResponse;
  onChange: () => void;
}

export default function AutoTriggerTab({ schedules, onChange }: Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-executive-muted">
        Two background tools that run continuously, independent of any schedule.
      </p>
      <EmailMonitorCard initial={schedules.email_monitor} onSaved={onChange} />
      <MeetingCard initial={schedules.meeting} onSaved={onChange} />
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function EmailMonitorCard({
  initial, onSaved,
}: {
  initial: EmailMonitorConfig; onSaved: () => void;
}) {
  const [cfg, setCfg] = useState<EmailMonitorConfig>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setCfg(initial); }, [initial]);

  const dirty = (
    cfg.priority_immediate !== initial.priority_immediate ||
    cfg.interval_minutes   !== initial.interval_minutes ||
    cfg.active_start       !== initial.active_start ||
    cfg.active_end         !== initial.active_end
  );

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await putEmailMonitorConfig(cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-executive-card border border-executive-border rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 rounded-lg bg-sky-400/10 text-sky-400">
          <Mail size={18} />
        </div>
        <div className="flex-1">
          <h3 className="text-base font-semibold text-executive-text">Email Monitor</h3>
          <p className="text-xs text-executive-muted mt-0.5">
            Watches your inbox and sends notifications based on these rules.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <Toggle
          checked={cfg.priority_immediate}
          onChange={v => setCfg(c => ({ ...c, priority_immediate: v }))}
          label="Send priority emails immediately"
          hint="Priority = CRM contact marked high priority OR AI flags as urgent. Skips active-hours when on."
        />

        <div>
          <Label>Digest interval</Label>
          <div className="flex items-center gap-2">
            <span className="text-xs text-executive-muted">Send a batched digest every</span>
            <input
              type="number"
              min={1}
              max={1440}
              value={cfg.interval_minutes}
              onChange={e => setCfg(c => ({ ...c, interval_minutes: parseInt(e.target.value || '15') }))}
              className="w-16 px-2 py-1 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
            <span className="text-xs text-executive-muted">minutes (1–1440)</span>
          </div>
        </div>

        <div>
          <Label>Active hours</Label>
          <div className="flex items-center gap-2">
            <span className="text-xs text-executive-muted">From</span>
            <input
              type="time"
              value={cfg.active_start}
              onChange={e => setCfg(c => ({ ...c, active_start: e.target.value }))}
              className="px-2 py-1 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
            <span className="text-xs text-executive-muted">to</span>
            <input
              type="time"
              value={cfg.active_end}
              onChange={e => setCfg(c => ({ ...c, active_end: e.target.value }))}
              className="px-2 py-1 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
            <span className="text-[11px] text-executive-muted ml-2">{browserTimezone()}</span>
          </div>
          <p className="text-[11px] text-executive-muted mt-1">
            Outside this window, only priority emails (with "immediate" enabled) get through.
          </p>
        </div>

        {error && (
          <div className="flex items-start gap-1.5 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-2 py-1.5">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2 border-t border-executive-border/40">
          {saved && (
            <span className="flex items-center gap-1 text-xs text-emerald-300">
              <CheckCircle2 size={12} /> Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function MeetingCard({
  initial, onSaved,
}: {
  initial: MeetingConfig; onSaved: () => void;
}) {
  const [cfg, setCfg] = useState<MeetingConfig>(initial);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setCfg(initial); }, [initial]);

  const dirty = (
    cfg.prep_enabled        !== initial.prep_enabled ||
    cfg.prep_minutes_before !== initial.prep_minutes_before ||
    cfg.summary_enabled     !== initial.summary_enabled
  );

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await putMeetingConfig(cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-executive-card border border-executive-border rounded-xl p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 rounded-lg bg-violet-400/10 text-violet-400">
          <Calendar size={18} />
        </div>
        <div className="flex-1">
          <h3 className="text-base font-semibold text-executive-text">Meeting</h3>
          <p className="text-xs text-executive-muted mt-0.5">
            Pre-meeting prep and post-meeting summaries based on calendar events.
          </p>
        </div>
      </div>

      <div className="space-y-4">
        <Toggle
          checked={cfg.prep_enabled}
          onChange={v => setCfg(c => ({ ...c, prep_enabled: v }))}
          label="Send pre-meeting prep"
          hint="Pushes attendee CRM context, related projects, and open action items shortly before each meeting."
        />

        {cfg.prep_enabled && (
          <div className="pl-6 border-l-2 border-executive-border/40">
            <Label>How far in advance (minutes)</Label>
            <input
              type="number"
              min={5}
              max={240}
              value={cfg.prep_minutes_before}
              onChange={e => setCfg(c => ({ ...c, prep_minutes_before: parseInt(e.target.value || '30') }))}
              className="w-20 px-2 py-1 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
            <p className="text-[11px] text-executive-muted mt-1">5–240 minutes. Polled every 5 min.</p>
          </div>
        )}

        <Toggle
          checked={cfg.summary_enabled}
          onChange={v => setCfg(c => ({ ...c, summary_enabled: v }))}
          label="Send post-meeting summary"
          hint="When a meeting recording lands on OneDrive, fires the transcription + summary + action items pipeline."
        />

        {error && (
          <div className="flex items-start gap-1.5 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-2 py-1.5">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2 border-t border-executive-border/40">
          {saved && (
            <span className="flex items-center gap-1 text-xs text-emerald-300">
              <CheckCircle2 size={12} /> Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Toggle({
  checked, onChange, label, hint,
}: {
  checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`mt-0.5 relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
          checked ? 'bg-executive-accent' : 'bg-executive-border'
        }`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          checked ? 'translate-x-4' : 'translate-x-0'
        }`} />
      </button>
      <div className="flex-1">
        <div className="text-sm text-executive-text">{label}</div>
        {hint && <p className="text-[11px] text-executive-muted mt-0.5 leading-relaxed">{hint}</p>}
      </div>
    </label>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{children}</div>;
}
