import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, CheckCircle2, X, Loader2, AlertCircle, ChevronDown, ChevronRight } from 'lucide-react';

type Confidence = 'high' | 'medium' | 'low';
type CandidateType = 'project_duplicate' | 'contact_duplicate' | 'stale_project' | 'stale_contact';

interface Preview {
  id?: string; email?: string;
  name?: string;
  summary?: string;
  status?: string;
  participants?: string[];
  key_topics?: string[];
  thread_count?: number;
  last_activity?: string;
  last_contact?: string;
  company?: string;
  role?: string;
}

interface Candidate {
  id: string;
  type: CandidateType;
  primary: Preview;
  duplicate: Preview | null;
  confidence: Confidence;
  reasoning: string;
  discovered_at: string;
  status?: string;
}

interface PendingResponse {
  candidates: Candidate[];
  last_scan: { timestamp: string | null; summary?: Record<string, number> };
}

export default function CleanupTab() {
  const [data, setData]           = useState<PendingResponse | null>(null);
  const [loading, setLoading]     = useState(true);
  const [scanning, setScanning]   = useState(false);
  const [selected, setSelected]   = useState<Set<string>>(new Set());
  const [processing, setProcessing] = useState(false);
  const [error, setError]         = useState('');
  const [expanded, setExpanded]   = useState<Set<string>>(new Set(['high']));

  const fetchPending = useCallback(async () => {
    try {
      const r = await fetch('/api/db-cleanup/pending', { credentials: 'include' });
      if (!r.ok) throw new Error('Failed to load candidates');
      const d = await r.json();
      setData(d);
      // High-confidence duplicates are pre-selected by default
      const presel = new Set<string>(
        (d.candidates || [])
          .filter((c: Candidate) =>
            c.confidence === 'high' &&
            (c.type === 'project_duplicate' || c.type === 'contact_duplicate') &&
            c.status !== 'dismissed'
          )
          .map((c: Candidate) => c.id)
      );
      setSelected(presel);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchPending(); }, [fetchPending]);

  const runScan = async () => {
    setScanning(true); setError('');
    try {
      await fetch('/api/db-cleanup/scan', { method: 'POST', credentials: 'include' });
      // Poll for completion: last_scan.timestamp will change
      const before = data?.last_scan?.timestamp || '';
      const start = Date.now();
      const tick = async () => {
        if (Date.now() - start > 10 * 60 * 1000) { setScanning(false); return; }
        const r = await fetch('/api/db-cleanup/pending', { credentials: 'include' });
        const d = await r.json();
        if (d?.last_scan?.timestamp && d.last_scan.timestamp !== before) {
          setData(d);
          setScanning(false);
        } else {
          setTimeout(tick, 4000);
        }
      };
      setTimeout(tick, 4000);
    } catch (e: any) {
      setError(e?.message || 'Scan failed');
      setScanning(false);
    }
  };

  const approveSelected = async () => {
    if (selected.size === 0) return;
    setProcessing(true); setError('');
    try {
      const r = await fetch('/api/db-cleanup/approve', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selected) }),
      });
      if (!r.ok) throw new Error('Approve failed');
      await fetchPending();
      setSelected(new Set());
    } catch (e: any) {
      setError(e?.message || 'Approve failed');
    } finally {
      setProcessing(false);
    }
  };

  const rejectSelected = async () => {
    if (selected.size === 0) return;
    setProcessing(true); setError('');
    try {
      await fetch('/api/db-cleanup/reject', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: Array.from(selected) }),
      });
      await fetchPending();
      setSelected(new Set());
    } catch (e: any) {
      setError(e?.message || 'Reject failed');
    } finally {
      setProcessing(false);
    }
  };

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleGroup = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-executive-muted py-12 justify-center">
        <Loader2 size={16} className="animate-spin" /> Loading candidates...
      </div>
    );
  }

  const cands = (data?.candidates || []).filter(c => c.status !== 'dismissed');
  const grouped = {
    high:   cands.filter(c => (c.type === 'project_duplicate' || c.type === 'contact_duplicate') && c.confidence === 'high'),
    medium: cands.filter(c => (c.type === 'project_duplicate' || c.type === 'contact_duplicate') && c.confidence === 'medium'),
    low:    cands.filter(c => (c.type === 'project_duplicate' || c.type === 'contact_duplicate') && c.confidence === 'low'),
    stale:  cands.filter(c => c.type === 'stale_project' || c.type === 'stale_contact'),
  };

  const lastScan = data?.last_scan?.timestamp
    ? new Date(data.last_scan.timestamp).toLocaleString()
    : 'never';

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between bg-executive-card border border-executive-border rounded-lg px-4 py-3">
        <div>
          <p className="text-xs font-mono text-executive-muted">Last scan: {lastScan}</p>
          <p className="text-sm font-medium mt-0.5">
            {cands.length} candidate{cands.length !== 1 ? 's' : ''} pending review
          </p>
        </div>
        <button
          onClick={runScan}
          disabled={scanning}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-executive-accent text-white text-sm font-medium hover:bg-emerald-400 disabled:opacity-50 transition"
        >
          {scanning ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {scanning ? 'Scanning...' : 'Scan now'}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 bg-rose-500/8 border border-rose-500/20 rounded-lg text-rose-500 text-xs font-mono">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Selection action bar — sticky at top when items selected */}
      {selected.size > 0 && (
        <div className="sticky top-0 z-10 flex items-center justify-between bg-executive-accent/10 border border-executive-accent/30 rounded-lg px-4 py-2">
          <p className="text-sm font-medium text-executive-accent">{selected.size} selected</p>
          <div className="flex gap-2">
            <button
              onClick={rejectSelected}
              disabled={processing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-executive-border text-xs text-executive-muted hover:text-executive-text disabled:opacity-50"
            >
              <X size={12} /> Reject
            </button>
            <button
              onClick={approveSelected}
              disabled={processing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-executive-accent text-white text-xs font-medium hover:bg-emerald-400 disabled:opacity-50"
            >
              {processing ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
              Approve ({selected.size})
            </button>
          </div>
        </div>
      )}

      {cands.length === 0 && (
        <div className="text-center py-16 text-sm text-executive-muted">
          <CheckCircle2 size={32} className="mx-auto mb-3 text-emerald-500" />
          <p className="font-medium text-executive-text">Nothing to clean up</p>
          <p className="mt-1">No duplicates or stale records found. Try "Scan now" if your data has changed since the last run.</p>
        </div>
      )}

      {/* Groups */}
      <Group
        title="High confidence duplicates"
        confidence="high"
        items={grouped.high}
        expanded={expanded.has('high')}
        onToggle={() => toggleGroup('high')}
        selected={selected}
        onItemToggle={toggle}
      />
      <Group
        title="Medium confidence duplicates"
        confidence="medium"
        items={grouped.medium}
        expanded={expanded.has('medium')}
        onToggle={() => toggleGroup('medium')}
        selected={selected}
        onItemToggle={toggle}
      />
      <Group
        title="Low confidence duplicates"
        confidence="low"
        items={grouped.low}
        expanded={expanded.has('low')}
        onToggle={() => toggleGroup('low')}
        selected={selected}
        onItemToggle={toggle}
      />
      <Group
        title="Stale records (auto-archivable)"
        confidence={null}
        items={grouped.stale}
        expanded={expanded.has('stale')}
        onToggle={() => toggleGroup('stale')}
        selected={selected}
        onItemToggle={toggle}
      />
    </div>
  );
}

function Group({
  title, confidence, items, expanded, onToggle, selected, onItemToggle,
}: {
  title: string; confidence: Confidence | null;
  items: Candidate[]; expanded: boolean; onToggle: () => void;
  selected: Set<string>; onItemToggle: (id: string) => void;
}) {
  if (items.length === 0) return null;
  const badgeColor =
    confidence === 'high'   ? 'bg-emerald-500/15 text-emerald-600' :
    confidence === 'medium' ? 'bg-amber-500/15 text-amber-600' :
    confidence === 'low'    ? 'bg-slate-500/15 text-slate-600' :
                              'bg-sky-500/15 text-sky-600';
  return (
    <div className="border border-executive-border rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-executive-card hover:bg-executive-border/30 transition"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span className="text-sm font-medium">{title}</span>
          <span className={`text-xs font-mono px-2 py-0.5 rounded ${badgeColor}`}>{items.length}</span>
        </div>
      </button>
      {expanded && (
        <div className="divide-y divide-executive-border">
          {items.map(c => (
            <CandidateRow
              key={c.id}
              candidate={c}
              checked={selected.has(c.id)}
              onToggle={() => onItemToggle(c.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CandidateRow({ candidate, checked, onToggle }: { candidate: Candidate; checked: boolean; onToggle: () => void }) {
  const isStale = candidate.type === 'stale_project' || candidate.type === 'stale_contact';
  return (
    <label className="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-executive-border/20 transition">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-1 w-4 h-4 rounded border-executive-border text-executive-accent focus:ring-executive-accent"
      />
      <div className="flex-1 min-w-0 space-y-2">
        {!isStale ? (
          <>
            <div className="grid grid-cols-2 gap-3">
              <PreviewCard label="Keep" preview={candidate.primary} />
              <PreviewCard label="Merge into above" preview={candidate.duplicate || {}} />
            </div>
            <p className="text-xs text-executive-muted italic">→ {candidate.reasoning}</p>
          </>
        ) : (
          <>
            <PreviewCard label="Archive" preview={candidate.primary} />
            <p className="text-xs text-executive-muted italic">→ {candidate.reasoning}</p>
          </>
        )}
      </div>
    </label>
  );
}

function PreviewCard({ label, preview }: { label: string; preview: Preview }) {
  const title = preview.name || preview.email || preview.id || '(unknown)';
  const sub: string[] = [];
  if (preview.company) sub.push(preview.company);
  if (preview.role)    sub.push(preview.role);
  if (preview.status)  sub.push(preview.status);
  if (preview.thread_count) sub.push(`${preview.thread_count} threads`);
  if (preview.last_activity) sub.push(`last: ${preview.last_activity}`);
  if (preview.last_contact)  sub.push(`last: ${preview.last_contact}`);
  return (
    <div className="border border-executive-border rounded-md p-2 bg-executive-bg">
      <p className="text-[10px] font-mono uppercase text-executive-muted tracking-wider mb-1">{label}</p>
      <p className="text-sm font-medium truncate">{title}</p>
      {preview.email && preview.name && (
        <p className="text-xs font-mono text-executive-muted truncate">{preview.email}</p>
      )}
      {sub.length > 0 && (
        <p className="text-xs text-executive-muted mt-1">{sub.join(' · ')}</p>
      )}
      {preview.summary && (
        <p className="text-xs text-executive-muted mt-1 line-clamp-2">{preview.summary}</p>
      )}
    </div>
  );
}
