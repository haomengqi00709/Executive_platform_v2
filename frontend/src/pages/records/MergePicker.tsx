import { useEffect, useMemo, useState } from 'react';
import { Search, X, Loader2, AlertCircle } from 'lucide-react';
import { mergeContactsDirect, mergeProjectsDirect } from '../../lib/api';
import type { CrmContact, ProjectRecord } from '../../lib/api';

type Kind = 'contact' | 'project';

interface ContactPickerProps {
  kind: 'contact';
  keepRecord: CrmContact;
  candidates: CrmContact[];
  onClose: () => void;
  onMerged: () => void;
}

interface ProjectPickerProps {
  kind: 'project';
  keepRecord: ProjectRecord;
  candidates: ProjectRecord[];
  onClose: () => void;
  onMerged: () => void;
}

type Props = ContactPickerProps | ProjectPickerProps;

export default function MergePicker(props: Props) {
  const { kind, keepRecord, candidates, onClose, onMerged } = props;
  const [search, setSearch]   = useState('');
  const [merging, setMerging] = useState<string | null>(null);  // id of the record currently merging
  const [error, setError]     = useState('');

  // Close on Esc
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return candidates;
    if (kind === 'contact') {
      return (candidates as CrmContact[]).filter(c =>
        (c.email || '').toLowerCase().includes(q) ||
        (c.name || '').toLowerCase().includes(q) ||
        (c.company || '').toLowerCase().includes(q) ||
        (c.role || '').toLowerCase().includes(q)
      );
    }
    return (candidates as ProjectRecord[]).filter(p =>
      (p.name || '').toLowerCase().includes(q) ||
      (p.summary || '').toLowerCase().includes(q) ||
      (p.category || '').toLowerCase().includes(q)
    );
  }, [candidates, search, kind]);

  const handlePick = async (mergeIdent: string) => {
    setMerging(mergeIdent); setError('');
    try {
      if (kind === 'contact') {
        await mergeContactsDirect((keepRecord as CrmContact).email, mergeIdent);
      } else {
        await mergeProjectsDirect((keepRecord as ProjectRecord).id, mergeIdent);
      }
      onMerged();
      onClose();
    } catch (e: any) {
      setError(e?.message || 'Merge failed');
      setMerging(null);
    }
  };

  const keepLabel = kind === 'contact'
    ? ((keepRecord as CrmContact).name || (keepRecord as CrmContact).email)
    : (keepRecord as ProjectRecord).name;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-executive-card border border-executive-border rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-4 border-b border-executive-border flex items-start justify-between">
          <div>
            <h3 className="text-base font-semibold">
              Merge into <span className="text-executive-accent">{keepLabel}</span>
            </h3>
            <p className="text-xs text-executive-muted mt-1">
              Pick the {kind === 'contact' ? 'duplicate contact' : 'duplicate project'} to merge in.
              The above record is kept; the one you pick will be deleted (fields combined first).
            </p>
          </div>
          <button onClick={onClose} className="text-executive-muted hover:text-executive-text">
            <X size={16} />
          </button>
        </div>

        {/* Search */}
        <div className="px-5 py-3 border-b border-executive-border">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-executive-muted" />
            <input
              autoFocus
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={kind === 'contact' ? 'Search by email, name, company...' : 'Search by project name, summary...'}
              className="w-full pl-9 pr-3 py-2 text-sm bg-executive-bg border border-executive-border rounded-md focus:outline-none focus:border-executive-accent/60"
            />
          </div>
        </div>

        {error && (
          <div className="mx-5 mt-3 flex items-center gap-2 p-2 bg-rose-500/8 border border-rose-500/20 rounded-md text-rose-500 text-xs font-mono">
            <AlertCircle size={12} /> {error}
          </div>
        )}

        {/* List */}
        <div className="flex-1 overflow-auto px-2 py-2">
          {filtered.length === 0 ? (
            <p className="text-center text-sm text-executive-muted py-8">
              {search ? 'No records match your search.' : 'No other records to merge into.'}
            </p>
          ) : (
            <div className="divide-y divide-executive-border/40">
              {filtered.map(r => {
                const id     = kind === 'contact' ? (r as CrmContact).email : (r as ProjectRecord).id;
                const isLoad = merging === id;
                const disabled = !!merging;
                return (
                  <button
                    key={id}
                    onClick={() => !disabled && handlePick(id)}
                    disabled={disabled}
                    className="w-full text-left px-3 py-2.5 rounded-md hover:bg-executive-border/30 disabled:opacity-40 transition-colors"
                  >
                    {kind === 'contact' ? (
                      <ContactRow contact={r as CrmContact} loading={isLoad} />
                    ) : (
                      <ProjectRow project={r as ProjectRecord} loading={isLoad} />
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ContactRow({ contact, loading }: { contact: CrmContact; loading: boolean }) {
  const sub: string[] = [];
  if (contact.company) sub.push(contact.company);
  if (contact.role)    sub.push(contact.role);
  if (contact.status)  sub.push(contact.status);
  if (contact.thread_count) sub.push(`${contact.thread_count} threads`);
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{contact.name || contact.email}</p>
        <p className="text-xs font-mono text-executive-muted truncate">{contact.email}</p>
        {sub.length > 0 && <p className="text-xs text-executive-muted mt-0.5 truncate">{sub.join(' · ')}</p>}
      </div>
      {loading && <Loader2 size={14} className="animate-spin text-executive-accent shrink-0" />}
    </div>
  );
}

function ProjectRow({ project, loading }: { project: ProjectRecord; loading: boolean }) {
  const sub: string[] = [];
  if (project.status)       sub.push(project.status);
  if (project.category)     sub.push(project.category);
  if (project.thread_count) sub.push(`${project.thread_count} threads`);
  if (project.last_activity) sub.push(`last: ${project.last_activity}`);
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{project.name}</p>
        {sub.length > 0 && <p className="text-xs text-executive-muted mt-0.5 truncate">{sub.join(' · ')}</p>}
        {project.summary && <p className="text-xs text-executive-muted mt-0.5 line-clamp-1">{project.summary}</p>}
      </div>
      {loading && <Loader2 size={14} className="animate-spin text-executive-accent shrink-0" />}
    </div>
  );
}

// Re-export the kind type for consumers
export type { Kind };
