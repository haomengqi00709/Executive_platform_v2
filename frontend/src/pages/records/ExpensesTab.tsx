import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Loader2, Search, Trash2, Check, X, Pencil, Plus, Image as ImageIcon,
  History, RefreshCw, Download,
} from 'lucide-react';
import {
  getAllExpenses, patchExpense, deleteExpense, createExpense, expensePhotoUrl,
  scanHistoricalExpenses, expensesExportXlsxUrl,
} from '../../lib/api';
import type { ExpenseRow } from '../../lib/api';
import { useActivity } from '../../components/ActivityDrawer';

const CATEGORY_OPTIONS = ['Travel', 'Meals', 'Software', 'Services', 'Equipment', 'Utilities', 'Other'];

const CAT_COLOR: Record<string, string> = {
  Travel:    'bg-sky-400/15 text-sky-300',
  Meals:     'bg-amber-400/15 text-amber-300',
  Software:  'bg-violet-400/15 text-violet-300',
  Services:  'bg-emerald-400/15 text-emerald-300',
  Equipment: 'bg-rose-400/15 text-rose-300',
  Utilities: 'bg-teal-400/15 text-teal-300',
  Other:     'bg-executive-border/40 text-executive-muted',
};

interface EditState {
  id: string;
  field: 'Vendor' | 'Amount' | 'Date';
  value: string;
}

export default function ExpensesTab() {
  const [rows, setRows] = useState<ExpenseRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  // Expenses are reimbursable receipts only (invoices/contracts are no longer captured).
  const docType = 'receipt' as const;
  const [savingId, setSavingId] = useState<string | null>(null);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [viewingPhotoId, setViewingPhotoId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const refresh = () => {
    setLoading(true);
    getAllExpenses()
      .then(setRows)
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const update = async (id: string, patch: Partial<ExpenseRow>) => {
    setSavingId(id);
    try {
      const updated = await patchExpense(id, patch);
      setRows(rs => rs.map(r => r.id === id ? { ...r, ...updated } : r));
    } finally {
      setSavingId(null);
    }
  };

  const remove = async (id: string) => {
    if (!confirm('Delete this receipt row? This cannot be undone.')) return;
    setSavingId(id);
    try {
      await deleteExpense(id);
      setRows(rs => rs.filter(r => r.id !== id));
    } finally {
      setSavingId(null);
    }
  };

  const saveEdit = async () => {
    if (!edit) return;
    let value: string | number = edit.value;
    if (edit.field === 'Amount') {
      const n = parseFloat(edit.value);
      if (!isNaN(n)) value = n;
    }
    await update(edit.id, { [edit.field]: value });
    setEdit(null);
  };

  const visible = useMemo(() => {
    return rows.filter(r => {
      if (((r.document_type as string) || 'receipt') !== docType) return false;
      if (docType === 'receipt' && categoryFilter !== 'all' && (r.Category || 'Other') !== categoryFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          String(r.Vendor || '').toLowerCase().includes(q) ||
          String(r.Counterparty || '').toLowerCase().includes(q) ||
          String(r.Subject || '').toLowerCase().includes(q) ||
          String(r.Email_Subject || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [rows, search, categoryFilter, docType]);

  const totalsByCategory = useMemo(() => {
    const totals: Record<string, number> = {};
    for (const r of visible) {
      const cat = r.Category || 'Other';
      const amt = typeof r.Amount === 'number' ? r.Amount : parseFloat(String(r.Amount || 0));
      if (!isNaN(amt)) totals[cat] = (totals[cat] ?? 0) + amt;
    }
    return totals;
  }, [visible]);

  return (
    <div className="space-y-4">
      <HistoricalScanBanner onRowsChanged={refresh} initialRowCount={rows.length} />

      <header className="flex flex-wrap items-center gap-3 justify-between">
        <div className="text-xs text-executive-muted">
          {loading ? 'Loading…' : `${visible.length} ${docType}${visible.length === 1 ? '' : 's'}`}
          {docType === 'receipt' && Object.keys(totalsByCategory).length > 0 && (
            <span className="ml-3">
              Total: {Object.entries(totalsByCategory).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(' · ')}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-executive-muted" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search vendor or email subject…"
              className="pl-7 pr-3 py-1.5 text-xs bg-executive-bg border border-executive-border rounded-lg w-64 focus:outline-none focus:border-executive-accent/60"
            />
          </div>
          {docType === 'receipt' && (
            <select
              value={categoryFilter}
              onChange={e => setCategoryFilter(e.target.value)}
              className="px-2 py-1.5 text-xs bg-executive-bg border border-executive-border rounded-lg focus:outline-none focus:border-executive-accent/60"
            >
              <option value="all">All categories</option>
              {CATEGORY_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
          <a
            href={expensesExportXlsxUrl}
            download
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border border-executive-border text-executive-muted hover:text-executive-text hover:bg-executive-border/40"
            title="Download expenses as Excel"
          >
            <Download size={12} /> Excel
          </a>
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-executive-accent text-white hover:opacity-90"
          >
            <Plus size={12} /> Add Receipt
          </button>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-executive-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center text-sm text-executive-muted py-12">
          No {docType}s captured yet, or none match the filter.
        </div>
      ) : (
        <div className="bg-executive-card border border-executive-border rounded-xl overflow-hidden overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-executive-bg border-b border-executive-border">
              <tr className="text-xs text-executive-muted uppercase tracking-wider">
                <th className="text-left px-3 py-2 font-medium">Date</th>
                <th className="text-left px-3 py-2 font-medium">Vendor</th>
                <th className="text-right px-3 py-2 font-medium">Amount</th>
                <th className="text-left px-3 py-2 font-medium">Category</th>
                <th className="text-left px-3 py-2 font-medium">From</th>
                <th className="text-center px-3 py-2 font-medium">Photo</th>
                <th className="text-right px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {visible.map(r => {
                const isEditingVendor = edit?.id === r.id && edit.field === 'Vendor';
                const isEditingAmount = edit?.id === r.id && edit.field === 'Amount';
                const isEditingDate = edit?.id === r.id && edit.field === 'Date';
                const hasAttachment = !!r.Attachment && String(r.Attachment).trim() !== '';
                return (
                  <tr key={r.id} className="border-b border-executive-border/60 last:border-b-0 hover:bg-executive-border/10">
                    <td className="px-3 py-2 text-xs text-executive-muted whitespace-nowrap">
                      {isEditingDate ? (
                        <EditCell value={edit.value} onChange={v => setEdit({ ...edit, value: v })} onSave={saveEdit} onCancel={() => setEdit(null)} />
                      ) : (
                        <button onClick={() => setEdit({ id: r.id, field: 'Date', value: String(r.Date || '') })} className="hover:text-executive-text">
                          {r.Date || '—'}
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {isEditingVendor ? (
                        <EditCell value={edit.value} onChange={v => setEdit({ ...edit, value: v })} onSave={saveEdit} onCancel={() => setEdit(null)} />
                      ) : (
                        <button onClick={() => setEdit({ id: r.id, field: 'Vendor', value: String(r.Vendor || '') })} className="hover:text-executive-text inline-flex items-center gap-1 group">
                          <span>{r.Vendor || '—'}</span>
                          <Pencil size={10} className="opacity-0 group-hover:opacity-100 text-executive-muted" />
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {isEditingAmount ? (
                        <EditCell value={edit.value} onChange={v => setEdit({ ...edit, value: v })} onSave={saveEdit} onCancel={() => setEdit(null)} />
                      ) : (
                        <button onClick={() => setEdit({ id: r.id, field: 'Amount', value: String(r.Amount || '') })} className="hover:text-executive-text inline-flex items-center gap-1 group">
                          {r.Amount ?? '—'} {r.Currency || ''}
                          <Pencil size={10} className="opacity-0 group-hover:opacity-100 text-executive-muted" />
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <select
                        value={String(r.Category || 'Other')}
                        onChange={e => update(r.id, { Category: e.target.value })}
                        className={`text-xs px-2 py-1 rounded-md border-0 cursor-pointer ${CAT_COLOR[r.Category || 'Other'] ?? CAT_COLOR.Other}`}
                      >
                        {CATEGORY_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2 text-xs text-executive-muted truncate max-w-[14rem]">
                      {r.From || '—'}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {hasAttachment ? (
                        <button
                          onClick={() => setViewingPhotoId(r.id)}
                          className="text-xs p-1 rounded-md text-executive-muted hover:text-executive-accent hover:bg-executive-accent/10 transition-colors"
                          title={`View ${r.Attachment}`}
                        >
                          <ImageIcon size={14} />
                        </button>
                      ) : (
                        <span className="text-xs text-executive-muted/40">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {savingId === r.id ? (
                        <Loader2 size={12} className="inline animate-spin text-executive-muted" />
                      ) : (
                        <button
                          onClick={() => remove(r.id)}
                          className="text-xs p-1 rounded-md text-executive-muted hover:text-rose-400 hover:bg-rose-400/10 transition-colors"
                          title="Delete row"
                        >
                          <Trash2 size={12} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {viewingPhotoId && (
        <PhotoModal
          rowId={viewingPhotoId}
          row={rows.find(r => r.id === viewingPhotoId)}
          onClose={() => setViewingPhotoId(null)}
        />
      )}

      {adding && (
        <AddReceiptModal
          onClose={() => setAdding(false)}
          onCreated={() => { setAdding(false); refresh(); }}
        />
      )}
    </div>
  );
}


function PhotoModal({
  rowId, row, onClose,
}: {
  rowId: string; row: ExpenseRow | undefined; onClose: () => void;
}) {
  const [error, setError] = useState(false);
  const url = expensePhotoUrl(rowId);

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-executive-card border border-executive-border rounded-xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col shadow-xl">
        <div className="px-4 py-3 border-b border-executive-border flex items-center justify-between">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-executive-text truncate">
              {row?.Vendor || 'Receipt'}
            </h2>
            <p className="text-xs text-executive-muted truncate">
              {row?.Date} · {row?.Amount} {row?.Currency} · {row?.Attachment}
            </p>
          </div>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text shrink-0 ml-3">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-auto bg-executive-bg flex items-center justify-center p-4">
          {error ? (
            <div className="text-center text-sm text-executive-muted">
              <p className="mb-1">Photo not found in OneDrive.</p>
              <p className="text-xs">Older email receipts may not have been uploaded yet.</p>
            </div>
          ) : (
            <img
              src={url}
              alt={row?.Attachment || 'receipt'}
              onError={() => setError(true)}
              className="max-w-full max-h-[70vh] object-contain"
            />
          )}
        </div>
      </div>
    </div>
  );
}

function AddReceiptModal({
  onClose, onCreated,
}: {
  onClose: () => void; onCreated: () => void;
}) {
  const [form, setForm] = useState<Partial<ExpenseRow>>({
    Date: new Date().toISOString().slice(0, 10),
    Vendor: '',
    Amount: '',
    Currency: 'CAD',
    Category: 'Other',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!form.Vendor || !form.Amount) {
      setError('Vendor and amount are required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createExpense(form);
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-executive-card border border-executive-border rounded-xl max-w-md w-full p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-executive-text">Add Receipt</h2>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3">
          <FieldRow label="Date">
            <input
              type="date"
              value={String(form.Date || '')}
              onChange={e => setForm(f => ({ ...f, Date: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
          </FieldRow>
          <FieldRow label="Vendor *">
            <input
              type="text"
              value={String(form.Vendor || '')}
              onChange={e => setForm(f => ({ ...f, Vendor: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
          </FieldRow>
          <div className="grid grid-cols-2 gap-3">
            <FieldRow label="Amount *">
              <input
                type="number"
                step="0.01"
                value={String(form.Amount || '')}
                onChange={e => setForm(f => ({ ...f, Amount: e.target.value }))}
                className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
              />
            </FieldRow>
            <FieldRow label="Currency">
              <input
                type="text"
                value={String(form.Currency || 'CAD')}
                onChange={e => setForm(f => ({ ...f, Currency: e.target.value }))}
                className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
              />
            </FieldRow>
          </div>
          <FieldRow label="Category">
            <select
              value={String(form.Category || 'Other')}
              onChange={e => setForm(f => ({ ...f, Category: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            >
              {CATEGORY_OPTIONS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </FieldRow>
          <FieldRow label="Note (optional)">
            <input
              type="text"
              value={String(form.Email_Subject || '')}
              onChange={e => setForm(f => ({ ...f, Email_Subject: e.target.value }))}
              placeholder="What was this for?"
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none"
            />
          </FieldRow>
        </div>

        {error && (
          <div className="mt-3 text-xs text-rose-300 bg-rose-400/10 border border-rose-400/30 rounded-md px-3 py-2">{error}</div>
        )}

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-md border border-executive-border text-executive-muted hover:text-executive-text">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className="flex items-center gap-1.5 px-4 py-2 text-sm rounded-md bg-executive-accent text-white hover:opacity-90 disabled:opacity-50">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {saving ? 'Adding…' : 'Add Receipt'}
          </button>
        </div>
      </div>
    </div>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{label}</div>
      {children}
    </div>
  );
}

function EditCell({
  value, onChange, onSave, onCancel,
}: {
  value: string; onChange: (v: string) => void; onSave: () => void; onCancel: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1">
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') onSave();
          if (e.key === 'Escape') onCancel();
        }}
        autoFocus
        className="px-2 py-0.5 text-xs bg-executive-bg border border-executive-accent/40 rounded w-32 focus:outline-none"
      />
      <button onClick={onSave} className="text-emerald-400 hover:text-emerald-300">
        <Check size={12} />
      </button>
      <button onClick={onCancel} className="text-rose-400 hover:text-rose-300">
        <X size={12} />
      </button>
    </span>
  );
}

// ── Historical scan banner ────────────────────────────────

function HistoricalScanBanner({
  onRowsChanged, initialRowCount,
}: { onRowsChanged: () => void; initialRowCount: number }) {
  const [state, setState] = useState<null | {
    days: number; estMin: number; startedAt: number; baselineCount: number;
  }>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const activity = useActivity();

  const start = async (days: number) => {
    setError(null);
    try {
      const r = await scanHistoricalExpenses(days);
      activity.start('expenses');
      setState({
        days:          r.days,
        estMin:        r.estimated_minutes,
        startedAt:     Date.now(),
        baselineCount: initialRowCount,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // While scanning, auto-refresh the table every 15s for up to estMin + 5 min
  // (so the user sees new rows stream in without manual refresh).
  useEffect(() => {
    if (!state) return;
    const maxMs = (state.estMin + 5) * 60 * 1000;
    pollRef.current = window.setInterval(() => {
      if (Date.now() - state.startedAt > maxMs) {
        if (pollRef.current) window.clearInterval(pollRef.current);
        setState(null);
        return;
      }
      onRowsChanged();
    }, 15_000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [state, onRowsChanged]);

  if (state) {
    return (
      <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-amber-400/10 border border-amber-400/30">
        <div className="flex items-center gap-2 min-w-0">
          <Loader2 size={14} className="animate-spin text-amber-400 shrink-0" />
          <span className="text-xs text-amber-200">
            Scanning last <span className="font-semibold">{state.days} days</span> of email
            attachments — estimated ~{state.estMin} min total. Table refreshes automatically.
          </span>
        </div>
        <button
          onClick={() => setState(null)}
          className="text-xs text-amber-300 hover:text-amber-200 shrink-0"
        >
          Dismiss
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg bg-executive-card border border-executive-border">
      <div className="flex items-center gap-2 min-w-0">
        <History size={14} className="text-executive-muted shrink-0" />
        <span className="text-xs text-executive-muted">
          <span className="text-executive-text font-medium">Scan historical receipts</span>
          {' '}— pull receipts from older emails. New mail is already captured automatically by the monitor.
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={() => start(90)}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-text transition-colors"
        >
          <RefreshCw size={11} /> Last 3 months
        </button>
        <button
          onClick={() => start(180)}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-text transition-colors"
        >
          <RefreshCw size={11} /> Last 6 months
        </button>
      </div>
      {error && (
        <p className="text-xs text-rose-400 w-full">{error}</p>
      )}
    </div>
  );
}
