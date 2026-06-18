// Shared TypeScript types across the frontend.

export type SectionStatus = 'fresh' | 'stale' | 'not_run' | 'running' | 'error';

export interface SectionResult {
  id: string;
  status: SectionStatus;
  last_run?: string;
  items?: unknown[];
  count?: number;
  empty?: boolean;
  error?: string;
  // ai_summary specific
  briefing?: string;
  events?: unknown[];
  top_emails?: unknown[];
  action_items?: unknown[];
  // dated sections
  date?: string;
  week_of?: string;
  // business_insights specific
  narrative?: string;
  stats?: Record<string, unknown>;
  // generic extras
  [key: string]: unknown;
}

// ──────────────────────────────────────────────────────────
// Item types (per section)

export interface ReplyNeededItem {
  email_id: string;
  subject: string;
  from_email: string;
  from_name: string;
  received: string;
  preview?: string;
  priority: 'high' | 'medium' | 'low';
  reason?: string;
  reply_tone?: string;
  suggested_opening?: string;
  contact?: { name?: string; company?: string; role?: string; status?: string };
  projects?: unknown[];
}

export interface FollowupItem {
  email_id: string;
  subject: string;
  to_email: string;
  to_name: string;
  sent: string;
  preview?: string;
  days_waiting?: number;
  urgency?: 'high' | 'medium' | 'low';
  reason?: string;
}

export interface CommitmentItem {
  id: string;
  type: 'my_commitment' | 'their_commitment';
  description: string;
  due_date: string | null;
  due_date_confidence?: string;
  contact_email?: string;
  contact_name?: string;
  email_id?: string;
  subject?: string;
  received?: string;
  priority?: 'high' | 'medium' | 'low';
  state?: 'done' | 'snoozed' | string;
  overdue?: boolean;
  source?: string;
}

export interface MeetingTodayItem {
  id: string;
  subject: string;
  start: string;
  end: string;
  start_time?: string;
  end_time?: string;
  is_all_day?: boolean;
  location?: string;
  attendees: string[];
  attendee_count?: number;
  body_preview?: string;
}

export interface RecentMeetingItem {
  meeting_id: string;
  title: string;
  date: string;
  attendees: string[];
  summary?: string;
  decisions?: string[];
  key_topics?: string[];
}

export interface ActionItem {
  owner: string;
  action: string;
  due_date: string | null;
  meeting_id: string;
  meeting_title: string;
  meeting_date: string;
  project_id?: string | null;
}

export interface ProjectItem {
  id: string;
  project_id: string;
  name: string;
  category: string;
  status: 'ongoing' | 'needs_attention' | 'paused' | 'early_stage' | 'completed' | string;
  momentum: 'accelerating' | 'steady' | 'slowing' | 'stalled' | string;
  summary: string;
  next_action?: string;
  last_activity: string;
  deadline?: string | null;
  participants?: string[];
  participant_count?: number;
  thread_count?: number;
  priority?: 'high' | 'medium' | 'low';
}

export interface RelationshipItem {
  id: string;
  contact_email: string;
  contact_name: string;
  company?: string;
  status?: string;
  health: 'at_risk' | 'cooling' | 'stalled' | 'new' | string;
  priority: 'high' | 'medium' | 'low';
  metrics: {
    emails_in_30d: number;
    emails_in_prev_30d: number;
    emails_out_30d?: number;
    emails_out_prev_30d?: number;
    last_inbound?: string | null;
    last_outbound?: string | null;
    days_since_inbound?: number | null;
    days_since_outbound?: number | null;
    trend_pct?: number | null;
    awaiting_my_reply?: boolean;
  };
  related_projects?: { id: string; name: string; status: string; momentum?: string }[];
  reminder?: string;
  suggested_action?: string;
}

export interface IntelReference {
  title: string;
  url: string;
}

export interface IntelItem {
  id: string;
  headline: string;
  summary: string;
  signal_type: string;
  source?: string;
  source_url?: string;
  published_date?: string;
  relevance?: string;
  priority: 'high' | 'medium' | 'low';
  company?: string;
  person?: string;
  // Added by the scoring + enrichment passes (optional; older results lack them)
  ai_score?: number;
  score_reason?: string;
  background?: string;
  community_view?: string;
  references?: IntelReference[];
}

export interface FeedRss { name: string; url: string; enabled?: boolean; category?: string; }
export interface FeedGoogleNews { name: string; query: string; enabled?: boolean; category?: string; }
export interface FeedsConfig {
  enabled: boolean;
  rss: FeedRss[];
  google_news: FeedGoogleNews[];
  hackernews: { enabled: boolean; fetch_top_stories?: number; min_score?: number };
  reddit: { enabled: boolean; subreddits: { subreddit: string; enabled?: boolean; sort?: string; fetch_limit?: number; min_score?: number }[] };
}
export interface FeedPreset {
  label: string;
  description?: string;
  rss?: FeedRss[];
  google_news?: FeedGoogleNews[];
}
export interface FeedsResponse { feeds: FeedsConfig; presets: Record<string, FeedPreset>; }

export interface ExpenseItem {
  vendor: string;
  date: string;
  amount: number | string;
  currency: string;
  gst_hst?: number | string | null;
  net_amount?: number | string | null;
  category: string;
  confidence?: string;
  attachment?: string;
  email_subject?: string;
  from?: string;
  processed_at?: string;
}

export interface BusinessInsightHeadline {
  id: string;
  category: 'pipeline' | 'engagement' | 'execution' | 'intel' | string;
  type: string;
  title: string;
  detail?: string;
  priority: 'high' | 'medium' | 'low';
  evidence?: string[];
}

export interface YesterdayRecapItem {
  type: 'inbound_email' | 'outbound_email' | 'meeting' | 'commitment' | string;
  subject?: string;
  from?: string;
  to?: string;
  time?: string;
  start?: string;
  end?: string;
  attendees?: string[];
  description?: string;
  commit_kind?: string;
  contact_name?: string;
  due_date?: string;
  priority?: string;
}

// ──────────────────────────────────────────────────────────
// Tools

export interface OutreachDraft {
  to: string;
  name: string;
  company: string;
  subject: string;
  web_link: string;
  source_file: string;
  sent?: boolean;          // bulk mode: true when actually sent (not just drafted)
}

export interface OutreachSkippedContact {
  reason: string;       // 'no_email' | 'draft_gen_failed' | ...
  file?: string;
  contact: {
    name?: string;
    email?: string;
    company?: string;
    role?: string;
    notes?: string;
  };
}

export interface OutreachLastRun {
  status?: 'fresh' | 'not_run' | 'error' | 'running';
  last_run?: string;        // ISO datetime — what the backend writes
  ran_at?: string;          // legacy alias (older runs may still have this)
  folder?: string;
  context_note?: string;
  mode?: string;            // 'crm' | 'bulk' | undefined (folder)
  send?: boolean;           // bulk mode: real send vs draft-only
  personalize?: boolean;    // bulk mode: AI per-contact vs template
  total?: number;           // bulk mode: recipients in this batch
  error?: string;
  drafts_created?: OutreachDraft[];
  contacts_skipped?: OutreachSkippedContact[];
  files_processed?: { file: string; type: string; contacts_found: number }[];
  errors?: { contact?: string; file?: string; error: string }[];
  summary?: {
    drafts: number;
    files: number;
    skipped: number;
    errors: number;
    sent?: number;          // bulk mode: count actually sent
  };
}

// ──────────────────────────────────────────────────────────
// Profile

export interface ProfileText {
  business_profile: string;
  market_segments: string;
}

/** A single phase in the onboarding init chain. reveal_data is attached
 *  by the backend when status flips to 'done' — the wizard's Step 5 uses
 *  it to render the animated reveal card. */
export interface InitStep {
  key: string;       // 'crm' | 'projects' | 'companies' | 'personal_profile' | 'business_profile' | 'market_segments'
  label: string;
  status: 'pending' | 'in_progress' | 'done' | 'failed';
  reveal_data?: {
    count?: number;          // for crm / projects / companies
    samples?: string[];      // 0-3 display names
    preview?: string;        // for the 3 profile docs (trimmed to ~240 chars)
  };
}

export interface ProfileStatus {
  stage: 'pending' | 'awaiting_confirmation' | 'generating' | 'draft_ready' | 'user_confirmed';
  last_update: string | null;
  steps: InitStep[];
  current_message: string;
}

export interface AuthUser {
  username?: string;
  user_id?: string;
}
