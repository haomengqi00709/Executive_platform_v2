// Typed API wrappers for the FastAPI backend.

import type { SectionResult, OutreachLastRun, ProfileStatus } from './types';

const BASE = ''; // proxied via Vite to :8000

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + url, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!r.ok) {
    throw new Error(`${r.status} ${r.statusText} — ${url}`);
  }
  return r.json() as Promise<T>;
}

// ── Sections ──────────────────────────────────────────────

export function getSection(sectionId: string): Promise<SectionResult> {
  return fetchJson<SectionResult>(`/api/sections/${sectionId}`);
}

export function runSection(sectionId: string): Promise<{ ok: boolean }> {
  return fetchJson<{ ok: boolean }>(`/api/sections/${sectionId}/run`, { method: 'POST' });
}

export function getSectionInstructions(sectionId: string): Promise<{ content: string }> {
  return fetchJson<{ content: string }>(`/api/sections/${sectionId}/instructions`);
}

export function updateSectionInstructions(sectionId: string, content: string): Promise<{ ok: boolean }> {
  return fetchJson<{ ok: boolean }>(`/api/sections/${sectionId}/instructions`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  });
}

// ── Profile ───────────────────────────────────────────────

export function getProfile(): Promise<{ business_profile: string; market_segments: string }> {
  return fetchJson(`/api/profile`);
}

export function saveBusinessProfile(content: string): Promise<{ ok: boolean }> {
  return fetchJson(`/api/profile/business`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export function saveMarketSegments(content: string): Promise<{ ok: boolean }> {
  return fetchJson(`/api/profile/segments`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export function getProfileStatus(): Promise<ProfileStatus> {
  return fetchJson<ProfileStatus>(`/api/profile/status`);
}

export function regenerateProfile(): Promise<{ ok: boolean }> {
  return fetchJson(`/api/profile/regenerate`, { method: 'POST' });
}

// ── Tools ─────────────────────────────────────────────────

export function runOutreach(folder: string, context_note: string): Promise<{ ok: boolean }> {
  return fetchJson(`/api/outreach/run`, {
    method: 'POST',
    body: JSON.stringify({ folder, context_note }),
  });
}

export function getOutreachLast(): Promise<OutreachLastRun> {
  return fetchJson<OutreachLastRun>(`/api/outreach/last`);
}

// ── Settings (read-only here for sidebar / dashboard) ─────

export function getSettings(): Promise<Record<string, unknown>> {
  return fetchJson(`/api/settings`);
}

// ── CRM ───────────────────────────────────────────────────

export interface CrmContact {
  email: string;
  name?: string;
  company?: string;
  role?: string;
  phone?: string;
  linkedin?: string;
  status?: string;          // client / prospect / partner / vendor / other
  priority?: string;        // high / medium / low / ignore
  summary?: string;
  writing_style?: string;
  thread_count?: number;
  last_contact?: string;
  ignore?: boolean;
  notes?: string;
  updated_at?: string;
}

export interface CrmResponse {
  last_scan: string | null;
  months_scanned?: number;
  total: number;
  contacts: CrmContact[];
}

export function getCrm(): Promise<CrmResponse> {
  return fetchJson<CrmResponse>(`/api/crm`);
}

export function patchCrmContact(email: string, updates: Partial<CrmContact>): Promise<CrmContact> {
  return fetchJson<CrmContact>(`/api/crm/${encodeURIComponent(email)}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export function createCrmContact(contact: Partial<CrmContact> & { email: string }): Promise<CrmContact> {
  return fetchJson<CrmContact>(`/api/crm`, {
    method: 'POST',
    body: JSON.stringify(contact),
  });
}

// ── Projects ──────────────────────────────────────────────

export interface ProjectRecord {
  id: string;
  name: string;
  category?: string;
  status: string;
  momentum: string;
  summary?: string;
  next_action?: string;
  last_activity?: string;
  deadline?: string | null;
  participants?: string[];
  key_topics?: string[];
  conversation_ids?: string[];
  thread_count?: number;
  ignore?: boolean;
  updated_at?: string;
}

export interface ProjectsResponse {
  last_scan: string | null;
  total: number;
  projects: ProjectRecord[];
}

export function getProjects(): Promise<ProjectsResponse> {
  return fetchJson<ProjectsResponse>(`/api/projects`);
}

export function patchProject(id: string, updates: Partial<ProjectRecord>): Promise<ProjectRecord> {
  return fetchJson<ProjectRecord>(`/api/projects/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

// ── Expenses (full master ledger) ─────────────────────────

export interface ExpenseRow {
  id: string;
  Date?: string;
  Vendor?: string;
  Amount?: number | string;
  Currency?: string;
  GST_HST?: number | string | null;
  Net_Amount?: number | string | null;
  Category?: string;
  Attachment?: string;
  Email_Subject?: string;
  From?: string;
  Msg_ID?: string;
  Att_ID?: string;
  Processed_Date?: string;
  [key: string]: unknown;
}

export function getAllExpenses(): Promise<ExpenseRow[]> {
  return fetchJson<ExpenseRow[]>(`/api/expenses/all`);
}

export function patchExpense(id: string, updates: Partial<ExpenseRow>): Promise<ExpenseRow> {
  return fetchJson<ExpenseRow>(`/api/expenses/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

export function deleteExpense(id: string): Promise<{ ok: boolean }> {
  return fetchJson<{ ok: boolean }>(`/api/expenses/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function createExpense(row: Partial<ExpenseRow>): Promise<ExpenseRow> {
  return fetchJson<ExpenseRow>(`/api/expenses`, {
    method: 'POST',
    body: JSON.stringify(row),
  });
}

export function expensePhotoUrl(id: string): string {
  return `/api/expenses/${encodeURIComponent(id)}/photo`;
}

// ── Schedules ─────────────────────────────────────────────

export interface Briefing {
  id: string;
  name: string;
  enabled: boolean;
  cron: string;
  tz?: string;       // IANA timezone (e.g. "America/New_York"); falls back to "UTC" on backend
  skills: string[];
}

export interface EmailMonitorConfig {
  priority_immediate: boolean;
  interval_minutes:   number;
  active_start:       string;  // HH:MM
  active_end:         string;  // HH:MM
}

export interface MeetingConfig {
  prep_enabled:        boolean;
  prep_minutes_before: number;
  summary_enabled:     boolean;
}

export interface SchedulesResponse {
  briefings:     Briefing[];
  email_monitor: EmailMonitorConfig;
  meeting:       MeetingConfig;
}

export function getSchedules(): Promise<SchedulesResponse> {
  return fetchJson<SchedulesResponse>(`/api/schedules`);
}

export function createBriefing(briefing: Omit<Briefing, 'id'>): Promise<Briefing> {
  return fetchJson<Briefing>(`/api/schedules/briefings`, {
    method: 'POST',
    body: JSON.stringify(briefing),
  });
}

export function updateBriefing(id: string, patch: Partial<Briefing>): Promise<Briefing> {
  return fetchJson<Briefing>(`/api/schedules/briefings/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export function deleteBriefing(id: string): Promise<{ ok: boolean }> {
  return fetchJson<{ ok: boolean }>(`/api/schedules/briefings/${id}`, {
    method: 'DELETE',
  });
}

export function testRunBriefing(id: string): Promise<{ ok: boolean; skills: string[] }> {
  return fetchJson<{ ok: boolean; skills: string[] }>(`/api/schedules/briefings/${id}/run`, {
    method: 'POST',
  });
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

// ── Bot chat (Audrey via HTTP — shared with Teams) ────────

export interface BotTurn {
  role: 'user' | 'model';
  content: string;
  ts: number;
}

export function botChat(message: string): Promise<{ response: string }> {
  return fetchJson<{ response: string }>(`/api/bot/chat`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

export function getBotHistory(limit = 20): Promise<{ turns: BotTurn[] }> {
  return fetchJson<{ turns: BotTurn[] }>(`/api/bot/history?limit=${limit}`);
}

export function putEmailMonitorConfig(cfg: Partial<EmailMonitorConfig>): Promise<EmailMonitorConfig> {
  return fetchJson<EmailMonitorConfig>(`/api/schedules/email_monitor`, {
    method: 'PUT',
    body: JSON.stringify(cfg),
  });
}

export function putMeetingConfig(cfg: Partial<MeetingConfig>): Promise<MeetingConfig> {
  return fetchJson<MeetingConfig>(`/api/schedules/meeting`, {
    method: 'PUT',
    body: JSON.stringify(cfg),
  });
}

// ── Helpers ───────────────────────────────────────────────

export function relativeTime(iso?: string): string {
  if (!iso) return 'never';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return 'just now';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    if (d < 30) return `${d}d ago`;
    const mo = Math.floor(d / 30);
    return `${mo}mo ago`;
  } catch {
    return iso;
  }
}
