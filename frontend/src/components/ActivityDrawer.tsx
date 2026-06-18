/**
 * Global task console — shows every long-running task (section refresh, CRM /
 * Projects re-scan, bulk email, …) while it runs, and removes its card ~4s
 * after it finishes.
 *
 * Architecture:
 *   - ActivityProvider wraps the app at the top level. It tracks a Set<id> of
 *     active jobs; each job carries its OWN poll() closure (jobs poll different
 *     endpoints). Poll closures live in a ref (not state) so registering a job
 *     never tears down the polling interval.
 *   - Any component starting a long task calls useActivity().startJob(job)
 *     (or start(sectionId) for the section convenience wrapper). The console
 *     auto-opens.
 *   - One interval (3s) calls every tracked job's poll(); when a job flips
 *     running→done/error it stays 4s with a final badge, then auto-removes.
 *   - A job with onRestore shows an "Open" button (used by bulk email to
 *     reopen its modal). User can dismiss the console; it reopens on next start.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X, Activity, Loader2, CheckCircle2, AlertCircle, ExternalLink } from 'lucide-react';
import { getSection, relativeTime } from '../lib/api';
import { SECTION_BY_ID } from '../lib/sections';

// ── Job model ──────────────────────────────────────────────

export type JobStatus = 'running' | 'done' | 'error';

export interface JobPoll {
  status: JobStatus;
  progress?: { current: number; total: number };
  logs?: string[];
  error?: string;
  last_run?: string;
}

export interface Job {
  id: string;                      // unique key ('section:reply_needed', 'bulk-email', 'crm-rescan', …)
  label: string;
  kind?: string;                   // grouping tag ('section' | 'bulk-email' | 'rescan')
  poll: () => Promise<JobPoll>;    // job-specific poll; provider calls this each tick
  onRestore?: () => void;          // if set, the card shows an "Open" button
}

/** Map any backend status string onto the console's 3 states. Unknown (e.g.
 * 'not_run') is treated as non-terminal so a job that hasn't produced output
 * yet doesn't auto-finalize. */
export function normalizeStatus(s: string): JobStatus {
  const v = (s || '').toLowerCase();
  if (v === 'fresh' || v === 'done' || v === 'ok' || v === 'stale') return 'done';
  if (v === 'error' || v === 'failed') return 'error';
  return 'running';
}

// ── Context ────────────────────────────────────────────────

interface ActivityCtx {
  startJob: (job: Job) => void;
  start: (sectionId: string) => void;      // back-compat: section convenience wrapper
  stop:  (id: string) => void;
  isActive: (id: string) => boolean;
}

const Ctx = createContext<ActivityCtx>({
  startJob: () => {}, start: () => {}, stop: () => {}, isActive: () => false,
});

export function useActivity() {
  return useContext(Ctx);
}

// ── Provider ───────────────────────────────────────────────

interface TaskState {
  id: string;
  label: string;
  status: JobStatus;
  progress?: { current: number; total: number };
  logs: string[];
  last_run?: string;
  error?: string;
  startedAt: number;
  finalisedAt?: number;
  onRestore?: () => void;
}

const HISTORY_CAP = 15;

/** Keep finished cards as history, but bounded — drop the oldest finished ones
 * once we exceed the cap. Running cards are never dropped. */
function capHistory(tasks: Record<string, TaskState>): Record<string, TaskState> {
  const entries = Object.values(tasks);
  if (entries.length <= HISTORY_CAP) return tasks;
  const finished = entries
    .filter(t => t.status !== 'running')
    .sort((a, b) => (a.finalisedAt ?? a.startedAt) - (b.finalisedAt ?? b.startedAt));
  const removeIds = new Set(finished.slice(0, entries.length - HISTORY_CAP).map(t => t.id));
  const next: Record<string, TaskState> = {};
  for (const [id, t] of Object.entries(tasks)) if (!removeIds.has(id)) next[id] = t;
  return next;
}

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [tasks, setTasks]     = useState<Record<string, TaskState>>({});
  // Default collapsed — the FAB is a persistent launcher, always present.
  const [forceClosed, setForceClosed] = useState(true);
  // poll closures live OUT of React state so registering a job doesn't churn
  // the polling effect's deps.
  const jobsRef = useRef<Map<string, Job>>(new Map());

  const startJob = useCallback((job: Job) => {
    jobsRef.current.set(job.id, job);
    setTracked(s => { const next = new Set(s); next.add(job.id); return next; });
    setTasks(t => capHistory({
      ...t,
      [job.id]: {
        id: job.id, label: job.label, status: 'running', logs: [],
        startedAt: Date.now(), onRestore: job.onRestore,
      },
    }));
    setForceClosed(false);
  }, []);

  const start = useCallback((sectionId: string) => {
    const meta = SECTION_BY_ID[sectionId];
    startJob({
      id: sectionId,
      label: meta?.name ?? sectionId,
      kind: 'section',
      poll: async () => {
        const r = await getSection(sectionId) as Record<string, unknown>;
        return {
          status: normalizeStatus(String(r.status ?? '')),
          logs: Array.isArray(r.logs) ? (r.logs as string[]) : undefined,
          last_run: typeof r.last_run === 'string' ? r.last_run : undefined,
          error: typeof r.error === 'string' ? r.error : undefined,
        };
      },
    });
  }, [startJob]);

  const stop = useCallback((id: string) => {
    jobsRef.current.delete(id);
    setTracked(s => { const next = new Set(s); next.delete(id); return next; });
    setTasks(t => { const { [id]: _, ...rest } = t; return rest; });
  }, []);

  const clearFinished = useCallback(() => {
    setTasks(t => {
      const next: Record<string, TaskState> = {};
      for (const [id, task] of Object.entries(t)) if (task.status === 'running') next[id] = task;
      return next;
    });
  }, []);

  const isActive = useCallback((id: string) => tracked.has(id), [tracked]);

  // One interval — fan out to each tracked job's own poll().
  const pollRef = useRef<number | null>(null);
  useEffect(() => {
    if (tracked.size === 0) {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    const tick = async () => {
      const ids = Array.from(tracked);
      const results = await Promise.all(
        ids.map(id => {
          const job = jobsRef.current.get(id);
          return job ? job.poll().catch(() => null) : Promise.resolve(null);
        })
      );
      const finalized: string[] = [];
      setTasks(prev => {
        const next = { ...prev };
        ids.forEach((id, i) => {
          const r = results[i];
          const existing = prev[id];
          if (!r || !existing) return;
          const justFinalised = existing.status === 'running' && r.status !== 'running';
          next[id] = {
            ...existing,
            status: r.status,
            progress: r.progress ?? existing.progress,
            logs: r.logs ?? existing.logs,
            last_run: r.last_run ?? existing.last_run,
            error: r.error ?? existing.error,
            finalisedAt: justFinalised ? Date.now() : existing.finalisedAt,
          };
          // Finished tasks stay in history until the user removes them.
          if (justFinalised) finalized.push(id);
        });
        return next;
      });
      // Stop polling finished jobs, but KEEP their card in `tasks` (history).
      if (finalized.length) {
        finalized.forEach(id => jobsRef.current.delete(id));
        setTracked(s => {
          const nx = new Set(s);
          finalized.forEach(id => nx.delete(id));
          return nx;
        });
      }
    };
    tick();
    pollRef.current = window.setInterval(tick, 3000);
    return () => {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [tracked, stop]);

  const taskList = useMemo(() => Object.values(tasks), [tasks]);
  const runningCount = taskList.filter(t => t.status === 'running').length;

  return (
    <Ctx.Provider value={{ startJob, start, stop, isActive }}>
      {children}
      <ActivityDrawer
        open={!forceClosed}
        tasks={taskList}
        onClose={() => setForceClosed(true)}
        onDismiss={stop}
        onClearFinished={clearFinished}
      />
      <ActivityFab
        show={forceClosed}
        count={taskList.length}
        running={runningCount > 0}
        onClick={() => setForceClosed(false)}
      />
    </Ctx.Provider>
  );
}

// ── Collapsed FAB ──────────────────────────────────────────
// When the drawer is dismissed but tasks are still tracked, collapse to a
// small round button (bottom-right) so the console is always recoverable.

function ActivityFab({
  show, count, running, onClick,
}: { show: boolean; count: number; running: boolean; onClick: () => void }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.button
          key="activity-fab"
          onClick={onClick}
          title="Show activity"
          className="fixed bottom-6 right-6 z-40 w-12 h-12 rounded-full bg-executive-accent
                     text-white shadow-2xl flex items-center justify-center hover:opacity-90"
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        >
          {running
            ? <Loader2 size={18} className="animate-spin" />
            : <Activity size={18} />}
          {count > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full
                             bg-executive-card border border-executive-border text-[10px]
                             font-semibold flex items-center justify-center text-executive-text">
              {count}
            </span>
          )}
        </motion.button>
      )}
    </AnimatePresence>
  );
}

// ── Drawer UI ──────────────────────────────────────────────

function ActivityDrawer({
  open, tasks, onClose, onDismiss, onClearFinished,
}: {
  open: boolean; tasks: TaskState[]; onClose: () => void;
  onDismiss: (id: string) => void; onClearFinished: () => void;
}) {
  const hasFinished = tasks.some(t => t.status !== 'running');
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          key="activity"
          className="fixed right-0 top-0 bottom-0 w-full md:w-[420px] z-40
                     bg-executive-card border-l border-executive-border
                     flex flex-col shadow-2xl"
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'tween', ease: [0.32, 0.72, 0, 1], duration: 0.28 }}
        >
          <header className="px-5 py-3 border-b border-executive-border flex items-center justify-between sticky top-0 bg-executive-card z-10">
            <div className="flex items-center gap-2">
              <Activity size={14} className="text-executive-accent" />
              <h3 className="text-sm font-semibold text-executive-text">Activity</h3>
              <span className="text-[10px] uppercase tracking-wider text-executive-muted">
                {tasks.length} task{tasks.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {hasFinished && (
                <button
                  onClick={onClearFinished}
                  title="Clear finished"
                  className="text-[10px] px-2 py-1 rounded text-executive-muted hover:text-executive-text hover:bg-executive-border/40 transition-colors"
                >
                  Clear
                </button>
              )}
              <button
                onClick={onClose}
                title="Minimize to a button"
                className="p-1.5 rounded text-executive-muted hover:text-executive-text hover:bg-executive-border/40 transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {tasks.length === 0
              ? <p className="text-xs text-executive-muted text-center py-10">No activity right now.</p>
              : tasks.map(t => <TaskPanel key={t.id} task={t} onDismiss={() => onDismiss(t.id)} />)}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function TaskPanel({ task, onDismiss }: { task: TaskState; onDismiss: () => void }) {
  const elapsedSec = Math.max(0, Math.floor((Date.now() - task.startedAt) / 1000));
  const running = task.status === 'running';
  const failed = task.status === 'error';
  const pct = task.progress && task.progress.total
    ? Math.round(100 * task.progress.current / task.progress.total)
    : 0;

  return (
    <div className={`rounded-lg border p-3 ${
      failed
        ? 'border-rose-400/40 bg-rose-400/5'
        : running
          ? 'border-amber-400/40 bg-amber-400/5'
          : 'border-emerald-400/40 bg-emerald-400/5'
    }`}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          {running ? <Loader2 size={12} className="animate-spin text-amber-400 shrink-0" />
            : failed ? <AlertCircle size={12} className="text-rose-400 shrink-0" />
              : <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />}
          <span className="text-xs font-semibold text-executive-text truncate">{task.label}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {task.onRestore && (
            <button
              onClick={task.onRestore}
              title="Open"
              className="flex items-center gap-0.5 text-[10px] text-executive-accent hover:opacity-80"
            >
              Open <ExternalLink size={10} />
            </button>
          )}
          <span className="text-[10px] tabular-nums text-executive-muted">
            {running ? formatElapsed(elapsedSec) : task.last_run ? relativeTime(task.last_run) : 'done'}
          </span>
          <button onClick={onDismiss} title="Remove task" className="text-executive-muted hover:text-rose-300">
            <X size={11} />
          </button>
        </div>
      </div>

      {task.progress && (
        <div className="mb-2">
          <div className="flex justify-between text-[10px] text-executive-muted mb-1">
            <span>{running ? 'Working' : 'Done'}</span>
            <span className="tabular-nums">{task.progress.current}/{task.progress.total}</span>
          </div>
          <div className="h-1 rounded bg-executive-border/40 overflow-hidden">
            <div className="h-full bg-executive-accent transition-[width] duration-300" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}

      {task.error && (
        <p className="text-[11px] text-rose-300 mb-2 break-words">{task.error}</p>
      )}

      {task.logs.length > 0 && (
        <pre className="text-[10px] leading-relaxed text-executive-muted whitespace-pre-wrap break-words font-mono max-h-48 overflow-y-auto">
          {task.logs.join('\n')}
        </pre>
      )}
    </div>
  );
}

function formatElapsed(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s}s`;
}
