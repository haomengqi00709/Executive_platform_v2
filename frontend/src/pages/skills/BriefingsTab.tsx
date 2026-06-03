import { useState } from 'react';
import {
  Plus, Edit, Trash2, Loader2, Clock, Power, X, Save, AlertCircle, PlayCircle, CheckCircle2,
  ChevronDown, ChevronRight, MessageCircle,
} from 'lucide-react';
import type { Briefing, SchedulesResponse } from '../../lib/api';
import {
  createBriefing, updateBriefing, deleteBriefing, testRunBriefing, browserTimezone,
} from '../../lib/api';
import { SECTION_BY_ID, CATEGORY_ORDER, CATEGORY_LABEL, sectionsByCategory } from '../../lib/sections';
import { parseCron, buildCron, describeSchedule, DAY_OPTIONS } from '../../lib/schedule';
import type { Preset } from '../../lib/schedule';
import BotChat from '../../components/BotChat';
import { useBotName } from '../../App';

const NON_SCHEDULABLE = new Set([
  'recent_meetings', 'meeting_action_items', 'expenses', 'meeting_prep',
]);

interface Props {
  schedules: SchedulesResponse;
  onChange: () => void;
}

export default function BriefingsTab({ schedules, onChange }: Props) {
  const [editing, setEditing] = useState<Briefing | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const briefings = schedules.briefings || [];
  const [testNotice, setTestNotice] = useState<{ id: string; n: number } | null>(null);
  const [chatOpenId, setChatOpenId] = useState<string | null>(null);

  const handleToggle = async (b: Briefing) => {
    setBusyId(b.id);
    try {
      await updateBriefing(b.id, { enabled: !b.enabled });
      onChange();
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (b: Briefing) => {
    if (!confirm(`Delete "${b.name}"?`)) return;
    setBusyId(b.id);
    try {
      await deleteBriefing(b.id);
      onChange();
    } finally {
      setBusyId(null);
    }
  };

  const handleTestRun = async (b: Briefing) => {
    setBusyId(b.id);
    // Auto-open this briefing's chat panel so the user can watch the pushed
    // messages stream in as the 5-second poll picks them up.
    setChatOpenId(b.id);
    try {
      const res = await testRunBriefing(b.id);
      setTestNotice({ id: b.id, n: res.skills?.length ?? 0 });
      setTimeout(() => setTestNotice(null), 5000);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-executive-muted">
          Each briefing is a bundle of skills that fires on its own schedule. Skills run sequentially
          and push to Teams as separate messages.
        </p>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-executive-accent text-white hover:opacity-90"
        >
          <Plus size={12} /> New Briefing
        </button>
      </div>

      {briefings.length === 0 ? (
        <div className="bg-executive-card border border-dashed border-executive-border rounded-xl p-8 text-center text-sm text-executive-muted">
          No briefings yet. Click "New Briefing" to create your first one (e.g. Morning Briefing at 07:00 weekdays).
        </div>
      ) : (
        <div className="space-y-3">
          {briefings.map(b => (
            <BriefingCard
              key={b.id}
              briefing={b}
              busy={busyId === b.id}
              justRanCount={testNotice?.id === b.id ? testNotice.n : undefined}
              chatOpen={chatOpenId === b.id}
              onToggleChat={() => setChatOpenId(chatOpenId === b.id ? null : b.id)}
              onToggle={() => handleToggle(b)}
              onEdit={() => setEditing(b)}
              onDelete={() => handleDelete(b)}
              onTestRun={() => handleTestRun(b)}
            />
          ))}
        </div>
      )}

      {(creating || editing) && (
        <BriefingFormModal
          briefing={editing}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { setCreating(false); setEditing(null); onChange(); }}
        />
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function BriefingCard({
  briefing, busy, justRanCount, chatOpen, onToggleChat,
  onToggle, onEdit, onDelete, onTestRun,
}: {
  briefing: Briefing; busy: boolean; justRanCount?: number;
  chatOpen: boolean; onToggleChat: () => void;
  onToggle: () => void; onEdit: () => void; onDelete: () => void; onTestRun: () => void;
}) {
  const sched = describeSchedule({ enabled: briefing.enabled, cron: briefing.cron });
  const tz = briefing.tz || 'UTC';
  const botName = useBotName();

  return (
    <div className={`bg-executive-card border rounded-xl p-4 transition-colors ${
      briefing.enabled ? 'border-executive-border' : 'border-executive-border opacity-60'
    }`}>
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-executive-text">{briefing.name}</h3>
          <p className={`text-xs mt-0.5 inline-flex items-center gap-1 ${briefing.enabled ? 'text-emerald-300' : 'text-executive-muted'}`}>
            <Clock size={11} />
            {sched} <span className="text-executive-muted">· {tz}</span>
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onTestRun}
            disabled={busy}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-executive-accent/10 hover:bg-executive-accent/20 text-executive-accent disabled:opacity-50"
            title="Run this briefing now"
          >
            {busy && justRanCount === undefined ? <Loader2 size={12} className="animate-spin" /> : <PlayCircle size={12} />}
            Test Run
          </button>
          <button
            onClick={onToggle}
            disabled={busy}
            className={`text-xs px-2 py-1.5 rounded-md transition-colors ${
              briefing.enabled
                ? 'text-emerald-300 hover:bg-emerald-400/10'
                : 'text-executive-muted hover:bg-executive-border/40'
            }`}
            title={briefing.enabled ? 'Disable' : 'Enable'}
          >
            <Power size={13} />
          </button>
          <button onClick={onEdit} disabled={busy} className="text-xs px-2 py-1.5 rounded-md text-executive-muted hover:bg-executive-border/40">
            <Edit size={13} />
          </button>
          <button onClick={onDelete} disabled={busy} className="text-xs px-2 py-1.5 rounded-md text-executive-muted hover:bg-rose-400/10 hover:text-rose-400">
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      {justRanCount !== undefined && (
        <div className="flex items-center gap-1.5 text-xs text-emerald-300 bg-emerald-400/10 border border-emerald-400/30 rounded-md px-2 py-1.5 mb-3">
          <CheckCircle2 size={12} />
          Running {justRanCount} skill{justRanCount === 1 ? '' : 's'} now — results push to Teams as they finish.
        </div>
      )}
      <div>
        <div className="text-[10px] uppercase tracking-wider text-executive-muted mb-1.5">
          {briefing.skills.length} skill{briefing.skills.length === 1 ? '' : 's'}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {briefing.skills.map(sid => {
            const def = SECTION_BY_ID[sid];
            return (
              <span key={sid} className="text-xs px-2 py-0.5 bg-executive-bg border border-executive-border rounded-md text-executive-text">
                {def?.name || sid}
              </span>
            );
          })}
        </div>
      </div>

      {/* Chat toggle */}
      <button
        onClick={onToggleChat}
        className="mt-3 -mb-1 flex items-center gap-1.5 text-xs text-executive-muted hover:text-executive-text transition-colors"
      >
        {chatOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <MessageCircle size={11} />
        {chatOpen ? 'Hide chat' : `Chat with ${botName} about this briefing`}
      </button>

      {chatOpen && (
        <div className="mt-3">
          <BotChat
            contextPreamble={`User is reviewing their scheduled briefing "${briefing.name}". It currently fires ${describeSchedule({ enabled: briefing.enabled, cron: briefing.cron })} (${briefing.tz || 'UTC'}) and includes these skills: ${briefing.skills.map(s => SECTION_BY_ID[s]?.name || s).join(', ')}. Help them adjust this briefing if they ask.`}
            placeholder="Refine this briefing… e.g. 'Move it to 8 AM', 'Drop expenses'"
            suggestions={[
              'What does this briefing currently include?',
              'Add yesterday recap to this',
              'Make this run at 8 AM instead',
            ]}
            historyLimit={8}
          />
        </div>
      )}
    </div>
  );
}

function BriefingFormModal({
  briefing, onClose, onSaved,
}: {
  briefing: Briefing | null; onClose: () => void; onSaved: () => void;
}) {
  const isEdit = briefing !== null;
  const parsedInitial = briefing ? parseCron(briefing.cron) : { preset: 'daily' as Preset };
  const [name, setName] = useState(briefing?.name || '');
  const [preset, setPreset] = useState<Preset>(briefing && briefing.cron ? parsedInitial.preset : 'daily');
  const [time, setTime] = useState(parsedInitial.time || '07:00');
  const [time2, setTime2] = useState(parsedInitial.times?.[1] || '13:00');
  const [dayOfWeek, setDOW] = useState(parsedInitial.dayOfWeek ?? 0);
  const [customCron, setCustom] = useState(briefing?.cron || '0 7 * * *');
  const [skills, setSkills] = useState<string[]>(briefing?.skills || []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    setError(null);
    if (!name.trim()) { setError('Name is required'); return; }
    if (skills.length === 0) { setError('Pick at least one skill'); return; }
    let cron: string;
    if (preset === 'custom') {
      cron = customCron.trim();
      if (!cron) { setError('Cron expression required'); return; }
    } else {
      cron = buildCron(preset, { time, times: [time, time2], dayOfWeek });
      if (!cron) { setError('Invalid schedule'); return; }
    }
    setSaving(true);
    try {
      const tz = browserTimezone();
      if (isEdit && briefing) {
        await updateBriefing(briefing.id, { name: name.trim(), cron, tz, skills, enabled: briefing.enabled });
      } else {
        await createBriefing({ name: name.trim(), cron, tz, skills, enabled: true });
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  const toggleSkill = (sid: string) => {
    setSkills(s => s.includes(sid) ? s.filter(x => x !== sid) : [...s, sid]);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-executive-card border border-executive-border rounded-xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col shadow-xl">
        <div className="px-5 py-3 border-b border-executive-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-executive-text">{isEdit ? 'Edit Briefing' : 'New Briefing'}</h2>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text">
            <X size={18} />
          </button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          {/* Name */}
          <div>
            <Label>Name</Label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Morning Briefing"
              className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
            />
          </div>

          {/* Schedule */}
          <div>
            <Label>Schedule</Label>
            <select
              value={preset}
              onChange={e => setPreset(e.target.value as Preset)}
              className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md"
            >
              <option value="daily">Every day</option>
              <option value="twice_daily">Twice a day</option>
              <option value="weekdays">Weekdays only</option>
              <option value="weekly">Weekly</option>
              <option value="custom">Custom cron</option>
            </select>

            {(preset === 'daily' || preset === 'weekdays') && (
              <div className="mt-2">
                <Label>Time</Label>
                <input type="time" value={time} onChange={e => setTime(e.target.value)}
                  className="px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md" />
                <p className="text-[10px] text-executive-muted mt-1">Your timezone ({browserTimezone()})</p>
              </div>
            )}
            {preset === 'twice_daily' && (
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div>
                  <Label>First</Label>
                  <input type="time" value={time} onChange={e => setTime(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md" />
                </div>
                <div>
                  <Label>Second</Label>
                  <input type="time" value={time2} onChange={e => setTime2(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md" />
                </div>
                <p className="text-[10px] text-executive-muted col-span-2 -mt-1">Your timezone ({browserTimezone()})</p>
              </div>
            )}
            {preset === 'weekly' && (
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div>
                  <Label>Day of week</Label>
                  <select value={dayOfWeek} onChange={e => setDOW(parseInt(e.target.value))}
                    className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md">
                    {DAY_OPTIONS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </div>
                <div>
                  <Label>Time</Label>
                  <input type="time" value={time} onChange={e => setTime(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md" />
                </div>
                <p className="text-[10px] text-executive-muted col-span-2 -mt-1">Your timezone ({browserTimezone()})</p>
              </div>
            )}
            {preset === 'custom' && (
              <div className="mt-2">
                <Label>Cron expression (5 fields)</Label>
                <input type="text" value={customCron} onChange={e => setCustom(e.target.value)}
                  className="w-full px-3 py-1.5 text-sm font-mono bg-executive-bg border border-executive-border rounded-md" />
                <p className="text-[10px] text-executive-muted mt-1">Interpreted in your timezone ({browserTimezone()}). day_of_week 0=Mon, 6=Sun.</p>
              </div>
            )}
          </div>

          {/* Skill picker */}
          <div>
            <Label>Skills to include ({skills.length} selected)</Label>
            <div className="space-y-3 max-h-72 overflow-y-auto border border-executive-border rounded-md p-2">
              {CATEGORY_ORDER.map(cat => {
                const candidates = sectionsByCategory(cat).filter(s => !NON_SCHEDULABLE.has(s.id));
                if (candidates.length === 0) return null;
                return (
                  <div key={cat}>
                    <div className="text-[10px] uppercase tracking-wider text-executive-muted px-1 py-0.5">{CATEGORY_LABEL[cat]}</div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-1 mt-1">
                      {candidates.map(s => {
                        const Icon = s.icon;
                        const selected = skills.includes(s.id);
                        return (
                          <button
                            key={s.id}
                            type="button"
                            onClick={() => toggleSkill(s.id)}
                            className={`flex items-center gap-2 px-2 py-1.5 rounded-md text-xs text-left transition-colors ${
                              selected
                                ? 'bg-executive-accent/10 text-executive-accent border border-executive-accent/30'
                                : 'text-executive-text hover:bg-executive-border/40 border border-transparent'
                            }`}
                          >
                            <Icon size={12} className="shrink-0" />
                            <span className="truncate">{s.name}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-1.5 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-2 py-1.5">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-executive-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded-md border border-executive-border text-executive-muted hover:text-executive-text">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="flex items-center gap-1.5 px-4 py-1.5 text-sm rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-50">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saving ? 'Saving…' : (isEdit ? 'Save changes' : 'Create briefing')}
          </button>
        </div>
      </div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{children}</div>;
}
