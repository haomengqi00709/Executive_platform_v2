import { useEffect, useMemo, useState } from 'react';
import {
  Loader2, Search, EyeOff, ChevronDown, ChevronRight, Save,
  Users, MessageSquare, CalendarClock, Tag, Activity, Archive, GitMerge, RefreshCw, Upload, Download,
} from 'lucide-react';
import { getProjects, patchProject, relativeTime, archiveRecord, scanProjects, projectsExportXlsxUrl } from '../../lib/api';
import type { ProjectRecord } from '../../lib/api';
import MergePicker from './MergePicker';
import BulkUploadModal from './BulkUploadModal';
import { useActivity } from '../../components/ActivityDrawer';

const STATUS_OPTIONS = ['ongoing', 'needs_attention', 'paused', 'early_stage', 'completed'];
const MOMENTUM_OPTIONS = ['accelerating', 'steady', 'slowing', 'stalled'];
const CATEGORY_OPTIONS = ['client_deal', 'internal', 'vendor', 'partnership', 'other'];
const STAGE_OPTIONS = ['lead', 'deal', 'project'];

const STAGE_COLOR: Record<string, string> = {
  lead:    'bg-violet-400/15 text-violet-300',
  deal:    'bg-amber-400/15 text-amber-300',
  project: 'bg-emerald-400/15 text-emerald-300',
};

// Stage is a client-only marker — no backend; remembered in localStorage per project id.
const stageKey = (id: string) => `project_stage_${id}`;
const getStage = (id: string): string => localStorage.getItem(stageKey(id)) || 'lead';
const setStageLS = (id: string, v: string): void => localStorage.setItem(stageKey(id), v);

const STATUS_COLOR: Record<string, string> = {
  ongoing:         'bg-emerald-400/15 text-emerald-300',
  needs_attention: 'bg-rose-400/15 text-rose-300',
  paused:          'bg-amber-400/15 text-amber-300',
  early_stage:     'bg-sky-400/15 text-sky-300',
  completed:       'bg-executive-border/40 text-executive-muted',
};

const MOMENTUM_COLOR: Record<string, string> = {
  accelerating: 'text-emerald-400',
  steady:       'text-executive-text',
  slowing:      'text-amber-400',
  stalled:      'text-rose-400',
};

export default function ProjectsTab() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [lastScan, setLastScan] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showIgnored, setShowIgnored] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [mergeSource, setMergeSource] = useState<ProjectRecord | null>(null);
  const { startJob, isActive } = useActivity();
  const [bulkOpen, setBulkOpen] = useState(false);
  const [stages, setStages] = useState<Record<string, string>>({});

  // Hydrate the client-only stage marker from localStorage whenever projects load.
  useEffect(() => {
    const m: Record<string, string> = {};
    for (const p of projects) m[p.id] = getStage(p.id);
    setStages(m);
  }, [projects]);

  const changeStage = (id: string, v: string) => {
    setStageLS(id, v);
    setStages(s => ({ ...s, [id]: v }));
  };

  const refresh = () => {
    setLoading(true);
    getProjects()
      .then(d => {
        setProjects(d.projects || []);
        setLastScan(d.last_scan);
      })
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const update = async (id: string, patch: Partial<ProjectRecord>) => {
    setSavingId(id);
    try {
      const updated = await patchProject(id, patch);
      setProjects(ps => ps.map(p => p.id === id ? { ...p, ...updated } : p));
    } finally {
      setSavingId(null);
    }
  };

  const archive = async (id: string, name: string) => {
    if (!confirm(`Archive "${name}"? This hides it from all sections.`)) return;
    try {
      await archiveRecord('project', id);
      setExpandedId(null);
      refresh();
    } catch (e: any) {
      alert(`Archive failed: ${e?.message || 'unknown error'}`);
    }
  };

  const rescan = async () => {
    if (!confirm('Re-scan inbox history and rebuild the Projects DB? This may take a few minutes.')) return;
    const before = lastScan;
    try {
      await scanProjects();
    } catch (e: any) {
      alert(`Scan failed: ${e?.message || 'unknown error'}`);
      return;
    }
    startJob({
      id: 'projects-rescan',
      label: 'Projects re-scan',
      kind: 'rescan',
      poll: async () => {
        const d = await getProjects();
        if (d.last_scan && d.last_scan !== before) {
          setProjects(d.projects || []);
          setLastScan(d.last_scan);
          return { status: 'done', last_run: d.last_scan };
        }
        return { status: 'running' };
      },
    });
  };

  const visible = useMemo(() => {
    return projects.filter(p => {
      if (!showIgnored && p.ignore) return false;
      if (statusFilter !== 'all' && p.status !== statusFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          (p.name || '').toLowerCase().includes(q) ||
          (p.summary || '').toLowerCase().includes(q) ||
          (p.key_topics || []).some(t => t.toLowerCase().includes(q))
        );
      }
      return true;
    });
  }, [projects, search, statusFilter, showIgnored]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3 justify-between">
        <div className="text-xs text-executive-muted">
          {loading ? 'Loading…' : (
            <>{projects.length} projects · last scan {relativeTime(lastScan ?? undefined)}</>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-executive-muted" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search name / summary / topic…"
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
          <label className="flex items-center gap-1.5 text-xs text-executive-muted">
            <input
              type="checkbox"
              checked={showIgnored}
              onChange={e => setShowIgnored(e.target.checked)}
              className="accent-executive-accent"
            />
            Show ignored
          </label>
          <a
            href={projectsExportXlsxUrl}
            download
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-executive-border text-executive-muted hover:text-executive-text hover:bg-executive-border/40"
            title="Download all projects as Excel"
          >
            <Download size={12} /> Excel
          </a>
          <button
            onClick={rescan}
            disabled={isActive('projects-rescan')}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-executive-border text-executive-muted hover:text-executive-text hover:bg-executive-border/40 disabled:opacity-50"
            title="Re-scan inbox history and rebuild projects DB"
          >
            {isActive('projects-rescan') ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            {isActive('projects-rescan') ? 'Scanning…' : 'Re-scan'}
          </button>
          <button
            onClick={() => setBulkOpen(true)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-executive-border text-executive-muted hover:text-executive-text hover:bg-executive-border/40"
            title="Upload CSV / Excel / PDF / Word to import projects in bulk"
          >
            <Upload size={12} /> Bulk Upload
          </button>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-executive-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center text-sm text-executive-muted py-12">
          No projects match the filter.
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map(p => (
            <div
              key={p.id}
              className={`bg-executive-card border border-executive-border rounded-xl overflow-hidden ${p.ignore ? 'opacity-50' : ''}`}
            >
              {/* Row */}
              <button
                onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-executive-border/10 text-left"
              >
                <span className="text-executive-muted shrink-0">
                  {expandedId === p.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-executive-text">{p.name}</div>
                  <div className="text-xs text-executive-muted mt-0.5 truncate">
                    {p.summary || 'No summary.'}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`text-xs px-2 py-1 rounded-md ${STAGE_COLOR[stages[p.id] ?? 'lead']}`}>
                    {stages[p.id] ?? 'lead'}
                  </span>
                  <span className={`text-xs px-2 py-1 rounded-md ${STATUS_COLOR[p.status] ?? STATUS_COLOR.completed}`}>
                    {p.status.replace('_', ' ')}
                  </span>
                  <span className={`text-xs ${MOMENTUM_COLOR[p.momentum] ?? ''}`}>
                    {p.momentum}
                  </span>
                  <span className="text-xs text-executive-muted whitespace-nowrap">
                    {p.last_activity || '—'}
                  </span>
                </div>
              </button>

              {expandedId === p.id && (
                <ProjectDetail
                  project={p}
                  saving={savingId === p.id}
                  stage={stages[p.id] ?? 'lead'}
                  onStageChange={v => changeStage(p.id, v)}
                  onSave={patch => update(p.id, patch)}
                  onArchive={() => archive(p.id, p.name || p.id)}
                  onMerge={() => setMergeSource(p)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {mergeSource && (
        <MergePicker
          kind="project"
          keepRecord={mergeSource}
          candidates={projects.filter(p =>
            p.id !== mergeSource.id && !p.ignore && !(p as any).archived
          )}
          onClose={() => setMergeSource(null)}
          onMerged={() => { setMergeSource(null); setExpandedId(null); refresh(); }}
        />
      )}

      {bulkOpen && (
        <BulkUploadModal
          kind="project"
          onClose={() => setBulkOpen(false)}
          onCommitted={() => refresh()}
        />
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function ProjectDetail({
  project, saving, stage, onStageChange, onSave, onArchive, onMerge,
}: {
  project: ProjectRecord;
  saving: boolean;
  stage: string;
  onStageChange: (v: string) => void;
  onSave: (patch: Partial<ProjectRecord>) => Promise<void>;
  onArchive: () => void;
  onMerge: () => void;
}) {
  const [draft, setDraft] = useState<ProjectRecord>(project);

  useEffect(() => { setDraft(project); }, [project]);

  const dirty = (
    draft.name        !== project.name ||
    draft.category    !== project.category ||
    draft.status      !== project.status ||
    draft.momentum    !== project.momentum ||
    draft.summary     !== project.summary ||
    draft.next_action !== project.next_action ||
    draft.deadline    !== project.deadline
  );

  const handleSave = async () => {
    const patch: Partial<ProjectRecord> = {};
    if (draft.name        !== project.name)        patch.name        = draft.name;
    if (draft.category    !== project.category)    patch.category    = draft.category;
    if (draft.status      !== project.status)      patch.status      = draft.status;
    if (draft.momentum    !== project.momentum)    patch.momentum    = draft.momentum;
    if (draft.summary     !== project.summary)     patch.summary     = draft.summary;
    if (draft.next_action !== project.next_action) patch.next_action = draft.next_action;
    if (draft.deadline    !== project.deadline)    patch.deadline    = draft.deadline;
    if (Object.keys(patch).length > 0) await onSave(patch);
  };

  return (
    <div className="bg-executive-bg/40 px-5 py-4 border-t border-executive-border/40 space-y-4">
      {/* Metadata strip */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
        <Stat icon={<Tag size={12} />} label="Stage">
          <select
            value={stage}
            onChange={e => onStageChange(e.target.value)}
            className="text-xs bg-executive-bg border border-executive-border rounded-md px-2 py-1 w-full"
          >
            {STAGE_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </Stat>
        <Stat icon={<Activity size={12} />} label="Status">
          <select
            value={draft.status}
            onChange={e => setDraft(d => ({ ...d, status: e.target.value }))}
            className="text-xs bg-executive-bg border border-executive-border rounded-md px-2 py-1 w-full"
          >
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </Stat>
        <Stat icon={<Activity size={12} />} label="Momentum">
          <select
            value={draft.momentum}
            onChange={e => setDraft(d => ({ ...d, momentum: e.target.value }))}
            className="text-xs bg-executive-bg border border-executive-border rounded-md px-2 py-1 w-full"
          >
            {MOMENTUM_OPTIONS.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </Stat>
        <Stat icon={<Tag size={12} />} label="Category">
          <select
            value={draft.category || 'other'}
            onChange={e => setDraft(d => ({ ...d, category: e.target.value }))}
            className="text-xs bg-executive-bg border border-executive-border rounded-md px-2 py-1 w-full"
          >
            {CATEGORY_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </Stat>
        <Stat icon={<CalendarClock size={12} />} label="Deadline">
          <input
            type="date"
            value={draft.deadline || ''}
            onChange={e => setDraft(d => ({ ...d, deadline: e.target.value || null }))}
            className="text-xs bg-executive-bg border border-executive-border rounded-md px-2 py-1 w-full"
          />
        </Stat>
      </div>

      {/* Name + Summary + Next Action */}
      <div>
        <Label>Project Name</Label>
        <input
          type="text"
          value={draft.name}
          onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
          className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
        />
      </div>
      <div>
        <Label>Current Summary <span className="text-executive-muted/60 normal-case font-normal">(latest state of the project)</span></Label>
        <textarea
          value={draft.summary || ''}
          onChange={e => setDraft(d => ({ ...d, summary: e.target.value }))}
          rows={3}
          className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
        />
      </div>
      <div>
        <Label>Next Action</Label>
        <textarea
          value={draft.next_action || ''}
          onChange={e => setDraft(d => ({ ...d, next_action: e.target.value }))}
          rows={2}
          className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
        />
      </div>

      {/* Read-only context from AI extraction */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <Label>
            <span className="inline-flex items-center gap-1">
              <Users size={11} />
              Participants ({project.participants?.length ?? 0})
            </span>
          </Label>
          {project.participants && project.participants.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {project.participants.slice(0, 20).map(email => (
                <span key={email} className="text-xs px-2 py-1 bg-executive-bg border border-executive-border rounded-md text-executive-text">
                  {email}
                </span>
              ))}
              {project.participants.length > 20 && (
                <span className="text-xs px-2 py-1 text-executive-muted">+{project.participants.length - 20} more</span>
              )}
            </div>
          ) : (
            <p className="text-xs text-executive-muted italic">No participants extracted.</p>
          )}
        </div>
        <div>
          <Label>
            <span className="inline-flex items-center gap-1">
              <Tag size={11} />
              Key Topics ({project.key_topics?.length ?? 0})
            </span>
          </Label>
          {project.key_topics && project.key_topics.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {project.key_topics.map((t, i) => (
                <span key={i} className="text-xs px-2 py-1 bg-executive-accent/10 text-executive-accent rounded-md">
                  {t}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-executive-muted italic">No topics extracted.</p>
          )}
        </div>
      </div>

      {/* Conversation history */}
      <div className="flex items-center gap-4 text-xs text-executive-muted pt-2 border-t border-executive-border/40">
        <span className="inline-flex items-center gap-1">
          <MessageSquare size={11} />
          {project.thread_count ?? 0} email thread{(project.thread_count ?? 0) === 1 ? '' : 's'}
        </span>
        <span>·</span>
        <span>
          {project.conversation_ids?.length ?? 0} conversation{(project.conversation_ids?.length ?? 0) === 1 ? '' : 's'} captured
        </span>
        <span>·</span>
        <span>Last activity {project.last_activity || '—'}</span>
        {project.updated_at && (
          <>
            <span>·</span>
            <span>DB updated {project.updated_at}</span>
          </>
        )}
      </div>

      {/* Footer actions */}
      <div className="flex items-center justify-between pt-3 border-t border-executive-border/40">
        <div className="flex items-center gap-1">
          <button
            onClick={() => onSave({ ignore: !project.ignore })}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md text-executive-muted hover:bg-executive-border/40 transition-colors"
          >
            <EyeOff size={12} />
            {project.ignore ? 'Un-ignore' : 'Hide'}
          </button>
          <button
            onClick={onArchive}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md text-executive-muted hover:bg-executive-border/40 transition-colors"
            title="Archive — mark as completed/inactive, hide from all sections"
          >
            <Archive size={12} />
            Archive
          </button>
          <button
            onClick={onMerge}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md text-executive-muted hover:bg-executive-border/40 transition-colors"
            title="Merge with… — combine this project with another (this one is kept)"
          >
            <GitMerge size={12} />
            Merge with…
          </button>
        </div>
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

// ───────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{children}</div>;
}

function Stat({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div>
      <Label>
        <span className="inline-flex items-center gap-1">
          {icon}
          {label}
        </span>
      </Label>
      {children}
    </div>
  );
}
