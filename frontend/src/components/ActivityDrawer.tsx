/**
 * Global activity drawer — shows live logs for whatever long-running task
 * the user just triggered (Re-run briefing, Refresh section, Scan
 * historical expenses, etc).
 *
 * Architecture:
 *   - ActivityProvider holds a Set<string> of section_ids currently being
 *     tracked. Wraps the app at the top level.
 *   - Any component triggering a long task calls useActivity().start(id)
 *     after kicking off the backend call. The drawer auto-opens.
 *   - Drawer polls /api/sections/{id} every 3s for each tracked id; reads
 *     the `logs` and `status` fields from result.json.
 *   - When a section's status flips to fresh/error, drawer keeps it visible
 *     for 4s with a final-state badge, then auto-removes.
 *   - User can manually dismiss the drawer; reopens automatically the next
 *     time any task starts.
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import type { ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { X, Activity, Loader2, CheckCircle2, AlertCircle } from 'lucide-react';
import { getSection, relativeTime } from '../lib/api';
import { SECTION_BY_ID } from '../lib/sections';

// ── Context ────────────────────────────────────────────────

interface ActivityCtx {
  start: (sectionId: string) => void;
  stop:  (sectionId: string) => void;
}

const Ctx = createContext<ActivityCtx>({ start: () => {}, stop: () => {} });

export function useActivity() {
  return useContext(Ctx);
}

// ── Provider + drawer ─────────────────────────────────────

interface TaskState {
  id:         string;          // section id
  status:     string;          // 'running' | 'fresh' | 'error' | …
  logs:       string[];
  last_run?:  string;
  error?:     string;
  startedAt:  number;
  // becomes truthy once the task finished — drawer keeps showing for 4s
  finalisedAt?: number;
}

export function ActivityProvider({ children }: { children: ReactNode }) {
  const [tracked, setTracked] = useState<Set<string>>(new Set());
  const [tasks, setTasks]     = useState<Record<string, TaskState>>({});
  // User-controlled "drawer open" override. true = force closed even if
  // tasks active; null = follow active-tasks default.
  const [forceClosed, setForceClosed] = useState(false);

  const start = useCallback((id: string) => {
    setTracked(s => {
      const next = new Set(s);
      next.add(id);
      return next;
    });
    setTasks(t => ({
      ...t,
      [id]: { id, status: 'running', logs: [], startedAt: Date.now() },
    }));
    setForceClosed(false);  // re-open if user dismissed earlier
  }, []);

  const stop = useCallback((id: string) => {
    setTracked(s => {
      const next = new Set(s);
      next.delete(id);
      return next;
    });
    setTasks(t => {
      const { [id]: _, ...rest } = t;
      return rest;
    });
  }, []);

  // Poll every 3s for each tracked id. Pull result.json's logs/status.
  const pollRef = useRef<number | null>(null);
  useEffect(() => {
    if (tracked.size === 0) {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    const tick = async () => {
      const ids = Array.from(tracked);
      const results = await Promise.all(ids.map(id => getSection(id).catch(() => null)));
      setTasks(prev => {
        const next = { ...prev };
        ids.forEach((id, i) => {
          const r = results[i] as (Record<string, unknown> | null);
          if (!r) return;
          const existing = prev[id];
          const status = String(r.status ?? '');
          const logs = Array.isArray(r.logs) ? (r.logs as string[]) : (existing?.logs ?? []);
          const last_run = typeof r.last_run === 'string' ? r.last_run : undefined;
          const error = typeof r.error === 'string' ? r.error : undefined;
          const justFinalised = existing && existing.status === 'running' && status !== 'running';
          next[id] = {
            id, status, logs, last_run, error,
            startedAt: existing?.startedAt ?? Date.now(),
            finalisedAt: justFinalised ? Date.now() : existing?.finalisedAt,
          };
          // Auto-remove 4s after final state
          if (justFinalised) {
            window.setTimeout(() => stop(id), 4000);
          }
        });
        return next;
      });
    };
    tick();
    pollRef.current = window.setInterval(tick, 3000);
    return () => {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [tracked, stop]);

  const open = tracked.size > 0 && !forceClosed;
  const taskList = useMemo(() => Object.values(tasks), [tasks]);

  return (
    <Ctx.Provider value={{ start, stop }}>
      {children}
      <ActivityDrawer
        open={open}
        tasks={taskList}
        onClose={() => setForceClosed(true)}
      />
    </Ctx.Provider>
  );
}

// ── Drawer UI ──────────────────────────────────────────────

function ActivityDrawer({
  open, tasks, onClose,
}: { open: boolean; tasks: TaskState[]; onClose: () => void }) {
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
          {/* Sticky header */}
          <header className="px-5 py-3 border-b border-executive-border flex items-center justify-between sticky top-0 bg-executive-card z-10">
            <div className="flex items-center gap-2">
              <Activity size={14} className="text-executive-accent" />
              <h3 className="text-sm font-semibold text-executive-text">Activity</h3>
              <span className="text-[10px] uppercase tracking-wider text-executive-muted">
                {tasks.length} task{tasks.length !== 1 ? 's' : ''}
              </span>
            </div>
            <button
              onClick={onClose}
              title="Hide (will auto-reopen when next task starts)"
              className="p-1.5 rounded text-executive-muted hover:text-executive-text hover:bg-executive-border/40 transition-colors"
            >
              <X size={14} />
            </button>
          </header>

          {/* Body */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {tasks.map(t => <TaskPanel key={t.id} task={t} />)}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

function TaskPanel({ task }: { task: TaskState }) {
  const meta = SECTION_BY_ID[task.id];
  const label = meta?.name ?? task.id;
  const elapsedSec = Math.max(0, Math.floor((Date.now() - task.startedAt) / 1000));
  const running = task.status === 'running';
  const failed = task.status === 'error';

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
          <span className="text-xs font-semibold text-executive-text truncate">{label}</span>
        </div>
        <span className="text-[10px] tabular-nums text-executive-muted shrink-0">
          {running
            ? `${formatElapsed(elapsedSec)}`
            : task.last_run ? relativeTime(task.last_run) : 'done'}
        </span>
      </div>

      {task.error && (
        <p className="text-[11px] text-rose-300 mb-2 break-words">{task.error}</p>
      )}

      <pre className="text-[10px] leading-relaxed text-executive-muted whitespace-pre-wrap break-words font-mono max-h-48 overflow-y-auto">
        {task.logs.length
          ? task.logs.join('\n')
          : running
            ? '(waiting for first log line…)'
            : '(no logs captured)'}
      </pre>
    </div>
  );
}

function formatElapsed(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s}s`;
}
