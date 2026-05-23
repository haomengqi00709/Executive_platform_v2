// Schedule helpers — parse/build cron expressions for the preset-based UI.
// Convention: 5-field cron (minute hour day month day_of_week).
// day_of_week follows APScheduler convention: 0=Mon, 6=Sun.

export interface ScheduleShape {
  enabled: boolean;
  cron: string;
}

export type Preset = 'off' | 'daily' | 'twice_daily' | 'weekdays' | 'weekly' | 'custom';

export interface ParsedSchedule {
  preset: Preset;
  time?: string;          // HH:MM
  times?: [string, string]; // for twice_daily
  dayOfWeek?: number;     // 0-6 (0=Mon)
}

const DAY_LABEL = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAY_LABEL_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function pad(n: number) { return String(n).padStart(2, '0'); }

function formatHM(h: number, m: number): string {
  return `${pad(h)}:${pad(m)}`;
}

function parseHM(s: string): [number, number] {
  const [h, m] = (s || '').split(':').map(x => parseInt(x, 10));
  return [isNaN(h) ? 0 : h, isNaN(m) ? 0 : m];
}

export function parseCron(cron: string): ParsedSchedule {
  if (!cron) return { preset: 'custom' };
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return { preset: 'custom' };
  const [min, hr, day, mo, dow] = parts;
  if (day !== '*' || mo !== '*') return { preset: 'custom' };
  if (!/^\d+$/.test(min)) return { preset: 'custom' };

  // Single hour
  const isSingleHour = /^\d+$/.test(hr);
  // Multiple hours separated by comma
  const isTwoHours   = /^\d+,\d+$/.test(hr);

  if (isSingleHour && dow === '*') {
    return { preset: 'daily', time: formatHM(+hr, +min) };
  }

  if (isTwoHours && dow === '*') {
    const [h1, h2] = hr.split(',').map(Number);
    return {
      preset: 'twice_daily',
      times: [formatHM(h1, +min), formatHM(h2, +min)],
    };
  }

  if (isSingleHour && (dow === '0-4' || dow === '1-5' || dow.toLowerCase() === 'mon-fri')) {
    return { preset: 'weekdays', time: formatHM(+hr, +min) };
  }

  if (isSingleHour && /^\d+$/.test(dow)) {
    return { preset: 'weekly', time: formatHM(+hr, +min), dayOfWeek: +dow };
  }

  return { preset: 'custom' };
}

export function buildCron(preset: Preset, opts: Partial<ParsedSchedule>): string {
  switch (preset) {
    case 'daily': {
      const [h, m] = parseHM(opts.time || '07:00');
      return `${m} ${h} * * *`;
    }
    case 'twice_daily': {
      const [h1, m1] = parseHM(opts.times?.[0] || '07:00');
      const [h2]     = parseHM(opts.times?.[1] || '13:00');
      // APScheduler 'minute' field must be single value here; share m1 across both fires
      return `${m1} ${h1},${h2} * * *`;
    }
    case 'weekdays': {
      const [h, m] = parseHM(opts.time || '07:00');
      // APScheduler 0=Mon, 4=Fri
      return `${m} ${h} * * 0-4`;
    }
    case 'weekly': {
      const [h, m] = parseHM(opts.time || '07:00');
      const dow = opts.dayOfWeek ?? 0;
      return `${m} ${h} * * ${dow}`;
    }
    case 'off':
    case 'custom':
    default:
      return '';
  }
}

export function describeSchedule(schedule: ScheduleShape): string {
  if (!schedule.enabled) return 'Off';
  if (!schedule.cron)   return 'Off';
  const p = parseCron(schedule.cron);
  switch (p.preset) {
    case 'daily':       return `Daily at ${p.time}`;
    case 'twice_daily': return `Twice daily · ${p.times?.join(' & ')}`;
    case 'weekdays':    return `Weekdays at ${p.time}`;
    case 'weekly':      return `${DAY_LABEL_FULL[p.dayOfWeek ?? 0]}s at ${p.time}`;
    case 'custom':      return `Custom: ${schedule.cron}`;
    default:            return schedule.cron;
  }
}

export const DAY_OPTIONS = DAY_LABEL.map((label, value) => ({ value, label }));
