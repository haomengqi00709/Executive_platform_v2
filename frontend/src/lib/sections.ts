// Section catalog — single source of truth for frontend display metadata.
// Keep in sync with src/server.py::_SECTION_RUNNERS and src/bot.py::SECTION_IDS.

import {
  Sparkles, Mail, Send, CheckCircle2, CalendarClock, Sunrise,
  CalendarDays, ListTodo, Video,
  FolderKanban, AlertTriangle,
  Globe, Building2,
  HeartPulse, TrendingUp,
  Receipt,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type SectionCategory =
  | 'briefing'
  | 'email'
  | 'meetings'
  | 'projects'
  | 'intelligence'
  | 'insights'
  | 'documents';

export type SectionTrigger = 'scheduled' | 'triggered' | 'derived' | 'live';

export interface SectionDef {
  id: string;
  name: string;
  category: SectionCategory;
  trigger: SectionTrigger;
  icon: LucideIcon;
  description: string;
  // Frontend hint: if true, render briefing-style hero text instead of items list
  hasNarrative?: boolean;
  // If true, this section's count = items.length is the main metric for dashboard
  dashboardStat?: boolean;
}

export const SECTIONS: SectionDef[] = [
  // BRIEFING
  {
    id: 'ai_summary',
    name: 'AI Morning Briefing',
    category: 'briefing',
    trigger: 'scheduled',
    icon: Sunrise,
    description: 'Daily summary of calendar, emails, priorities, and key relationships.',
    hasNarrative: true,
  },

  // EMAIL
  {
    id: 'reply_needed',
    name: 'Emails Awaiting Reply',
    category: 'email',
    trigger: 'scheduled',
    icon: Mail,
    description: 'Inbox emails where the sender is waiting for your response.',
    dashboardStat: true,
  },
  {
    id: 'followup_needed',
    name: 'Sent — No Response',
    category: 'email',
    trigger: 'scheduled',
    icon: Send,
    description: 'Emails you sent where the other party has not replied yet.',
    dashboardStat: true,
  },
  {
    id: 'upcoming_commitments',
    name: 'Upcoming Commitments',
    category: 'email',
    trigger: 'derived',
    icon: CalendarClock,
    description: 'Forward-looking view of deadlines in the next 7 days.',
  },
  {
    id: 'yesterday_recap',
    name: "Yesterday's Recap",
    category: 'email',
    trigger: 'scheduled',
    icon: Sunrise,
    description: "Yesterday's inbound, outbound, meetings, and new commitments.",
  },
  {
    id: 'due_today',
    name: 'Due Today',
    category: 'email',
    trigger: 'derived',
    icon: CheckCircle2,
    description: 'Commitments you owe today.',
    dashboardStat: true,
  },
  {
    id: 'commitments_extract',
    name: 'Commitments (Raw)',
    category: 'email',
    trigger: 'scheduled',
    icon: ListTodo,
    description: 'All promises and deadlines extracted from inbox emails. Source for due_today and upcoming_commitments.',
  },

  // MEETINGS
  {
    id: 'meetings_today',
    name: "Today's Meetings",
    category: 'meetings',
    trigger: 'live',
    icon: CalendarDays,
    description: "Calendar view of meetings scheduled for today.",
    dashboardStat: true,
  },
  {
    id: 'meeting_action_items',
    name: 'Meeting Action Items',
    category: 'meetings',
    trigger: 'triggered',
    icon: ListTodo,
    description: 'Open action items extracted from recorded meetings.',
  },
  {
    id: 'recent_meetings',
    name: 'Recent Meetings',
    category: 'meetings',
    trigger: 'triggered',
    icon: Video,
    description: 'Summaries and decisions from recorded meetings.',
  },

  // PROJECTS
  {
    id: 'projects_needing_attention',
    name: 'Projects Needing Attention',
    category: 'projects',
    trigger: 'scheduled',
    icon: AlertTriangle,
    description: 'Projects flagged needs_attention or early_stage.',
    dashboardStat: true,
  },
  {
    id: 'project_status',
    name: 'Project Status',
    category: 'projects',
    trigger: 'scheduled',
    icon: FolderKanban,
    description: 'Portfolio view of all active projects with status and momentum.',
  },

  // INTELLIGENCE
  {
    id: 'relationship_health',
    name: 'Relationship Health',
    category: 'intelligence',
    trigger: 'scheduled',
    icon: HeartPulse,
    description: 'Contacts whose engagement pattern needs attention.',
    dashboardStat: true,
  },
  {
    id: 'market_intelligence',
    name: 'Market Intelligence',
    category: 'intelligence',
    trigger: 'scheduled',
    icon: Globe,
    description: 'Macro market signals via Gemini Google Search grounding.',
  },
  {
    id: 'company_intelligence',
    name: 'Company Intelligence',
    category: 'intelligence',
    trigger: 'scheduled',
    icon: Building2,
    description: 'Targeted signals on CRM companies and watchlist.',
  },

  // INSIGHTS
  {
    id: 'business_insights',
    name: 'Weekly Brief',
    category: 'insights',
    trigger: 'scheduled',
    icon: TrendingUp,
    description: 'Aggregated weekly executive brief: stats, deltas, narrative.',
    hasNarrative: true,
  },

  // DOCUMENTS
  {
    id: 'expenses',
    name: 'Receipts & Expenses',
    category: 'documents',
    trigger: 'triggered',
    icon: Receipt,
    description: 'Auto-captured receipts from email attachments and Teams DMs.',
  },
];

export const SECTION_BY_ID: Record<string, SectionDef> = SECTIONS.reduce(
  (acc, s) => ((acc[s.id] = s), acc),
  {} as Record<string, SectionDef>,
);

export const CATEGORY_ORDER: SectionCategory[] = [
  'briefing',
  'email',
  'meetings',
  'projects',
  'intelligence',
  'insights',
  'documents',
];

export const CATEGORY_LABEL: Record<SectionCategory, string> = {
  briefing:     'BRIEFING',
  email:        'EMAIL',
  meetings:     'MEETINGS',
  projects:     'PROJECTS',
  intelligence: 'INTELLIGENCE',
  insights:     'INSIGHTS',
  documents:    'DOCUMENTS',
};

export const CATEGORY_ACCENT: Record<SectionCategory, string> = {
  briefing:     'text-amber-400',
  email:        'text-sky-400',
  meetings:     'text-violet-400',
  projects:     'text-emerald-400',
  intelligence: 'text-rose-400',
  insights:     'text-orange-400',
  documents:    'text-teal-400',
};

export function sectionsByCategory(category: SectionCategory): SectionDef[] {
  return SECTIONS.filter(s => s.category === category);
}
