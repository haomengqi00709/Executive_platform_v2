import { useState, useCallback, useEffect } from 'react';
import { Upload, FileText, Loader2, X, AlertCircle, CheckCircle2 } from 'lucide-react';

type Kind = 'crm' | 'project';

interface PreviewItem {
  // common
  _already_exists?: boolean;
  // contact fields
  email?: string;
  name?: string;
  company?: string;
  role?: string;
  status?: string;
  priority?: string;
  // project fields
  summary?: string;
  category?: string;
  participants?: string[];
  key_topics?: string[];
}

interface FileSummary {
  name: string;
  count: number;
  error: string | null;
}

interface UploadResponse {
  contacts?: PreviewItem[];
  projects?: PreviewItem[];
  files: FileSummary[];
}

const ALLOWED_EXTS = ['.csv', '.xlsx', '.xls', '.docx', '.pdf', '.txt', '.md'];

export default function BulkUploadModal({
  kind, onClose, onCommitted,
}: {
  kind: Kind;
  onClose: () => void;
  onCommitted: (added: number) => void;
}) {
  const [stage, setStage]       = useState<'select' | 'parsing' | 'preview' | 'committing'>('select');
  const [error, setError]       = useState('');
  const [items, setItems]       = useState<PreviewItem[]>([]);
  const [files, setFiles]       = useState<FileSummary[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult]     = useState<{ added: number; skipped_existing: number; skipped_invalid: number } | null>(null);

  // Close on Esc
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && stage !== 'parsing' && stage !== 'committing') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, stage]);

  const handleFiles = useCallback(async (fileList: FileList | File[]) => {
    const arr = Array.from(fileList).filter(f => {
      const ext = '.' + (f.name.split('.').pop() || '').toLowerCase();
      return ALLOWED_EXTS.includes(ext);
    });
    if (arr.length === 0) {
      setError('No supported files selected. Use CSV / Excel / PDF / Word / TXT.');
      return;
    }

    setStage('parsing'); setError(''); setItems([]); setFiles([]); setSelected(new Set());

    const formData = new FormData();
    for (const f of arr) formData.append('files', f);

    const endpoint = kind === 'crm' ? '/api/crm/bulk-upload' : '/api/projects/bulk-upload';

    try {
      const r = await fetch(endpoint, { method: 'POST', credentials: 'include', body: formData });
      if (!r.ok) throw new Error(`Upload failed: ${r.status}`);
      const d = (await r.json()) as UploadResponse;
      const list = (kind === 'crm' ? d.contacts : d.projects) || [];
      setItems(list);
      setFiles(d.files || []);
      // Pre-select all rows that are NOT already in the DB
      setSelected(new Set(
        list.map((_, i) => i).filter(i => !list[i]._already_exists)
      ));
      setStage('preview');
    } catch (e: any) {
      setError(e?.message || 'Upload failed');
      setStage('select');
    }
  }, [kind]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  const toggle = (i: number) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i); else next.add(i);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === items.length) setSelected(new Set());
    else setSelected(new Set(items.map((_, i) => i)));
  };

  const commit = async () => {
    if (selected.size === 0) return;
    setStage('committing'); setError('');
    const chosen = Array.from(selected).map(i => items[i]);
    const endpoint = kind === 'crm' ? '/api/crm/bulk-commit' : '/api/projects/bulk-commit';
    const payload = kind === 'crm' ? { contacts: chosen } : { projects: chosen };
    try {
      const r = await fetch(endpoint, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(`Commit failed: ${r.status}`);
      const d = await r.json();
      setResult(d);
      onCommitted(d.added || 0);
    } catch (e: any) {
      setError(e?.message || 'Commit failed');
      setStage('preview');
    }
  };

  const recordLabel = kind === 'crm' ? 'contacts' : 'projects';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={() => { if (stage !== 'parsing' && stage !== 'committing') onClose(); }}
    >
      <div
        className="bg-executive-card border border-executive-border rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-executive-border flex items-start justify-between">
          <div>
            <h3 className="text-base font-semibold">Bulk upload {recordLabel}</h3>
            <p className="text-xs text-executive-muted mt-1">
              Upload CSV / Excel / PDF / Word files. AI extracts {recordLabel}; you review before they're saved.
            </p>
          </div>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text disabled:opacity-40"
                  disabled={stage === 'parsing' || stage === 'committing'}>
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto px-5 py-4">
          {error && (
            <div className="flex items-center gap-2 p-3 mb-3 bg-rose-500/8 border border-rose-500/20 rounded-md text-rose-500 text-xs font-mono">
              <AlertCircle size={14} /> {error}
            </div>
          )}

          {/* Select stage — file picker */}
          {stage === 'select' && (
            <label
              onDragOver={e => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={`flex flex-col items-center justify-center gap-3 py-12 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
                dragOver ? 'border-executive-accent bg-executive-accent/5' : 'border-executive-border hover:border-executive-accent/40'
              }`}
            >
              <Upload size={28} className="text-executive-muted" />
              <p className="text-sm font-medium">Drop files here or click to select</p>
              <p className="text-xs text-executive-muted">{ALLOWED_EXTS.join(' · ')} · up to 10MB each · multiple OK</p>
              <input
                type="file"
                multiple
                accept={ALLOWED_EXTS.join(',')}
                onChange={e => e.target.files && handleFiles(e.target.files)}
                className="hidden"
              />
            </label>
          )}

          {/* Parsing stage — spinner */}
          {stage === 'parsing' && (
            <div className="flex flex-col items-center justify-center gap-4 py-16">
              <Loader2 size={28} className="animate-spin text-executive-accent" />
              <p className="text-sm">AI is reading your files...</p>
              <p className="text-xs text-executive-muted">This can take 30 seconds to a couple of minutes for large files.</p>
            </div>
          )}

          {/* Preview stage — checkbox list */}
          {stage === 'preview' && (
            <div className="space-y-3">
              {/* File summaries */}
              <div className="text-xs text-executive-muted flex flex-wrap gap-2">
                {files.map((f, i) => (
                  <span key={i} className={`px-2 py-1 rounded font-mono ${f.error ? 'bg-rose-500/10 text-rose-500' : 'bg-executive-border/40'}`}>
                    <FileText size={10} className="inline mr-1" />
                    {f.name}: {f.error ? `error: ${f.error}` : `${f.count} ${recordLabel}`}
                  </span>
                ))}
              </div>

              {items.length === 0 ? (
                <p className="text-center text-sm text-executive-muted py-8">No {recordLabel} extracted.</p>
              ) : (
                <>
                  <div className="flex items-center justify-between sticky top-0 bg-executive-card py-2 border-b border-executive-border">
                    <label className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={selected.size === items.length && items.length > 0}
                        onChange={toggleAll}
                        className="w-4 h-4 rounded border-executive-border text-executive-accent focus:ring-executive-accent"
                      />
                      <span className="font-medium">Select all ({items.length})</span>
                    </label>
                    <span className="text-xs text-executive-muted">
                      {selected.size} selected · {items.filter(i => i._already_exists).length} already exist
                    </span>
                  </div>
                  <div className="divide-y divide-executive-border/40">
                    {items.map((it, i) => (
                      <label key={i} className="flex items-start gap-3 py-2.5 cursor-pointer hover:bg-executive-border/20 px-2 rounded">
                        <input
                          type="checkbox"
                          checked={selected.has(i)}
                          onChange={() => toggle(i)}
                          disabled={it._already_exists}
                          className="mt-1 w-4 h-4 rounded border-executive-border text-executive-accent focus:ring-executive-accent"
                        />
                        <div className="flex-1 min-w-0">
                          {kind === 'crm' ? <CrmRow item={it} /> : <ProjectRow item={it} />}
                          {it._already_exists && (
                            <p className="text-[10px] font-mono uppercase text-amber-500 mt-1">⚠ already exists — skipped</p>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* Committing stage */}
          {stage === 'committing' && !result && (
            <div className="flex flex-col items-center justify-center gap-4 py-16">
              <Loader2 size={28} className="animate-spin text-executive-accent" />
              <p className="text-sm">Saving to {kind === 'crm' ? 'CRM' : 'Projects DB'}...</p>
            </div>
          )}

          {/* Done */}
          {result && (
            <div className="flex flex-col items-center justify-center gap-4 py-12">
              <CheckCircle2 size={32} className="text-emerald-500" />
              <p className="text-sm font-medium">Added {result.added} {recordLabel}</p>
              <p className="text-xs text-executive-muted">
                {result.skipped_existing > 0 && `${result.skipped_existing} skipped (already existed). `}
                {result.skipped_invalid > 0 && `${result.skipped_invalid} skipped (invalid).`}
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        {stage === 'preview' && (
          <div className="px-5 py-3 border-t border-executive-border flex items-center justify-between">
            <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-lg border border-executive-border text-executive-muted hover:text-executive-text">
              Cancel
            </button>
            <button
              onClick={commit}
              disabled={selected.size === 0}
              className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-lg bg-executive-accent text-white hover:opacity-90 disabled:opacity-40"
            >
              <CheckCircle2 size={12} />
              Confirm and add {selected.size} {recordLabel}
            </button>
          </div>
        )}
        {result && (
          <div className="px-5 py-3 border-t border-executive-border flex justify-end">
            <button onClick={onClose} className="text-xs px-4 py-1.5 rounded-lg bg-executive-accent text-white hover:opacity-90">
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function CrmRow({ item }: { item: PreviewItem }) {
  return (
    <div className="text-sm">
      <p className="font-medium truncate">{item.name || item.email}</p>
      <p className="text-xs font-mono text-executive-muted truncate">{item.email}</p>
      <p className="text-xs text-executive-muted truncate">
        {[item.company, item.role, item.status].filter(Boolean).join(' · ')}
      </p>
    </div>
  );
}

function ProjectRow({ item }: { item: PreviewItem }) {
  return (
    <div className="text-sm">
      <p className="font-medium truncate">{item.name}</p>
      <p className="text-xs text-executive-muted truncate">
        {[item.status, item.category].filter(Boolean).join(' · ')}
      </p>
      {item.summary && <p className="text-xs text-executive-muted line-clamp-1 mt-0.5">{item.summary}</p>}
    </div>
  );
}
