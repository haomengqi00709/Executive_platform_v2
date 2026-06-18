import { useEffect, useState } from 'react';
import { Loader2, Plus, Trash2, Rss, Search, Save, Check } from 'lucide-react';
import { getFeeds, saveFeeds, applyFeedPreset } from '../../lib/api';
import type { FeedsConfig, FeedPreset } from '../../lib/types';

const EMPTY: FeedsConfig = {
  enabled: false,
  rss: [],
  google_news: [],
  hackernews: { enabled: false, fetch_top_stories: 30, min_score: 50 },
  reddit: { enabled: false, subreddits: [] },
};

export default function FeedsTab() {
  const [cfg, setCfg] = useState<FeedsConfig>(EMPTY);
  const [presets, setPresets] = useState<Record<string, FeedPreset>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await getFeeds();
      setCfg({ ...EMPTY, ...r.feeds });
      setPresets(r.presets || {});
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const patch = (p: Partial<FeedsConfig>) => { setCfg(c => ({ ...c, ...p })); setSaved(false); };

  const save = async () => {
    setSaving(true);
    try { await saveFeeds(cfg); setSaved(true); setTimeout(() => setSaved(false), 2000); }
    finally { setSaving(false); }
  };

  const usePreset = async (key: string) => {
    setSaving(true);
    try { const updated = await applyFeedPreset(key); setCfg({ ...EMPTY, ...updated }); }
    finally { setSaving(false); }
  };

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="animate-spin text-executive-muted" /></div>;
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-executive-text">Market Intelligence Feeds</h3>
          <p className="text-xs text-executive-muted mt-0.5 max-w-xl">
            Public sources merged into your market brief and scored for relevance to your business.
            All credential-free — RSS, Google News topic searches, Hacker News, Reddit. No accounts or passwords needed.
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-executive-text flex-shrink-0">
          <input type="checkbox" checked={cfg.enabled} onChange={e => patch({ enabled: e.target.checked })} />
          Feeds enabled
        </label>
      </div>

      {/* Presets */}
      <Section title="Quick add — industry presets">
        <div className="flex flex-wrap gap-2">
          {Object.entries(presets).map(([key, p]) => (
            <button
              key={key}
              onClick={() => usePreset(key)}
              disabled={saving}
              title={p.description}
              className="text-xs px-3 py-1.5 rounded-lg border border-executive-border hover:bg-executive-border/30 text-executive-text disabled:opacity-50"
            >
              <Plus size={11} className="inline mr-1" />{p.label}
            </button>
          ))}
          {Object.keys(presets).length === 0 && <p className="text-xs text-executive-muted">No presets configured.</p>}
        </div>
      </Section>

      {/* RSS feeds */}
      <Section title="RSS / Atom feeds" icon={<Rss size={13} />}>
        {cfg.rss.map((f, i) => (
          <Row key={i} onRemove={() => patch({ rss: cfg.rss.filter((_, j) => j !== i) })}>
            <input
              className="bg-transparent text-xs text-executive-text border-b border-executive-border focus:outline-none w-40"
              value={f.name} placeholder="name"
              onChange={e => { const rss = [...cfg.rss]; rss[i] = { ...f, name: e.target.value }; patch({ rss }); }}
            />
            <input
              className="bg-transparent text-xs text-executive-muted border-b border-executive-border focus:outline-none flex-1 min-w-0"
              value={f.url} placeholder="https://…/feed.xml"
              onChange={e => { const rss = [...cfg.rss]; rss[i] = { ...f, url: e.target.value }; patch({ rss }); }}
            />
            <input type="checkbox" checked={f.enabled !== false}
              onChange={e => { const rss = [...cfg.rss]; rss[i] = { ...f, enabled: e.target.checked }; patch({ rss }); }} />
          </Row>
        ))}
        <AddBtn onClick={() => patch({ rss: [...cfg.rss, { name: '', url: '', enabled: true }] })}>Add RSS feed</AddBtn>
      </Section>

      {/* Google News queries */}
      <Section title="Google News topic searches" icon={<Search size={13} />}
        hint="Turn any topic into a feed — e.g. “industrial water pump tender Canada”.">
        {cfg.google_news.map((f, i) => (
          <Row key={i} onRemove={() => patch({ google_news: cfg.google_news.filter((_, j) => j !== i) })}>
            <input
              className="bg-transparent text-xs text-executive-text border-b border-executive-border focus:outline-none w-40"
              value={f.name} placeholder="label"
              onChange={e => { const g = [...cfg.google_news]; g[i] = { ...f, name: e.target.value }; patch({ google_news: g }); }}
            />
            <input
              className="bg-transparent text-xs text-executive-muted border-b border-executive-border focus:outline-none flex-1 min-w-0"
              value={f.query} placeholder="search query"
              onChange={e => { const g = [...cfg.google_news]; g[i] = { ...f, query: e.target.value }; patch({ google_news: g }); }}
            />
            <input type="checkbox" checked={f.enabled !== false}
              onChange={e => { const g = [...cfg.google_news]; g[i] = { ...f, enabled: e.target.checked }; patch({ google_news: g }); }} />
          </Row>
        ))}
        <AddBtn onClick={() => patch({ google_news: [...cfg.google_news, { name: '', query: '', enabled: true }] })}>Add topic search</AddBtn>
      </Section>

      {/* Hacker News + Reddit toggles */}
      <Section title="Community sources">
        <label className="flex items-center gap-2 text-xs text-executive-text">
          <input type="checkbox" checked={cfg.hackernews.enabled}
            onChange={e => patch({ hackernews: { ...cfg.hackernews, enabled: e.target.checked } })} />
          Hacker News (AI / tech pulse)
        </label>
        <label className="flex items-center gap-2 text-xs text-executive-text mt-2">
          <input type="checkbox" checked={cfg.reddit.enabled}
            onChange={e => patch({ reddit: { ...cfg.reddit, enabled: e.target.checked } })} />
          Reddit subreddits
        </label>
        {cfg.reddit.enabled && (
          <div className="mt-2 space-y-1.5 pl-5">
            {cfg.reddit.subreddits.map((s, i) => (
              <Row key={i} onRemove={() => patch({ reddit: { ...cfg.reddit, subreddits: cfg.reddit.subreddits.filter((_, j) => j !== i) } })}>
                <span className="text-xs text-executive-muted">r/</span>
                <input
                  className="bg-transparent text-xs text-executive-text border-b border-executive-border focus:outline-none w-40"
                  value={s.subreddit} placeholder="subreddit"
                  onChange={e => { const subs = [...cfg.reddit.subreddits]; subs[i] = { ...s, subreddit: e.target.value }; patch({ reddit: { ...cfg.reddit, subreddits: subs } }); }}
                />
              </Row>
            ))}
            <AddBtn onClick={() => patch({ reddit: { ...cfg.reddit, subreddits: [...cfg.reddit.subreddits, { subreddit: '', enabled: true }] } })}>Add subreddit</AddBtn>
          </div>
        )}
      </Section>

      <div className="flex justify-end">
        <button onClick={save} disabled={saving}
          className="flex items-center gap-1.5 text-xs px-4 py-2 rounded-lg bg-executive-accent/10 hover:bg-executive-accent/20 border border-executive-accent/30 text-executive-accent disabled:opacity-50">
          {saving ? <Loader2 size={13} className="animate-spin" /> : saved ? <Check size={13} /> : <Save size={13} />}
          {saved ? 'Saved' : 'Save feeds'}
        </button>
      </div>
    </div>
  );
}

function Section({ title, icon, hint, children }: { title: string; icon?: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <div className="bg-executive-card border border-executive-border rounded-xl p-4">
      <div className="flex items-center gap-1.5 mb-2">
        {icon}<h4 className="text-xs font-semibold text-executive-text uppercase tracking-wide">{title}</h4>
      </div>
      {hint && <p className="text-[11px] text-executive-muted mb-2">{hint}</p>}
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Row({ children, onRemove }: { children: React.ReactNode; onRemove: () => void }) {
  return (
    <div className="flex items-center gap-2">
      {children}
      <button onClick={onRemove} className="text-executive-muted hover:text-rose-400 flex-shrink-0"><Trash2 size={12} /></button>
    </div>
  );
}

function AddBtn({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className="text-xs text-executive-accent hover:underline flex items-center gap-1 mt-1">
      <Plus size={11} />{children}
    </button>
  );
}
