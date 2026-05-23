import { useEffect, useMemo, useState } from 'react';
import {
  Loader2, Search, ChevronDown, ChevronRight, Plus, EyeOff, Save, X, Star,
  Phone, Linkedin, Mail, Building2, Briefcase,
} from 'lucide-react';
import { getCrm, patchCrmContact, createCrmContact, relativeTime } from '../../lib/api';
import type { CrmContact } from '../../lib/api';

const STATUS_OPTIONS = ['client', 'prospect', 'partner', 'vendor', 'other'];
const PRIORITY_OPTIONS = ['high', 'medium', 'low', 'ignore'];

const STATUS_COLOR: Record<string, string> = {
  client:   'bg-emerald-400/15 text-emerald-300',
  prospect: 'bg-sky-400/15 text-sky-300',
  partner:  'bg-violet-400/15 text-violet-300',
  vendor:   'bg-amber-400/15 text-amber-300',
  other:    'bg-executive-border/40 text-executive-muted',
};

export default function CrmTab() {
  const [contacts, setContacts] = useState<CrmContact[]>([]);
  const [lastScan, setLastScan] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showIgnored, setShowIgnored] = useState(false);
  const [expandedEmail, setExpandedEmail] = useState<string | null>(null);
  const [savingEmail, setSavingEmail] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = () => {
    setLoading(true);
    getCrm()
      .then(d => {
        setContacts(d.contacts || []);
        setLastScan(d.last_scan);
      })
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const update = async (email: string, patch: Partial<CrmContact>) => {
    setSavingEmail(email);
    try {
      const updated = await patchCrmContact(email, patch);
      setContacts(cs => cs.map(c => c.email === email ? { ...c, ...updated } : c));
    } finally {
      setSavingEmail(null);
    }
  };

  const visible = useMemo(() => {
    return contacts.filter(c => {
      if (!showIgnored && c.ignore) return false;
      if (statusFilter !== 'all' && (c.status || 'other') !== statusFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          (c.email || '').toLowerCase().includes(q) ||
          (c.name || '').toLowerCase().includes(q) ||
          (c.company || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [contacts, search, statusFilter, showIgnored]);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3 justify-between">
        <div className="text-xs text-executive-muted">
          {loading ? 'Loading…' : (
            <>{contacts.length} contacts · last scan {relativeTime(lastScan ?? undefined)}</>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-executive-muted" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search name / email / company…"
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
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-executive-accent text-white hover:opacity-90"
          >
            <Plus size={12} /> New Contact
          </button>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center py-12 text-executive-muted">
          <Loader2 size={20} className="animate-spin" />
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center text-sm text-executive-muted py-12">
          No contacts match the filter.
        </div>
      ) : (
        <div className="bg-executive-card border border-executive-border rounded-xl overflow-hidden">
          {visible.map(c => (
            <div key={c.email} className={`border-b border-executive-border/60 last:border-b-0 ${c.ignore ? 'opacity-50' : ''}`}>
              {/* Row */}
              <button
                onClick={() => setExpandedEmail(expandedEmail === c.email ? null : c.email)}
                className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-executive-border/10 text-left"
              >
                <span className="text-executive-muted shrink-0">
                  {expandedEmail === c.email ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
                <div className="flex-1 min-w-0 grid grid-cols-12 gap-3 items-center">
                  <div className="col-span-4 min-w-0">
                    <div className="font-medium text-executive-text text-sm truncate">{c.name || '—'}</div>
                    <div className="text-xs text-executive-muted truncate">
                      {c.email}{c.company && <> · {c.company}</>}
                    </div>
                  </div>
                  <div className="col-span-2">
                    <span className={`text-xs px-2 py-1 rounded-md ${STATUS_COLOR[c.status || 'other'] ?? STATUS_COLOR.other}`}>
                      {c.status || 'other'}
                    </span>
                  </div>
                  <div className="col-span-2 text-xs text-executive-muted">
                    {c.priority || 'medium'} priority
                  </div>
                  <div className="col-span-2 text-xs text-executive-muted text-right tabular-nums">
                    {c.thread_count ?? 0} threads
                  </div>
                  <div className="col-span-2 text-xs text-executive-muted text-right whitespace-nowrap">
                    {c.last_contact || '—'}
                  </div>
                </div>
              </button>

              {expandedEmail === c.email && (
                <ContactDetail
                  contact={c}
                  saving={savingEmail === c.email}
                  onSave={patch => update(c.email, patch)}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {creating && (
        <NewContactModal
          onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); refresh(); }}
        />
      )}
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function ContactDetail({
  contact, saving, onSave,
}: {
  contact: CrmContact;
  saving: boolean;
  onSave: (patch: Partial<CrmContact>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<CrmContact>(contact);

  useEffect(() => { setDraft(contact); }, [contact]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(contact);

  const handleSave = async () => {
    const patch: Partial<CrmContact> = {};
    (Object.keys(draft) as (keyof CrmContact)[]).forEach(k => {
      if (draft[k] !== contact[k]) {
        // @ts-expect-error — generic assignment is fine
        patch[k] = draft[k];
      }
    });
    if (Object.keys(patch).length > 0) await onSave(patch);
  };

  return (
    <div className="bg-executive-bg/40 px-6 py-4 border-t border-executive-border/40">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <Field label="Name" icon={<Star size={11} />} value={draft.name || ''} onChange={v => setDraft(d => ({ ...d, name: v }))} />
        <Field label="Email" icon={<Mail size={11} />} value={draft.email} onChange={() => undefined} disabled />
        <Field label="Company" icon={<Building2 size={11} />} value={draft.company || ''} onChange={v => setDraft(d => ({ ...d, company: v }))} />
        <Field label="Role" icon={<Briefcase size={11} />} value={draft.role || ''} onChange={v => setDraft(d => ({ ...d, role: v }))} />
        <Field label="Phone" icon={<Phone size={11} />} value={draft.phone || ''} onChange={v => setDraft(d => ({ ...d, phone: v }))} />
        <Field label="LinkedIn" icon={<Linkedin size={11} />} value={draft.linkedin || ''} onChange={v => setDraft(d => ({ ...d, linkedin: v }))} />
        <div>
          <Label>Status</Label>
          <select
            value={draft.status || 'other'}
            onChange={e => setDraft(d => ({ ...d, status: e.target.value }))}
            className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md"
          >
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <Label>Priority</Label>
          <select
            value={draft.priority || 'medium'}
            onChange={e => setDraft(d => ({ ...d, priority: e.target.value }))}
            className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md"
          >
            {PRIORITY_OPTIONS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
      </div>

      <div className="space-y-3">
        <div>
          <Label>Summary</Label>
          <textarea
            value={draft.summary || ''}
            onChange={e => setDraft(d => ({ ...d, summary: e.target.value }))}
            rows={3}
            className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
            placeholder="What is this relationship about? Recent topics?"
          />
        </div>
        <div>
          <Label>Writing Style <span className="text-executive-muted/60 normal-case font-normal">(extracted from your replies to this person)</span></Label>
          <textarea
            value={draft.writing_style || ''}
            onChange={e => setDraft(d => ({ ...d, writing_style: e.target.value }))}
            rows={3}
            className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
            placeholder="e.g. greeting: 'Hi Sarah,'; sign-off: 'Cheers, Daniel'; tone: casual but direct."
          />
        </div>
        <div>
          <Label>Notes</Label>
          <textarea
            value={draft.notes || ''}
            onChange={e => setDraft(d => ({ ...d, notes: e.target.value }))}
            rows={2}
            className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 resize-y"
            placeholder="Personal notes (only you see these)."
          />
        </div>
      </div>

      <div className="flex items-center justify-between mt-4 pt-3 border-t border-executive-border/40">
        <button
          onClick={() => onSave({ ignore: !contact.ignore })}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md text-executive-muted hover:bg-executive-border/40 transition-colors"
        >
          <EyeOff size={12} />
          {contact.ignore ? 'Un-ignore' : 'Ignore from all sections'}
        </button>
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

function NewContactModal({
  onClose, onCreated,
}: {
  onClose: () => void; onCreated: () => void;
}) {
  const [form, setForm] = useState<Partial<CrmContact>>({
    email: '', name: '', company: '', role: '', status: 'other', priority: 'medium',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!form.email || !form.email.includes('@')) {
      setError('Valid email is required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createCrmContact({ email: form.email, ...form });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={e => e.stopPropagation()} className="bg-executive-card border border-executive-border rounded-xl max-w-lg w-full p-6 shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-executive-text">New Contact</h2>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text">
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Email *" value={form.email || ''} onChange={v => setForm(f => ({ ...f, email: v }))} />
          <Field label="Name" value={form.name || ''} onChange={v => setForm(f => ({ ...f, name: v }))} />
          <Field label="Company" value={form.company || ''} onChange={v => setForm(f => ({ ...f, company: v }))} />
          <Field label="Role" value={form.role || ''} onChange={v => setForm(f => ({ ...f, role: v }))} />
          <Field label="Phone" value={form.phone || ''} onChange={v => setForm(f => ({ ...f, phone: v }))} />
          <Field label="LinkedIn" value={form.linkedin || ''} onChange={v => setForm(f => ({ ...f, linkedin: v }))} />
          <div>
            <Label>Status</Label>
            <select
              value={form.status || 'other'}
              onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md"
            >
              {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <Label>Priority</Label>
            <select
              value={form.priority || 'medium'}
              onChange={e => setForm(f => ({ ...f, priority: e.target.value }))}
              className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md"
            >
              {PRIORITY_OPTIONS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
        </div>

        <div className="mt-3">
          <Label>Summary</Label>
          <textarea
            value={form.summary || ''}
            onChange={e => setForm(f => ({ ...f, summary: e.target.value }))}
            rows={2}
            className="w-full px-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none resize-y"
          />
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
            {saving ? 'Adding…' : 'Add Contact'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium uppercase tracking-wider text-executive-muted mb-1">{children}</div>;
}

function Field({
  label, value, onChange, icon, disabled,
}: {
  label: string; value: string; onChange: (v: string) => void; icon?: React.ReactNode; disabled?: boolean;
}) {
  return (
    <div>
      <Label>
        <span className="inline-flex items-center gap-1">
          {icon}
          {label}
        </span>
      </Label>
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
        className="w-full px-2 py-1.5 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60 disabled:opacity-50"
      />
    </div>
  );
}
