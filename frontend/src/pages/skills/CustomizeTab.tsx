import { useEffect, useState, useCallback } from 'react';
import {
  Loader2, ChevronDown, ChevronRight, Sparkles, Save, Play,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import {
  runSection, getSectionInstructions, updateSectionInstructions,
} from '../../lib/api';
import {
  SECTIONS, CATEGORY_ORDER, CATEGORY_LABEL, CATEGORY_ACCENT, sectionsByCategory,
} from '../../lib/sections';
import type { SectionDef } from '../../lib/sections';
import { useActivity } from '../../components/ActivityDrawer';

// Sections that have no instruction.md / are not customisable
const NO_CUSTOMIZE = new Set([
  'upcoming_commitments', 'recent_meetings', 'meeting_action_items',
  'expenses',
]);

interface Props {
  initialSectionId?: string;
  onClearInitial: () => void;
}

export default function CustomizeTab({ initialSectionId, onClearInitial }: Props) {
  const [instructions, setInstructions] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const activity = useActivity();

  const refresh = useCallback(async () => {
    setLoading(true);
    const customizable = SECTIONS.filter(s => !NO_CUSTOMIZE.has(s.id));
    const pairs = await Promise.all(
      customizable.map(async s => [
        s.id,
        (await getSectionInstructions(s.id).catch(() => ({ content: '' }))).content,
      ] as const),
    );
    setInstructions(Object.fromEntries(pairs));
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (initialSectionId) {
      setExpandedId(initialSectionId);
      setTimeout(() => {
        const el = document.getElementById(`customize-row-${initialSectionId}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 50);
      onClearInitial();
    }
  }, [initialSectionId, onClearInitial]);

  const handleRun = async (sid: string) => {
    setRunning(r => ({ ...r, [sid]: true }));
    activity.start(sid);
    try {
      await runSection(sid);
    } finally {
      setTimeout(() => setRunning(r => ({ ...r, [sid]: false })), 1500);
    }
  };

  const handleSave = async (sid: string, content: string) => {
    await updateSectionInstructions(sid, content);
    setInstructions(i => ({ ...i, [sid]: content }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-executive-muted">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-executive-muted">
        Free-form rules layered on top of each skill's default behavior. The validator AI reads these
        on every run. Examples: "skip projects with 'internal' in the name", "only surface high-priority items".
      </p>

      {CATEGORY_ORDER.map(category => {
        const sections = sectionsByCategory(category).filter(s => !NO_CUSTOMIZE.has(s.id));
        if (sections.length === 0) return null;
        return (
          <section key={category} className="space-y-2">
            <h2 className={`text-xs font-semibold uppercase tracking-wider ${CATEGORY_ACCENT[category]}`}>
              {CATEGORY_LABEL[category]}
            </h2>
            <div className="bg-executive-card border border-executive-border rounded-xl overflow-hidden">
              {sections.map((s, i) => (
                <CustomizeRow
                  key={s.id}
                  def={s}
                  instruction={instructions[s.id] || ''}
                  expanded={expandedId === s.id}
                  onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
                  onSave={(c) => handleSave(s.id, c)}
                  onRun={() => handleRun(s.id)}
                  running={!!running[s.id]}
                  isLast={i === sections.length - 1}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function CustomizeRow({
  def, instruction, expanded, onToggle, onSave, onRun, running, isLast,
}: {
  def: SectionDef;
  instruction: string;
  expanded: boolean;
  onToggle: () => void;
  onSave: (content: string) => Promise<void>;
  onRun: () => void;
  running: boolean;
  isLast: boolean;
}) {
  const Icon: LucideIcon = def.icon;
  const customized = looksCustomized(instruction);

  return (
    <div id={`customize-row-${def.id}`} className={!isLast ? 'border-b border-executive-border/60' : ''}>
      <div className="flex items-center gap-3 px-4 py-3">
        <button onClick={onToggle} className="text-executive-muted hover:text-executive-text shrink-0">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <Icon size={16} className={`${CATEGORY_ACCENT[def.category]} shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-executive-text truncate">{def.name}</span>
            {customized && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-executive-accent/15 text-executive-accent font-semibold uppercase tracking-wider inline-flex items-center gap-1">
                <Sparkles size={9} /> customized
              </span>
            )}
          </div>
          <div className="text-xs text-executive-muted truncate">{def.description}</div>
        </div>
        <button
          onClick={onRun}
          disabled={running}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-executive-accent/10 hover:bg-executive-accent/20 text-executive-accent disabled:opacity-50 shrink-0"
        >
          {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          {running ? 'Running' : 'Run'}
        </button>
      </div>

      {expanded && (
        <InstructionEditor
          instruction={instruction}
          onSave={onSave}
        />
      )}
    </div>
  );
}

function InstructionEditor({
  instruction, onSave,
}: {
  instruction: string;
  onSave: (content: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(instruction);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { setDraft(instruction); }, [instruction]);

  const dirty = draft !== instruction;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(draft);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-executive-bg/40 px-6 py-4 border-t border-executive-border/40">
      <textarea
        value={draft}
        onChange={e => setDraft(e.target.value)}
        rows={10}
        spellCheck={false}
        className="w-full px-3 py-2 text-sm font-mono bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
        placeholder="# My filter rules&#10;&#10;- Skip projects with 'internal' in the name&#10;- Only show high-priority emails"
      />
      <div className="flex items-center justify-end gap-2 mt-2">
        {saved && <span className="text-xs text-emerald-300">Saved.</span>}
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

function looksCustomized(content: string): boolean {
  if (!content.trim()) return false;
  const lines = content.split('\n').map(l => l.trim()).filter(Boolean);
  const hasRules = /^##\s+(my|filter|customization|rules|priorities|skip|hide|only|show)/i;
  return lines.some(l => hasRules.test(l));
}
