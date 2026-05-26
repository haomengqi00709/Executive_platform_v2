import { useEffect, useState } from 'react';
import { Save, RefreshCw, Loader2, AlertCircle, CheckCircle2, FileText, Building2, User } from 'lucide-react';
import { getProfile, saveBusinessProfile, saveMarketSegments, savePersonalProfile, regenerateProfile } from '../lib/api';

type Tab = 'personal' | 'business' | 'segments';

export default function ProfilePage() {
  const [tab, setTab] = useState<Tab>('business');
  const [personal, setPersonal] = useState('');
  const [business, setBusiness] = useState('');
  const [segments, setSegments] = useState('');
  const [origPersonal, setOrigPersonal] = useState('');
  const [origBusiness, setOrigBusiness] = useState('');
  const [origSegments, setOrigSegments] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getProfile()
      .then(p => {
        setPersonal(p.personal_profile ?? '');
        setBusiness(p.business_profile ?? '');
        setSegments(p.market_segments ?? '');
        setOrigPersonal(p.personal_profile ?? '');
        setOrigBusiness(p.business_profile ?? '');
        setOrigSegments(p.market_segments ?? '');
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setError(null);
    setSuccess(null);
    setSaving(true);
    try {
      if (tab === 'personal') {
        await savePersonalProfile(personal);
        setOrigPersonal(personal);
        setSuccess('Personal profile saved.');
      } else if (tab === 'business') {
        await saveBusinessProfile(business);
        setOrigBusiness(business);
        setSuccess('Business profile saved.');
      } else {
        await saveMarketSegments(segments);
        setOrigSegments(segments);
        setSuccess('Market segments saved.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    if (!confirm('Regenerate profile from your sent emails, CRM, and projects? This will overwrite current content.')) return;
    setError(null);
    setSuccess(null);
    setRegenerating(true);
    try {
      await regenerateProfile();
      setSuccess('Regeneration started. Refresh this page in ~1 minute to see the new draft.');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRegenerating(false);
    }
  };

  const dirty =
    tab === 'personal' ? personal !== origPersonal
    : tab === 'business' ? business !== origBusiness
    : segments !== origSegments;

  const currentText = tab === 'personal' ? personal : tab === 'business' ? business : segments;
  const setCurrentText = (v: string) => {
    if (tab === 'personal') setPersonal(v);
    else if (tab === 'business') setBusiness(v);
    else setSegments(v);
  };
  const fileName =
    tab === 'personal' ? 'personal_profile.md'
    : tab === 'business' ? 'business_profile.md'
    : 'market_segments.md';
  const titleLabel =
    tab === 'personal' ? 'Personal Profile'
    : tab === 'business' ? 'Business Profile'
    : 'Market Segments';

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-executive-text">Profile</h1>
        <p className="text-sm text-executive-muted mt-1">
          These documents are injected into every AI prompt so the system understands your company.
          Be specific and concrete.
        </p>
      </header>

      {/* Tabs */}
      <div className="flex gap-1 bg-executive-card border border-executive-border rounded-lg p-1 w-fit">
        <TabBtn active={tab === 'personal'} onClick={() => setTab('personal')} icon={<User size={14} />}>
          Personal Profile
        </TabBtn>
        <TabBtn active={tab === 'business'} onClick={() => setTab('business')} icon={<Building2 size={14} />}>
          Business Profile
        </TabBtn>
        <TabBtn active={tab === 'segments'} onClick={() => setTab('segments')} icon={<FileText size={14} />}>
          Market Segments
        </TabBtn>
      </div>

      {/* Editor */}
      <div className="bg-executive-card border border-executive-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-executive-border flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-executive-text">{fileName}</h2>
            <p className="text-xs text-executive-muted mt-0.5">
              Markdown — preview rendering happens when sent to AI.
            </p>
          </div>
          {dirty && (
            <span className="text-xs text-amber-400 italic">Unsaved changes</span>
          )}
        </div>

        {loading ? (
          <div className="h-80 flex items-center justify-center">
            <Loader2 size={20} className="animate-spin text-executive-muted" />
          </div>
        ) : (
          <textarea
            value={currentText}
            onChange={e => setCurrentText(e.target.value)}
            spellCheck={false}
            className="w-full px-4 py-3 bg-executive-bg text-sm font-mono text-executive-text resize-y min-h-[24rem] focus:outline-none"
            placeholder={`# ${titleLabel}\n\n…`}
          />
        )}
      </div>

      {/* Status messages */}
      {error && (
        <div className="flex items-start gap-2 px-3 py-2 bg-rose-400/10 border border-rose-400/30 rounded-lg text-xs text-rose-300">
          <AlertCircle size={14} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-start gap-2 px-3 py-2 bg-emerald-400/10 border border-emerald-400/30 rounded-lg text-xs text-emerald-300">
          <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={handleRegenerate}
          disabled={regenerating}
          className="flex items-center gap-2 px-3 py-2 text-xs rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-muted hover:text-executive-text transition-colors disabled:opacity-50"
        >
          {regenerating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {regenerating ? 'Regenerating…' : 'Regenerate from emails'}
        </button>

        <button
          onClick={handleSave}
          disabled={saving || !dirty}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-executive-accent text-white hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  );
}

function TabBtn({
  active, onClick, icon, children,
}: {
  active: boolean; onClick: () => void; icon: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
        active
          ? 'bg-executive-accent/10 text-executive-accent'
          : 'text-executive-muted hover:text-executive-text'
      }`}
    >
      {icon}
      {children}
    </button>
  );
}
